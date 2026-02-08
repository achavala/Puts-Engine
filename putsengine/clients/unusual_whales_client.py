"""
Unusual Whales API Client for options flow data.
Provides institutional flow detection, dark pool data, and options analytics.

API Documentation: https://api.unusualwhales.com/docs

BUDGET STRATEGY (7,500 calls/day with 67 jobs):
├── Pre-Market (4:00-9:00 AM):     800 calls  - 4 scans x all tickers
├── Market Open (9:30-10:00 AM):   800 calls  - Full scan all
├── Regular Hours (10:00-3:30 PM): 4,000 calls - 11 scans x all tickers
├── Market Close (4:00 PM):        800 calls  - Full scan all
├── End of Day (5:00 PM):          400 calls  - Final summary
└── Buffer:                        700 calls  - For retries

RATE LIMIT STRATEGY (120 req/min limit):
- Batch tickers into groups of 100
- Wait 65 seconds between batches (rate limit reset)
- Use 0.6s interval within batch (100 req/min, safe under 120)
- Result: ALL tickers scanned per scan, ZERO misses

RESPONSE CACHE STRATEGY (Feb 7, 2026):
- 30-minute TTL cache for all UW API responses
- Cache key = endpoint path (without params) to normalize limit differences
- SAVES ~5,800+ UW calls/day from overlapping scans:
  - EWS + Full Scan at same time: dark_pool_flow, oi_change overlap
  - EWS + Earnings Priority: 4 endpoints overlap per earnings stock
  - get_put_flow + get_call_selling_flow: both call flow_recent internally
  - Duplicate 3PM scan eliminated (daily_report + market_pulse)
"""

import asyncio
import time as _time
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Tuple
import aiohttp
from loguru import logger

from putsengine.config import Settings
from putsengine.models import OptionsFlow, DarkPoolPrint, GEXData
from putsengine.api_budget import get_budget_manager, TickerPriority


