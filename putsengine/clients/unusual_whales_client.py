"""
Unusual Whales API Client for options flow data.
Provides institutional flow detection, dark pool data, and options analytics.

API Documentation: https://api.unusualwhales.com/docs
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
import aiohttp
from loguru import logger

from putsengine.config import Settings
from putsengine.models import OptionsFlow, DarkPoolPrint, GEXData


class UnusualWhalesClient:
    """
    Client for Unusual Whales API.

    Rate limit: 5,000 calls/day, ~2 requests/second
    Strategy: Use surgical queries only after Alpaca pre-filtering.

    API Base: https://api.unusualwhales.com
    Docs: https://api.unusualwhales.com/docs
    """

    BASE_URL = "https://api.unusualwhales.com"
    
    # Rate limiting: ~2 requests per second to avoid 429 errors
    MIN_REQUEST_INTERVAL = 0.5  # 500ms between requests

    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_key = settings.unusual_whales_api_key
        self.daily_limit = settings.uw_daily_limit
        self._session: Optional[aiohttp.ClientSession] = None
        self._calls_today = 0
        self._calls_reset_date = date.today()
        self._last_request_time = 0.0  # For rate limiting
        self._rate_limit_lock: Optional[asyncio.Lock] = None  # Lazy init for thread-safe rate limiting

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
        params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make HTTP request to Unusual Whales API."""
        # Check daily limit
        if self.remaining_calls <= 0:
            logger.error("Unusual Whales daily API limit reached!")
            return {}

        # Rate limiting - wait between requests
        await self._rate_limit_wait()

        url = f"{self.BASE_URL}{endpoint}"
        session = await self._get_session()

        try:
            async with session.get(url, params=params) as response:
                self._calls_today += 1

                if response.status == 200:
                    return await response.json()
                elif response.status == 429:
                    # Rate limited - wait longer and retry once
                    logger.debug("UW rate limit - waiting 2s before retry")
                    await asyncio.sleep(2.0)
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
        limit: int = 50
    ) -> List[OptionsFlow]:
        """
        Get recent options flow for a symbol.
        Endpoint: /api/stock/{ticker}/flow-recent
        """
        endpoint = f"/api/stock/{symbol}/flow-recent"
        params = {"limit": limit}

        result = await self._request(endpoint, params)
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

        result = await self._request(endpoint, params)
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

        result = await self._request(endpoint, params)
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
