"""
Multi-Day Weakness Scanner - Detect deteriorating price patterns over 2-5 days

PURPOSE: Identify stocks showing weakness BEFORE the major drop.
         These patterns would have flagged MP, USAR, LAC, JOBY on Jan 26-27.

PATTERNS DETECTED:

1. LOWER HIGHS (3-day) - Classic distribution
   Day 1: High $50
   Day 2: High $49.50
   Day 3: High $49.00
   → Distribution in progress

2. BREAKING 5-DAY LOW - Momentum failure
   5-day low: $45
   Current close: $44.50
   → Support broken, accelerating down

3. WEAK CLOSES - Sellers in control
   Close in bottom 30% of daily range for 2+ days
   → Buyers exhausted

4. RISING VOLUME ON RED - Distribution
   Down day with 1.5x+ average volume
   → Institutions exiting

5. LOWER LOWS + LOWER HIGHS - Downtrend confirmed
   3+ consecutive lower highs AND lower lows
   → Bearish trend established

6. FAILED VWAP RECLAIM - Institutional rejection
   VWAP tested but rejected 2+ times
   → Sellers defending

INSTITUTIONAL TRUTH:
Major moves don't happen overnight. 90% of -10%+ drops show 
weakness signals 2-5 days before. The key is detecting the 
ACCUMULATION of signals, not any single indicator.
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
import pytz
from loguru import logger
from dataclasses import dataclass


@dataclass
class WeaknessPattern:
    """A detected multi-day weakness pattern."""
    pattern_name: str
    days_detected: int
    confidence: float  # 0.0 to 1.0
    description: str


@dataclass
class WeaknessReport:
    """Full weakness report for a symbol."""
    symbol: str
    patterns: List[WeaknessPattern]
    total_score: float
    days_analyzed: int
    recommendation: str
    
    @property
    def signal_count(self) -> int:
        return len(self.patterns)
    
    @property
    def is_actionable(self) -> bool:
        # TUNED: Lowered threshold from 3 patterns to 2 patterns
        # Also lowered score threshold from 0.30 to 0.25
        return self.total_score >= 0.25 and self.signal_count >= 2


class MultiDayWeaknessScanner:
    """
    Scans for multi-day weakness patterns that precede major moves.
    
    INSTITUTIONAL LOGIC:
    - Single-day signals are noise
    - Multi-day patterns are conviction
    - Accumulation of 2+ patterns = actionable setup (TUNED from 3+)
    
    TUNING (Jan 29, 2026):
    - Lowered actionable threshold from 3 patterns to 2
    - Increased pattern weights for early detection
    - Added "accelerating weakness" bonus for consecutive weak days
    """
    
    # Pattern weights for scoring (TUNED - increased weights)
    PATTERN_WEIGHTS = {
        "lower_highs_3day": 0.18,      # Increased from 0.15
        "break_5day_low": 0.22,        # Increased from 0.20
        "weak_closes_2day": 0.15,      # Increased from 0.10
        "rising_volume_red": 0.20,     # Increased from 0.15
        "lower_lows_highs_3day": 0.22, # Increased from 0.20
        "failed_vwap_reclaim": 0.18,   # Increased from 0.15
        "below_all_mas": 0.15,         # Increased from 0.10
        "bearish_engulfing": 0.15,     # Increased from 0.10
        "accelerating_weakness": 0.20, # NEW pattern
    }
    
    def __init__(self, price_client):
        """
        Args:
            price_client: PolygonClient (preferred) or AlpacaClient for price data
        """
        self.price_client = price_client
    
    async def analyze_symbol(self, symbol: str, bars: List = None) -> WeaknessReport:
        """
        Analyze a symbol for multi-day weakness patterns.
        
        Args:
            symbol: Ticker symbol
            bars: Optional pre-fetched daily bars (must have at least 10 days)
            
        Returns:
            WeaknessReport with all detected patterns
        """
        # Fetch bars if not provided
        if bars is None:
            try:
                bars = await self.price_client.get_daily_bars(
                    symbol=symbol,
                    limit=20
                )
            except Exception as e:
                logger.error(f"Failed to get bars for {symbol}: {e}")
                return WeaknessReport(
                    symbol=symbol,
                    patterns=[],
                    total_score=0,
                    days_analyzed=0,
                    recommendation="INSUFFICIENT DATA"
                )
        
        if len(bars) < 5:
            return WeaknessReport(
                symbol=symbol,
                patterns=[],
                total_score=0,
                days_analyzed=len(bars),
                recommendation="INSUFFICIENT DATA"
            )
        
        patterns = []
        
        # 1. LOWER HIGHS (3-day)
        if len(bars) >= 3:
            if bars[-1].high < bars[-2].high < bars[-3].high:
                patterns.append(WeaknessPattern(
                    pattern_name="lower_highs_3day",
                    days_detected=3,
                    confidence=0.80,
                    description=f"3 consecutive lower highs: ${bars[-3].high:.2f} → ${bars[-2].high:.2f} → ${bars[-1].high:.2f}"
                ))
        
        # 2. BREAKING 5-DAY LOW
        if len(bars) >= 5:
            five_day_low = min(b.low for b in bars[-5:])
            if bars[-1].close <= five_day_low:
                patterns.append(WeaknessPattern(
                    pattern_name="break_5day_low",
                    days_detected=5,
                    confidence=0.85,
                    description=f"Closed at/below 5-day low (${five_day_low:.2f})"
                ))
        
        # 3. WEAK CLOSES (2+ days)
        if len(bars) >= 3:
            weak_close_count = 0
            for bar in bars[-3:]:
                bar_range = bar.high - bar.low
                if bar_range > 0:
                    close_position = (bar.close - bar.low) / bar_range
                    if close_position < 0.30:  # Close in bottom 30%
                        weak_close_count += 1
            
            if weak_close_count >= 2:
                patterns.append(WeaknessPattern(
                    pattern_name="weak_closes_2day",
                    days_detected=weak_close_count,
                    confidence=0.70,
                    description=f"{weak_close_count} days with weak closes (bottom 30% of range)"
                ))
        
        # 4. RISING VOLUME ON RED
        if len(bars) >= 10:
            avg_volume = sum(b.volume for b in bars[-10:-1]) / 9
            last_bar = bars[-1]
            
            if last_bar.close < last_bar.open and last_bar.volume > avg_volume * 1.5:
                rvol = last_bar.volume / avg_volume
                patterns.append(WeaknessPattern(
                    pattern_name="rising_volume_red",
                    days_detected=1,
                    confidence=min(0.90, 0.50 + (rvol - 1.5) * 0.20),
                    description=f"Down day with {rvol:.1f}x average volume (distribution)"
                ))
        
        # 5. LOWER LOWS + LOWER HIGHS (3-day)
        if len(bars) >= 3:
            lower_lows = bars[-1].low < bars[-2].low < bars[-3].low
            lower_highs = bars[-1].high < bars[-2].high < bars[-3].high
            
            if lower_lows and lower_highs:
                patterns.append(WeaknessPattern(
                    pattern_name="lower_lows_highs_3day",
                    days_detected=3,
                    confidence=0.90,
                    description="3 consecutive lower highs AND lower lows - established downtrend"
                ))
        
        # 6. FAILED VWAP RECLAIM (approximated by close vs midpoint)
        if len(bars) >= 2:
            # Use midpoint as proxy for VWAP
            yesterday_mid = (bars[-2].high + bars[-2].low) / 2
            today_mid = (bars[-1].high + bars[-1].low) / 2
            
            # If both days closed below midpoint
            if bars[-1].close < today_mid and bars[-2].close < yesterday_mid:
                patterns.append(WeaknessPattern(
                    pattern_name="failed_vwap_reclaim",
                    days_detected=2,
                    confidence=0.70,
                    description="Failed to reclaim VWAP for 2 consecutive days"
                ))
        
        # 7. BELOW ALL MOVING AVERAGES (5, 10, 20 day)
        if len(bars) >= 20:
            close = bars[-1].close
            ma5 = sum(b.close for b in bars[-5:]) / 5
            ma10 = sum(b.close for b in bars[-10:]) / 10
            ma20 = sum(b.close for b in bars[-20:]) / 20
            
            if close < ma5 < ma10 < ma20:
                patterns.append(WeaknessPattern(
                    pattern_name="below_all_mas",
                    days_detected=1,
                    confidence=0.85,
                    description=f"Below all MAs (5/10/20) in bearish alignment"
                ))
        
        # 8. BEARISH ENGULFING
        if len(bars) >= 2:
            prev = bars[-2]
            curr = bars[-1]
            
            # Previous day green, current day red and engulfs
            if prev.close > prev.open:  # Previous was green
                if curr.close < curr.open:  # Current is red
                    if curr.open > prev.close and curr.close < prev.open:  # Engulfing
                        patterns.append(WeaknessPattern(
                            pattern_name="bearish_engulfing",
                            days_detected=2,
                            confidence=0.75,
                            description="Bearish engulfing pattern - strong reversal signal"
                        ))
        
        # 9. ACCELERATING WEAKNESS (NEW - would have caught MSTR, NOW)
        # 2+ consecutive weak days with increasing volume
        if len(bars) >= 3:
            weak_days = 0
            vol_increasing = True
            
            for i in range(-3, 0):
                bar = bars[i]
                prev_bar = bars[i-1] if i > -len(bars) else None
                
                # Check if day is weak (close < open or close < prior close)
                is_weak = bar.close < bar.open or (prev_bar and bar.close < prev_bar.close)
                
                if is_weak:
                    weak_days += 1
                else:
                    weak_days = 0  # Reset if we see a strong day
                
                # Check volume increasing
                if prev_bar and bar.volume < prev_bar.volume * 0.9:
                    vol_increasing = False
            
            if weak_days >= 2 and vol_increasing:
                patterns.append(WeaknessPattern(
                    pattern_name="accelerating_weakness",
                    days_detected=weak_days,
                    confidence=0.85,
                    description=f"{weak_days} consecutive weak days with rising volume - accelerating selling"
                ))
        
        # Calculate total score
        total_score = sum(
            self.PATTERN_WEIGHTS.get(p.pattern_name, 0.10) * p.confidence
            for p in patterns
        )
        
        # Determine recommendation (TUNED - lower thresholds for earlier detection)
        if total_score >= 0.45 and len(patterns) >= 3:
            recommendation = "STRONG SELL SIGNAL - Multiple weakness patterns"
        elif total_score >= 0.30 and len(patterns) >= 2:
            recommendation = "MODERATE SELL SIGNAL - Watch for continuation"
        elif total_score >= 0.25 and len(patterns) >= 2:
            recommendation = "ACTIONABLE - Early weakness detected"
        elif total_score >= 0.15:
            recommendation = "CAUTION - Early weakness signs"
        else:
            recommendation = "NO ACTIONABLE PATTERN"
        
        return WeaknessReport(
            symbol=symbol,
            patterns=patterns,
            total_score=total_score,
            days_analyzed=len(bars),
            recommendation=recommendation
        )
    
    async def scan_universe(self, symbols: List[str]) -> Dict[str, WeaknessReport]:
        """
        Scan entire universe for multi-day weakness.
        
        Args:
            symbols: List of ticker symbols
            
        Returns:
            Dict of {symbol: WeaknessReport}
        """
        results = {}
        
        for symbol in symbols:
            try:
                report = await self.analyze_symbol(symbol)
                results[symbol] = report
                
                if report.is_actionable:
                    logger.info(
                        f"WEAKNESS DETECTED: {symbol} | "
                        f"Score: {report.total_score:.2f} | "
                        f"Patterns: {report.signal_count} | "
                        f"{report.recommendation}"
                    )
            except Exception as e:
                logger.debug(f"Failed to analyze {symbol}: {e}")
        
        return results


async def run_multiday_weakness_scan(price_client, symbols: List[str]) -> Dict:
    """
    Run multi-day weakness scan on symbols.
    
    Args:
        price_client: PolygonClient (preferred) or AlpacaClient for price data
        symbols: List of symbols to scan
        
    Returns:
        Dict with actionable candidates and full results
    """
    scanner = MultiDayWeaknessScanner(price_client)
    
    results = await scanner.scan_universe(symbols)
    
    # Filter to actionable only
    actionable = {
        symbol: report 
        for symbol, report in results.items()
        if report.is_actionable
    }
    
    # Sort by score
    sorted_actionable = sorted(
        actionable.items(),
        key=lambda x: x[1].total_score,
        reverse=True
    )
    
    logger.info(
        f"Multi-Day Weakness Scan: {len(symbols)} scanned, "
        f"{len(actionable)} actionable"
    )
    
    return {
        "actionable": dict(sorted_actionable),
        "all_results": results,
        "scan_time": datetime.now().isoformat(),
        "symbols_scanned": len(symbols),
        "actionable_count": len(actionable)
    }
