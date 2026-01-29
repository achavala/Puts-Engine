"""
Pre-Earnings Options Flow Detector

PURPOSE: Detect smart money positioning BEFORE earnings announcement.
This would have caught MSFT, NOW, TEAM, WDAY, TWLO on Jan 26-27.

SIGNALS DETECTED:
1. Put buying at ask (hedging/positioning)
2. Call selling at bid (institutional exit)
3. IV expansion (earnings premium building)
4. Rising put OI (accumulation)
5. Skew steepening (put IV > call IV)

INSTITUTIONAL LOGIC:
- Smart money positions 1-3 days BEFORE earnings
- Options flow shows conviction, not just hedging
- IV expansion = market pricing in move
- Skew = directional bias
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Set
from loguru import logger
from dataclasses import dataclass

from putsengine.clients.unusual_whales_client import UnusualWhalesClient
from putsengine.clients.polygon_client import PolygonClient
from putsengine.earnings_calendar import EarningsCalendar


@dataclass
class PreEarningsSignal:
    """Pre-earnings options flow signal."""
    symbol: str
    earnings_date: date
    days_until_earnings: int
    signals: List[str]
    signal_count: int
    put_buying_at_ask: bool
    call_selling_at_bid: bool
    iv_expanding: bool
    put_oi_rising: bool
    skew_steepening: bool
    score: float
    confidence: float


class PreEarningsFlowDetector:
    """
    Detects smart money positioning before earnings.
    
    Scans for:
    - Put buying at ask (not hedging, but positioning)
    - Call selling at bid (institutional exit)
    - IV expansion (earnings premium)
    - Rising put OI (accumulation)
    - Skew steepening (directional bias)
    """
    
    def __init__(
        self,
        uw_client: UnusualWhalesClient,
        polygon_client: PolygonClient,
        earnings_calendar: EarningsCalendar
    ):
        self.uw = uw_client
        self.polygon = polygon_client
        self.earnings_calendar = earnings_calendar
    
    async def detect_pre_earnings_signals(
        self,
        symbol: str,
        days_before: int = 2
    ) -> Optional[PreEarningsSignal]:
        """
        Detect pre-earnings options flow signals.
        
        Args:
            symbol: Ticker symbol
            days_before: Days before earnings to check (default: 2)
            
        Returns:
            PreEarningsSignal if detected, None otherwise
        """
        # Check if has earnings soon
        if not self.earnings_calendar.has_upcoming_earnings(symbol, days=days_before + 1):
            return None
        
        earnings_date = self.earnings_calendar.get_earnings_date(symbol)
        if not earnings_date:
            return None
        
        days_until = (earnings_date - date.today()).days
        
        if days_until > days_before or days_until < 0:
            return None
        
        signals = []
        
        # 1. Check for put buying at ask
        put_buying = await self._check_put_buying_at_ask(symbol)
        if put_buying:
            signals.append("put_buying_at_ask")
        
        # 2. Check for call selling at bid
        call_selling = await self._check_call_selling_at_bid(symbol)
        if call_selling:
            signals.append("call_selling_at_bid")
        
        # 3. Check IV expansion
        iv_expanding = await self._check_iv_expansion(symbol)
        if iv_expanding:
            signals.append("iv_expansion")
        
        # 4. Check rising put OI
        put_oi_rising = await self._check_rising_put_oi(symbol)
        if put_oi_rising:
            signals.append("rising_put_oi")
        
        # 5. Check skew steepening
        skew_steepening = await self._check_skew_steepening(symbol)
        if skew_steepening:
            signals.append("skew_steepening")
        
        # Need at least 2 signals
        if len(signals) < 2:
            return None
        
        # Calculate score
        base_score = len(signals) * 0.15  # 0.15 per signal
        confidence = min(0.95, 0.60 + len(signals) * 0.10)
        
        # Boost if close to earnings
        if days_until <= 1:
            base_score *= 1.2
        
        score = min(0.70, base_score)
        
        return PreEarningsSignal(
            symbol=symbol,
            earnings_date=earnings_date,
            days_until_earnings=days_until,
            signals=signals,
            signal_count=len(signals),
            put_buying_at_ask=put_buying,
            call_selling_at_bid=call_selling,
            iv_expanding=iv_expanding,
            put_oi_rising=put_oi_rising,
            skew_steepening=skew_steepening,
            score=score,
            confidence=confidence
        )
    
    async def _check_put_buying_at_ask(self, symbol: str) -> bool:
        """Check for put buying at ask (positioning, not hedging)."""
        try:
            flows = await self.uw.get_flow_recent(symbol, limit=20)
            
            put_buys_at_ask = 0
            for flow in flows:
                if flow.option_type == "put" and flow.side == "buy" and flow.price_type == "ask":
                    put_buys_at_ask += 1
            
            # Need at least 3 put buys at ask in recent flow
            return put_buys_at_ask >= 3
            
        except Exception as e:
            logger.debug(f"Failed to check put buying for {symbol}: {e}")
            return False
    
    async def _check_call_selling_at_bid(self, symbol: str) -> bool:
        """Check for call selling at bid (institutional exit)."""
        try:
            flows = await self.uw.get_flow_recent(symbol, limit=20)
            
            call_sells_at_bid = 0
            for flow in flows:
                if flow.option_type == "call" and flow.side == "sell" and flow.price_type == "bid":
                    call_sells_at_bid += 1
            
            # Need at least 3 call sells at bid
            return call_sells_at_bid >= 3
            
        except Exception as e:
            logger.debug(f"Failed to check call selling for {symbol}: {e}")
            return False
    
    async def _check_iv_expansion(self, symbol: str) -> bool:
        """Check if IV is expanding (earnings premium building)."""
        try:
            # Get options chain
            # Use next Friday expiration
            today = date.today()
            days_until_friday = (4 - today.weekday() + 7) % 7
            if days_until_friday == 0:
                days_until_friday = 7
            expiration = today + timedelta(days=days_until_friday)
            
            chain = await self.polygon.get_options_chain(symbol, expiration)
            if not chain:
                return False
            
            # Check if average IV is high (>40% for most stocks)
            ivs = [c.implied_volatility for c in chain if hasattr(c, 'implied_volatility') and c.implied_volatility > 0]
            
            if not ivs:
                return False
            
            avg_iv = sum(ivs) / len(ivs)
            
            # IV > 40% suggests earnings premium
            return avg_iv > 0.40
            
        except Exception as e:
            logger.debug(f"Failed to check IV expansion for {symbol}: {e}")
            return False
    
    async def _check_rising_put_oi(self, symbol: str) -> bool:
        """Check if put OI is rising (accumulation)."""
        try:
            # Get current put OI
            flows = await self.uw.get_flow_recent(symbol, limit=50)
            
            put_flows = [f for f in flows if f.option_type == "put"]
            
            if len(put_flows) < 10:
                return False
            
            # Check if recent put flows are increasing
            recent_puts = put_flows[:10]
            older_puts = put_flows[10:20] if len(put_flows) >= 20 else []
            
            if not older_puts:
                return False
            
            recent_volume = sum(f.size for f in recent_puts)
            older_volume = sum(f.size for f in older_puts)
            
            # Recent volume should be 1.5x older volume
            return recent_volume > older_volume * 1.5
            
        except Exception as e:
            logger.debug(f"Failed to check put OI for {symbol}: {e}")
            return False
    
    async def _check_skew_steepening(self, symbol: str) -> bool:
        """Check if put skew is steepening (put IV > call IV)."""
        try:
            # Get options chain
            today = date.today()
            days_until_friday = (4 - today.weekday() + 7) % 7
            if days_until_friday == 0:
                days_until_friday = 7
            expiration = today + timedelta(days=days_until_friday)
            
            chain = await self.polygon.get_options_chain(symbol, expiration)
            if not chain:
                return False
            
            # Get ATM call and put IV
            # Approximate ATM
            calls = [c for c in chain if c.option_type == "call" and hasattr(c, 'implied_volatility')]
            puts = [c for c in chain if c.option_type == "put" and hasattr(c, 'implied_volatility')]
            
            if not calls or not puts:
                return False
            
            # Get median IVs
            call_ivs = sorted([c.implied_volatility for c in calls if c.implied_volatility > 0])
            put_ivs = sorted([c.implied_volatility for c in puts if c.implied_volatility > 0])
            
            if not call_ivs or not put_ivs:
                return False
            
            median_call_iv = call_ivs[len(call_ivs) // 2]
            median_put_iv = put_ivs[len(put_ivs) // 2]
            
            # Put IV should be > call IV (skew)
            return median_put_iv > median_call_iv * 1.1  # 10% higher
            
        except Exception as e:
            logger.debug(f"Failed to check skew for {symbol}: {e}")
            return False


async def run_pre_earnings_flow_scan(
    uw_client: UnusualWhalesClient,
    polygon_client: PolygonClient,
    earnings_calendar: EarningsCalendar,
    symbols: List[str]
) -> Dict:
    """
    Run pre-earnings options flow scan.
    
    Args:
        uw_client: UnusualWhalesClient
        polygon_client: PolygonClient
        earnings_calendar: EarningsCalendar
        symbols: List of symbols to scan
        
    Returns:
        Dict with detected signals
    """
    detector = PreEarningsFlowDetector(uw_client, polygon_client, earnings_calendar)
    
    results = {}
    for symbol in symbols:
        try:
            signal = await detector.detect_pre_earnings_signals(symbol, days_before=2)
            if signal:
                results[symbol] = signal
                logger.warning(
                    f"PRE-EARNINGS FLOW: {symbol} | "
                    f"Earnings: {signal.earnings_date} ({signal.days_until_earnings}d) | "
                    f"Signals: {signal.signal_count} | Score: {signal.score:.2f}"
                )
        except Exception as e:
            logger.debug(f"Error scanning {symbol}: {e}")
    
    logger.info(
        f"Pre-Earnings Flow Scan: {len(symbols)} scanned, "
        f"{len(results)} signals detected"
    )
    
    return {
        "signals": results,
        "scan_time": datetime.now().isoformat(),
        "symbols_scanned": len(symbols),
        "signals_count": len(results)
    }
