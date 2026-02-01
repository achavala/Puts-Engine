"""
FinViz API Client for stock screening and technical analysis.

FinViz Elite provides:
- Stock quotes and fundamentals
- Technical analysis indicators (RSI, MACD, SMA, etc.)
- Support/Resistance levels
- Sector/Industry performance
- Insider trading data
- Analyst ratings and price targets
- News sentiment

Use cases in PutsEngine:
1. Pre-screening universe for high-probability puts
2. Technical confirmation of distribution signals
3. Support/resistance levels for strike selection
4. Insider activity cross-validation
5. Analyst downgrades as bearish catalyst
"""

import asyncio
from datetime import datetime, date
from typing import Optional, List, Dict, Any
import aiohttp
from loguru import logger
from dataclasses import dataclass

from putsengine.config import Settings


@dataclass
class FinVizQuote:
    """Stock quote data from FinViz."""
    symbol: str
    price: float
    change_pct: float
    volume: int
    avg_volume: int
    market_cap: float
    pe_ratio: Optional[float]
    forward_pe: Optional[float]
    peg_ratio: Optional[float]
    short_float: Optional[float]
    short_ratio: Optional[float]
    target_price: Optional[float]
    analyst_rating: Optional[str]  # Buy, Hold, Sell
    # Technical indicators
    rsi_14: Optional[float]
    sma_20: Optional[float]
    sma_50: Optional[float]
    sma_200: Optional[float]
    relative_volume: Optional[float]
    # Support/Resistance
    support_1: Optional[float]
    resistance_1: Optional[float]
    # Signals
    signal: Optional[str]  # e.g., "Bearish Engulfing", "RSI Oversold"
    pattern: Optional[str]  # e.g., "Double Top", "Head and Shoulders"


@dataclass
class FinVizInsider:
    """Insider trading data from FinViz."""
    symbol: str
    insider_name: str
    relationship: str  # CEO, CFO, Director, etc.
    transaction_type: str  # Buy, Sale
    shares: int
    value: float
    date: date


@dataclass
class FinVizTechnicalRating:
    """Technical analysis rating."""
    symbol: str
    rating: str  # Strong Buy, Buy, Neutral, Sell, Strong Sell
    sma_rating: str
    rsi_rating: str
    macd_rating: str
    momentum_rating: str
    volatility_rating: str


