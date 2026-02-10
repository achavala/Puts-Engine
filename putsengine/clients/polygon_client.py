"""
Polygon.io API Client for market data.

FEB 4, 2026 UPDATE - SUBSCRIPTION STATUS:
==================================================
User has MASSIVE (Polygon) PAID subscription:
- ✅ UNLIMITED API calls
- ✅ Real-time stock AND options data
- ✅ Greeks, IV, Open Interest, GEX
- ✅ Technical indicators (SMA, EMA, RSI, MACD)
- ✅ Snapshots for real-time quotes

PRIMARY DATA SOURCE for all scans (replacing Alpaca)
==================================================
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
import aiohttp
from loguru import logger

from putsengine.config import Settings
from putsengine.models import PriceBar, OptionsContract, DarkPoolPrint


class PolygonClient:
    """
    Client for Polygon.io Market Data API.
    
    Subscription: OPTIONS ADVANCED ($199/month)
    - Unlimited API Calls
    - Real-time Data
    - 5+ Years Historical Data
    - Greeks, IV, & Open Interest
    """

    BASE_URL = "https://api.polygon.io"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_key = settings.polygon_api_key
        self.rate_limit = settings.polygon_rate_limit  # Default 100 for paid plans
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_loop_id: Optional[int] = None  # Track which event loop owns the session
        self._last_request_time = 0.0
        self._request_interval = 1.0 / max(self.rate_limit, 10)  # Minimum 10 req/sec

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
            
            self._session = aiohttp.ClientSession()
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
        """Wait to respect rate limits."""
        import time
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._request_interval:
            await asyncio.sleep(self._request_interval - elapsed)
        self._last_request_time = time.time()

    async def _request(
        self,
        endpoint: str,
        params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make HTTP request to Polygon API."""
        await self._rate_limit_wait()

        url = f"{self.BASE_URL}{endpoint}"
        if params is None:
            params = {}
        params["apiKey"] = self.api_key

        session = await self._get_session()
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 429:
                        # For paid plans (unlimited), this should be rare
                        # Use exponential backoff: 2s, 4s, 8s
                        wait_time = 2 ** (attempt + 1)
                        logger.warning(f"Polygon rate limit (attempt {attempt+1}/{max_retries}), waiting {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    elif response.status == 403:
                        logger.error("Polygon API key invalid or subscription issue")
                        return {}
                    else:
                        error_text = await response.text()
                        logger.error(f"Polygon API error {response.status}: {error_text}")
                        return {}
            except asyncio.TimeoutError:
                logger.warning(f"Polygon request timeout (attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(1)
                continue
            except Exception as e:
                logger.error(f"Polygon request failed: {e}")
                return {}
        
        logger.error(f"Polygon request failed after {max_retries} retries")
        return {}

    # ==================== Aggregates / Bars ====================

    async def get_aggregates(
        self,
        symbol: str,
        multiplier: int = 1,
        timespan: str = "minute",
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        limit: int = 5000
    ) -> List[PriceBar]:
        """
        Get aggregate bars for a symbol.

        Args:
            symbol: Stock ticker symbol
            multiplier: Timespan multiplier (e.g., 1 for 1-minute bars)
            timespan: minute, hour, day, week, month, quarter, year
            from_date: Start date
            to_date: End date
            limit: Maximum number of results
        """
        if from_date is None:
            from_date = date.today() - timedelta(days=7)
        if to_date is None:
            to_date = date.today()

        endpoint = f"/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{from_date.isoformat()}/{to_date.isoformat()}"
        params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": limit
        }

        result = await self._request(endpoint, params)
        bars = []

        if "results" in result:
            for bar in result["results"]:
                bars.append(PriceBar(
                    timestamp=datetime.fromtimestamp(bar["t"] / 1000),
                    open=float(bar["o"]),
                    high=float(bar["h"]),
                    low=float(bar["l"]),
                    close=float(bar["c"]),
                    volume=int(bar["v"]),
                    vwap=float(bar.get("vw", 0))
                ))
        return bars

    async def get_daily_bars(
        self,
        symbol: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        limit: int = None
    ) -> List[PriceBar]:
        """Get daily bars for a symbol.
        
        FEB 10 FIX: Added limit parameter for compatibility with scanners
        (pump-dump, big-movers, vol-price-div, gap, precatalyst) that
        pass limit=N instead of from_date/to_date.
        """
        if limit is not None and from_date is None:
            from_date = date.today() - timedelta(days=limit + 5)
        if to_date is None:
            to_date = date.today()
        return await self.get_aggregates(
            symbol=symbol,
            multiplier=1,
            timespan="day",
            from_date=from_date,
            to_date=to_date
        )

    async def get_minute_bars(
        self,
        symbol: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        limit: int = 5000
    ) -> List[PriceBar]:
        """Get minute bars for a symbol."""
        return await self.get_aggregates(
            symbol=symbol,
            multiplier=1,
            timespan="minute",
            from_date=from_date,
            to_date=to_date,
            limit=limit
        )

    async def get_latest_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get latest quote (bid/ask) for a symbol using Polygon snapshot.
        Compatible with Alpaca's get_latest_quote() interface.
        
        Returns:
            Dict with 'bid', 'ask', 'bid_size', 'ask_size', 'price' keys
        """
        try:
            snapshot = await self.get_snapshot(symbol)
            if not snapshot or "ticker" not in snapshot:
                return None
            
            ticker_data = snapshot.get("ticker", {})
            last_quote = ticker_data.get("lastQuote", {})
            last_trade = ticker_data.get("lastTrade", {})
            
            return {
                "bid": last_quote.get("p", 0),  # bid price
                "ask": last_quote.get("P", 0),  # ask price
                "bid_size": last_quote.get("s", 0),
                "ask_size": last_quote.get("S", 0),
                "price": last_trade.get("p", 0),  # last trade price
                "volume": ticker_data.get("day", {}).get("v", 0),
                "timestamp": last_trade.get("t", None)
            }
        except Exception as e:
            logger.error(f"Error getting latest quote for {symbol}: {e}")
            return None

    async def get_latest_bar(self, symbol: str) -> Optional[PriceBar]:
        """
        Get the most recent bar for a symbol.
        Compatible with Alpaca's get_latest_bar() interface.
        
        Returns:
            PriceBar with today's OHLCV data
        """
        try:
            snapshot = await self.get_snapshot(symbol)
            if not snapshot or "ticker" not in snapshot:
                return None
            
            ticker_data = snapshot.get("ticker", {})
            day_data = ticker_data.get("day", {})
            prev_day = ticker_data.get("prevDay", {})
            
            if not day_data:
                return None
            
            return PriceBar(
                timestamp=datetime.now(),
                open=float(day_data.get("o", prev_day.get("c", 0))),
                high=float(day_data.get("h", 0)),
                low=float(day_data.get("l", 0)),
                close=float(day_data.get("c", 0)),
                volume=int(day_data.get("v", 0)),
                vwap=float(day_data.get("vw", 0))
            )
        except Exception as e:
            logger.error(f"Error getting latest bar for {symbol}: {e}")
            return None

    async def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Get the current price for a symbol (real-time).
        
        Returns:
            Current price as float, or None if unavailable
        """
        try:
            snapshot = await self.get_snapshot(symbol)
            if not snapshot or "ticker" not in snapshot:
                return None
            
            ticker_data = snapshot.get("ticker", {})
            last_trade = ticker_data.get("lastTrade", {})
            
            return float(last_trade.get("p", 0))
        except Exception as e:
            logger.error(f"Error getting current price for {symbol}: {e}")
            return None

    async def get_intraday_change(self, symbol: str) -> Optional[float]:
        """
        Get intraday price change percentage.
        
        Returns:
            Change percentage (e.g., -5.2 for -5.2%)
        """
        try:
            snapshot = await self.get_snapshot(symbol)
            if not snapshot or "ticker" not in snapshot:
                return None
            
            ticker_data = snapshot.get("ticker", {})
            today_change = ticker_data.get("todaysChangePerc", None)
            
            return float(today_change) if today_change is not None else None
        except Exception as e:
            logger.error(f"Error getting intraday change for {symbol}: {e}")
            return None

    # ==================== Snapshots ====================

    async def get_snapshot(self, symbol: str) -> Dict[str, Any]:
        """Get current snapshot for a symbol."""
        endpoint = f"/v2/snapshot/locale/us/markets/stocks/tickers/{symbol}"
        return await self._request(endpoint)

    async def get_all_tickers_snapshot(self) -> List[Dict[str, Any]]:
        """Get snapshots for all tickers."""
        endpoint = "/v2/snapshot/locale/us/markets/stocks/tickers"
        result = await self._request(endpoint)
        return result.get("tickers", [])

    async def get_gainers_losers(
        self,
        direction: str = "losers"
    ) -> List[Dict[str, Any]]:
        """Get top gainers or losers."""
        endpoint = f"/v2/snapshot/locale/us/markets/stocks/{direction}"
        result = await self._request(endpoint)
        return result.get("tickers", [])

    # ==================== Options ====================

    async def get_options_contract(
        self,
        contract_symbol: str
    ) -> Dict[str, Any]:
        """Get details for an options contract."""
        endpoint = f"/v3/reference/options/contracts/{contract_symbol}"
        return await self._request(endpoint)

    async def get_options_chain(
        self,
        underlying: str,
        expiration_date: Optional[date] = None,
        contract_type: Optional[str] = None,
        strike_price_gte: Optional[float] = None,
        strike_price_lte: Optional[float] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Get options chain for an underlying."""
        endpoint = "/v3/reference/options/contracts"
        params = {
            "underlying_ticker": underlying,
            "limit": limit
        }

        if expiration_date:
            params["expiration_date"] = expiration_date.isoformat()
        if contract_type:
            params["contract_type"] = contract_type
        if strike_price_gte:
            params["strike_price.gte"] = strike_price_gte
        if strike_price_lte:
            params["strike_price.lte"] = strike_price_lte

        result = await self._request(endpoint, params)
        return result.get("results", [])

    async def get_options_snapshot(
        self,
        underlying: str
    ) -> Dict[str, Any]:
        """Get options snapshot for an underlying."""
        endpoint = f"/v3/snapshot/options/{underlying}"
        return await self._request(endpoint)

    async def get_options_quotes(
        self,
        contract_symbol: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Get historical quotes for an options contract."""
        endpoint = f"/v3/quotes/{contract_symbol}"
        params = {"limit": limit}

        if from_date:
            params["timestamp.gte"] = f"{from_date.isoformat()}T00:00:00Z"
        if to_date:
            params["timestamp.lte"] = f"{to_date.isoformat()}T23:59:59Z"

        result = await self._request(endpoint, params)
        return result.get("results", [])

    # ==================== Technical Indicators ====================

    async def get_sma(
        self,
        symbol: str,
        window: int = 20,
        timespan: str = "day",
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get Simple Moving Average."""
        endpoint = f"/v1/indicators/sma/{symbol}"
        params = {
            "timespan": timespan,
            "window": window,
            "limit": limit
        }
        result = await self._request(endpoint, params)
        return result.get("results", {}).get("values", [])

    async def get_ema(
        self,
        symbol: str,
        window: int = 20,
        timespan: str = "day",
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get Exponential Moving Average."""
        endpoint = f"/v1/indicators/ema/{symbol}"
        params = {
            "timespan": timespan,
            "window": window,
            "limit": limit
        }
        result = await self._request(endpoint, params)
        return result.get("results", {}).get("values", [])

    async def get_rsi(
        self,
        symbol: str,
        window: int = 14,
        timespan: str = "day",
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get Relative Strength Index."""
        endpoint = f"/v1/indicators/rsi/{symbol}"
        params = {
            "timespan": timespan,
            "window": window,
            "limit": limit
        }
        result = await self._request(endpoint, params)
        return result.get("results", {}).get("values", [])

    async def get_macd(
        self,
        symbol: str,
        short_window: int = 12,
        long_window: int = 26,
        signal_window: int = 9,
        timespan: str = "day",
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get MACD indicator."""
        endpoint = f"/v1/indicators/macd/{symbol}"
        params = {
            "timespan": timespan,
            "short_window": short_window,
            "long_window": long_window,
            "signal_window": signal_window,
            "limit": limit
        }
        result = await self._request(endpoint, params)
        return result.get("results", {}).get("values", [])

    # ==================== Reference Data ====================

    async def get_ticker_details(self, symbol: str) -> Dict[str, Any]:
        """Get detailed information about a ticker."""
        endpoint = f"/v3/reference/tickers/{symbol}"
        return await self._request(endpoint)

    async def get_related_companies(self, symbol: str) -> List[str]:
        """Get related companies for a ticker."""
        endpoint = f"/v1/related-companies/{symbol}"
        result = await self._request(endpoint)
        return [r.get("ticker") for r in result.get("results", [])]

    async def get_market_holidays(self) -> List[Dict[str, Any]]:
        """Get market holidays."""
        endpoint = "/v1/marketstatus/upcoming"
        result = await self._request(endpoint)
        return result if isinstance(result, list) else []

    async def get_market_status(self) -> Dict[str, Any]:
        """Get current market status."""
        endpoint = "/v1/marketstatus/now"
        return await self._request(endpoint)

    # ==================== News ====================

    async def get_ticker_news(
        self,
        symbol: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get news articles for a ticker."""
        endpoint = "/v2/reference/news"
        params = {
            "ticker": symbol,
            "limit": limit,
            "sort": "published_utc"
        }
        result = await self._request(endpoint, params)
        return result.get("results", [])

    async def check_earnings_proximity(
        self,
        symbol: str,
        lookback_days: int = 30
    ) -> Dict[str, Any]:
        """
        Check earnings proximity using news analysis.
        
        Per Final Architect Report:
        - Never buy puts BEFORE earnings
        - Buy 1 day AFTER earnings only if gap down + VWAP reclaim fails
        
        Returns:
            Dict with earnings-related signals
        """
        result = {
            "has_recent_earnings": False,
            "is_pre_earnings": False,
            "is_post_earnings": False,
            "days_to_earnings": None,
            "days_since_earnings": None,
            "guidance_sentiment": "neutral",
            "earnings_keywords_found": []
        }
        
        try:
            news = await self.get_ticker_news(symbol, limit=50)
            
            # Earnings-related keywords
            earnings_keywords = [
                "earnings", "quarterly results", "q1", "q2", "q3", "q4",
                "eps", "revenue", "guidance", "outlook", "forecast",
                "beat", "miss", "exceeded", "fell short"
            ]
            
            # Bearish guidance keywords (for post-earnings put opportunities)
            bearish_keywords = [
                "cuts", "lowers", "reduces", "misses", "disappoints",
                "below expectations", "weak guidance", "lowered outlook",
                "revenue miss", "eps miss", "warns"
            ]
            
            # Bullish keywords (avoid puts)
            bullish_keywords = [
                "beats", "exceeds", "raises", "strong guidance",
                "above expectations", "record revenue", "upside"
            ]
            
            from datetime import datetime, timedelta
            now = datetime.now()
            
            for article in news:
                title = article.get("title", "").lower()
                description = article.get("description", "").lower()
                pub_date_str = article.get("published_utc", "")
                
                # Parse publication date
                try:
                    pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                    days_ago = (now - pub_date.replace(tzinfo=None)).days
                except:
                    days_ago = 999
                
                # Check for earnings mentions in recent news
                content = title + " " + description
                
                for keyword in earnings_keywords:
                    if keyword in content:
                        result["earnings_keywords_found"].append(keyword)
                        
                        # Within 7 days = recent earnings
                        if days_ago <= 7:
                            result["has_recent_earnings"] = True
                            result["is_post_earnings"] = True
                            result["days_since_earnings"] = days_ago
                            
                        # Check sentiment
                        for bkw in bearish_keywords:
                            if bkw in content:
                                result["guidance_sentiment"] = "negative"
                                break
                        for gkw in bullish_keywords:
                            if gkw in content:
                                result["guidance_sentiment"] = "positive"
                                break
                        break
                
                # Check for upcoming earnings mentions
                if "upcoming earnings" in content or "reports earnings" in content:
                    if days_ago <= 14:  # Mentioned within 2 weeks
                        result["is_pre_earnings"] = True
                        
        except Exception as e:
            logger.debug(f"Error checking earnings proximity for {symbol}: {e}")
            
        return result

    # ==================== Trades ====================

    async def get_trades(
        self,
        symbol: str,
        from_date: Optional[date] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Get historical trades for a symbol."""
        endpoint = f"/v3/trades/{symbol}"
        params = {"limit": limit}

        if from_date:
            params["timestamp.gte"] = f"{from_date.isoformat()}T00:00:00Z"

        result = await self._request(endpoint, params)
        return result.get("results", [])

    # ==================== Dark Pool / Block Trades ====================

    async def get_large_trades(
        self,
        symbol: str,
        min_size: int = 10000,
        from_date: Optional[date] = None
    ) -> List[DarkPoolPrint]:
        """
        Get large trades that might indicate institutional activity.
        Note: This filters regular trades by size - true dark pool data
        requires a premium data subscription.
        """
        trades = await self.get_trades(symbol, from_date, limit=5000)
        large_trades = []

        for trade in trades:
            size = trade.get("size", 0)
            if size >= min_size:
                large_trades.append(DarkPoolPrint(
                    timestamp=datetime.fromtimestamp(trade["participant_timestamp"] / 1e9),
                    symbol=symbol,
                    price=float(trade["price"]),
                    size=int(size),
                    exchange=trade.get("exchange", "unknown"),
                    is_buy=None  # Cannot determine from trade data alone
                ))

        return large_trades
