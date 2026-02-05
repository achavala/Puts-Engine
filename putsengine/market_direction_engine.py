#!/usr/bin/env python3
"""
Market Direction Engine
=======================
Predicts market direction using multiple data sources.

THE HARD TRUTH (30-year trader perspective):
- No model predicts direction with >65% accuracy consistently
- The edge comes from COMBINING multiple weak signals
- GEX regime is the most actionable institutional signal
- VIX term structure tells you WHEN to expect moves

Data Sources Used:
1. Polygon (Massive) - Pre-market prices, historical data
2. Unusual Whales - GEX, dark pool, options flow, VIX
3. Finviz - Sector performance, technical levels
4. Alpaca - Real-time quotes

Feb 4, 2026
"""

import asyncio
import json
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from putsengine.config import get_settings, EngineConfig
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient


class MarketDirection(Enum):
    """Market direction prediction."""
    STRONG_BULLISH = "STRONG_BULLISH"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    STRONG_BEARISH = "STRONG_BEARISH"


class GEXRegime(Enum):
    """Gamma Exposure regime - THE KEY INSTITUTIONAL SIGNAL."""
    POSITIVE = "POSITIVE"    # Market tends to mean-revert, low volatility
    NEGATIVE = "NEGATIVE"    # Market tends to trend, high volatility
    NEUTRAL = "NEUTRAL"


@dataclass
class MarketSignal:
    """Individual market signal."""
    name: str
    value: float
    direction: int  # -1 (bearish), 0 (neutral), +1 (bullish)
    weight: float
    confidence: float
    source: str
    description: str


@dataclass
class MarketDirectionResult:
    """Complete market direction analysis."""
    timestamp: datetime
    direction: MarketDirection
    confidence: float  # 0-100%
    
    # Component scores
    spy_signal: float
    qqq_signal: float
    vix_signal: float
    gex_regime: GEXRegime
    gex_value: float
    dark_pool_signal: float
    put_call_ratio: float
    
    # Individual signals
    signals: List[MarketSignal] = field(default_factory=list)
    
    # Recommendations
    best_plays: List[Dict] = field(default_factory=list)
    avoid_plays: List[Dict] = field(default_factory=list)
    
    # Raw data
    raw_data: Dict = field(default_factory=dict)


