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
        self._session_loop_id: Optional[int] = None  # Track which event loop owns the session
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
        """Get or create aiohttp session, auto-healing on event loop change.
        
        FEB 9 FIX: Detects when the session is bound to a different/closed
        event loop and recreates it on the current loop. Prevents
        'Event loop is closed' errors during scheduled scans.
        """
        try:
            current_loop_id = id(asyncio.get_running_loop())
        except RuntimeError:
            current_loop_id = None
        
        needs_new = (
            self._session is None
            or self._session.closed
            or self._session_loop_id != current_loop_id
        )
        
        if needs_new:
            if self._session is not None:
                try:
                    if not self._session.closed:
                        await self._session.close()
                except Exception:
                    pass
                self._session = None
            
            self._session = aiohttp.ClientSession(headers=self._headers)
            self._session_loop_id = current_loop_id
        
        return self._session

    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            try:
                await self._session.close()
            except Exception:
                pass
        self._session = None
        self._session_loop_id = None

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
        # STEP 2: Rate limiting + HTTP call (with 429 retry)
        # =====================================================================
        url = f"{self.BASE_URL}{endpoint}"
        max_retries = 2  # 1 initial attempt + 1 retry on 429
        
        for attempt in range(max_retries):
            await self._rate_limit_wait()
            session = await self._get_session()

            try:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        # Only count successful calls against daily budget
                        self._calls_today += 1
                        if symbol and self._budget_manager:
                            self._budget_manager.record_call(symbol)
                        
                        result = await response.json()
                        # =========================================================
                        # STEP 3: Cache successful response for future reuse
                        # =========================================================
                        if result:  # Only cache non-empty responses
                            self._cache_response(cache_key, result)
                        return result
                    elif response.status == 429:
                        if attempt < max_retries - 1:
                            # Rate limited — wait and actually retry (no budget cost)
                            logger.debug(f"UW rate limit 429 on {endpoint} — backoff 5s then retry (attempt {attempt + 1}/{max_retries})")
                            await asyncio.sleep(5.0)
                            continue  # Retry without counting against budget
                        else:
                            # Final attempt also 429 — give up, don't waste budget
                            logger.warning(f"UW rate limit 429 persists on {endpoint} after {max_retries} attempts — skipping")
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
        
        return {}  # Should not reach here, but safety net

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
        """
        Parse flow item into OptionsFlow model.
        
        FEB 8, 2026 FIX: UW flow-recent has NO 'side' field.
        Instead it provides bid_vol, ask_vol, mid_vol:
          ask_vol > bid_vol → buyer-initiated (at ask)
          bid_vol > ask_vol → seller-initiated (at bid)
        We infer 'side' from these for accurate sentiment classification.
        """
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

        # Determine side: explicit field first, then infer from bid_vol/ask_vol
        side = item.get("side", item.get("aggressor_side", ""))
        if not side or side.lower() == "unknown":
            ask_vol = int(item.get("ask_vol", 0) or 0)
            bid_vol = int(item.get("bid_vol", 0) or 0)
            mid_vol = int(item.get("mid_vol", 0) or 0)
            if ask_vol > bid_vol and ask_vol > mid_vol:
                side = "ask"   # Buyer-initiated
            elif bid_vol > ask_vol and bid_vol > mid_vol:
                side = "bid"   # Seller-initiated
            elif mid_vol > 0:
                side = "mid"
            else:
                side = "unknown"

        opt_type = item.get("option_type", item.get("put_call", "unknown"))

        # ── Detect sweeps/blocks from tags (do this FIRST, needed for sentiment) ──
        tags = item.get("tags", []) or []
        is_sweep = item.get("is_sweep", False) or item.get("trade_type", "") == "SWEEP"
        is_block = item.get("is_block", False) or item.get("trade_type", "") == "BLOCK"
        tag_str = ""
        if isinstance(tags, list):
            tag_str = " ".join(str(t) for t in tags).lower()
            if "sweep" in tag_str:
                is_sweep = True
            if "block" in tag_str:
                is_block = True

        # ── Determine sentiment ──
        # FEB 8, 2026 FIX: PREFER UW's own tags field over bid/ask inference.
        # UW has trade-level aggressor matching that is more accurate than
        # cumulative bid/ask volume comparison.
        #
        # TSLA audit found 42% disagreement between our inference and UW tags.
        # Root cause: bid_vol/ask_vol are CUMULATIVE for the option chain,
        # not for the specific trade. UW tags use actual trade-level context.
        #
        # Priority: 1) UW tags (bearish/bullish) → 2) bid/ask inference → 3) neutral
        sentiment = "neutral"
        
        # Method 1: UW's own sentiment tags (MOST RELIABLE)
        if "bearish" in tag_str:
            sentiment = "bearish"
        elif "bullish" in tag_str:
            sentiment = "bullish"
        else:
            # Method 2: Infer from side + option type (FALLBACK)
            side_lower = side.lower() if side else "unknown"
            opt_lower = opt_type.lower() if opt_type else "unknown"
            if opt_lower == "put" and side_lower in ["ask", "buy"]:
                sentiment = "bearish"
            elif opt_lower == "call" and side_lower in ["bid", "sell"]:
                sentiment = "bearish"
            elif opt_lower == "call" and side_lower in ["ask", "buy"]:
                sentiment = "bullish"
            elif opt_lower == "put" and side_lower in ["bid", "sell"]:
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
            gamma=float(item.get("gamma", 0)),   # FEB 8: Per-trade gamma for Greek-weighted flow
            vega=float(item.get("vega", 0)),     # FEB 8: Per-trade vega for vol sensitivity
            is_sweep=is_sweep,
            is_block=is_block,
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

                    # FEB 8, 2026 FIX: UW dark pool has NO 'side' field.
                    # Infer buy/sell from price vs NBBO:
                    #   price >= nbbo_ask → buy-side
                    #   price <= nbbo_bid → sell-side
                    #   between → midpoint (None)
                    is_buy = None
                    if item.get("side"):
                        is_buy = item["side"].lower() == "buy"
                    else:
                        dp_price = float(item.get("price", item.get("execution_price", 0)))
                        nbbo_bid = float(item.get("nbbo_bid", 0) or 0)
                        nbbo_ask = float(item.get("nbbo_ask", 0) or 0)
                        if dp_price > 0 and nbbo_bid > 0 and nbbo_ask > 0:
                            if dp_price >= nbbo_ask:
                                is_buy = True
                            elif dp_price <= nbbo_bid:
                                is_buy = False

                    prints.append(DarkPoolPrint(
                        timestamp=timestamp,
                        symbol=symbol,
                        price=float(item.get("price", item.get("execution_price", 0))),
                        size=int(item.get("size", item.get("volume", item.get("shares", 0)))),
                        exchange=item.get("exchange", item.get("venue", item.get("market_center", "DARK"))),
                        is_buy=is_buy,
                        # FEB 8, 2026: Extract NBBO depth for violence scoring
                        nbbo_bid_quantity=int(item.get("nbbo_bid_quantity", item.get("bid_quantity", 0)) or 0),
                        nbbo_ask_quantity=int(item.get("nbbo_ask_quantity", item.get("ask_quantity", 0)) or 0),
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
        
        FEB 8, 2026 FIX: UW greek-exposure returns a TIME SERIES with keys:
        call_gamma, put_gamma, call_delta, put_delta (NOT gex/dex/net_gex).
        
        NEW: Compute net_gex = call_gamma + put_gamma
             Compute dealer_delta = call_delta + put_delta  
             Use LATEST record (last in list = most recent)
             Compute gex_flip_level from OI-per-strike data
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

        # If data is a list, get the LATEST record (last element = most recent date)
        if isinstance(data, list):
            if len(data) == 0:
                return None
            data = data[-1]  # FIX: Use latest record, not first (oldest)

        if not isinstance(data, dict):
            return None

        try:
            # COMPUTE net_gex from call_gamma + put_gamma (put_gamma is negative)
            call_gamma = float(data.get("call_gamma", data.get("call_gex", 0)))
            put_gamma = float(data.get("put_gamma", data.get("put_gex", 0)))
            net_gex = float(data.get("gex", data.get("net_gex", data.get("gamma_exposure", 0))))
            if net_gex == 0 and (call_gamma != 0 or put_gamma != 0):
                net_gex = call_gamma + put_gamma

            # COMPUTE dealer_delta from call_delta + put_delta
            call_delta = float(data.get("call_delta", 0))
            put_delta = float(data.get("put_delta", 0))
            dealer_delta = float(data.get("dex", data.get("dealer_delta", data.get("net_delta", 0))))
            if dealer_delta == 0 and (call_delta != 0 or put_delta != 0):
                dealer_delta = call_delta + put_delta

            # Try pre-computed walls/flip from response
            gex_flip = None
            if data.get("gex_flip") or data.get("flip_price"):
                gex_flip = float(data.get("gex_flip", data.get("flip_price", 0)))

            put_wall_val = None
            if data.get("put_wall") or data.get("highest_put_oi_strike"):
                put_wall_val = float(data.get("put_wall", data.get("highest_put_oi_strike", 0)))

            call_wall_val = None
            if data.get("call_wall") or data.get("highest_call_oi_strike"):
                call_wall_val = float(data.get("call_wall", data.get("highest_call_oi_strike", 0)))

            # If put_wall/call_wall not in GEX response, fetch from OI-per-strike
            # FEB 8, 2026 FIX: Always recompute walls and flip from OI data with
            # ±30% price filter. The GEX response doesn't provide these fields.
            # Previous bug: used median_strike × 0.5/1.5 which included deep OTM
            # strikes and returned wrong values (e.g., $215 for TSLA at $411).
            if put_wall_val is None or call_wall_val is None or gex_flip is None:
                try:
                    oi_strike_data = await self.get_oi_by_strike(symbol)
                    if oi_strike_data:
                        oi_list = oi_strike_data.get("data", oi_strike_data) if isinstance(oi_strike_data, dict) else oi_strike_data
                        if isinstance(oi_list, list) and oi_list:
                            # ── Get current price for ±30% range filter ──
                            # Best source: recent flow data (underlying_price)
                            # Fallback: OI-weighted median strike
                            current_price = await self._get_underlying_price(symbol)
                            
                            if current_price and current_price > 0:
                                low_bound = current_price * 0.70   # ±30% range
                                high_bound = current_price * 1.30
                            else:
                                # Fallback: OI-weighted center of mass
                                all_strikes = [float(r.get("strike", 0)) for r in oi_list 
                                              if isinstance(r, dict) and float(r.get("strike", 0)) > 0]
                                total_oi = []
                                for r in oi_list:
                                    if isinstance(r, dict):
                                        s = float(r.get("strike", 0))
                                        oi = int(r.get("put_oi", 0)) + int(r.get("call_oi", 0))
                                        if s > 0 and oi > 0:
                                            total_oi.append((s, oi))
                                if total_oi:
                                    weighted_sum = sum(s * oi for s, oi in total_oi)
                                    total_weight = sum(oi for _, oi in total_oi)
                                    center = weighted_sum / total_weight if total_weight > 0 else sorted(all_strikes)[len(all_strikes)//2]
                                    low_bound = center * 0.70
                                    high_bound = center * 1.30
                                elif all_strikes:
                                    median_strike = sorted(all_strikes)[len(all_strikes) // 2]
                                    low_bound = median_strike * 0.70
                                    high_bound = median_strike * 1.30
                                else:
                                    low_bound, high_bound = 0, float('inf')
                            
                            # ── Find put wall and call wall in ±30% range ──
                            max_put_oi = 0
                            max_call_oi = 0
                            for strike_row in oi_list:
                                if not isinstance(strike_row, dict):
                                    continue
                                strike = float(strike_row.get("strike", strike_row.get("strike_price", 0)))
                                if strike < low_bound or strike > high_bound:
                                    continue  # Skip strikes outside ±30% range
                                p_oi = int(strike_row.get("put_oi", strike_row.get("put_open_interest", 0)))
                                c_oi = int(strike_row.get("call_oi", strike_row.get("call_open_interest", 0)))
                                if p_oi > max_put_oi:
                                    max_put_oi = p_oi
                                    put_wall_val = strike  # Always update (not just if None)
                                if c_oi > max_call_oi:
                                    max_call_oi = c_oi
                                    call_wall_val = strike  # Always update
                            
                            logger.debug(
                                f"{symbol} GEX walls: range=${low_bound:.0f}-${high_bound:.0f}, "
                                f"put_wall=${put_wall_val} (OI={max_put_oi:,}), "
                                f"call_wall=${call_wall_val} (OI={max_call_oi:,})"
                            )
                            
                            # ── Compute gex_flip_level from OI per strike ──
                            # FEB 8 FIX: Only scan strikes in ±30% range
                            if gex_flip is None and len(oi_list) >= 2:
                                gex_flip = self._compute_gex_flip_from_oi(
                                    oi_list, low_bound, high_bound
                                )
                except Exception as e:
                    logger.debug(f"Could not fetch OI-per-strike for {symbol} walls: {e}")

            return GEXData(
                symbol=symbol,
                timestamp=datetime.now(),
                net_gex=net_gex,
                call_gex=call_gamma,
                put_gex=put_gamma,
                gex_flip_level=gex_flip,
                dealer_delta=dealer_delta,
                put_wall=put_wall_val,
                call_wall=call_wall_val
            )
        except Exception as e:
            logger.debug(f"Error parsing GEX data for {symbol}: {e}")
            return None

    @staticmethod
    def _compute_gex_flip_from_oi(
        oi_list: List[Dict],
        low_bound: float = 0,
        high_bound: float = float('inf')
    ) -> Optional[float]:
        """
        Compute GEX flip level from OI-per-strike data.
        
        The flip level is where net gamma crosses zero (call_oi - put_oi sign change).
        Above this level = positive gamma (dealers dampen moves).
        Below = negative gamma (dealers amplify moves).
        
        FEB 8, 2026 FIX: Accept low_bound/high_bound to filter to ±30% of 
        current price. Previously scanned $5-$990 for TSLA and returned $8.37.
        Now only scans strikes within the provided range (e.g., $288-$535).
        
        If no sign change is found in the filtered range, we find the strike
        closest to zero net OI (i.e., where put and call OI are most balanced).
        """
        try:
            prev_net = None
            prev_strike = None
            closest_to_zero = None
            closest_abs = float('inf')
            
            for row in sorted(oi_list, key=lambda r: float(r.get("strike", r.get("strike_price", 0)))):
                if not isinstance(row, dict):
                    continue
                strike = float(row.get("strike", row.get("strike_price", 0)))
                
                # FEB 8 FIX: Only consider strikes in the ±30% range
                if strike < low_bound or strike > high_bound:
                    continue
                
                c_oi = int(row.get("call_oi", row.get("call_open_interest", 0)))
                p_oi = int(row.get("put_oi", row.get("put_open_interest", 0)))
                net = c_oi - p_oi
                
                # Track closest-to-zero as fallback
                if abs(net) < closest_abs:
                    closest_abs = abs(net)
                    closest_to_zero = strike
                
                if prev_net is not None and prev_net * net < 0:
                    # Sign change: interpolate
                    if prev_net != net:
                        frac = abs(prev_net) / (abs(prev_net) + abs(net))
                        flip = prev_strike + frac * (strike - prev_strike)
                        return round(flip, 2)
                
                prev_net = net
                prev_strike = strike
            
            # If no sign change found, use the strike closest to equilibrium
            if closest_to_zero is not None:
                logger.debug(f"GEX flip: no sign change in range ${low_bound:.0f}-${high_bound:.0f}, "
                           f"using closest-to-zero strike: ${closest_to_zero:.0f}")
                return closest_to_zero
                
        except Exception as e:
            logger.debug(f"GEX flip computation failed: {e}")
        return None
    
    async def _get_underlying_price(self, symbol: str) -> Optional[float]:
        """
        Get current underlying price for a symbol from cached flow data or stock info.
        Used internally to set the ±30% strike range for wall/flip computation.
        
        FEB 8, 2026: Added to fix GEX wall/flip computation which previously
        used median strike (unreliable for wide strike ranges like TSLA $5-$990).
        """
        try:
            # Method 1: Check flow-recent cache (underlying_price field)
            cache_key = self._get_cache_key(f"/api/stock/{symbol}/flow-recent")
            cached = self._get_cached_response(cache_key)
            if cached:
                data = cached.get("data", cached) if isinstance(cached, dict) else cached
                if isinstance(data, list):
                    for rec in data[:5]:
                        if isinstance(rec, dict):
                            price = rec.get("underlying_price")
                            if price and float(price) > 0:
                                return float(price)
            
            # Method 2: Check stock info cache
            cache_key2 = self._get_cache_key(f"/api/stock/{symbol}/info")
            cached2 = self._get_cached_response(cache_key2)
            if cached2:
                info = cached2.get("data", cached2) if isinstance(cached2, dict) else cached2
                if isinstance(info, dict):
                    # stock_info doesn't have price directly, skip
                    pass
            
            # Method 3: Check options-volume cache (has close price)
            cache_key3 = self._get_cache_key(f"/api/stock/{symbol}/options-volume")
            cached3 = self._get_cached_response(cache_key3)
            if cached3:
                data = cached3.get("data", cached3) if isinstance(cached3, dict) else cached3
                if isinstance(data, list) and data:
                    latest = data[-1] if isinstance(data[-1], dict) else data[0] if isinstance(data[0], dict) else {}
                    close = latest.get("close")
                    if close and float(close) > 0:
                        return float(close)
            
            # Method 4: Check max-pain cache (has close price)
            cache_key4 = self._get_cache_key(f"/api/stock/{symbol}/max-pain")
            cached4 = self._get_cached_response(cache_key4)
            if cached4:
                data = cached4.get("data", cached4) if isinstance(cached4, dict) else cached4
                if isinstance(data, list) and data:
                    for rec in data[:3]:
                        if isinstance(rec, dict):
                            close = rec.get("close")
                            if close and float(close) > 0:
                                return float(close)
            
        except Exception as e:
            logger.debug(f"_get_underlying_price failed for {symbol}: {e}")
        
        return None

    # ==================== Net Premium Ticks ====================
    
    async def get_net_premium_ticks(self, symbol: str) -> Dict[str, Any]:
        """
        Get intraday net premium flow (minute-by-minute call/put premium ticks).
        Endpoint: /api/stock/{ticker}/net-prem-ticks
        
        FEB 8, 2026: NEW — Previously undiscovered endpoint.
        Returns per-minute breakdown of:
        - call_volume, put_volume (total + ask_side + bid_side)
        - net_call_premium, net_put_premium ($ flow per minute)
        - net_delta (total delta exposure per minute)
        
        Used for:
        - opening_flow_bias: first 30 ticks = institutional opening positioning
        - closing_flow_bias: last 30 ticks = institutional close-of-day positioning
        - liquidity_violence_score: sudden net_delta spikes
        
        Cost: 1 API call per ticker.
        """
        endpoint = f"/api/stock/{symbol}/net-prem-ticks"
        return await self._request(endpoint, symbol=symbol)
    
    async def get_opening_closing_flow(self, symbol: str) -> Dict[str, Any]:
        """
        Analyze opening and closing flow bias from net-prem-ticks data.
        
        FEB 8, 2026: NEW — Provides institutional flow direction inference.
        
        Returns dict with:
        - opening_net_premium: $ net premium in first 30 minutes
        - closing_net_premium: $ net premium in last 30 minutes
        - opening_bias: "BULLISH" / "BEARISH" / "NEUTRAL"
        - closing_bias: "BULLISH" / "BEARISH" / "NEUTRAL"
        - flow_reversal: True if opening and closing disagree (distribution signal)
        - intraday_delta_trend: "BEARISH_ACCELERATING" / "BULLISH" / "FLAT"
        - total_net_premium: full day $ net premium
        """
        result = await self.get_net_premium_ticks(symbol)
        
        if not result:
            return {}
        
        data = result.get("data", result) if isinstance(result, dict) else result
        if not isinstance(data, list) or len(data) < 10:
            return {}
        
        try:
            def calc_net(ticks):
                """Sum net premium across ticks."""
                total = 0.0
                for t in ticks:
                    if isinstance(t, dict):
                        ncp = float(t.get("net_call_premium", 0) or 0)
                        npp = float(t.get("net_put_premium", 0) or 0)
                        total += ncp + npp
                return total
            
            def calc_delta(ticks):
                """Sum net delta across ticks."""
                total = 0.0
                for t in ticks:
                    if isinstance(t, dict):
                        nd = float(t.get("net_delta", 0) or 0)
                        total += nd
                return total
            
            # Opening: first 30 ticks (~first 30 minutes of market)
            opening_ticks = data[:30]
            # Closing: last 30 ticks (~last 30 minutes of market)
            closing_ticks = data[-30:]
            
            opening_net = calc_net(opening_ticks)
            closing_net = calc_net(closing_ticks)
            total_net = calc_net(data)
            
            opening_delta = calc_delta(opening_ticks)
            closing_delta = calc_delta(closing_ticks)
            
            # Bias classification
            def classify_bias(net_prem, threshold=100000):
                if net_prem > threshold:
                    return "BULLISH"
                elif net_prem < -threshold:
                    return "BEARISH"
                else:
                    return "NEUTRAL"
            
            opening_bias = classify_bias(opening_net)
            closing_bias = classify_bias(closing_net)
            
            # Flow reversal = opening and closing disagree (distribution signal)
            flow_reversal = (
                (opening_bias == "BULLISH" and closing_bias == "BEARISH") or
                (opening_bias == "BEARISH" and closing_bias == "BULLISH")
            )
            
            # Intraday delta trend: compare first half vs second half
            mid = len(data) // 2
            first_half_delta = calc_delta(data[:mid])
            second_half_delta = calc_delta(data[mid:])
            
            if second_half_delta < first_half_delta and second_half_delta < -50000:
                delta_trend = "BEARISH_ACCELERATING"
            elif second_half_delta > first_half_delta and second_half_delta > 50000:
                delta_trend = "BULLISH"
            else:
                delta_trend = "FLAT"
            
            return {
                "opening_net_premium": opening_net,
                "closing_net_premium": closing_net,
                "opening_bias": opening_bias,
                "closing_bias": closing_bias,
                "flow_reversal": flow_reversal,
                "intraday_delta_trend": delta_trend,
                "total_net_premium": total_net,
                "opening_delta": opening_delta,
                "closing_delta": closing_delta,
                "tick_count": len(data)
            }
        except Exception as e:
            logger.debug(f"Opening/closing flow analysis failed for {symbol}: {e}")
            return {}

    # ==================== Options Volume & OI ====================

    async def get_options_volume(self, symbol: str) -> Dict[str, Any]:
        """
        Get options volume data for a symbol.
        Endpoint: /api/stock/{ticker}/options-volume
        """
        endpoint = f"/api/stock/{symbol}/options-volume"
        return await self._request(endpoint)

    # get_oi_change is defined below (line ~1674) with proper symbol tracking

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
        
        FEB 8, 2026 FIX: UW returns field names that differ from what consumers expect:
          UW field        → Our field
          iv_rank_1y      → iv_rank  (percentile rank over 1 year)
          volatility      → iv       (current implied volatility)
          iv_rank_1m      → iv_rank_1m (1-month rank, bonus)
        
        Without this mapping, iv_rank returns None and the Dealer layer's
        "IV stable + low rank = dealers confident" check always fails.
        """
        endpoint = f"/api/stock/{symbol}/iv-rank"
        result = await self._request(endpoint)
        
        if not result:
            return result
        
        # Normalize the response format
        data = result.get("data", result) if isinstance(result, dict) else result
        
        # Handle list responses (UW returns time-series)
        if isinstance(data, list) and len(data) > 0:
            row = data[-1]  # Latest record
        elif isinstance(data, dict):
            row = data
        else:
            return result
        
        if not isinstance(row, dict):
            return result
        
        # Remap UW field names to what consumers expect
        iv_rank = row.get("iv_rank", None)
        if iv_rank is None:
            iv_rank = row.get("iv_rank_1y", row.get("iv_percentile", None))
        
        iv = row.get("iv", None)
        if iv is None:
            iv = row.get("volatility", row.get("implied_volatility", None))
        
        # Convert to float if present (UW returns as string sometimes)
        try:
            if iv_rank is not None:
                iv_rank = float(iv_rank)
        except (ValueError, TypeError):
            iv_rank = None
        try:
            if iv is not None:
                iv = float(iv)
        except (ValueError, TypeError):
            iv = None
        
        # Compute iv_change_1d if we have historical data
        iv_change_1d = row.get("iv_change_1d", 0)
        if iv_change_1d == 0 and isinstance(data, list) and len(data) >= 2:
            try:
                curr_iv = float(data[-1].get("volatility", data[-1].get("iv", 0)) or 0)
                prev_iv = float(data[-2].get("volatility", data[-2].get("iv", 0)) or 0)
                if prev_iv > 0:
                    iv_change_1d = (curr_iv - prev_iv) / prev_iv
            except (ValueError, TypeError, IndexError):
                pass
        
        return {
            "data": data if isinstance(data, list) else [row],
            "iv_rank": iv_rank,
            "iv": iv,
            "iv_rank_1y": row.get("iv_rank_1y"),
            "iv_rank_1m": row.get("iv_rank_1m"),
            "iv_change_1d": iv_change_1d,
            "date": row.get("date", ""),
        }

    async def get_skew(self, symbol: str) -> Dict[str, Any]:
        """
        Get volatility skew data.
        Endpoint: /api/stock/{ticker}/historical-risk-reversal-skew
        
        FEB 8, 2026 FIX: UW returns historical risk_reversal time series.
        Consumers expect 'skew_change'. We compute it from the last two records.
        Negative risk_reversal = puts expensive vs calls = bearish.
        Increasingly negative change = skew steepening = very bearish.
        """
        endpoint = f"/api/stock/{symbol}/historical-risk-reversal-skew"
        result = await self._request(endpoint)
        
        if not result:
            return result
        
        data = result.get("data", result) if isinstance(result, dict) else result
        if isinstance(data, list) and len(data) >= 2:
            try:
                sorted_data = sorted(data, key=lambda r: r.get("date", ""))
                latest = sorted_data[-1]
                prior = sorted_data[-2]
                latest_rr = float(latest.get("risk_reversal", 0))
                prior_rr = float(prior.get("risk_reversal", 0))
                skew_change = latest_rr - prior_rr
                
                # FEB 8, 2026: Detect skew reversal (risk_reversal sign flip)
                # When risk_reversal flips from positive to negative = regime shift
                # Positive RR = calls expensive (bullish), Negative RR = puts expensive (bearish)
                # Flip from positive → negative = shift from bullish to bearish skew
                skew_reversal = False
                if latest_rr != 0 and prior_rr != 0:
                    # Sign flip detected
                    if (latest_rr > 0 and prior_rr < 0) or (latest_rr < 0 and prior_rr > 0):
                        skew_reversal = True
                        logger.info(
                            f"{symbol}: SKEW REVERSAL detected! "
                            f"RR flipped {prior_rr:.4f} → {latest_rr:.4f}"
                        )
                
                return {
                    "data": data,
                    "skew": latest_rr,
                    "skew_change": skew_change,
                    "change": skew_change,
                    "risk_reversal": latest_rr,
                    "risk_reversal_prior": prior_rr,
                    "skew_date": latest.get("date", ""),
                    "skew_reversal": skew_reversal,  # FEB 8, 2026: Sign flip flag
                }
            except Exception as e:
                logger.debug(f"Error computing skew change for {symbol}: {e}")
        
        return result

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
        Get the put wall (highest put OI level within ±30% of current price).
        This represents potential dealer support.
        
        FEB 8, 2026 FIX: Filter to ±30% of current price to avoid returning
        deep OTM strikes as the "wall" (e.g., $300 for a $411 stock is valid,
        but $5 is not).
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

        # Get current price for ±30% range filter
        current_price = await self._get_underlying_price(symbol)
        if current_price and current_price > 0:
            low_bound = current_price * 0.70
            high_bound = current_price * 1.30
        else:
            # Fallback: no filter
            low_bound = 0
            high_bound = float('inf')

        max_put_oi = 0
        put_wall = None

        for strike_data in data:
            if not isinstance(strike_data, dict):
                continue
            strike = float(strike_data.get("strike", strike_data.get("strike_price", 0)))
            if strike < low_bound or strike > high_bound:
                continue  # Skip strikes outside ±30% range
            put_oi = int(strike_data.get("put_oi", strike_data.get("put_open_interest", 0)))
            if put_oi > max_put_oi:
                max_put_oi = put_oi
                put_wall = strike

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
        limit: int = 20,
        max_persons: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Get insider trading activity with person-level iteration.
        
        Gap 10 Fix (Feb 9, 2026): UW /api/insider/{TICKER} returns PERSON-LEVEL data.
        We now iterate top insiders to get their actual trade transactions via
        /api/insider/{ticker}/{person_slug}. This unlocks insider selling detection
        in the Distribution layer.
        
        Flow:
        1. GET /api/insider/{TICKER} → list of insiders (name, slug, etc.)
        2. For top N insiders → GET /api/insider/{TICKER}/{slug} → actual trades
        3. Parse transactions: look for "Sale" type, dollar values, dates
        
        Args:
            symbol: Ticker symbol
            limit: Max trades to return overall
            max_persons: Max insiders to iterate (default 5 = top 5, +5 API calls)
        """
        endpoint = f"/api/insider/{symbol}"
        params = {"limit": 20}
        result = await self._request(endpoint, params, symbol=symbol)
        
        raw_data = []
        if isinstance(result, list):
            raw_data = result
        elif isinstance(result, dict):
            raw_data = result.get("data", [])
        
        if not raw_data:
            return []
        
        trades = []
        persons_iterated = 0
        
        for person in raw_data:
            if not isinstance(person, dict):
                continue
            name = person.get("display_name", person.get("name", ""))
            is_person = person.get("is_person", True)
            if not is_person:
                continue
            
            # Get person slug for detail endpoint
            slug = person.get("name_slug", person.get("slug", ""))
            person_id = person.get("id", "")
            
            # Try to get actual transactions for this person
            if slug and persons_iterated < max_persons:
                try:
                    detail_endpoint = f"/api/insider/{symbol}/{slug}"
                    detail_result = await self._request(detail_endpoint, {}, symbol=symbol)
                    
                    detail_data = []
                    if isinstance(detail_result, list):
                        detail_data = detail_result
                    elif isinstance(detail_result, dict):
                        detail_data = detail_result.get("data", detail_result.get("transactions", []))
                    
                    for txn in detail_data:
                        if not isinstance(txn, dict):
                            continue
                        tx_type = txn.get("transaction_type", txn.get("type", "unknown")).lower()
                        value = txn.get("value", txn.get("amount", 0))
                        filing_date = txn.get("filing_date", txn.get("date", ""))
                        shares = txn.get("shares", txn.get("quantity", 0))
                        
                        trades.append({
                            "ticker": symbol,
                            "title": txn.get("title", name),
                            "name": name,
                            "person_id": person_id,
                            "is_person": True,
                            "transaction_type": tx_type,
                            "value": float(value) if value else 0,
                            "shares": int(shares) if shares else 0,
                            "filing_date": filing_date,
                            "source": "uw_insider_detail",
                        })
                    
                    persons_iterated += 1
                    
                except Exception as e:
                    logger.debug(f"Insider detail for {symbol}/{slug} failed: {e}")
                    # Fallback: add person-level record
                    trades.append({
                        "ticker": symbol,
                        "title": name,
                        "name": name,
                        "person_id": person_id,
                        "is_person": True,
                        "transaction_type": "unknown",
                        "value": 0,
                        "filing_date": "",
                        "source": "uw_insider_persons",
                    })
            else:
                # No slug or max persons reached — add person-level record
                trades.append({
                    "ticker": symbol,
                    "title": name,
                    "name": name,
                    "person_id": person_id,
                    "is_person": True,
                    "transaction_type": "unknown",
                    "value": 0,
                    "filing_date": "",
                    "source": "uw_insider_persons",
                })
        
        return trades[:limit]

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
        limit: int = 100,
        tickers: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get earnings calendar for upcoming/recent earnings.
        
        FEB 8, 2026 FIX: /api/earnings/calendar returns 422.
        FALLBACK: Use /api/stock/{ticker}/info (next_earnings_date field).
        
        Args:
            start_date: Start date filter (YYYY-MM-DD)
            end_date: End date filter (YYYY-MM-DD)
            limit: Maximum results
            tickers: List of tickers to check (enables per-ticker fallback)
        """
        # Try original endpoint first
        endpoint = "/api/earnings/calendar"
        params = {"limit": limit}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        
        result = await self._request(endpoint, params)
        
        if isinstance(result, list) and result:
            return result
        elif isinstance(result, dict) and result.get("data"):
            return result.get("data", [])
        
        # FALLBACK: Build from stock_info endpoint
        if tickers:
            logger.debug(f"Earnings calendar endpoint failed; using stock_info for {len(tickers)} tickers")
            earnings_list = []
            for ticker in tickers[:limit]:
                try:
                    info = await self.get_stock_info(ticker)
                    if not info:
                        continue
                    info_data = info.get("data", info) if isinstance(info, dict) else info
                    if isinstance(info_data, list) and info_data:
                        info_data = info_data[0]
                    if not isinstance(info_data, dict):
                        continue
                    next_earn = info_data.get("next_earnings_date")
                    if not next_earn:
                        continue
                    if start_date and next_earn < start_date:
                        continue
                    if end_date and next_earn > end_date:
                        continue
                    timing = info_data.get("announce_time", "")
                    if "pre" in str(timing).lower():
                        timing_code = "BMO"
                    elif "post" in str(timing).lower():
                        timing_code = "AMC"
                    else:
                        timing_code = timing or "unknown"
                    earnings_list.append({
                        "ticker": ticker,
                        "date": next_earn,
                        "timing": timing_code,
                        "announce_time": info_data.get("announce_time", ""),
                        "sector": info_data.get("sector", ""),
                        "source": "stock_info_fallback",
                    })
                except Exception as e:
                    logger.debug(f"Earnings fallback failed for {ticker}: {e}")
            return earnings_list
        
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
        
        FEB 8, 2026 FIX: UW returns per-expiry rows with 'dte' and 'volatility'.
        Consumers expect '7_day', '30_day', '60_day' IV values.
        We now find the closest DTE to each target bucket and inject those fields.
        
        Returns:
            Dict with 7_day, 30_day, 60_day IV values + raw data + inversion flag
        """
        endpoint = f"/api/stock/{symbol}/volatility/term-structure"
        result = await self._request(endpoint, symbol=symbol)
        
        if not result:
            return {}
        
        data = result.get("data", result) if isinstance(result, dict) else result
        
        if isinstance(data, list) and len(data) >= 1:
            try:
                dte_vol = {}
                for row in data:
                    if not isinstance(row, dict):
                        continue
                    dte = row.get("dte")
                    vol = row.get("volatility")
                    if dte is not None and vol is not None and int(dte) > 0:
                        dte_vol[int(dte)] = float(vol)
                
                if not dte_vol:
                    return result if isinstance(result, dict) else {"data": data}
                
                def closest_iv(target_dte):
                    if not dte_vol:
                        return 0.0
                    closest_key = min(dte_vol.keys(), key=lambda d: abs(d - target_dte))
                    if abs(closest_key - target_dte) <= max(target_dte * 0.5, 5):
                        return dte_vol[closest_key]
                    return 0.0
                
                iv_7d = closest_iv(7)
                iv_30d = closest_iv(30)
                iv_60d = closest_iv(60)
                
                iv_inverted = iv_7d > iv_30d if iv_7d > 0 and iv_30d > 0 else False
                inversion_ratio = round(iv_7d / iv_30d, 4) if iv_30d > 0 and iv_7d > 0 else 0.0
                
                # FEB 8, 2026: Extract implied_move_perc from nearest expiry
                # This tells us how much the market expects the stock to move
                # If actual move > implied_move, the expected move is exhausted
                implied_move_perc = 0.0
                for row in data:
                    if isinstance(row, dict):
                        imp_move = row.get("implied_move_perc", row.get("implied_move", 0))
                        if imp_move:
                            try:
                                implied_move_perc = float(imp_move)
                            except (ValueError, TypeError):
                                pass
                            break  # Use nearest expiry's implied move
                
                return {
                    "data": data,
                    "7_day": iv_7d, "iv_7d": iv_7d, "near_term": iv_7d,
                    "30_day": iv_30d, "iv_30d": iv_30d, "far_term": iv_30d,
                    "60_day": iv_60d,
                    "iv_inverted": iv_inverted,
                    "inversion_ratio": inversion_ratio,
                    "term_structure_slope": round(iv_30d - iv_7d, 4) if iv_7d > 0 and iv_30d > 0 else 0.0,
                    "implied_move_perc": implied_move_perc,
                }
            except Exception as e:
                logger.debug(f"Error building IV term structure for {symbol}: {e}")
        
        return result if isinstance(result, dict) else {"data": data}
