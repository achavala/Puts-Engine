"""
Unusual Whales API Budget Manager

Feb 10, 2026 (v2): SMART BUDGET RESERVATION for critical PM scan.
- NO per-ticker cooldowns (previously 60-300 seconds)
- NO per-ticker daily max (previously 10-50 per ticker)
- NO priority-tier budget splitting (previously P1=60%, P2=30%, P3=10%)
- NO skip_uw_use_alpaca_only throttling

DAILY LIMIT: UW server's 15,000 hard limit (resets 8 PM EST).

AFTERNOON RESERVATION: 4,000 calls reserved for 2 PM-4 PM window.
Before 2 PM ET:  scans may use up to 11,000 calls (15,000 - 4,000 reserve).
After 2 PM ET:   full remaining budget is released to the 3 PM market_pulse scan.

This ensures the critical 3 PM full scan (which captures power-hour
institutional positioning) ALWAYS has enough budget for ~361 tickers x ~6 endpoints.

Without this reservation, hourly EWS scans (~1,800 calls each) exhaust
the entire 15,000 budget by ~1 PM, leaving ZERO for the PM scan.

The 30-minute response cache in unusual_whales_client.py still prevents duplicate
calls (same endpoint+ticker within 30 min = cache hit, 0 API calls).

Rate limit protection: 0.6s between HTTP requests (100 req/min to stay under 120 limit).
"""

import asyncio
from datetime import datetime, date, time, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
import pytz

from loguru import logger

# ======================================================================
# AFTERNOON BUDGET RESERVATION
# ======================================================================
# Reserve this many calls for the 2 PM - 4 PM window so the critical
# 2:45 PM Market Pulse scan (361 tickers x ~6 UW endpoints = ~2,200 calls)
# always has budget.  4,000 provides ~80% headroom.
#
# FEB 10 SCHEDULE OPTIMIZATION:
#   - 12 PM EWS REMOVED (saves 1,800)
#   - daily_report_3pm REMOVED (saves 2,200 — was duplicate of market_pulse)
#   - early_warning_3pm REMOVED (saves 1,800)
#   - market_pulse moved 3:00 PM → 2:45 PM (finishes by ~3:06 PM)
#   - Meta Engine reads at 3:15 PM → ONE combined pipeline
#
# Budget projection:
#   8 AM EWS: 1,800 | 9 AM Full: 4,000 | 9:45 AM EWS: 1,800
#   11 AM EWS: 1,800 | 1 PM EWS: 1,600 (ceiling) = 11,000
#   --- 2 PM: release to 15,000 ---
#   2 PM EWS: 1,800 | 2:45 PM Market Pulse: 2,200 = 15,000
#   3:15 PM Meta Engine: reads files (0 UW calls)
AFTERNOON_RESERVE = 4000
# The cutoff time: before this, the reserve is enforced.
# After this, the full remaining budget is released.
AFTERNOON_CUTOFF = time(14, 0)  # 2:00 PM ET
# ======================================================================


class TimeWindow(Enum):
    """Trading day time windows."""
    PRE_MARKET = "pre_market"          # 4:00 AM - 9:30 AM
    OPENING_RANGE = "opening_range"    # 9:30 AM - 10:30 AM
    MID_MORNING = "mid_morning"        # 10:30 AM - 12:00 PM
    MIDDAY = "midday"                  # 12:00 PM - 2:00 PM
    AFTERNOON = "afternoon"            # 2:00 PM - 3:30 PM
    CLOSE = "close"                    # 3:30 PM - 4:00 PM
    AFTER_HOURS = "after_hours"        # 4:00 PM - 4:00 AM


class TickerPriority(Enum):
    """Ticker priority levels (kept for compatibility, NO budget enforcement)."""
    PRIORITY_1 = 1  # Index ETFs, Active signals (0.35+), DUI promoted
    PRIORITY_2 = 2  # High-beta groups, Watching (0.25-0.34)
    PRIORITY_3 = 3  # Everything else


@dataclass
class APIBudget:
    """Budget allocation for a time window (kept for compatibility)."""
    window: TimeWindow
    total_calls: int
    priority_1_pct: float = 0.60
    priority_2_pct: float = 0.30
    priority_3_pct: float = 0.10
    
    @property
    def priority_1_budget(self) -> int:
        return int(self.total_calls * self.priority_1_pct)
    
    @property
    def priority_2_budget(self) -> int:
        return int(self.total_calls * self.priority_2_pct)
    
    @property
    def priority_3_budget(self) -> int:
        return int(self.total_calls * self.priority_3_pct)