class MarketDirectionEngine:
    """
    Engine to predict market direction using institutional signals.
    
    THE QUANTITATIVE FRAMEWORK:
    
    1. GEX Regime (Gamma Exposure) - 25% weight
       - Positive GEX: Market makers SHORT gamma = they BUY dips, SELL rips
         → Expect range-bound, mean-reverting action
       - Negative GEX: Market makers LONG gamma = they SELL dips, BUY rips
         → Expect trending, volatile action
    
    2. VIX Term Structure - 20% weight
       - Contango (VIX < VIX futures): Normal, bullish bias
       - Backwardation (VIX > VIX futures): Fear, bearish bias
    
    3. Pre-Market Internals - 20% weight
       - SPY/QQQ pre-market direction
       - Gap size and direction
    
    4. Dark Pool Flow - 15% weight
       - Net buying/selling from institutions
    
    5. Options Flow - 15% weight
       - Put/Call ratio
       - Large premium direction
    
    6. Technical Levels - 5% weight
       - Key support/resistance proximity
    """
    
    # Key ETFs for market direction
    MARKET_ETFS = {
        "SPY": {"name": "S&P 500", "weight": 0.5},
        "QQQ": {"name": "Nasdaq 100", "weight": 0.3},
        "IWM": {"name": "Russell 2000", "weight": 0.1},
        "DIA": {"name": "Dow 30", "weight": 0.1}
    }
    
    # VIX thresholds
    VIX_LOW = 15      # Complacency
    VIX_NORMAL = 20   # Normal
    VIX_ELEVATED = 25 # Caution
    VIX_HIGH = 30     # Fear
    VIX_EXTREME = 40  # Panic
    
    # GEX thresholds (in billions)
    GEX_POSITIVE_THRESHOLD = 2.0   # Strongly positive
    GEX_NEGATIVE_THRESHOLD = -2.0  # Strongly negative
    
    def __init__(self):
        self.settings = get_settings()
        self.polygon: Optional[PolygonClient] = None
        self.uw: Optional[UnusualWhalesClient] = None
        
    async def _init_clients(self):
        """Initialize API clients."""
        if self.polygon is None:
            self.polygon = PolygonClient(self.settings)
        if self.uw is None:
            self.uw = UnusualWhalesClient(self.settings)
    
    async def close(self):
        """Close client connections."""
        if self.polygon:
            await self.polygon.close()
        if self.uw:
            await self.uw.close()
    
    # =========================================================================
    # SIGNAL GENERATORS
    # =========================================================================
    
    async def get_premarket_internals(self) -> Dict[str, Any]:
        """
        Get pre-market price action for key ETFs.
        
        This tells us:
        - Gap direction (bullish/bearish bias)
        - Gap size (conviction level)
        - Relative strength (tech vs broad market)
        """
        await self._init_clients()
        
        internals = {}
        
        for symbol, config in self.MARKET_ETFS.items():
            try:
                # Get today's snapshot
                snapshot = await self.polygon.get_snapshot(symbol)
                
                if snapshot and "ticker" in snapshot:
                    ticker = snapshot["ticker"]
                    
                    # Current price
                    current = ticker.get("lastTrade", {}).get("p", 0)
                    
                    # Previous close
                    prev_day = ticker.get("prevDay", {})
                    prev_close = prev_day.get("c", current)
                    
                    # Today's data
                    today = ticker.get("day", {})
                    today_open = today.get("o", current)
                    today_high = today.get("h", current)
                    today_low = today.get("l", current)
                    
                    # Calculate gap
                    gap_pct = ((today_open - prev_close) / prev_close * 100) if prev_close else 0
                    
                    # Calculate change from open
                    change_from_open = ((current - today_open) / today_open * 100) if today_open else 0
                    
                    # Total change
                    total_change = ticker.get("todaysChangePerc", 0)
                    
                    internals[symbol] = {
                        "current": current,
                        "prev_close": prev_close,
                        "open": today_open,
                        "high": today_high,
                        "low": today_low,
                        "gap_pct": gap_pct,
                        "change_from_open": change_from_open,
                        "total_change": total_change,
                        "weight": config["weight"]
                    }
                    
            except Exception as e:
                logger.debug(f"Error getting internals for {symbol}: {e}")
                
        return internals
    
    async def get_gex_signal(self) -> Tuple[GEXRegime, float, Dict]:
        """
        Get Gamma Exposure (GEX) regime from Unusual Whales.
        
        THIS IS THE MOST IMPORTANT SIGNAL FOR INSTITUTIONAL BEHAVIOR.
        
        GEX tells us how market makers are positioned:
        - Positive GEX: MMs are short gamma → they provide liquidity
          → Market tends to be range-bound, mean-reverting
          → Dips get bought, rallies get sold
          
        - Negative GEX: MMs are long gamma → they remove liquidity  
          → Market tends to trend, high volatility
          → Moves get amplified in both directions
        """
        await self._init_clients()
        
        try:
            gex_data = await self.uw.get_gex_data("SPY")
            
            if gex_data:
                # Get GEX value (in billions typically)
                gex_value = getattr(gex_data, 'gex', 0) or 0
                
                # Determine regime
                if gex_value > self.GEX_POSITIVE_THRESHOLD:
                    regime = GEXRegime.POSITIVE
                elif gex_value < self.GEX_NEGATIVE_THRESHOLD:
                    regime = GEXRegime.NEGATIVE
                else:
                    regime = GEXRegime.NEUTRAL
                
                return regime, gex_value, {
                    "gex": gex_value,
                    "regime": regime.value,
                    "interpretation": self._interpret_gex(regime, gex_value)
                }
                
        except Exception as e:
            logger.debug(f"Error getting GEX: {e}")
            
        return GEXRegime.NEUTRAL, 0, {}
    
    def _interpret_gex(self, regime: GEXRegime, value: float) -> str:
        """Interpret GEX for trading."""
        if regime == GEXRegime.POSITIVE:
            return f"POSITIVE GEX ({value:.2f}B): Expect range-bound action. Sell rallies, buy dips. Low volatility expected."
        elif regime == GEXRegime.NEGATIVE:
            return f"NEGATIVE GEX ({value:.2f}B): Expect trending/volatile action. Trade with momentum, not against."
        else:
            return f"NEUTRAL GEX ({value:.2f}B): Mixed signals. Watch for regime change."
    
    async def get_vix_signal(self) -> Tuple[float, int, Dict]:
        """
        Get VIX analysis.
        
        VIX tells us:
        - Current fear level
        - Term structure (contango vs backwardation)
        - Expected volatility
        """
        await self._init_clients()
        
        try:
            # Get VIX snapshot
            vix_snapshot = await self.polygon.get_snapshot("VIX")
            
            if vix_snapshot and "ticker" in vix_snapshot:
                ticker = vix_snapshot["ticker"]
                vix_current = ticker.get("lastTrade", {}).get("p", 20)
                vix_change = ticker.get("todaysChangePerc", 0)
                
                # Determine signal
                if vix_current > self.VIX_EXTREME:
                    signal = 1  # Extreme fear = potential bounce
                    interpretation = "EXTREME FEAR - Capitulation likely, watch for reversal"
                elif vix_current > self.VIX_HIGH:
                    signal = -1  # High fear = bearish
                    interpretation = "HIGH FEAR - Bearish, but getting oversold"
                elif vix_current > self.VIX_ELEVATED:
                    signal = -1  # Elevated = cautious
                    interpretation = "ELEVATED - Caution warranted, volatility expected"
                elif vix_current > self.VIX_NORMAL:
                    signal = 0  # Normal
                    interpretation = "NORMAL - Balanced risk/reward"
                else:
                    signal = 1  # Low VIX = bullish (but watch for complacency)
                    interpretation = "LOW VIX - Bullish bias, but watch for complacency spike"
                
                # VIX change matters too
                if vix_change > 10:
                    signal = -1  # Spiking VIX = bearish
                    interpretation += " | VIX SPIKING - Risk-off mode"
                elif vix_change < -10:
                    signal = 1  # Falling VIX = bullish
                    interpretation += " | VIX FALLING - Risk-on mode"
                
                return vix_current, signal, {
                    "vix": vix_current,
                    "change_pct": vix_change,
                    "level": self._get_vix_level(vix_current),
                    "interpretation": interpretation
                }
                
        except Exception as e:
            logger.debug(f"Error getting VIX: {e}")
            
        return 20.0, 0, {}
    
    def _get_vix_level(self, vix: float) -> str:
        """Categorize VIX level."""
        if vix > self.VIX_EXTREME:
            return "EXTREME"
        elif vix > self.VIX_HIGH:
            return "HIGH"
        elif vix > self.VIX_ELEVATED:
            return "ELEVATED"
        elif vix > self.VIX_NORMAL:
            return "NORMAL"
        else:
            return "LOW"
    
    # =========================================================================
    # NEW SIGNALS (Feb 4, 2026) - FILLING THE GAPS
    # =========================================================================
    
    async def get_news_signal(self) -> Tuple[int, Dict]:
        """
        Get news-based market signal from Polygon.
        
        Checks for market-moving news keywords:
        - Fed, FOMC, rate, inflation, CPI, jobs
        - Tariff, trade war, China
        - Earnings surprises (major companies)
        """
        await self._init_clients()
        
        # Market-moving keywords (bearish)
        BEARISH_KEYWORDS = [
            "crash", "plunge", "tumble", "selloff", "recession",
            "layoffs", "downgrade", "miss", "weak", "fears",
            "tariff", "trade war", "sanctions", "lawsuit"
        ]
        
        # Market-moving keywords (bullish)  
        BULLISH_KEYWORDS = [
            "surge", "rally", "soar", "beat", "strong",
            "upgrade", "breakthrough", "deal", "record"
        ]
        
        try:
            # Get news for major market movers
            spy_news = await self.polygon.get_ticker_news("SPY", limit=10)
            
            bearish_count = 0
            bullish_count = 0
            news_items = []
            
            if spy_news:
                for article in spy_news:
                    title = article.get('title', '').lower()
                    description = article.get('description', '').lower()
                    content = title + " " + description
                    
                    for keyword in BEARISH_KEYWORDS:
                        if keyword in content:
                            bearish_count += 1
                            break
                    
                    for keyword in BULLISH_KEYWORDS:
                        if keyword in content:
                            bullish_count += 1
                            break
                    
                    news_items.append(article.get('title', '')[:80])
            
            # Calculate signal
            net_sentiment = bullish_count - bearish_count
            
            if net_sentiment >= 2:
                signal = 1
            elif net_sentiment <= -2:
                signal = -1
            else:
                signal = 0
            
            return signal, {
                "bullish_count": bullish_count,
                "bearish_count": bearish_count,
                "net_sentiment": net_sentiment,
                "news_items": news_items[:5],
                "interpretation": f"News sentiment: {net_sentiment:+d} (Bull:{bullish_count} Bear:{bearish_count})"
            }
            
        except Exception as e:
            logger.debug(f"Error getting news signal: {e}")
            return 0, {}
    
    async def get_top_movers_signal(self) -> Tuple[int, Dict]:
        """
        Get pre-market movers signal (Futures Proxy).
        
        Pre-market movers indicate:
        - More losers = risk-off = bearish
        - More gainers = risk-on = bullish
        """
        await self._init_clients()
        
        try:
            losers = await self.polygon.get_gainers_losers("losers")
            gainers = await self.polygon.get_gainers_losers("gainers")
            
            loser_avg = 0
            gainer_avg = 0
            
            if losers:
                loser_changes = [l.get('todaysChangePerc', 0) for l in losers[:10]]
                loser_avg = sum(loser_changes) / len(loser_changes) if loser_changes else 0
            
            if gainers:
                gainer_changes = [g.get('todaysChangePerc', 0) for g in gainers[:10]]
                gainer_avg = sum(gainer_changes) / len(gainer_changes) if gainer_changes else 0
            
            # Net strength = gainer avg - abs(loser avg)
            net_strength = gainer_avg + loser_avg  # loser_avg is negative
            
            if net_strength > 2:
                signal = 1  # Strong gainers
            elif net_strength < -2:
                signal = -1  # Strong losers
            else:
                signal = 0
            
            return signal, {
                "gainer_avg": gainer_avg,
                "loser_avg": loser_avg,
                "net_strength": net_strength,
                "top_losers": [(l.get('ticker'), l.get('todaysChangePerc', 0)) for l in (losers or [])[:5]],
                "top_gainers": [(g.get('ticker'), g.get('todaysChangePerc', 0)) for g in (gainers or [])[:5]],
                "interpretation": f"Pre-market: Gainers avg {gainer_avg:+.1f}%, Losers avg {loser_avg:.1f}%"
            }
            
        except Exception as e:
            logger.debug(f"Error getting top movers: {e}")
            return 0, {}
    
    async def get_skew_signal(self) -> Tuple[float, int, Dict]:
        """
        Get options skew signal from Unusual Whales.
        
        OPTIONS SKEW IS BETTER THAN REDDIT SENTIMENT!
        
        Skew tells us what smart money expects:
        - High put skew = institutions hedging = bearish
        - Low put skew = complacency = neutral/bullish
        """
        await self._init_clients()
        
        try:
            skew = await self.uw.get_skew("SPY")
            
            if skew and isinstance(skew, dict):
                data = skew.get('data', [])
                
                if data:
                    latest = data[-1] if isinstance(data, list) else data
                    
                    # Get skew value (put vol - call vol essentially)
                    skew_value = float(latest.get('skew', latest.get('put_call_skew', 0)))
                    
                    # High skew = more expensive puts = bearish hedging
                    if skew_value > 1.2:
                        signal = -1  # Heavy put buying
                    elif skew_value < 0.8:
                        signal = 1  # Complacent
                    else:
                        signal = 0
                    
                    return skew_value, signal, {
                        "skew": skew_value,
                        "interpretation": f"Options skew: {skew_value:.2f} - {'Put heavy (bearish)' if signal < 0 else 'Call heavy (bullish)' if signal > 0 else 'Balanced'}"
                    }
            
        except Exception as e:
            logger.debug(f"Error getting skew: {e}")
            
        return 1.0, 0, {}
    
    async def get_max_pain_signal(self) -> Tuple[float, int, Dict]:
        """
        Get max pain signal from Unusual Whales.
        
        MAX PAIN = Where market makers want price to expire.
        
        - If current price > max pain: Gravity pulls down
        - If current price < max pain: Gravity pulls up
        """
        await self._init_clients()
        
        try:
            max_pain = await self.uw.get_max_pain("SPY")
            
            if max_pain and isinstance(max_pain, dict):
                data = max_pain.get('data', [])
                
                if data:
                    # Get nearest expiry max pain
                    if isinstance(data, list) and len(data) > 0:
                        mp_data = data[0]
                    else:
                        mp_data = data
                    
                    mp_price = float(mp_data.get('price', mp_data.get('max_pain', 0)))
                    
                    # Get current SPY price
                    snapshot = await self.polygon.get_snapshot("SPY")
                    if snapshot and "ticker" in snapshot:
                        current_price = snapshot["ticker"].get("lastTrade", {}).get("p", 0)
                        
                        if current_price > 0 and mp_price > 0:
                            # Distance from max pain as percentage
                            distance_pct = (current_price - mp_price) / mp_price * 100
                            
                            # If price is above max pain, expect pull down (bearish)
                            # If price is below max pain, expect pull up (bullish)
                            if distance_pct > 1:
                                signal = -1  # Above max pain = bearish gravity
                            elif distance_pct < -1:
                                signal = 1   # Below max pain = bullish gravity
                            else:
                                signal = 0   # At max pain
                            
                            return mp_price, signal, {
                                "max_pain": mp_price,
                                "current_price": current_price,
                                "distance_pct": distance_pct,
                                "interpretation": f"Max Pain: ${mp_price:.2f} | Current: ${current_price:.2f} | Distance: {distance_pct:+.1f}%"
                            }
            
        except Exception as e:
            logger.debug(f"Error getting max pain: {e}")
            
        return 0, 0, {}
    
    async def get_dark_pool_signal(self) -> Tuple[float, int, Dict]:
        """
        Get dark pool flow signal.
        
        Dark pool tells us institutional positioning:
        - Net buying = bullish
        - Net selling = bearish
        """
        await self._init_clients()
        
        try:
            # Get dark pool for SPY
            dp_data = await self.uw.get_dark_pool_flow("SPY", limit=50)
            
            if dp_data:
                # Analyze buy/sell ratio
                total_buy_volume = 0
                total_sell_volume = 0
                total_neutral = 0
                
                for print_data in dp_data:
                    size = print_data.size
                    if print_data.is_buy is True:
                        total_buy_volume += size
                    elif print_data.is_buy is False:
                        total_sell_volume += size
                    else:
                        total_neutral += size
                
                total_volume = total_buy_volume + total_sell_volume + total_neutral
                
                if total_volume > 0:
                    buy_pct = total_buy_volume / total_volume
                    sell_pct = total_sell_volume / total_volume
                    
                    net_flow = buy_pct - sell_pct
                    
                    if net_flow > 0.1:
                        signal = 1  # Net buying
                    elif net_flow < -0.1:
                        signal = -1  # Net selling
                    else:
                        signal = 0  # Neutral
                    
                    return net_flow, signal, {
                        "buy_volume": total_buy_volume,
                        "sell_volume": total_sell_volume,
                        "net_flow": net_flow,
                        "prints_analyzed": len(dp_data),
                        "interpretation": f"Dark pool net flow: {net_flow:+.1%}"
                    }
                    
        except Exception as e:
            logger.debug(f"Error getting dark pool: {e}")
            
        return 0.0, 0, {}
    
    async def get_options_flow_signal(self) -> Tuple[float, int, Dict]:
        """
        Get options flow signal.
        
        Put/Call ratio and flow direction:
        - High put flow = bearish
        - High call flow = bullish
        """
        await self._init_clients()
        
        try:
            # Get market tide (overall flow sentiment)
            tide = await self.uw.get_market_tide()
            
            if tide:
                # Parse tide data
                calls = tide.get("calls", {})
                puts = tide.get("puts", {})
                
                call_premium = calls.get("total_premium", 0)
                put_premium = puts.get("total_premium", 0)
                
                total_premium = call_premium + put_premium
                
                if total_premium > 0:
                    put_call_ratio = put_premium / call_premium if call_premium > 0 else 2.0
                    
                    if put_call_ratio > 1.5:
                        signal = -1  # Heavy puts = bearish
                    elif put_call_ratio < 0.7:
                        signal = 1  # Heavy calls = bullish
                    else:
                        signal = 0  # Balanced
                    
                    return put_call_ratio, signal, {
                        "put_call_ratio": put_call_ratio,
                        "call_premium": call_premium,
                        "put_premium": put_premium,
                        "interpretation": f"P/C Ratio: {put_call_ratio:.2f} - {'Bearish' if signal < 0 else 'Bullish' if signal > 0 else 'Neutral'}"
                    }
                    
        except Exception as e:
            logger.debug(f"Error getting options flow: {e}")
            
        return 1.0, 0, {}
    
    # =========================================================================
    # MAIN ANALYSIS
    # =========================================================================
    
    async def analyze_market_direction(self) -> MarketDirectionResult:
        """
        Main analysis function - combines all signals.
        
        Returns complete market direction analysis.
        """
        await self._init_clients()
        
        logger.info("=" * 60)
        logger.info("MARKET DIRECTION ENGINE - Starting Analysis")
        logger.info("=" * 60)
        
        signals = []
        raw_data = {}
        
        # 1. Pre-market internals (20% weight)
        logger.info("Analyzing pre-market internals...")
        internals = await self.get_premarket_internals()
        raw_data["internals"] = internals
        
        # Calculate weighted market signal
        spy_signal = 0
        qqq_signal = 0
        weighted_signal = 0
        
        for symbol, data in internals.items():
            change = data.get("total_change", 0)
            weight = data.get("weight", 0)
            
            if symbol == "SPY":
                spy_signal = change
            elif symbol == "QQQ":
                qqq_signal = change
                
            weighted_signal += change * weight
            
            # Create signal
            direction = 1 if change > 0.3 else -1 if change < -0.3 else 0
            signals.append(MarketSignal(
                name=f"{symbol} Pre-Market",
                value=change,
                direction=direction,
                weight=0.05,  # 5% each, 20% total
                confidence=min(abs(change) * 10, 100),
                source="Polygon",
                description=f"{symbol} {change:+.2f}%"
            ))
        
        # 2. GEX Signal (25% weight)
        logger.info("Analyzing GEX regime...")
        gex_regime, gex_value, gex_data = await self.get_gex_signal()
        raw_data["gex"] = gex_data
        
        gex_direction = 0
        if gex_regime == GEXRegime.NEGATIVE:
            gex_direction = -1 if weighted_signal < 0 else 1  # Amplifies direction
        elif gex_regime == GEXRegime.POSITIVE:
            gex_direction = 1 if weighted_signal < 0 else -1  # Mean reversion
            
        signals.append(MarketSignal(
            name="GEX Regime",
            value=gex_value,
            direction=gex_direction,
            weight=0.25,
            confidence=70 if gex_regime != GEXRegime.NEUTRAL else 40,
            source="Unusual Whales",
            description=gex_data.get("interpretation", "N/A")
        ))
        
        # 3. VIX Signal (20% weight)
        logger.info("Analyzing VIX...")
        vix_value, vix_direction, vix_data = await self.get_vix_signal()
        raw_data["vix"] = vix_data
        
        signals.append(MarketSignal(
            name="VIX Analysis",
            value=vix_value,
            direction=vix_direction,
            weight=0.20,
            confidence=60,
            source="Polygon",
            description=vix_data.get("interpretation", "N/A")
        ))
        
        # 4. Dark Pool Signal (15% weight)
        logger.info("Analyzing dark pool...")
        dp_flow, dp_direction, dp_data = await self.get_dark_pool_signal()
        raw_data["dark_pool"] = dp_data
        
        signals.append(MarketSignal(
            name="Dark Pool Flow",
            value=dp_flow,
            direction=dp_direction,
            weight=0.15,
            confidence=50 if dp_data else 20,
            source="Unusual Whales",
            description=dp_data.get("interpretation", "N/A")
        ))
        
        # 5. Options Flow Signal (10% weight - reduced)
        logger.info("Analyzing options flow...")
        pc_ratio, flow_direction, flow_data = await self.get_options_flow_signal()
        raw_data["options_flow"] = flow_data
        
        signals.append(MarketSignal(
            name="Options Flow",
            value=pc_ratio,
            direction=flow_direction,
            weight=0.10,
            confidence=50 if flow_data else 20,
            source="Unusual Whales",
            description=flow_data.get("interpretation", "N/A")
        ))
        
        # =====================================================================
        # NEW SIGNALS (Feb 4, 2026) - Filling the gaps!
        # =====================================================================
        
        # 6. News Signal (5% weight)
        logger.info("Analyzing market news...")
        news_direction, news_data = await self.get_news_signal()
        raw_data["news"] = news_data
        
        signals.append(MarketSignal(
            name="📰 News Sentiment",
            value=news_data.get("net_sentiment", 0),
            direction=news_direction,
            weight=0.05,
            confidence=40 if news_data else 20,
            source="Polygon News",
            description=news_data.get("interpretation", "N/A")
        ))
        
        # 7. Pre-Market Movers (5% weight) - FUTURES PROXY
        logger.info("Analyzing pre-market movers (futures proxy)...")
        movers_direction, movers_data = await self.get_top_movers_signal()
        raw_data["movers"] = movers_data
        
        signals.append(MarketSignal(
            name="📊 Pre-Market Movers",
            value=movers_data.get("net_strength", 0),
            direction=movers_direction,
            weight=0.05,
            confidence=50 if movers_data else 20,
            source="Polygon Movers",
            description=movers_data.get("interpretation", "N/A")
        ))
        
        # 8. Options Skew (5% weight) - BETTER THAN REDDIT!
        logger.info("Analyzing options skew (smart money sentiment)...")
        skew_value, skew_direction, skew_data = await self.get_skew_signal()
        raw_data["skew"] = skew_data
        
        signals.append(MarketSignal(
            name="📈 Options Skew",
            value=skew_value,
            direction=skew_direction,
            weight=0.05,
            confidence=60 if skew_data else 20,
            source="Unusual Whales",
            description=skew_data.get("interpretation", "N/A")
        ))
        
        # 9. Max Pain (5% weight) - KEY LEVEL
        logger.info("Analyzing max pain (MM target)...")
        max_pain_value, mp_direction, mp_data = await self.get_max_pain_signal()
        raw_data["max_pain"] = mp_data
        
        signals.append(MarketSignal(
            name="🎯 Max Pain",
            value=max_pain_value,
            direction=mp_direction,
            weight=0.05,
            confidence=50 if mp_data else 20,
            source="Unusual Whales",
            description=mp_data.get("interpretation", "N/A")
        ))
        
        # Calculate overall direction
        total_score = 0
        total_weight = 0
        
        for signal in signals:
            total_score += signal.direction * signal.weight * signal.confidence
            total_weight += signal.weight
        
        if total_weight > 0:
            normalized_score = total_score / total_weight
        else:
            normalized_score = 0
        
        # Determine direction
        if normalized_score > 30:
            direction = MarketDirection.STRONG_BULLISH
        elif normalized_score > 10:
            direction = MarketDirection.BULLISH
        elif normalized_score < -30:
            direction = MarketDirection.STRONG_BEARISH
        elif normalized_score < -10:
            direction = MarketDirection.BEARISH
        else:
            direction = MarketDirection.NEUTRAL
        
        # Calculate confidence
        confidence = min(abs(normalized_score), 80)  # Cap at 80%
        
        # Generate best plays
        best_plays = await self._generate_best_plays(direction, gex_regime)
        avoid_plays = await self._generate_avoid_plays(direction, gex_regime)
        
        result = MarketDirectionResult(
            timestamp=datetime.now(),
            direction=direction,
            confidence=confidence,
            spy_signal=spy_signal,
            qqq_signal=qqq_signal,
            vix_signal=vix_value,
            gex_regime=gex_regime,
            gex_value=gex_value,
            dark_pool_signal=dp_flow,
            put_call_ratio=pc_ratio,
            signals=signals,
            best_plays=best_plays,
            avoid_plays=avoid_plays,
            raw_data=raw_data
        )
        
        # Log results
        logger.info("=" * 60)
        logger.info(f"DIRECTION: {direction.value}")
        logger.info(f"CONFIDENCE: {confidence:.1f}%")
        logger.info(f"GEX REGIME: {gex_regime.value}")
        logger.info("=" * 60)
        
        return result
    
    async def _generate_best_plays(
        self, 
        direction: MarketDirection, 
        gex_regime: GEXRegime
    ) -> List[Dict]:
        """Generate 8 best plays based on market direction."""
        
        plays = []
        
        if direction in [MarketDirection.STRONG_BEARISH, MarketDirection.BEARISH]:
            # Bearish plays - PUT opportunities
            plays = [
                {"symbol": "SPY", "action": "BUY PUTS", "reason": "Market weakness - ride the trend"},
                {"symbol": "QQQ", "action": "BUY PUTS", "reason": "Tech weakness - higher beta"},
                {"symbol": "NVDA", "action": "BUY PUTS", "reason": "High beta tech - amplifies moves"},
                {"symbol": "TSLA", "action": "BUY PUTS", "reason": "Volatile - big moves expected"},
                {"symbol": "AMD", "action": "BUY PUTS", "reason": "Semi weakness - sector drag"},
                {"symbol": "META", "action": "BUY PUTS", "reason": "Tech weakness play"},
                {"symbol": "COIN", "action": "BUY PUTS", "reason": "Risk-off correlation"},
                {"symbol": "ARKK", "action": "BUY PUTS", "reason": "Growth selloff proxy"},
            ]
            
            if gex_regime == GEXRegime.NEGATIVE:
                for play in plays:
                    play["note"] = "NEGATIVE GEX - Trend likely to continue"
                    
        elif direction in [MarketDirection.STRONG_BULLISH, MarketDirection.BULLISH]:
            # Bullish plays - avoid puts, or play calls
            plays = [
                {"symbol": "SPY", "action": "AVOID PUTS", "reason": "Market strength"},
                {"symbol": "QQQ", "action": "AVOID PUTS", "reason": "Tech leading"},
                {"symbol": "NVDA", "action": "AVOID PUTS", "reason": "AI momentum"},
                {"symbol": "MSFT", "action": "AVOID PUTS", "reason": "Quality tech bid"},
                {"symbol": "AAPL", "action": "AVOID PUTS", "reason": "Safe haven bid"},
                {"symbol": "GOOGL", "action": "AVOID PUTS", "reason": "Mega-cap strength"},
                {"symbol": "AMZN", "action": "AVOID PUTS", "reason": "Consumer strength"},
                {"symbol": "META", "action": "AVOID PUTS", "reason": "Ad spend recovery"},
            ]
            
        else:
            # Neutral - focus on range plays
            plays = [
                {"symbol": "SPY", "action": "WAIT", "reason": "No clear direction"},
                {"symbol": "QQQ", "action": "WAIT", "reason": "Consolidation expected"},
                {"symbol": "IWM", "action": "WATCH", "reason": "Small caps may lead"},
                {"symbol": "VIX", "action": "WATCH", "reason": "Monitor for breakout"},
                {"symbol": "NVDA", "action": "WATCH", "reason": "Key level test"},
                {"symbol": "TSLA", "action": "WATCH", "reason": "Coiling pattern"},
                {"symbol": "AMD", "action": "WATCH", "reason": "Range bound"},
                {"symbol": "META", "action": "WATCH", "reason": "Awaiting catalyst"},
            ]
            
            if gex_regime == GEXRegime.POSITIVE:
                for play in plays:
                    play["note"] = "POSITIVE GEX - Mean reversion likely, fade extremes"
        
        return plays[:8]
    
    async def _generate_avoid_plays(
        self, 
        direction: MarketDirection, 
        gex_regime: GEXRegime
    ) -> List[Dict]:
        """Generate plays to avoid."""
        
        if direction in [MarketDirection.STRONG_BEARISH, MarketDirection.BEARISH]:
            return [
                {"symbol": "CALLS", "reason": "Fighting the trend"},
                {"symbol": "DEFENSIVE PUTS", "reason": "Low beta = low reward"},
            ]
        elif direction in [MarketDirection.STRONG_BULLISH, MarketDirection.BULLISH]:
            return [
                {"symbol": "PUTS", "reason": "Fighting the trend"},
                {"symbol": "SHORT VOL", "reason": "Risk of reversal"},
            ]
        else:
            return [
                {"symbol": "DIRECTIONAL BETS", "reason": "No clear trend"},
                {"symbol": "EARNINGS PLAYS", "reason": "Added uncertainty"},
            ]


