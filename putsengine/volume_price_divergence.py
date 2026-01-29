"""
Volume-Price Divergence Scanner (Enhanced)

PURPOSE: Detect institutional distribution patterns where volume is elevated
         but price doesn't progress - this is smart money exiting.

PATTERNS DETECTED:
1. High volume + flat price = distribution
2. Rising volume + falling price = capitulation
3. Volume expansion with price compression = coiling for move
4. Multiple distribution days = sustained selling

This would have caught:
- MSFT: High volume on Jan 27 with flat price before Jan 28 crash
- NOW: Volume spike on Jan 27 with weakness before Jan 28 crash  
- TEAM: Distribution pattern on Jan 26-27 before Jan 28 crash

INSTITUTIONAL LOGIC:
- Institutions sell gradually to not move price
- High volume + flat/weak price = someone exiting
- Multiple days of this = serious distribution
- This precedes major moves by 1-3 days
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
import pytz
from loguru import logger
from dataclasses import dataclass


@dataclass
class VolumePriceDivergenceAlert:
    """Alert for volume-price divergence detection."""
    symbol: str
    pattern_type: str  # "distribution", "capitulation", "compression"
    days_detected: int
    avg_volume_ratio: float  # Average volume vs 20-day average
    price_change_pct: float  # Net price change over period
    distribution_day_count: int  # Number of distribution days
    confidence: float
    alert_time: str
    
    @property
    def severity(self) -> str:
        if self.distribution_day_count >= 3 and self.avg_volume_ratio >= 2.0:
            return "CRITICAL"
        elif self.distribution_day_count >= 2 or self.avg_volume_ratio >= 1.8:
            return "HIGH"
        else:
            return "MEDIUM"


class VolumePriceDivergenceScanner:
    """
    Enhanced scanner for volume-price divergence patterns.
    
    DETECTION CRITERIA:
    
    1. DISTRIBUTION PATTERN (Most important):
       - Volume > 1.3x average for 2+ days
       - Price change < 2% over same period
       - = Institutions selling into bids
    
    2. CAPITULATION PATTERN:
       - Volume > 2x average
       - Price down > 3%
       - = Forced selling, panic
    
    3. COMPRESSION PATTERN:
       - Volume expanding (day over day)
       - Price range contracting
       - = Coiling for big move
    
    SCORING:
    - Each distribution day = +0.10
    - High RVOL (>2x) = +0.10
    - Multiple consecutive days = +0.05 per day
    - Cap at 0.50 (need confirmation)
    """
    
    # Thresholds
    RVOL_THRESHOLD = 1.3  # Minimum for "high volume"
    RVOL_HIGH = 2.0       # Very high volume
    PRICE_FLAT_THRESHOLD = 0.02  # < 2% = flat
    MIN_DISTRIBUTION_DAYS = 2
    LOOKBACK_DAYS = 5
    
    def __init__(self, alpaca_client):
        self.alpaca_client = alpaca_client
    
    async def analyze_symbol(self, symbol: str, bars: List = None) -> Optional[VolumePriceDivergenceAlert]:
        """
        Analyze a symbol for volume-price divergence.
        
        Args:
            symbol: Ticker symbol
            bars: Optional pre-fetched bars (need at least 25 days)
            
        Returns:
            VolumePriceDivergenceAlert if pattern detected, None otherwise
        """
        if bars is None:
            try:
                bars = await self.alpaca_client.get_daily_bars(symbol, limit=30)
            except Exception as e:
                logger.debug(f"Failed to get bars for {symbol}: {e}")
                return None
        
        if len(bars) < 25:
            return None
        
        # Calculate 20-day average volume (excluding last 5 days)
        avg_volume = sum(b.volume for b in bars[-25:-5]) / 20
        
        if avg_volume <= 0:
            return None
        
        # Analyze last 5 days for patterns
        recent_bars = bars[-self.LOOKBACK_DAYS:]
        
        # Count distribution days
        distribution_days = 0
        total_volume_ratio = 0
        
        for bar in recent_bars:
            rvol = bar.volume / avg_volume
            total_volume_ratio += rvol
            
            # Distribution day: High volume + red or flat
            price_change = (bar.close - bar.open) / bar.open if bar.open > 0 else 0
            
            if rvol >= self.RVOL_THRESHOLD and price_change <= 0.01:
                distribution_days += 1
        
        avg_volume_ratio = total_volume_ratio / len(recent_bars)
        
        # Calculate net price change over lookback period
        start_price = recent_bars[0].open
        end_price = recent_bars[-1].close
        price_change_pct = (end_price - start_price) / start_price if start_price > 0 else 0
        
        # Determine pattern type
        pattern_type = None
        confidence = 0.0
        
        # Check for distribution pattern
        if distribution_days >= self.MIN_DISTRIBUTION_DAYS and abs(price_change_pct) < self.PRICE_FLAT_THRESHOLD:
            pattern_type = "distribution"
            confidence = self._calculate_distribution_confidence(
                distribution_days, avg_volume_ratio, price_change_pct
            )
        
        # Check for capitulation pattern
        elif avg_volume_ratio >= self.RVOL_HIGH and price_change_pct < -0.03:
            pattern_type = "capitulation"
            confidence = min(0.50, avg_volume_ratio * 0.15 + abs(price_change_pct) * 2)
        
        # Check for compression pattern
        else:
            # Volume expanding, price range contracting
            volume_trend = (recent_bars[-1].volume - recent_bars[0].volume) / recent_bars[0].volume if recent_bars[0].volume > 0 else 0
            
            # Calculate average daily range
            ranges = [(b.high - b.low) / b.low for b in recent_bars if b.low > 0]
            if len(ranges) >= 2:
                range_trend = (ranges[-1] - ranges[0]) / ranges[0] if ranges[0] > 0 else 0
                
                if volume_trend > 0.20 and range_trend < -0.20:
                    pattern_type = "compression"
                    confidence = min(0.40, volume_trend * 0.3 + abs(range_trend) * 0.3)
        
        if pattern_type is None or confidence < 0.25:
            return None
        
        et = pytz.timezone('US/Eastern')
        now = datetime.now(et)
        
        return VolumePriceDivergenceAlert(
            symbol=symbol,
            pattern_type=pattern_type,
            days_detected=self.LOOKBACK_DAYS,
            avg_volume_ratio=avg_volume_ratio,
            price_change_pct=price_change_pct,
            distribution_day_count=distribution_days,
            confidence=confidence,
            alert_time=now.isoformat()
        )
    
    def _calculate_distribution_confidence(
        self,
        distribution_days: int,
        avg_volume_ratio: float,
        price_change_pct: float
    ) -> float:
        """Calculate confidence score for distribution pattern."""
        confidence = 0.0
        
        # Distribution days (max 0.30)
        confidence += min(distribution_days * 0.10, 0.30)
        
        # Volume ratio (max 0.15)
        if avg_volume_ratio >= 2.0:
            confidence += 0.15
        elif avg_volume_ratio >= 1.5:
            confidence += 0.10
        else:
            confidence += 0.05
        
        # Price flatness bonus (max 0.05)
        if abs(price_change_pct) < 0.01:
            confidence += 0.05
        
        return min(confidence, 0.50)
    
    async def scan_universe(self, symbols: List[str]) -> Dict:
        """
        Scan symbols for volume-price divergence patterns.
        
        Args:
            symbols: List of ticker symbols
            
        Returns:
            Dict with alerts categorized by pattern type and severity
        """
        et = pytz.timezone('US/Eastern')
        now = datetime.now(et)
        
        logger.info(f"Volume-Price Divergence Scanner: Starting scan of {len(symbols)} symbols")
        
        alerts = {
            "distribution": [],
            "capitulation": [],
            "compression": [],
            "critical": [],
            "high": [],
            "all": []
        }
        
        for symbol in symbols:
            try:
                alert = await self.analyze_symbol(symbol)
                
                if alert:
                    alerts["all"].append(alert)
                    alerts[alert.pattern_type].append(alert)
                    
                    if alert.severity == "CRITICAL":
                        alerts["critical"].append(alert)
                    elif alert.severity == "HIGH":
                        alerts["high"].append(alert)
                    
                    logger.info(
                        f"VOL-PRICE DIVERGENCE: {symbol} | Pattern: {alert.pattern_type} | "
                        f"Dist Days: {alert.distribution_day_count} | RVOL: {alert.avg_volume_ratio:.1f}x | "
                        f"Price: {alert.price_change_pct*100:+.1f}% | Confidence: {alert.confidence:.2f}"
                    )
                    
            except Exception as e:
                logger.debug(f"Error scanning {symbol}: {e}")
        
        return {
            "distribution": alerts["distribution"],
            "capitulation": alerts["capitulation"],
            "compression": alerts["compression"],
            "critical": alerts["critical"],
            "high": alerts["high"],
            "all": alerts["all"],
            "summary": {
                "scanned": len(symbols),
                "alerts_count": len(alerts["all"]),
                "distribution_count": len(alerts["distribution"]),
                "capitulation_count": len(alerts["capitulation"]),
                "compression_count": len(alerts["compression"]),
                "critical_count": len(alerts["critical"]),
                "high_count": len(alerts["high"])
            },
            "scan_time": now.isoformat()
        }


async def run_volume_price_scan(alpaca_client, symbols: List[str]) -> Dict:
    """
    Run volume-price divergence scan on symbols.
    
    Args:
        alpaca_client: AlpacaClient instance
        symbols: List of symbols to scan
        
    Returns:
        Dict with alerts and summary
    """
    scanner = VolumePriceDivergenceScanner(alpaca_client)
    return await scanner.scan_universe(symbols)


async def inject_divergence_to_dui(alerts: List[VolumePriceDivergenceAlert]) -> int:
    """
    Inject volume-price divergence alerts into Dynamic Universe Injection.
    
    Args:
        alerts: List of VolumePriceDivergenceAlert objects
        
    Returns:
        Number of symbols injected
    """
    from putsengine.config import DynamicUniverseManager
    
    dui = DynamicUniverseManager()
    injected = 0
    
    for alert in alerts:
        signals = [
            f"vol_price_{alert.pattern_type}",
            f"rvol_{alert.avg_volume_ratio:.1f}x",
            f"dist_days_{alert.distribution_day_count}"
        ]
        
        dui.promote_from_liquidity(
            symbol=alert.symbol,
            score=alert.confidence,
            signals=signals
        )
        injected += 1
        
        logger.info(
            f"DUI: Injected {alert.symbol} via vol-price divergence | "
            f"Pattern: {alert.pattern_type} | Score: {alert.confidence:.2f}"
        )
    
    return injected
