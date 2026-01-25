"""
Alpaca API Client for trading and market data.
Handles stock data, options chains, and order execution.
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
import aiohttp
from loguru import logger

from putsengine.config import Settings
from putsengine.models import PriceBar, OptionsContract, TradeExecution


class AlpacaClient:
    """Client for Alpaca Trading API and Market Data API."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_key = settings.alpaca_api_key
        self.secret_key = settings.alpaca_secret_key
        self.base_url = settings.alpaca_base_url
        self.data_url = settings.alpaca_data_url
        self.options_url = settings.alpaca_options_url
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def _headers(self) -> Dict[str, str]:
        """Authentication headers for Alpaca API."""
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
            "Content-Type": "application/json"
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self._headers)
        return self._session

    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make HTTP request to Alpaca API."""
        session = await self._get_session()
        try:
            async with session.request(method, url, params=params, json=json_data) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 429:
                    logger.warning("Alpaca rate limit hit, waiting 1 second...")
                    await asyncio.sleep(1)
                    return await self._request(method, url, params, json_data)
                else:
                    error_text = await response.text()
                    logger.error(f"Alpaca API error {response.status}: {error_text}")
                    return {}
        except Exception as e:
            logger.error(f"Alpaca request failed: {e}")
            return {}

    # ==================== Account & Trading ====================

    async def get_account(self) -> Dict[str, Any]:
        """Get account information."""
        url = f"{self.base_url}/account"
        return await self._request("GET", url)

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get all open positions."""
        url = f"{self.base_url}/positions"
        result = await self._request("GET", url)
        return result if isinstance(result, list) else []

    async def submit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        order_type: str = "market",
        time_in_force: str = "day",
        limit_price: Optional[float] = None
    ) -> Dict[str, Any]:
        """Submit an order to Alpaca."""
        url = f"{self.base_url}/orders"
        order_data = {
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force
        }
        if limit_price and order_type == "limit":
            order_data["limit_price"] = str(limit_price)

        logger.info(f"Submitting order: {order_data}")
        return await self._request("POST", url, json_data=order_data)

    async def get_order(self, order_id: str) -> Dict[str, Any]:
        """Get order status by ID."""
        url = f"{self.base_url}/orders/{order_id}"
        return await self._request("GET", url)

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order by ID."""
        url = f"{self.base_url}/orders/{order_id}"
        session = await self._get_session()
        async with session.delete(url) as response:
            return response.status in [200, 204]

    # ==================== Market Data ====================

    async def get_bars(
        self,
        symbol: str,
        timeframe: str = "1Min",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 1000
    ) -> List[PriceBar]:
        """Get historical price bars."""
        if start is None:
            start = datetime.now() - timedelta(days=5)
        if end is None:
            end = datetime.now()

        url = f"{self.data_url}/stocks/{symbol}/bars"
        params = {
            "timeframe": timeframe,
            "start": start.isoformat() + "Z",
            "end": end.isoformat() + "Z",
            "limit": limit,
            "adjustment": "split"
        }

        result = await self._request("GET", url, params=params)
        bars = []

        if "bars" in result:
            for bar in result["bars"]:
                bars.append(PriceBar(
                    timestamp=datetime.fromisoformat(bar["t"].replace("Z", "+00:00")),
                    open=float(bar["o"]),
                    high=float(bar["h"]),
                    low=float(bar["l"]),
                    close=float(bar["c"]),
                    volume=int(bar["v"]),
                    vwap=float(bar.get("vw", 0))
                ))
        return bars

    async def get_latest_quote(self, symbol: str) -> Dict[str, Any]:
        """Get latest quote for a symbol."""
        url = f"{self.data_url}/stocks/{symbol}/quotes/latest"
        return await self._request("GET", url)

    async def get_latest_trade(self, symbol: str) -> Dict[str, Any]:
        """Get latest trade for a symbol."""
        url = f"{self.data_url}/stocks/{symbol}/trades/latest"
        return await self._request("GET", url)

    async def get_snapshot(self, symbol: str) -> Dict[str, Any]:
        """Get snapshot (quote, trade, bars) for a symbol."""
        url = f"{self.data_url}/stocks/{symbol}/snapshot"
        return await self._request("GET", url)

    async def get_multi_bars(
        self,
        symbols: List[str],
        timeframe: str = "1Day",
        start: Optional[datetime] = None,
        limit: int = 100
    ) -> Dict[str, List[PriceBar]]:
        """Get bars for multiple symbols."""
        if start is None:
            start = datetime.now() - timedelta(days=30)

        url = f"{self.data_url}/stocks/bars"
        params = {
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "start": start.isoformat() + "Z",
            "limit": limit
        }

        result = await self._request("GET", url, params=params)
        bars_dict = {}

        if "bars" in result:
            for symbol, bar_list in result["bars"].items():
                bars_dict[symbol] = [
                    PriceBar(
                        timestamp=datetime.fromisoformat(bar["t"].replace("Z", "+00:00")),
                        open=float(bar["o"]),
                        high=float(bar["h"]),
                        low=float(bar["l"]),
                        close=float(bar["c"]),
                        volume=int(bar["v"]),
                        vwap=float(bar.get("vw", 0))
                    )
                    for bar in bar_list
                ]
        return bars_dict

    # ==================== Options Data ====================

    async def get_options_chain(
        self,
        underlying: str,
        expiration_date: Optional[date] = None,
        option_type: Optional[str] = None,
        strike_price_gte: Optional[float] = None,
        strike_price_lte: Optional[float] = None
    ) -> List[OptionsContract]:
        """Get options chain for an underlying symbol."""
        url = f"{self.options_url}/options/contracts"
        params = {
            "underlying_symbols": underlying,
            "status": "active",
            "limit": 1000
        }

        if expiration_date:
            params["expiration_date"] = expiration_date.isoformat()
        if option_type:
            params["type"] = option_type
        if strike_price_gte:
            params["strike_price_gte"] = str(strike_price_gte)
        if strike_price_lte:
            params["strike_price_lte"] = str(strike_price_lte)

        result = await self._request("GET", url, params=params)
        contracts = []

        if "option_contracts" in result:
            for contract in result["option_contracts"]:
                try:
                    exp_date = datetime.strptime(
                        contract["expiration_date"], "%Y-%m-%d"
                    ).date()
                    dte = (exp_date - date.today()).days

                    contracts.append(OptionsContract(
                        symbol=contract["symbol"],
                        underlying=contract["underlying_symbol"],
                        expiration=exp_date,
                        strike=float(contract["strike_price"]),
                        option_type=contract["type"],
                        bid=0.0,  # Will be filled by quote
                        ask=0.0,
                        last=0.0,
                        volume=0,
                        open_interest=int(contract.get("open_interest", 0)),
                        implied_volatility=0.0,
                        delta=0.0,
                        gamma=0.0,
                        theta=0.0,
                        vega=0.0,
                        dte=dte
                    ))
                except Exception as e:
                    logger.warning(f"Error parsing contract: {e}")
                    continue

        return contracts

    async def get_options_quotes(
        self,
        contract_symbols: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Get quotes for options contracts."""
        if not contract_symbols:
            return {}

        url = f"{self.options_url}/options/quotes/latest"
        params = {"symbols": ",".join(contract_symbols[:100])}  # API limit

        result = await self._request("GET", url, params=params)
        return result.get("quotes", {})

    async def get_options_trades(
        self,
        contract_symbol: str,
        start: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get trades for an options contract."""
        url = f"{self.options_url}/options/trades"
        params = {
            "symbols": contract_symbol,
            "limit": limit
        }
        if start:
            params["start"] = start.isoformat() + "Z"

        result = await self._request("GET", url, params=params)
        return result.get("trades", {}).get(contract_symbol, [])

    async def get_options_snapshots(
        self,
        underlying: str
    ) -> Dict[str, Any]:
        """Get snapshots for all options of an underlying."""
        url = f"{self.options_url}/options/snapshots/{underlying}"
        return await self._request("GET", url)

    # ==================== Utility Methods ====================

    async def get_tradeable_assets(
        self,
        asset_class: str = "us_equity"
    ) -> List[Dict[str, Any]]:
        """Get list of tradeable assets."""
        url = f"{self.base_url}/assets"
        params = {
            "status": "active",
            "asset_class": asset_class
        }
        result = await self._request("GET", url, params=params)
        return result if isinstance(result, list) else []

    async def is_market_open(self) -> bool:
        """Check if market is currently open."""
        url = f"{self.base_url}/clock"
        result = await self._request("GET", url)
        return result.get("is_open", False)

    async def get_calendar(
        self,
        start: Optional[date] = None,
        end: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """Get market calendar."""
        url = f"{self.base_url}/calendar"
        params = {}
        if start:
            params["start"] = start.isoformat()
        if end:
            params["end"] = end.isoformat()

        result = await self._request("GET", url, params=params)
        return result if isinstance(result, list) else []

    async def get_asset(self, symbol: str) -> Dict[str, Any]:
        """
        Get asset details including borrow status.
        
        Per Final Architect Report:
        - ETB → HTB transition = liquidity stress signal
        - HTB = penalty for puts (squeeze risk)
        """
        url = f"{self.base_url}/assets/{symbol}"
        return await self._request("GET", url)

    async def check_borrow_status(self, symbol: str) -> Dict[str, Any]:
        """
        Check if asset is easy-to-borrow or hard-to-borrow.
        
        Per Final Architect Report:
        "ETB → HTB = liquidity stress"
        "HTB transition = penalty for puts (squeeze risk)"
        
        Returns:
            Dict with borrow status and squeeze risk assessment
        """
        result = {
            "symbol": symbol,
            "easy_to_borrow": True,
            "shortable": True,
            "marginable": True,
            "squeeze_risk": False,
            "borrow_status": "easy"
        }
        
        try:
            asset = await self.get_asset(symbol)
            
            if asset:
                result["easy_to_borrow"] = asset.get("easy_to_borrow", True)
                result["shortable"] = asset.get("shortable", True)
                result["marginable"] = asset.get("marginable", True)
                
                # Determine borrow status
                if not result["shortable"]:
                    result["borrow_status"] = "not_shortable"
                    result["squeeze_risk"] = True
                elif not result["easy_to_borrow"]:
                    result["borrow_status"] = "hard_to_borrow"
                    result["squeeze_risk"] = True
                else:
                    result["borrow_status"] = "easy_to_borrow"
                    result["squeeze_risk"] = False
                    
                logger.debug(
                    f"{symbol} borrow status: {result['borrow_status']}, "
                    f"squeeze_risk: {result['squeeze_risk']}"
                )
                
        except Exception as e:
            logger.warning(f"Error checking borrow status for {symbol}: {e}")
            
        return result