async def run_market_direction_analysis() -> MarketDirectionResult:
    """Run market direction analysis."""
    engine = MarketDirectionEngine()
    try:
        return await engine.analyze_market_direction()
    finally:
        await engine.close()


def format_result_for_display(result: MarketDirectionResult) -> str:
    """Format result for console/dashboard display."""
    output = []
    output.append("=" * 60)
    output.append("🎯 MARKET DIRECTION ANALYSIS")
    output.append(f"   Time: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S ET')}")
    output.append("=" * 60)
    
    # Direction with emoji
    direction_emoji = {
        MarketDirection.STRONG_BULLISH: "🟢🟢",
        MarketDirection.BULLISH: "🟢",
        MarketDirection.NEUTRAL: "⚪",
        MarketDirection.BEARISH: "🔴",
        MarketDirection.STRONG_BEARISH: "🔴🔴",
    }
    
    output.append(f"\n{direction_emoji.get(result.direction, '⚪')} DIRECTION: {result.direction.value}")
    output.append(f"📊 CONFIDENCE: {result.confidence:.1f}%")
    
    output.append(f"\n📈 Market Internals:")
    output.append(f"   SPY: {result.spy_signal:+.2f}%")
    output.append(f"   QQQ: {result.qqq_signal:+.2f}%")
    output.append(f"   VIX: {result.vix_signal:.2f}")
    
    output.append(f"\n🎰 GEX Regime: {result.gex_regime.value}")
    output.append(f"   GEX Value: {result.gex_value:.2f}B")
    
    output.append(f"\n🏊 Dark Pool: {result.dark_pool_signal:+.1%}")
    output.append(f"📊 Put/Call: {result.put_call_ratio:.2f}")
    
    output.append("\n" + "-" * 60)
    output.append("🎯 8 BEST PLAYS TODAY:")
    output.append("-" * 60)
    
    for i, play in enumerate(result.best_plays, 1):
        note = play.get('note', '')
        output.append(f"{i}. {play['symbol']:6} | {play['action']:12} | {play['reason']}")
        if note:
            output.append(f"         ↳ {note}")
    
    output.append("\n" + "-" * 60)
    output.append("⚠️ AVOID TODAY:")
    output.append("-" * 60)
    
    for avoid in result.avoid_plays:
        output.append(f"   ❌ {avoid['symbol']}: {avoid['reason']}")
    
    output.append("\n" + "=" * 60)
    
    return "\n".join(output)


if __name__ == "__main__":
    async def main():
        result = await run_market_direction_analysis()
        print(format_result_for_display(result))
        
        # Save to file
        output_file = Path("/Users/chavala/PutsEngine/logs/market_direction.json")
        with open(output_file, "w") as f:
            json.dump({
                "timestamp": result.timestamp.isoformat(),
                "direction": result.direction.value,
                "confidence": result.confidence,
                "spy_signal": result.spy_signal,
                "qqq_signal": result.qqq_signal,
                "vix_signal": result.vix_signal,
                "gex_regime": result.gex_regime.value,
                "gex_value": result.gex_value,
                "dark_pool_signal": result.dark_pool_signal,
                "put_call_ratio": result.put_call_ratio,
                "best_plays": result.best_plays,
                "avoid_plays": result.avoid_plays,
                "raw_data": result.raw_data
            }, f, indent=2, default=str)
        print(f"\n📁 Saved to: {output_file}")
    
    asyncio.run(main())
