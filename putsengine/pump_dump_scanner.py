"""
Pump-and-Dump Reversal Pattern Scanner

PURPOSE: Detect stocks that had strong upward moves followed by reversal signals.
         These are high-probability put candidates.

PATTERN DETECTION:
- Stock up +5% or more in 1-2 days
- Followed by reversal signals (bearish candle, volume spike)
- Target: Catch the dump after the pump

This would have caught on Jan 29, 2026:
- OKLO: +10.7% Jan 27 → -8.8% Jan 28
- CLS: +3.6% Jan 27 → -13.1% Jan 28  
- FSLR: +6.1% Jan 27 → -10.2% Jan 28

INSTITUTIONAL LOGIC:
- Pump = retail FOMO buying
- Dump = smart money exiting into strength
- Reversal candle = trap complete
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
import pytz
from loguru import logger
from dataclasses import dataclass


@dataclass
class PumpDumpAlert:
    """Alert for pump-and-dump pattern detection."""
    symbol: str
    pump_pct: float  # How much it pumped
    pump_days: int   # Over how many days
    reversal_signal: str  # What triggered the dump alert
    prior_high: float
    current_price: float
    volume_ratio: float  # Current vol vs average
    confidence: float  # 0-1 confidence score
    alert_time: str
    
    @property
    def severity(self) -> str:
        if self.pump_pct >= 10.0 and self.confidence >= 0.80:
            return "CRITICAL"
        elif self.pump_pct >= 7.0 or self.confidence >= 0.70:
            return "HIGH"
        else:
            return "MEDIUM"


class PumpDumpScanner:
    """
    Scans for pump-and-dump reversal patterns.
    
    DETECTION CRITERIA:
    1. Stock up >= 5% in last 1-3 days (the pump)
    2. One or more reversal signals:
       - Bearish engulfing candle
       - Close below prior day's low
       - High volume red candle
       - Failed breakout (new high then close lower)
    3. Volume confirmation (RVOL > 1.3)
    
    INSTITUTIONAL TRUTH:
    - Pumps create liquidity for institutions to sell into
    - Reversal signals = smart money exiting
    - High RVOL on red = distribution, not accumulation
    """
    
    # Thresholds - LOWERED from 5% to 3% to catch more patterns (NET, CLS, etc.)
    MIN_PUMP_PCT = 3.0  # Minimum % gain to be considered a "pump" (was 5.0)
    MIN_PUMP_DAYS = 1   # Minimum days for pump
    MAX_PUMP_DAYS = 3   # Maximum days for pump (fresh pump)
    MIN_RVOL = 1.3      # Minimum relative volume for confirmation
    
    def __init__(self, alpaca_client):
        self.alpaca_client = alpaca_client
    
    async def detect_pump(self, symbol: str, bars: List = None) -> Optional[Dict]:
        """
        Detect if symbol has had a recent pump (+5%+ move).
        
        Args:
            symbol: Ticker symbol
            bars: Optional pre-fetched bars (need at least 10 days)
            
        Returns:
            Dict with pump info or None
        """
        if bars is None:
            try:
                bars = await self.alpaca_client.get_daily_bars(symbol, limit=15)
            except Exception as e:
                logger.debug(f"Failed to get bars for {symbol}: {e}")
                return None
        
        if len(bars) < 5:
            return None
        
        # Look for pump in last 3 days
        for days_back in range(1, self.MAX_PUMP_DAYS + 1):
            if len(bars) < days_back + 2:
                continue
            
            # Compare current to days_back ago
            start_idx = -(days_back + 1)
            start_price = bars[start_idx].close
            current_price = bars[-1].close
            high_in_period = max(b.high for b in bars[start_idx:])
            
            # Calculate pump percentage (to highest point)
            pump_pct = ((high_in_period - start_price) / start_price) * 100
            
            if pump_pct >= self.MIN_PUMP_PCT:
                return {
                    "symbol": symbol,
                    "pump_pct": pump_pct,
                    "pump_days": days_back,
                    "start_price": start_price,
                    "high_price": high_in_period,
                    "current_price": current_price,
                    "bars": bars
                }
        
        return None
    
    def detect_reversal_signals(self, bars: List) -> List[str]:
        """
        Detect reversal signals after a pump.
        
        Args:
            bars: Daily bars (most recent is last)
            
        Returns:
            List of detected reversal signal names
        """
        signals = []
        
        if len(bars) < 2:
            return signals
        
        current = bars[-1]
        prior = bars[-2]
        
        # 1. Bearish Engulfing
        if prior.close > prior.open:  # Prior was green
            if current.close < current.open:  # Current is red
                if current.open >= prior.close and current.close <= prior.open:
                    signals.append("bearish_engulfing")
        
        # 2. Close below prior day's low
        if current.close < prior.low:
            signals.append("close_below_prior_low")
        
        # 3. High volume red candle
        if len(bars) >= 10:
            avg_vol = sum(b.volume for b in bars[-10:-1]) / 9
            if current.volume > avg_vol * 1.5 and current.close < current.open:
                signals.append("high_vol_red")
        
        # 4. Failed breakout (new high then close lower)
        if len(bars) >= 3:
            three_day_high = max(b.high for b in bars[-3:-1])  # Excluding today
            if current.high > three_day_high and current.close < prior.close:
                signals.append("failed_breakout")
        
        # 5. Topping tail (long upper wick)
        body = abs(current.close - current.open)
        upper_wick = current.high - max(current.close, current.open)
        if body > 0 and upper_wick > body * 2:
            signals.append("topping_tail")
        
        # 6. Gap down open after pump
        if current.open < prior.close * 0.98:  # >2% gap down
            signals.append("gap_down_after_pump")
        
        return signals
    
    async def scan_for_pump_dumps(self, symbols: List[str]) -> Dict:
        """
        Scan symbols for pump-and-dump patterns.
        
        Args:
            symbols: List of ticker symbols
            
        Returns:
            Dict with alerts categorized by severity
        """
        et = pytz.timezone('US/Eastern')
        now = datetime.now(et)
        
        logger.info(f"Pump-Dump Scanner: Starting scan of {len(symbols)} symbols")
        
        alerts = {
            "critical": [],
            "high": [],
            "medium": [],
            "all": []
        }
        
        for symbol in symbols:
            try:
                # Check for pump
                pump_info = await self.detect_pump(symbol)
                
                if pump_info is None:
                    continue
                
                # Check for reversal signals
                bars = pump_info["bars"]
                reversal_signals = self.detect_reversal_signals(bars)
                
                if not reversal_signals:
                    continue
                
                # Calculate volume ratio
                if len(bars) >= 10:
                    avg_vol = sum(b.volume for b in bars[-10:-1]) / 9
                    vol_ratio = bars[-1].volume / avg_vol if avg_vol > 0 else 1.0
                else:
                    vol_ratio = 1.0
                
                # Calculate confidence
                confidence = self._calculate_confidence(
                    pump_info["pump_pct"],
                    reversal_signals,
                    vol_ratio
                )
                
                # Create alert
                alert = PumpDumpAlert(
                    symbol=symbol,
                    pump_pct=pump_info["pump_pct"],
                    pump_days=pump_info["pump_days"],
                    reversal_signal=", ".join(reversal_signals),
                    prior_high=pump_info["high_price"],
                    current_price=pump_info["current_price"],
                    volume_ratio=vol_ratio,
                    confidence=confidence,
                    alert_time=now.isoformat()
                )
                
                # Categorize by severity
                alerts["all"].append(alert)
                
                if alert.severity == "CRITICAL":
                    alerts["critical"].append(alert)
                elif alert.severity == "HIGH":
                    alerts["high"].append(alert)
                else:
                    alerts["medium"].append(alert)
                
                logger.info(
                    f"PUMP-DUMP: {symbol} | Pump: +{pump_info['pump_pct']:.1f}% over {pump_info['pump_days']}d | "
                    f"Signals: {', '.join(reversal_signals)} | Confidence: {confidence:.2f}"
                )
                
            except Exception as e:
                logger.debug(f"Error scanning {symbol}: {e}")
        
        return {
            "critical": alerts["critical"],
            "high": alerts["high"],
            "medium": alerts["medium"],
            "all": alerts["all"],
            "summary": {
                "scanned": len(symbols),
                "alerts_count": len(alerts["all"]),
                "critical_count": len(alerts["critical"]),
                "high_count": len(alerts["high"]),
                "medium_count": len(alerts["medium"])
            },
            "scan_time": now.isoformat()
        }
    
    def _calculate_confidence(
        self, 
        pump_pct: float, 
        signals: List[str], 
        vol_ratio: float
    ) -> float:
        """Calculate confidence score for pump-dump alert."""
        confidence = 0.0
        
        # Pump size contribution (max 0.30)
        if pump_pct >= 15.0:
            confidence += 0.30
        elif pump_pct >= 10.0:
            confidence += 0.25
        elif pump_pct >= 7.0:
            confidence += 0.20
        else:
            confidence += 0.15
        
        # Signal count contribution (max 0.40)
        signal_score = min(len(signals) * 0.10, 0.40)
        confidence += signal_score
        
        # Volume ratio contribution (max 0.30)
        if vol_ratio >= 2.0:
            confidence += 0.30
        elif vol_ratio >= 1.5:
            confidence += 0.20
        elif vol_ratio >= 1.3:
            confidence += 0.10
        
        return min(confidence, 1.0)


async def run_pump_dump_scan(alpaca_client, symbols: List[str]) -> Dict:
    """
    Run pump-and-dump scan on symbols.
    
    Args:
        alpaca_client: AlpacaClient instance
        symbols: List of symbols to scan
        
    Returns:
        Dict with alerts and summary
    """
    scanner = PumpDumpScanner(alpaca_client)
    return await scanner.scan_for_pump_dumps(symbols)


async def inject_pump_dumps_to_dui(alerts: List[PumpDumpAlert]) -> int:
    """
    Inject pump-dump alerts into Dynamic Universe Injection.
    
    Args:
        alerts: List of PumpDumpAlert objects
        
    Returns:
        Number of symbols injected
    """
    from putsengine.config import DynamicUniverseManager
    
    dui = DynamicUniverseManager()
    injected = 0
    
    for alert in alerts:
        # Calculate score based on confidence
        score = min(0.50, 0.30 + alert.confidence * 0.20)
        
        signals = [
            "pump_dump_reversal",
            f"pump_{alert.pump_pct:.0f}pct",
            alert.reversal_signal.replace(", ", "_")
        ]
        
        dui.promote_from_distribution(
            symbol=alert.symbol,
            score=score,
            signals=signals
        )
        injected += 1
        
        logger.info(
            f"DUI: Injected {alert.symbol} via pump-dump reversal | "
            f"Pump: +{alert.pump_pct:.1f}% | Score: {score:.2f}"
        )
    
    return injected