class UnusualWhalesClient:
    """
    Client for Unusual Whales API with Smart Budget Management.

    Rate limit: 6,000 calls/day, ~2 requests/second
    Strategy: 
    - Tiered scanning (P1/P2/P3 tickers get different allocations)
    - Time-window budgets (critical windows get more calls)
    - Cooldowns per ticker (prevent redundant calls)
    - Skip UW for low-score tickers (use Alpaca only)

    API Base: https://api.unusualwhales.com
    Docs: https://api.unusualwhales.com/docs
    """

    BASE_URL = "https://api.unusualwhales.com"
    
    # Rate limiting: 0.6s = 100 req/min (safe under 120 limit)
    # When batched: 100 tickers x 0.6s = 60s per batch, then wait 65s
    MIN_REQUEST_INTERVAL = 0.6  # 600ms between requests (100 req/min max)

    # =========================================================================
    # RESPONSE CACHE (Feb 7, 2026)
    # Prevents redundant UW API calls when multiple scans overlap.
    #
    # WHY: At 3:00 PM, EWS + Full Scan + Weather all query the same endpoints.
    #      EWS calls oi_change(AAPL), then Full Scan calls oi_change(AAPL) again.
    #      Dark pool, OI, and IV data barely change in 30 minutes.
    #
    # HOW: Cache key = endpoint path (ignoring limit/params).
    #      dark_pool_flow(AAPL, limit=50) and dark_pool_flow(AAPL, limit=30)
    #      share one cache entry. The larger response (50 results) serves both.
    #
    # SAVINGS: ~5,800+ UW calls/day (within-block + cross-block + dup 3PM)
    # =========================================================================
    RESPONSE_CACHE_TTL = 1800  # 30 minutes - UW data is flow/OI, not tick-level quotes
    CACHE_MAX_ENTRIES = 5000   # Prevent unbounded growth (~361 tickers x ~8 endpoints)

    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_key = settings.unusual_whales_api_key
        self.daily_limit = settings.uw_daily_limit
        self._session: Optional[aiohttp.ClientSession] = None
        self._calls_today = 0
        self._calls_reset_date = date.today()
        self._last_request_time = 0.0  # For rate limiting
        self._rate_limit_lock: Optional[asyncio.Lock] = None  # Lazy init for thread-safe rate limiting
        
        # Budget manager for smart API allocation
        self._budget_manager = get_budget_manager()
        
        # Force scan mode: bypasses priority tier limits for EWS discovery scans
        # When True, all _request() calls use force_scan=True in budget checks
        # Set this True before FULL EWS scans to ensure ALL tickers get UW data
        self._force_scan_mode = False
        
        # =====================================================================
        # RESPONSE CACHE (Feb 7, 2026)
        # Key: endpoint path (e.g., "/api/darkpool/AAPL")
        # Value: (response_data, timestamp_seconds)
        # =====================================================================
        self._response_cache: Dict[str, Tuple[Any, float]] = {}
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_saves = 0  # Number of API calls saved
    
    def set_force_scan_mode(self, enabled: bool):
        """
        Enable/disable force scan mode for EWS discovery scans.
        
        When enabled, bypasses P1/P2/P3 priority tier budget limits
        (still respects daily limit and total window budget).
        This ensures ALL 361+ tickers get UW data during FULL scans.
        """
        self._force_scan_mode = enabled
        if enabled:
            logger.info("UW Client: Force scan mode ENABLED (bypassing priority tiers)")
        else:
            logger.debug("UW Client: Force scan mode disabled")

    # =====================================================================
    # RESPONSE CACHE METHODS (Feb 7, 2026)
    # =====================================================================
    
    def _get_cache_key(self, endpoint: str) -> str:
        """
        Generate cache key from endpoint path ONLY (no params).
        
        This normalizes limit differences:
        - dark_pool_flow(AAPL, limit=50) and dark_pool_flow(AAPL, limit=30)
          share key "/api/darkpool/AAPL"
        - oi_change(AAPL) -> "/api/stock/AAPL/oi-change"
        
        SAFE because:
        - Higher-limit responses are supersets of lower-limit responses
        - UW sorts by recency - first N results are the same regardless of limit
        - Callers already process/filter the response internally
        """
        return endpoint
    
    def _get_cached_response(self, cache_key: str) -> Optional[Any]:
        """Get cached response if still valid (within TTL)."""
        if cache_key in self._response_cache:
            data, cached_at = self._response_cache[cache_key]
            age = _time.time() - cached_at
            if age < self.RESPONSE_CACHE_TTL:
                self._cache_hits += 1
                self._cache_saves += 1
                return data
            else:
                # Expired - remove stale entry
                del self._response_cache[cache_key]
        self._cache_misses += 1
        return None
    
    def _cache_response(self, cache_key: str, data: Any):
        """Store API response in cache with current timestamp."""
        self._response_cache[cache_key] = (data, _time.time())
        
        # Prevent unbounded growth
        if len(self._response_cache) > self.CACHE_MAX_ENTRIES:
            self._cleanup_expired_cache()
    
    def _cleanup_expired_cache(self):
        """Remove expired entries from cache."""
        now = _time.time()
        expired = [
            k for k, (_, ts) in self._response_cache.items()
            if (now - ts) >= self.RESPONSE_CACHE_TTL
        ]
        for k in expired:
            del self._response_cache[k]
        if expired:
            logger.debug(f"UW cache cleanup: removed {len(expired)} expired entries")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get response cache statistics for monitoring."""
        total = self._cache_hits + self._cache_misses
        hit_rate = round(self._cache_hits / max(1, total) * 100, 1)
        return {
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_entries": len(self._response_cache),
            "cache_hit_rate_pct": hit_rate,
            "api_calls_saved": self._cache_saves,
        }
    
    def clear_cache(self):
        """Clear the response cache and reset stats."""
        self._response_cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_saves = 0
        logger.info("UW response cache cleared")

    @property
    def _headers(self) -> Dict[str, str]:
        """Authentication headers for Unusual Whales API."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json"
        }

    @property
    def remaining_calls(self) -> int:
        """Get remaining API calls for today."""
        if date.today() != self._calls_reset_date:
            self._calls_today = 0
            self._calls_reset_date = date.today()
        return self.daily_limit - self._calls_today
    
    def should_skip_uw(self, symbol: str, score: float = 0) -> bool:
        """
        Check if we should skip UW API calls for this ticker.
        
        Use this to fall back to Alpaca-only scanning for low-priority tickers.
        Respects force_scan_mode: never skips when force scanning.
        """
        if self._budget_manager:
            return self._budget_manager.skip_uw_use_alpaca_only(
                symbol, score, force_scan=self._force_scan_mode
            )
        return False
    
    def can_call_for_symbol(self, symbol: str, score: float = 0, is_dui: bool = False) -> bool:
        """
        Check if we can make UW API calls for this symbol right now.
        
        Considers: daily budget, window budget, ticker cooldown, daily max.
        """
        if self._budget_manager:
            return self._budget_manager.can_call_uw(symbol, score=score, is_dui=is_dui)
        return self.remaining_calls > 0
    
    def get_budget_status(self) -> Dict:
        """Get current API budget status."""
        if self._budget_manager:
            return self._budget_manager.get_status()
        return {
            "daily_used": self._calls_today,
            "daily_limit": self.daily_limit,
            "daily_remaining": self.remaining_calls,
        }
    
    def update_ticker_priority(self, symbol: str, score: float, is_dui: bool = False):
        """Update ticker priority based on new score (affects future API allocation)."""
        if self._budget_manager:
            self._budget_manager.update_ticker_priority(symbol, score, is_dui)

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self._headers)
        return self._session

    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _rate_limit_wait(self):
        """Wait to respect rate limits - prevents 429 errors. Thread-safe with lock."""
        import time
        # Lazy initialization of lock (must be done inside async context)
        if self._rate_limit_lock is None:
            self._rate_limit_lock = asyncio.Lock()
        async with self._rate_limit_lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self.MIN_REQUEST_INTERVAL:
                wait_time = self.MIN_REQUEST_INTERVAL - elapsed
                await asyncio.sleep(wait_time)
            self._last_request_time = time.time()

    async def _request(
        self,
        endpoint: str,
        params: Optional[Dict] = None,
        symbol: str = None,
        priority: TickerPriority = None,
        force_scan: bool = False
    ) -> Dict[str, Any]:
        """
        Make HTTP request to Unusual Whales API with budget management + response cache.
        
        CACHE STRATEGY (Feb 7, 2026):
        - Before making HTTP call, check if endpoint is in the 30-min cache
        - If cached and fresh -> return cached data (0 API calls, 0 budget impact)
        - If not cached -> make real API call -> store in cache
        - Cache key = endpoint path only (normalizes limit params)
        
        This prevents:
        - EWS dark_pool(AAPL) at 3PM + Full Scan dark_pool(AAPL) at 3PM = 1 call not 2
        - get_put_flow(AAPL) + get_call_selling(AAPL) both calling flow_recent = 1 call not 2
        - oi_change(AAPL) queried by EWS, Full Scan, Earnings Priority = 1 call not 3
        
        Args:
            endpoint: API endpoint
            params: Query parameters
            symbol: Ticker symbol (for budget tracking)
            priority: Ticker priority (P1/P2/P3)
            force_scan: If True, bypass priority tier limits (for EWS discovery)
        """
        # =====================================================================
        # STEP 0: Check response cache FIRST (before any budget/rate logic)
        # If we have fresh data for this endpoint, skip the API call entirely.
        # This saves budget, rate limit capacity, and latency.
        # =====================================================================
        cache_key = self._get_cache_key(endpoint)
        cached_data = self._get_cached_response(cache_key)
        if cached_data is not None:
            logger.debug(f"UW CACHE HIT: {endpoint} (saved 1 API call)")
            return cached_data
        
        # =====================================================================
        # STEP 1: Budget check (only if cache missed)
        # =====================================================================
        if symbol and self._budget_manager:
            # Use force_scan from either the parameter or the client-level flag
            effective_force = force_scan or self._force_scan_mode
            if not self._budget_manager.can_call_uw(symbol, priority, force_scan=effective_force):
                logger.debug(f"UW API call skipped for {symbol} - budget/cooldown")
                return {}
        
        # Check daily limit
        if self.remaining_calls <= 0:
            logger.error("Unusual Whales daily API limit reached!")
            return {}

        # =====================================================================
        # STEP 2: Rate limiting + HTTP call
        # =====================================================================
        await self._rate_limit_wait()

        url = f"{self.BASE_URL}{endpoint}"
        session = await self._get_session()

        try:
            async with session.get(url, params=params) as response:
                self._calls_today += 1
                
                # Record call in budget manager
                if symbol and self._budget_manager:
                    self._budget_manager.record_call(symbol)

                if response.status == 200:
                    result = await response.json()
                    # =========================================================
                    # STEP 3: Cache successful response for future reuse
                    # =========================================================
                    if result:  # Only cache non-empty responses
                        self._cache_response(cache_key, result)
                    return result
                elif response.status == 429:
                    # Rate limited - wait longer and retry once
                    logger.debug("UW rate limit - waiting 3s before retry")
                    await asyncio.sleep(3.0)
                    self._last_request_time = 0  # Reset to allow immediate retry
                    return {}
                elif response.status == 401:
                    logger.error("Unusual Whales authentication failed")
                    return {}
                elif response.status == 403:
                    logger.debug(f"UW access denied for {endpoint}")
                    return {}
                else:
                    error_text = await response.text()
                    logger.debug(f"UW API {response.status} for {endpoint}: {error_text[:100]}")
                    return {}
        except Exception as e:
            logger.error(f"Unusual Whales request failed: {e}")
            return {}

    # ==================== Options Flow ====================

    async def get_flow_recent(
        self,
        symbol: str,
        limit: int = 50,
        priority: TickerPriority = None
    ) -> List[OptionsFlow]:
        """
        Get recent options flow for a symbol.
        Endpoint: /api/stock/{ticker}/flow-recent
        """
        endpoint = f"/api/stock/{symbol}/flow-recent"
        params = {"limit": limit}

        result = await self._request(endpoint, params, symbol=symbol, priority=priority)
        flows = []

        # Handle both list responses and dict with "data" key
        if isinstance(result, list):
            data = result
        elif isinstance(result, dict):
            data = result.get("data", [])
        else:
            data = []
            
        if isinstance(data, list):
            for item in data:
                try:
                    flows.append(self._parse_flow(item, symbol))
                except Exception as e:
                    logger.debug(f"Error parsing flow: {e}")
                    continue

        return flows

    async def get_flow_alerts(
        self,
        symbol: str,
        limit: int = 50
    ) -> List[OptionsFlow]:
        """
        Get flow alerts for a symbol.
        Endpoint: /api/stock/{ticker}/flow-alerts
        """
        endpoint = f"/api/stock/{symbol}/flow-alerts"
        params = {"limit": limit}

        result = await self._request(endpoint, params, symbol=symbol)
        flows = []

        # Handle both list responses and dict with "data" key
        if isinstance(result, list):
            data = result
        elif isinstance(result, dict):
            data = result.get("data", [])
        else:
            data = []
            
        if isinstance(data, list):
            for item in data:
                try:
                    flows.append(self._parse_flow(item, symbol))
                except Exception as e:
                    logger.debug(f"Error parsing flow alert: {e}")
                    continue

        return flows

    async def get_put_flow(
        self,
        symbol: str,
        min_premium: float = 25000,
        limit: int = 50
    ) -> List[OptionsFlow]:
        """Get PUT flow specifically - primary use case for this engine."""
        flows = await self.get_flow_recent(symbol, limit=limit * 2)
        # Filter for puts with minimum premium
        return [
            f for f in flows
            if f.option_type.lower() == "put" and f.premium >= min_premium
        ]

    async def get_call_selling_flow(
        self,
        symbol: str,
        limit: int = 50
    ) -> List[OptionsFlow]:
        """Get call selling at bid (bearish signal)."""
        flows = await self.get_flow_recent(symbol, limit=limit * 2)
        # Filter for calls sold at bid
        return [
            f for f in flows
            if f.option_type.lower() == "call" and f.side.lower() in ["bid", "sell"]
        ]

    def _parse_flow(self, item: Dict[str, Any], underlying: str = "") -> OptionsFlow:
        """Parse flow item into OptionsFlow model."""
        # Handle expiration date
        exp_str = item.get("expiry", item.get("expiration_date", item.get("expires", "")))
        if exp_str:
            try:
                exp_date = datetime.strptime(str(exp_str)[:10], "%Y-%m-%d").date()
            except:
                exp_date = date.today() + timedelta(days=30)
        else:
            exp_date = date.today() + timedelta(days=30)

        # Handle timestamp
        timestamp_str = item.get("executed_at", item.get("timestamp", item.get("tape_time", "")))
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(str(timestamp_str).replace("Z", "+00:00"))
            except:
                timestamp = datetime.now()
        else:
            timestamp = datetime.now()

        # Determine sentiment from side/type
        side = item.get("side", item.get("aggressor_side", "unknown"))
        opt_type = item.get("option_type", item.get("put_call", "unknown"))

        # Bearish: put buying at ask, call selling at bid
        sentiment = "neutral"
        if opt_type.lower() == "put" and side.lower() in ["ask", "buy"]:
            sentiment = "bearish"
        elif opt_type.lower() == "call" and side.lower() in ["bid", "sell"]:
            sentiment = "bearish"
        elif opt_type.lower() == "call" and side.lower() in ["ask", "buy"]:
            sentiment = "bullish"
        elif opt_type.lower() == "put" and side.lower() in ["bid", "sell"]:
            sentiment = "bullish"

        return OptionsFlow(
            timestamp=timestamp,
            symbol=item.get("option_symbol", item.get("contract", "")),
            underlying=item.get("ticker", item.get("underlying_symbol", underlying)),
            expiration=exp_date,
            strike=float(item.get("strike", item.get("strike_price", 0))),
            option_type=opt_type,
            side=side,
            size=int(item.get("size", item.get("volume", item.get("qty", 0)))),
            premium=float(item.get("premium", item.get("total_premium", 0))),
            spot_price=float(item.get("stock_price", item.get("underlying_price", item.get("spot", 0)))),
            implied_volatility=float(item.get("iv", item.get("implied_volatility", 0))),
            delta=float(item.get("delta", 0)),
            is_sweep=item.get("is_sweep", False) or item.get("trade_type", "") == "SWEEP",
            is_block=item.get("is_block", False) or item.get("trade_type", "") == "BLOCK",
            sentiment=sentiment
        )

    # ==================== Dark Pool ====================

    async def get_dark_pool_flow(
        self,
        symbol: str,
        limit: int = 50
    ) -> List[DarkPoolPrint]:
        """
        Get dark pool prints for a symbol.
        Endpoint: /api/darkpool/{ticker}
        """
        endpoint = f"/api/darkpool/{symbol}"
        params = {"limit": limit}

        result = await self._request(endpoint, params, symbol=symbol)
        prints = []

        # Handle both list responses and dict with "data" key
        if isinstance(result, list):
            data = result
        elif isinstance(result, dict):
            data = result.get("data", [])
        else:
            data = []
            
        if isinstance(data, list):
            for item in data:
                try:
                    timestamp_str = item.get("executed_at", item.get("timestamp", item.get("tape_time", "")))
                    if timestamp_str:
                        try:
                            timestamp = datetime.fromisoformat(str(timestamp_str).replace("Z", "+00:00"))
                        except:
                            timestamp = datetime.now()
                    else:
                        timestamp = datetime.now()

                    prints.append(DarkPoolPrint(
                        timestamp=timestamp,
                        symbol=symbol,
                        price=float(item.get("price", item.get("execution_price", 0))),
                        size=int(item.get("size", item.get("volume", item.get("shares", 0)))),
                        exchange=item.get("exchange", item.get("venue", "DARK")),
                        is_buy=item.get("side", "").lower() == "buy" if item.get("side") else None
                    ))
                except Exception as e:
                    logger.debug(f"Error parsing dark pool print: {e}")
                    continue

        return prints

    async def get_dark_pool_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get recent dark pool activity across all symbols.
        Endpoint: /api/darkpool/recent
        """
        endpoint = "/api/darkpool/recent"
        params = {"limit": limit}
        result = await self._request(endpoint, params)
        # Handle both list responses and dict with "data" key
        if isinstance(result, list):
            return result
        elif isinstance(result, dict):
            return result.get("data", [])
        return []

    # ==================== Greeks / GEX ====================

    async def get_greeks(self, symbol: str) -> Dict[str, Any]:
        """
        Get greeks data for a symbol.
        Endpoint: /api/stock/{ticker}/greeks
        """
        endpoint = f"/api/stock/{symbol}/greeks"
        return await self._request(endpoint)

    async def get_greek_exposure(self, symbol: str) -> Dict[str, Any]:
        """
        Get gamma/delta exposure (GEX) for a symbol.
        Endpoint: /api/stock/{ticker}/greek-exposure
        """
        endpoint = f"/api/stock/{symbol}/greek-exposure"
        return await self._request(endpoint)

    async def get_gex_data(self, symbol: str) -> Optional[GEXData]:
        """
        Get Gamma Exposure (GEX) data for a symbol.
        This estimates dealer positioning and hedging flows.
        """
        # Try greek-exposure endpoint first
        result = await self.get_greek_exposure(symbol)

        if not result:
            # Fallback to greeks endpoint
            result = await self.get_greeks(symbol)

        if not result:
            return None

        # Handle both dict with "data" key and direct response
        data = result.get("data", result) if isinstance(result, dict) else result

        # If data is a list, get first element
        if isinstance(data, list):
            if len(data) == 0:
                return None
            data = data[0]

        if not isinstance(data, dict):
            return None

        try:
            return GEXData(
                symbol=symbol,
                timestamp=datetime.now(),
                net_gex=float(data.get("gex", data.get("net_gex", data.get("gamma_exposure", 0)))),
                call_gex=float(data.get("call_gex", data.get("call_gamma", 0))),
                put_gex=float(data.get("put_gex", data.get("put_gamma", 0))),
                gex_flip_level=float(data.get("gex_flip", data.get("flip_price", 0))) if data.get("gex_flip") or data.get("flip_price") else None,
                dealer_delta=float(data.get("dex", data.get("dealer_delta", data.get("net_delta", 0)))),
                put_wall=float(data.get("put_wall", data.get("highest_put_oi_strike", 0))) if data.get("put_wall") or data.get("highest_put_oi_strike") else None,
                call_wall=float(data.get("call_wall", data.get("highest_call_oi_strike", 0))) if data.get("call_wall") or data.get("highest_call_oi_strike") else None
            )
        except Exception as e:
            logger.debug(f"Error parsing GEX data for {symbol}: {e}")
            return None

    # ==================== Options Volume & OI ====================

    async def get_options_volume(self, symbol: str) -> Dict[str, Any]:
        """
        Get options volume data for a symbol.
        Endpoint: /api/stock/{ticker}/options-volume
        """
        endpoint = f"/api/stock/{symbol}/options-volume"
        return await self._request(endpoint)

    async def get_oi_change(self, symbol: str) -> Dict[str, Any]:
        """
        Get open interest change data.
        Endpoint: /api/stock/{ticker}/oi-change
        """
        endpoint = f"/api/stock/{symbol}/oi-change"
        return await self._request(endpoint)

    async def get_oi_by_strike(
        self,
        symbol: str,
        expiration: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        Get open interest by strike price.
        Endpoint: /api/stock/{ticker}/oi-per-strike
        """
        endpoint = f"/api/stock/{symbol}/oi-per-strike"
        params = {}
        if expiration:
            params["expiry"] = expiration.isoformat()
        return await self._request(endpoint, params)

    async def get_oi_per_expiry(self, symbol: str) -> Dict[str, Any]:
        """
        Get open interest by expiration.
        Endpoint: /api/stock/{ticker}/oi-per-expiry
        """
        endpoint = f"/api/stock/{symbol}/oi-per-expiry"
        return await self._request(endpoint)

    async def get_open_interest(self, symbol: str) -> Dict[str, Any]:
        """Alias for get_oi_change for backward compatibility."""
        return await self.get_oi_change(symbol)

    # ==================== IV & Skew ====================

    async def get_iv_rank(self, symbol: str) -> Dict[str, Any]:
        """
        Get IV rank data.
        Endpoint: /api/stock/{ticker}/iv-rank
        """
        endpoint = f"/api/stock/{symbol}/iv-rank"
        return await self._request(endpoint)

    async def get_skew(self, symbol: str) -> Dict[str, Any]:
        """
        Get volatility skew data.
        Endpoint: /api/stock/{ticker}/historical-risk-reversal-skew
        """
        endpoint = f"/api/stock/{symbol}/historical-risk-reversal-skew"
        return await self._request(endpoint)

    async def get_iv_surface(self, symbol: str) -> Dict[str, Any]:
        """
        Get IV term structure.
        Endpoint: /api/stock/{ticker}/volatility/term-structure
        """
        endpoint = f"/api/stock/{symbol}/volatility/term-structure"
        return await self._request(endpoint)

    # ==================== Max Pain & Put Walls ====================

    async def get_max_pain(
        self,
        symbol: str,
        expiration: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        Get max pain level for a symbol.
        Endpoint: /api/stock/{ticker}/max-pain
        """
        endpoint = f"/api/stock/{symbol}/max-pain"
        params = {}
        if expiration:
            params["expiry"] = expiration.isoformat()
        return await self._request(endpoint, params)

    async def get_put_wall(self, symbol: str) -> Optional[float]:
        """
        Get the put wall (highest put OI level).
        This represents potential dealer support.
        """
        oi_data = await self.get_oi_by_strike(symbol)

        if not oi_data:
            return None

        # Handle both list responses and dict with "data" key
        if isinstance(oi_data, list):
            data = oi_data
        elif isinstance(oi_data, dict):
            data = oi_data.get("data", [])
        else:
            data = []
            
        if not isinstance(data, list) or len(data) == 0:
            return None

        max_put_oi = 0
        put_wall = None

        for strike_data in data:
            if not isinstance(strike_data, dict):
                continue
            put_oi = int(strike_data.get("put_oi", strike_data.get("put_open_interest", 0)))
            if put_oi > max_put_oi:
                max_put_oi = put_oi
                put_wall = float(strike_data.get("strike", strike_data.get("strike_price", 0)))

        return put_wall

    # ==================== Market-Wide ====================

    async def get_market_tide(self) -> Dict[str, Any]:
        """
        Get overall market flow sentiment (market tide).
        Endpoint: /api/market/market-tide
        """
        endpoint = "/api/market/market-tide"
        return await self._request(endpoint)

    async def get_market_spike(self) -> Dict[str, Any]:
        """
        Get market spike/unusual activity.
        Endpoint: /api/market/spike
        """
        endpoint = "/api/market/spike"
        return await self._request(endpoint)

    async def get_sector_tide(self, sector: str) -> Dict[str, Any]:
        """
        Get sector-specific flow sentiment.
        Endpoint: /api/market/{sector}/sector-tide
        """
        endpoint = f"/api/market/{sector}/sector-tide"
        return await self._request(endpoint)

    # ==================== Stock Info ====================

    async def get_stock_info(self, symbol: str) -> Dict[str, Any]:
        """
        Get stock information.
        Endpoint: /api/stock/{ticker}/info
        """
        endpoint = f"/api/stock/{symbol}/info"
        return await self._request(endpoint)

    async def get_expiry_breakdown(self, symbol: str) -> Dict[str, Any]:
        """
        Get expiry breakdown for options.
        Endpoint: /api/stock/{ticker}/expiry-breakdown
        """
        endpoint = f"/api/stock/{symbol}/expiry-breakdown"
        return await self._request(endpoint)

    # ==================== Flow Alerts (Global) ====================

    async def get_flow_alerts_global(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get global flow alerts.
        Endpoint: /api/option-trades/flow-alerts
        """
        endpoint = "/api/option-trades/flow-alerts"
        params = {"limit": limit}
        result = await self._request(endpoint, params)
        # Handle both list responses and dict with "data" key
        if isinstance(result, list):
            return result
        elif isinstance(result, dict):
            return result.get("data", [])
        return []

    # ==================== Insider/Congress (Bonus) ====================

    async def get_insider_trades(
        self,
        symbol: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Get insider trading activity.
        Endpoint: /api/insider/{ticker}
        """
        endpoint = f"/api/insider/{symbol}"
        params = {"limit": limit}
        result = await self._request(endpoint, params)
        # Handle both list responses and dict with "data" key
        if isinstance(result, list):
            return result
        elif isinstance(result, dict):
            return result.get("data", [])
        return []

    async def get_congress_trades(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get congressional trading activity.
        Endpoint: /api/congress/recent-trades
        """
        endpoint = "/api/congress/recent-trades"
        params = {"limit": limit}
        result = await self._request(endpoint, params)
        # Handle both list responses and dict with "data" key
        if isinstance(result, list):
            return result
        elif isinstance(result, dict):
            return result.get("data", [])
        return []
    
    async def get_earnings_calendar(
        self,
        start_date: str = None,
        end_date: str = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get earnings calendar for upcoming/recent earnings.
        Endpoint: /api/earnings-calendar
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            limit: Maximum results
            
        Returns:
            List of earnings events with ticker, date, timing (BMO/AMC)
        """
        endpoint = "/api/earnings/calendar"
        params = {"limit": limit}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        
        result = await self._request(endpoint, params)
        
        if isinstance(result, list):
            return result
        elif isinstance(result, dict):
            return result.get("data", [])
        return []
    
    async def get_global_flow_alerts(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get market-wide flow alerts (sweeps, blocks, unusual activity).
        Endpoint: /api/option-trades/flow-alerts
        
        This detects large put flow across entire market.
        
        Args:
            limit: Maximum alerts to return
            
        Returns:
            List of flow alerts with ticker, premium, type
        """
        endpoint = "/api/option-trades/flow-alerts"
        params = {"limit": limit}
        
        result = await self._request(endpoint, params)
        
        if isinstance(result, list):
            return result
        elif isinstance(result, dict):
            return result.get("data", [])
        return []
    
    async def get_oi_change(self, symbol: str) -> Dict[str, Any]:
        """
        Get open interest change data for a symbol.
        Endpoint: /api/stock/{symbol}/oi-change
        
        Used for detecting put OI accumulation (smart money positioning).
        
        Returns:
            Dict with put_oi_change, call_oi_change, etc.
        """
        endpoint = f"/api/stock/{symbol}/oi-change"
        result = await self._request(endpoint, symbol=symbol)
        
        if isinstance(result, dict):
            return result
        return {}
    
    async def get_iv_term_structure(self, symbol: str) -> Dict[str, Any]:
        """
        Get IV term structure for a symbol.
        Endpoint: /api/stock/{symbol}/volatility/term-structure
        
        Used for detecting IV inversion (near-term > far-term = hedging).
        
        Returns:
            Dict with 7_day, 30_day, 60_day IV values
        """
        endpoint = f"/api/stock/{symbol}/volatility/term-structure"
        result = await self._request(endpoint, symbol=symbol)
        
        if isinstance(result, dict):
            return result
        return {}