# Window budgets set to 15,000 each (kept for API compatibility).
WINDOW_BUDGETS: Dict[TimeWindow, APIBudget] = {
    TimeWindow.PRE_MARKET: APIBudget(TimeWindow.PRE_MARKET, 15000),
    TimeWindow.OPENING_RANGE: APIBudget(TimeWindow.OPENING_RANGE, 15000),
    TimeWindow.MID_MORNING: APIBudget(TimeWindow.MID_MORNING, 15000),
    TimeWindow.MIDDAY: APIBudget(TimeWindow.MIDDAY, 15000),
    TimeWindow.AFTERNOON: APIBudget(TimeWindow.AFTERNOON, 15000),
    TimeWindow.CLOSE: APIBudget(TimeWindow.CLOSE, 15000),
    TimeWindow.AFTER_HOURS: APIBudget(TimeWindow.AFTER_HOURS, 15000),
}


@dataclass
class APIBudgetManager:
    """
    Manages Unusual Whales API call budget across trading day.
    
    Feb 10, 2026 (v2): SMART AFTERNOON RESERVATION.
    
    Before 2 PM ET: effective ceiling = daily_limit - AFTERNOON_RESERVE (11,000)
    After  2 PM ET: effective ceiling = daily_limit (15,000)
    
    This guarantees ~4,000 calls for the critical 3 PM market_pulse scan.
    No other restrictions (cooldowns, per-ticker max, priority tiers).
    
    Usage:
        manager = APIBudgetManager()
        if manager.can_call_uw(symbol, priority):
            manager.record_call(symbol)
    """
    
    daily_limit: int = 15000  # UW server hard limit
    _calls_today: int = 0
    _calls_reset_date: date = field(default_factory=date.today)
    _window_calls: Dict[TimeWindow, int] = field(default_factory=dict)
    _ticker_last_call: Dict[str, datetime] = field(default_factory=dict)
    _ticker_call_count: Dict[str, int] = field(default_factory=dict)
    _priority_cache: Dict[str, TickerPriority] = field(default_factory=dict)
    
    # Per-ticker cooldowns: REMOVED
    TICKER_COOLDOWN = {
        TickerPriority.PRIORITY_1: 0,
        TickerPriority.PRIORITY_2: 0,
        TickerPriority.PRIORITY_3: 0,
    }
    
    SCAN_WINDOW_SECONDS = 30  # Kept for compatibility
    
    # Per-ticker daily max: effectively unlimited
    MAX_CALLS_PER_TICKER = {
        TickerPriority.PRIORITY_1: 999,
        TickerPriority.PRIORITY_2: 999,
        TickerPriority.PRIORITY_3: 999,
    }
    
    def __post_init__(self):
        """Initialize window call counters."""
        for window in TimeWindow:
            self._window_calls[window] = 0
    
    @property
    def remaining_daily(self) -> int:
        """Remaining API calls for today."""
        self._check_reset()
        return max(0, self.daily_limit - self._calls_today)
    
    def _check_reset(self):
        """Reset counters if new day."""
        today = date.today()
        if today != self._calls_reset_date:
            logger.info(f"API Budget: New day, resetting counters. Yesterday used: {self._calls_today}")
            self._calls_today = 0
            self._calls_reset_date = today
            self._window_calls = {w: 0 for w in TimeWindow}
            self._ticker_call_count = {}
    
    def _is_afternoon(self) -> bool:
        """Check if current ET time is at or past the afternoon cutoff (2 PM)."""
        et = pytz.timezone('US/Eastern')
        now_et = datetime.now(et).time()
        return now_et >= AFTERNOON_CUTOFF
    
    def _effective_ceiling(self) -> int:
        """
        Effective call ceiling based on time of day.
        
        Before 2 PM ET:  daily_limit - AFTERNOON_RESERVE  (e.g. 11,000)
        After 2 PM ET:   daily_limit                       (e.g. 15,000)
        """
        if self._is_afternoon():
            return self.daily_limit
        return self.daily_limit - AFTERNOON_RESERVE
    
    def get_current_window(self) -> TimeWindow:
        """Get current time window."""
        et = pytz.timezone('US/Eastern')
        now = datetime.now(et).time()
        
        if now < time(9, 30):
            return TimeWindow.PRE_MARKET
        elif now < time(10, 30):
            return TimeWindow.OPENING_RANGE
        elif now < time(12, 0):
            return TimeWindow.MID_MORNING
        elif now < time(14, 0):
            return TimeWindow.MIDDAY
        elif now < time(15, 30):
            return TimeWindow.AFTERNOON
        elif now < time(16, 0):
            return TimeWindow.CLOSE
        else:
            return TimeWindow.AFTER_HOURS
    
    def get_ticker_priority(self, symbol: str, score: float = 0, 
                           is_dui: bool = False, is_index: bool = False) -> TickerPriority:
        """
        Determine ticker priority for API allocation.
        Kept for compatibility -- priorities no longer restrict API calls.
        """
        if symbol in self._priority_cache:
            return self._priority_cache[symbol]
        
        if is_index or symbol in {'SPY', 'QQQ', 'IWM', 'DIA'}:
            priority = TickerPriority.PRIORITY_1
        elif score >= 0.35:
            priority = TickerPriority.PRIORITY_1
        elif is_dui:
            priority = TickerPriority.PRIORITY_1
        elif score >= 0.25:
            priority = TickerPriority.PRIORITY_2
        else:
            priority = TickerPriority.PRIORITY_3
        
        self._priority_cache[symbol] = priority
        return priority
    
    def update_ticker_priority(self, symbol: str, score: float, is_dui: bool = False):
        """Update ticker priority based on new score."""
        if symbol in self._priority_cache:
            del self._priority_cache[symbol]
        return self.get_ticker_priority(symbol, score, is_dui)
    
    def can_call_uw(self, symbol: str, priority: TickerPriority = None, 
                   score: float = 0, is_dui: bool = False,
                   force_scan: bool = False) -> bool:
        """
        Check if we can make a UW API call for this ticker.
        
        SMART AFTERNOON RESERVATION:
        
        Before 2 PM ET:
          - Returns True if calls_today < daily_limit - AFTERNOON_RESERVE (11,000)
          - This preserves 4,000 calls for the 3 PM market_pulse scan
          - force_scan=True bypasses the reservation (for the 3 PM scan itself)
        
        After 2 PM ET:
          - Returns True if calls_today < daily_limit (15,000)
          - Full remaining budget available for the PM scan
        
        Returns False ONLY if the effective ceiling is reached.
        """
        self._check_reset()
        
        # Hard daily limit (UW server enforced)
        if self._calls_today >= self.daily_limit:
            return False
        
        # Smart reservation: before 2 PM, enforce the ceiling
        # force_scan bypasses the reservation (used by 3 PM market_pulse scan)
        ceiling = self._effective_ceiling()
        if not force_scan and self._calls_today >= ceiling:
            if not self._is_afternoon():
                # Only log periodically to avoid log spam
                if self._calls_today % 100 == 0 or self._calls_today == ceiling:
                    logger.info(
                        f"API Budget: Pre-2PM ceiling reached ({self._calls_today}/{ceiling}). "
                        f"Reserving {AFTERNOON_RESERVE} calls for 3 PM market_pulse scan. "
                        f"force_scan=True bypasses this."
                    )
                return False
        
        return True
    
    def record_call(self, symbol: str, calls: int = 1):
        """Record API call(s) for budget tracking."""
        self._check_reset()
        
        # Update counters
        self._calls_today += calls
        window = self.get_current_window()
        self._window_calls[window] = self._window_calls.get(window, 0) + calls
        self._ticker_call_count[symbol] = self._ticker_call_count.get(symbol, 0) + calls
        self._ticker_last_call[symbol] = datetime.now()
        
        # Log budget status periodically
        if self._calls_today % 500 == 0:
            self._log_status()
    
    def _log_status(self):
        """Log current budget status."""
        window = self.get_current_window()
        window_used = self._window_calls.get(window, 0)
        ceiling = self._effective_ceiling()
        is_pm = self._is_afternoon()
        
        logger.info(
            f"API Budget Status: "
            f"Daily: {self._calls_today}/{self.daily_limit} ({100*self._calls_today/self.daily_limit:.1f}%) | "
            f"Ceiling: {ceiling} ({'PM released' if is_pm else f'reserve {AFTERNOON_RESERVE}'}) | "
            f"Window ({window.value}): {window_used} | "
            f"Tickers: {len(self._ticker_call_count)}"
        )
    
    def get_scannable_tickers(self, all_tickers: List[str], 
                             scores: Dict[str, float] = None,
                             dui_tickers: Set[str] = None) -> List[str]:
        """
        Get list of tickers that can be scanned with UW API right now.
        Returns ALL tickers unless ceiling is hit.
        """
        scores = scores or {}
        dui_tickers = dui_tickers or set()
        
        ceiling = self._effective_ceiling()
        if self._calls_today >= ceiling:
            return []
        
        # Return all tickers sorted by score (highest first)
        scored = [(s, scores.get(s, 0)) for s in all_tickers]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [t[0] for t in scored]
    
    def get_status(self) -> Dict:
        """Get current budget status as dict."""
        self._check_reset()
        window = self.get_current_window()
        ceiling = self._effective_ceiling()
        
        return {
            "daily_used": self._calls_today,
            "daily_limit": self.daily_limit,
            "daily_remaining": self.remaining_daily,
            "daily_pct": 100 * self._calls_today / self.daily_limit,
            "current_window": window.value,
            "window_used": self._window_calls.get(window, 0),
            "window_budget": ceiling,
            "afternoon_reserve": AFTERNOON_RESERVE,
            "is_afternoon": self._is_afternoon(),
            "effective_ceiling": ceiling,
            "unique_tickers_called": len(self._ticker_call_count),
        }
    
    def skip_uw_use_alpaca_only(self, symbol: str, score: float = 0,
                               force_scan: bool = False) -> bool:
        """
        NEVER skip UW. All tickers use full UW data.
        """
        return False


# Singleton instance
_budget_manager: Optional[APIBudgetManager] = None


def get_budget_manager() -> APIBudgetManager:
    """Get singleton API budget manager."""
    global _budget_manager
    if _budget_manager is None:
        _budget_manager = APIBudgetManager()
    return _budget_manager