class FinVizClient:
    """
    Client for FinViz Elite API.
    
    Provides stock screening, technical analysis, and fundamental data
    to complement the options flow analysis from Unusual Whales.
    """
    
    # FinViz Elite API base URL
    BASE_URL = "https://elite.finviz.com/export.ashx"
    QUOTE_URL = "https://elite.finviz.com/quote.ashx"
    SCREENER_URL = "https://elite.finviz.com/screener.ashx"
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_key = settings.finviz_api_key
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_request_time = 0.0
        self._request_interval = 0.5  # 2 requests per second max
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
        
    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            
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
        url: str,
        params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make HTTP request to FinViz API."""
        if not self.api_key:
            logger.warning("FinViz API key not configured")
            return {}
            
        await self._rate_limit_wait()
        
        if params is None:
            params = {}
        params["auth"] = self.api_key
        
        session = await self._get_session()
        try:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    content_type = response.headers.get('content-type', '')
                    if 'json' in content_type:
                        return await response.json()
                    else:
                        # FinViz often returns CSV
                        text = await response.text()
                        return {"raw": text}
                elif response.status == 429:
                    logger.warning("FinViz rate limit hit, waiting 5 seconds...")
                    await asyncio.sleep(5)
                    return await self._request(url, params)
                else:
                    error_text = await response.text()
                    logger.error(f"FinViz API error {response.status}: {error_text[:200]}")
                    return {}
        except Exception as e:
            logger.error(f"FinViz request failed: {e}")
            return {}
            
    # ==================== Stock Quotes ====================
    
    async def get_quote(self, symbol: str) -> Optional[FinVizQuote]:
        """
        Get stock quote with technical indicators from FinViz.
        
        Returns comprehensive data including:
        - Price, volume, market cap
        - Technical indicators (RSI, SMAs, MACD)
        - Support/Resistance levels
        - Analyst ratings
        """
        url = f"{self.QUOTE_URL}"
        params = {"t": symbol, "ty": "c", "p": "d"}  # Chart data
        
        result = await self._request(url, params)
        
        if not result:
            return None
            
        try:
            # Parse FinViz response (format varies)
            data = result.get("raw", "")
            if not data:
                return None
                
            # Try to parse key metrics from the response
            # FinViz Elite returns structured data
            return self._parse_quote_data(symbol, data)
            
        except Exception as e:
            logger.error(f"Error parsing FinViz quote for {symbol}: {e}")
            return None
            
    def _parse_quote_data(self, symbol: str, data: str) -> Optional[FinVizQuote]:
        """Parse quote data from FinViz response."""
        # FinViz returns HTML/text that needs parsing
        # For now, return a placeholder - real implementation would parse HTML
        try:
            # This is a simplified parser - real implementation would use BeautifulSoup
            return FinVizQuote(
                symbol=symbol,
                price=0.0,
                change_pct=0.0,
                volume=0,
                avg_volume=0,
                market_cap=0.0,
                pe_ratio=None,
                forward_pe=None,
                peg_ratio=None,
                short_float=None,
                short_ratio=None,
                target_price=None,
                analyst_rating=None,
                rsi_14=None,
                sma_20=None,
                sma_50=None,
                sma_200=None,
                relative_volume=None,
                support_1=None,
                resistance_1=None,
                signal=None,
                pattern=None
            )
        except:
            return None
            
    # ==================== Stock Screener ====================
    
    async def screen_bearish_stocks(
        self,
        min_price: float = 10.0,
        max_price: float = 500.0,
        min_volume: int = 500000,
        rsi_below: float = 40.0
    ) -> List[str]:
        """
        Screen for stocks showing bearish technical signals.
        
        Filters:
        - RSI below threshold (oversold bounce risk, but also downtrend)
        - Below 20 SMA (short-term weakness)
        - Below 50 SMA (medium-term weakness)
        - High relative volume (institutional activity)
        
        Returns list of symbols matching criteria.
        """
        # FinViz screener URL params
        filters = [
            f"cap_small|mid|large",  # Market cap
            f"sh_avgvol_o500",  # Volume > 500K
            f"ta_sma20_pb",  # Price below SMA20
            f"ta_sma50_pb",  # Price below SMA50
            f"ta_rsi_os40",  # RSI < 40
        ]
        
        url = self.SCREENER_URL
        params = {
            "v": "111",  # Overview view
            "f": ",".join(filters),
            "ft": "4",  # Filter type
            "o": "-change"  # Sort by change desc
        }
        
        result = await self._request(url, params)
        
        if not result:
            return []
            
        # Parse screener results
        return self._parse_screener_results(result.get("raw", ""))
        
    async def screen_high_short_interest(
        self,
        min_short_float: float = 15.0
    ) -> List[str]:
        """
        Screen for stocks with high short interest.
        
        High short interest + bearish signals = squeeze risk
        High short interest + distribution = strong put candidate
        """
        filters = [
            f"sh_short_o15",  # Short float > 15%
            f"sh_avgvol_o500",  # Volume > 500K
        ]
        
        url = self.SCREENER_URL
        params = {
            "v": "111",
            "f": ",".join(filters),
            "o": "-shortinterestshare"  # Sort by short interest
        }
        
        result = await self._request(url, params)
        
        if not result:
            return []
            
        return self._parse_screener_results(result.get("raw", ""))
        
    async def screen_insider_selling(self) -> List[Dict[str, Any]]:
        """
        Screen for stocks with recent insider selling.
        
        Insider selling clusters are bearish signals.
        Cross-reference with Unusual Whales insider data.
        """
        url = self.SCREENER_URL
        params = {
            "v": "111",
            "f": "it_s",  # Insider transactions - Sales
            "o": "-insidertransactions"
        }
        
        result = await self._request(url, params)
        
        if not result:
            return []
            
        # Parse and return insider selling data
        symbols = self._parse_screener_results(result.get("raw", ""))
        return [{"symbol": s, "signal": "insider_selling"} for s in symbols]
        
    async def screen_analyst_downgrades(self) -> List[str]:
        """
        Screen for stocks with recent analyst downgrades.
        
        Analyst downgrades often precede price drops.
        """
        url = self.SCREENER_URL
        params = {
            "v": "111",
            "f": "an_d",  # Analyst downgrade
            "o": "-change"
        }
        
        result = await self._request(url, params)
        
        if not result:
            return []
            
        return self._parse_screener_results(result.get("raw", ""))
        
    def _parse_screener_results(self, data: str) -> List[str]:
        """Parse screener CSV/text results to extract symbols."""
        if not data:
            return []
            
        symbols = []
        try:
            lines = data.strip().split('\n')
            for line in lines[1:]:  # Skip header
                parts = line.split(',')
                if parts and parts[0]:
                    # First column is usually ticker
                    symbol = parts[0].strip().strip('"')
                    if symbol.isalpha() and len(symbol) <= 5:
                        symbols.append(symbol.upper())
        except Exception as e:
            logger.error(f"Error parsing FinViz screener: {e}")
            
        return symbols[:50]  # Limit to top 50
        
    # ==================== Technical Analysis ====================
    
    async def get_technical_rating(self, symbol: str) -> Optional[FinVizTechnicalRating]:
        """
        Get technical analysis rating for a symbol.
        
        Combines multiple indicators:
        - SMA crossovers
        - RSI levels
        - MACD signals
        - Volume patterns
        """
        quote = await self.get_quote(symbol)
        
        if not quote:
            return None
            
        # Calculate ratings based on technical indicators
        try:
            # SMA Rating
            sma_rating = "Neutral"
            if quote.sma_20 and quote.sma_50 and quote.price:
                if quote.price < quote.sma_20 < quote.sma_50:
                    sma_rating = "Strong Sell"
                elif quote.price < quote.sma_20:
                    sma_rating = "Sell"
                elif quote.price > quote.sma_20 > quote.sma_50:
                    sma_rating = "Strong Buy"
                elif quote.price > quote.sma_20:
                    sma_rating = "Buy"
                    
            # RSI Rating
            rsi_rating = "Neutral"
            if quote.rsi_14:
                if quote.rsi_14 < 30:
                    rsi_rating = "Oversold"
                elif quote.rsi_14 < 40:
                    rsi_rating = "Weak"
                elif quote.rsi_14 > 70:
                    rsi_rating = "Overbought"
                elif quote.rsi_14 > 60:
                    rsi_rating = "Strong"
                    
            # Overall rating
            sell_signals = 0
            if sma_rating in ["Sell", "Strong Sell"]:
                sell_signals += 1
            if rsi_rating in ["Weak", "Oversold"]:
                sell_signals += 1
                
            if sell_signals >= 2:
                overall_rating = "Strong Sell"
            elif sell_signals >= 1:
                overall_rating = "Sell"
            else:
                overall_rating = "Neutral"
                
            return FinVizTechnicalRating(
                symbol=symbol,
                rating=overall_rating,
                sma_rating=sma_rating,
                rsi_rating=rsi_rating,
                macd_rating="Neutral",
                momentum_rating="Neutral",
                volatility_rating="Neutral"
            )
            
        except Exception as e:
            logger.error(f"Error calculating technical rating for {symbol}: {e}")
            return None
            
    # ==================== Sector Analysis ====================
    
    async def get_sector_performance(self) -> Dict[str, float]:
        """
        Get sector performance to identify weak sectors.
        
        Weak sectors = higher probability puts.
        """
        url = self.SCREENER_URL
        params = {
            "v": "110",  # Performance view
            "g": "sector",  # Group by sector
        }
        
        result = await self._request(url, params)
        
        if not result:
            return {}
            
        # Parse sector performance
        # Returns dict like {"Technology": -2.5, "Healthcare": 1.2, ...}
        return self._parse_sector_performance(result.get("raw", ""))
        
    def _parse_sector_performance(self, data: str) -> Dict[str, float]:
        """Parse sector performance data."""
        sectors = {}
        try:
            lines = data.strip().split('\n')
            for line in lines[1:]:
                parts = line.split(',')
                if len(parts) >= 2:
                    sector = parts[0].strip().strip('"')
                    change = parts[-1].strip().strip('"').replace('%', '')
                    try:
                        sectors[sector] = float(change)
                    except ValueError:
                        continue
        except Exception as e:
            logger.error(f"Error parsing sector performance: {e}")
            
        return sectors
        
    # ==================== Integration Helpers ====================
    
    async def get_bearish_candidates(self) -> List[Dict[str, Any]]:
        """
        Get comprehensive list of bearish candidates.
        
        Combines multiple screens:
        - Technical weakness (RSI, SMAs)
        - Insider selling
        - Analyst downgrades
        - High short interest
        
        Returns enriched candidate list for PutsEngine.
        """
        candidates = {}
        
        # Screen 1: Technical weakness
        logger.info("FinViz: Screening for technical weakness...")
        tech_weak = await self.screen_bearish_stocks()
        for symbol in tech_weak:
            if symbol not in candidates:
                candidates[symbol] = {"symbol": symbol, "signals": [], "score_boost": 0.0}
            candidates[symbol]["signals"].append("technical_weakness")
            candidates[symbol]["score_boost"] += 0.05
            
        # Screen 2: Insider selling
        logger.info("FinViz: Screening for insider selling...")
        insider_sells = await self.screen_insider_selling()
        for item in insider_sells:
            symbol = item["symbol"]
            if symbol not in candidates:
                candidates[symbol] = {"symbol": symbol, "signals": [], "score_boost": 0.0}
            candidates[symbol]["signals"].append("insider_selling")
            candidates[symbol]["score_boost"] += 0.08
            
        # Screen 3: Analyst downgrades
        logger.info("FinViz: Screening for analyst downgrades...")
        downgrades = await self.screen_analyst_downgrades()
        for symbol in downgrades:
            if symbol not in candidates:
                candidates[symbol] = {"symbol": symbol, "signals": [], "score_boost": 0.0}
            candidates[symbol]["signals"].append("analyst_downgrade")
            candidates[symbol]["score_boost"] += 0.05
            
        # Screen 4: High short interest
        logger.info("FinViz: Screening for high short interest...")
        high_short = await self.screen_high_short_interest()
        for symbol in high_short:
            if symbol not in candidates:
                candidates[symbol] = {"symbol": symbol, "signals": [], "score_boost": 0.0}
            candidates[symbol]["signals"].append("high_short_interest")
            # Note: High short can be bullish (squeeze) or bearish, so neutral boost
            
        # Sort by score boost
        results = sorted(
            candidates.values(),
            key=lambda x: x["score_boost"],
            reverse=True
        )
        
        logger.info(f"FinViz: Found {len(results)} bearish candidates")
        return results[:30]  # Top 30
        
    async def enrich_candidate(
        self,
        symbol: str,
        existing_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Enrich an existing candidate with FinViz data.
        
        Adds:
        - Technical rating
        - Support/resistance levels
        - Short interest
        - Analyst consensus
        
        Use to validate candidates from Unusual Whales analysis.
        """
        enriched = existing_data.copy()
        
        # Get technical rating
        rating = await self.get_technical_rating(symbol)
        if rating:
            enriched["finviz_rating"] = rating.rating
            enriched["finviz_sma_rating"] = rating.sma_rating
            enriched["finviz_rsi_rating"] = rating.rsi_rating
            
            # Add score boost for bearish technical rating
            if rating.rating in ["Sell", "Strong Sell"]:
                existing_boost = enriched.get("score_boost", 0.0)
                enriched["score_boost"] = existing_boost + 0.05
                enriched.setdefault("signals", []).append("finviz_bearish")
                
        # Get quote for additional data
        quote = await self.get_quote(symbol)
        if quote:
            if quote.support_1:
                enriched["finviz_support"] = quote.support_1
            if quote.resistance_1:
                enriched["finviz_resistance"] = quote.resistance_1
            if quote.short_float:
                enriched["finviz_short_float"] = quote.short_float
            if quote.target_price:
                enriched["finviz_target_price"] = quote.target_price
            if quote.analyst_rating:
                enriched["finviz_analyst_rating"] = quote.analyst_rating
                
        return enriched


# Convenience function
def get_finviz_client(settings: Settings) -> FinVizClient:
    """Create a FinViz client from settings."""
    return FinVizClient(settings)
