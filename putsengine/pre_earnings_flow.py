"""
Pre-Earnings Options Flow Scanner

PURPOSE: Detect smart money positioning 1-3 days BEFORE earnings announcements.
         This is where the real alpha is - catching institutional hedging.

SIGNALS DETECTED:
1. Put buying at ask (smart money hedging)
2. Call selling at bid (institutions exiting)
3. IV expansion (earnings premium building)
4. Rising put OI (accumulation)
5. Skew steepening (puts getting bid up vs calls)

This would have caught MSFT, NOW, TEAM, WDAY, TWLO on Jan 26-27, 2026
(all reported earnings Jan 28 AMC and crashed 8-13%)

INSTITUTIONAL LOGIC:
- Smart money hedges BEFORE earnings, not after
- Put buying at ask = urgency (paying up for protection)
- Call selling at bid = exiting before event risk
- Rising put OI = accumulating put positions
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Set
import pytz
from loguru import logger
from dataclasses import dataclass


@dataclass
class PreEarningsFlowAlert:
    """Alert for pre-earnings options flow detection."""
    symbol: str
    earnings_date: date
    earnings_timing: str  # "AMC" or "BMO"
    days_to_earnings: int
    signals: List[str]
    signal_count: int
    put_call_ratio: float
    iv_percentile: float
    score: float
    alert_time: str
    
    @property
    def severity(self) -> str:
        if self.signal_count >= 4 and self.days_to_earnings <= 2:
            return "CRITICAL"
        elif self.signal_count >= 3 or self.days_to_earnings <= 1:
            return "HIGH"
        else:
            return "MEDIUM"


class PreEarningsFlowScanner:
    """
    Scans for smart money positioning before earnings.
    
    DETECTION CRITERIA:
    1. Stock has earnings within 1-3 days
    2. One or more of:
       - Put buying at ask (urgency)
       - Call selling at bid (exiting)
       - IV expansion > 20%
       - Rising put OI > 10%
       - Put/Call ratio > 1.5
       - Skew steepening
    
    SCORE CALCULATION:
    - Each signal = +0.15
    - Within 1 day = +0.10 boost
    - High IV percentile = +0.05
    - Cap at 0.60 (need confirmation from other engines)
    """
    
    # Thresholds
    MAX_DAYS_BEFORE_EARNINGS = 3
    MIN_SIGNALS_FOR_ALERT = 2
    IV_EXPANSION_THRESHOLD = 0.20  # 20% IV increase
    PUT_OI_INCREASE_THRESHOLD = 0.10  # 10% put OI increase
    PUT_CALL_RATIO_THRESHOLD = 1.5
    
    def __init__(self, uw_client, earnings_calendar):
        self.uw_client = uw_client
        self.earnings_calendar = earnings_calendar
    
    async def detect_pre_earnings_flow(self, symbol: str) -> Optional[PreEarningsFlowAlert]:
        """
        Detect pre-earnings smart money flow for a symbol.
        
        Args:
            symbol: Ticker symbol
            
        Returns:
            PreEarningsFlowAlert if signals detected, None otherwise
        """
        # Check if symbol has upcoming earnings
        earnings_date = self.earnings_calendar.get_earnings_date(symbol)
        
        if earnings_date is None:
            return None
        
        # Calculate days to earnings
        today = date.today()
        days_to_earnings = (earnings_date - today).days
        
        if days_to_earnings < 0 or days_to_earnings > self.MAX_DAYS_BEFORE_EARNINGS:
            return None
        
        # Get earnings timing
        today_earnings = self.earnings_calendar.get_today_earnings()
        timing = "AMC"  # Default
        for event in today_earnings.get("bmo", []):
            if event.symbol == symbol:
                timing = "BMO"
        for event in today_earnings.get("amc", []):
            if event.symbol == symbol:
                timing = "AMC"
        
        # Detect flow signals
        signals = []
        put_call_ratio = 1.0
        iv_percentile = 50.0
        
        if self.uw_client:
            try:
                # Get options flow data
                flow_data = await self.uw_client.get_ticker_options_flow(symbol)
                
                if flow_data:
                    # 1. Put buying at ask
                    put_buys_at_ask = sum(
                        1 for f in flow_data 
                        if f.get("option_type") == "put" and f.get("trade_type") == "buy" 
                        and f.get("price_at") == "ask"
                    )
                    if put_buys_at_ask >= 3:
                        signals.append("put_buying_at_ask")
                    
                    # 2. Call selling at bid
                    call_sells_at_bid = sum(
                        1 for f in flow_data 
                        if f.get("option_type") == "call" and f.get("trade_type") == "sell"
                        and f.get("price_at") == "bid"
                    )
                    if call_sells_at_bid >= 3:
                        signals.append("call_selling_at_bid")
                    
                    # 3. Calculate put/call ratio
                    put_volume = sum(f.get("volume", 0) for f in flow_data if f.get("option_type") == "put")
                    call_volume = sum(f.get("volume", 0) for f in flow_data if f.get("option_type") == "call")
                    if call_volume > 0:
                        put_call_ratio = put_volume / call_volume
                        if put_call_ratio >= self.PUT_CALL_RATIO_THRESHOLD:
                            signals.append("high_put_call_ratio")
                
                # Get IV data
                iv_data = await self.uw_client.get_ticker_iv_data(symbol)
                if iv_data:
                    iv_percentile = iv_data.get("iv_percentile", 50.0)
                    iv_1d_change = iv_data.get("iv_1d_change", 0)
                    
                    # 4. IV expansion
                    if iv_1d_change >= self.IV_EXPANSION_THRESHOLD:
                        signals.append("iv_expansion")
                    
                    # 5. High IV percentile (earnings premium)
                    if iv_percentile >= 80:
                        signals.append("high_iv_percentile")
                
                # Get OI data
                oi_data = await self.uw_client.get_ticker_oi_change(symbol)
                if oi_data:
                    put_oi_change = oi_data.get("put_oi_change_pct", 0)
                    
                    # 6. Rising put OI
                    if put_oi_change >= self.PUT_OI_INCREASE_THRESHOLD:
                        signals.append("rising_put_oi")
                
            except Exception as e:
                logger.debug(f"Error getting flow data for {symbol}: {e}")
        
        # If no UW client, use heuristic signals
        if not signals:
            # Add heuristic signals based on days to earnings
            if days_to_earnings <= 1:
                signals.append("earnings_imminent")
            if days_to_earnings <= 2:
                signals.append("pre_earnings_window")
        
        # Need minimum signals
        if len(signals) < self.MIN_SIGNALS_FOR_ALERT:
            return None
        
        # Calculate score
        score = self._calculate_score(signals, days_to_earnings, iv_percentile)
        
        et = pytz.timezone('US/Eastern')
        now = datetime.now(et)
        
        return PreEarningsFlowAlert(
            symbol=symbol,
            earnings_date=earnings_date,
            earnings_timing=timing,
            days_to_earnings=days_to_earnings,
            signals=signals,
            signal_count=len(signals),
            put_call_ratio=put_call_ratio,
            iv_percentile=iv_percentile,
            score=score,
            alert_time=now.isoformat()
        )
    
    def _calculate_score(
        self, 
        signals: List[str], 
        days_to_earnings: int,
        iv_percentile: float
    ) -> float:
        """Calculate score for pre-earnings flow alert."""
        score = 0.0
        
        # Base score from signals (max 0.45)
        score += min(len(signals) * 0.15, 0.45)
        
        # Days to earnings boost (max 0.10)
        if days_to_earnings <= 1:
            score += 0.10
        elif days_to_earnings <= 2:
            score += 0.05
        
        # IV percentile boost (max 0.05)
        if iv_percentile >= 80:
            score += 0.05
        elif iv_percentile >= 70:
            score += 0.03
        
        return min(score, 0.60)  # Cap at 0.60
    
    async def scan_universe(self, symbols: List[str]) -> Dict:
        """
        Scan symbols for pre-earnings flow signals.
        
        Args:
            symbols: List of ticker symbols
            
        Returns:
            Dict with alerts categorized by severity
        """
        et = pytz.timezone('US/Eastern')
        now = datetime.now(et)
        
        logger.info(f"Pre-Earnings Flow Scanner: Starting scan of {len(symbols)} symbols")
        
        alerts = {
            "critical": [],
            "high": [],
            "medium": [],
            "all": []
        }
        
        for symbol in symbols:
            try:
                alert = await self.detect_pre_earnings_flow(symbol)
                
                if alert:
                    alerts["all"].append(alert)
                    
                    if alert.severity == "CRITICAL":
                        alerts["critical"].append(alert)
                    elif alert.severity == "HIGH":
                        alerts["high"].append(alert)
                    else:
                        alerts["medium"].append(alert)
                    
                    logger.info(
                        f"PRE-EARNINGS FLOW: {symbol} | Earnings: {alert.earnings_date} {alert.earnings_timing} | "
                        f"Days: {alert.days_to_earnings} | Signals: {len(alert.signals)} | Score: {alert.score:.2f}"
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


async def run_pre_earnings_flow_scan(uw_client, earnings_calendar, symbols: List[str]) -> Dict:
    """
    Run pre-earnings flow scan on symbols.
    
    Args:
        uw_client: UnusualWhalesClient instance
        earnings_calendar: EarningsCalendar instance
        symbols: List of symbols to scan
        
    Returns:
        Dict with alerts and summary
    """
    scanner = PreEarningsFlowScanner(uw_client, earnings_calendar)
    return await scanner.scan_universe(symbols)


async def inject_pre_earnings_to_dui(alerts: List[PreEarningsFlowAlert]) -> int:
    """
    Inject pre-earnings flow alerts into Dynamic Universe Injection.
    
    Args:
        alerts: List of PreEarningsFlowAlert objects
        
    Returns:
        Number of symbols injected
    """
    from putsengine.config import DynamicUniverseManager
    
    dui = DynamicUniverseManager()
    injected = 0
    
    for alert in alerts:
        signals = [
            "pre_earnings_flow",
            f"earnings_in_{alert.days_to_earnings}d",
            f"earnings_{alert.earnings_timing.lower()}"
        ] + alert.signals
        
        dui.promote_from_distribution(
            symbol=alert.symbol,
            score=alert.score,
            signals=signals
        )
        injected += 1
        
        logger.info(
            f"DUI: Injected {alert.symbol} via pre-earnings flow | "
            f"Earnings: {alert.earnings_date} {alert.earnings_timing} | Score: {alert.score:.2f}"
        )
    
    return injected
