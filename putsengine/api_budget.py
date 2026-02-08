"""
Unusual Whales API Budget Manager

STRATEGY: Distribute 7,500 daily API calls wisely across trading day.

PROBLEM: 
- 200+ tickers × 3-5 API calls/ticker × 19 scans/day = high call volume
- Rate limit of 120 req/min can cause throttling

SOLUTION:
- BATCHED SCANNING: Split tickers into 3 batches of ~100, wait 65s between batches
- Time-window budgets (not all scans are equal)
- Caching (don't re-fetch unchanged data)
- Rate limit protection (100 req/min to stay under 120 limit)

DAILY BUDGET ALLOCATION (7,500 calls):
├── Pre-Market (4:00-9:00 AM):     800 calls  (10.7%)  - 4 scans × 200 tickers
├── Market Open (9:30 AM):         400 calls  (5.3%)   - Full scan all
├── Regular Hours (10:00-3:30 PM): 4,400 calls (58.7%) - 11 scans × 200 tickers
├── Market Close (4:00 PM):        400 calls  (5.3%)   - Full scan all
├── End of Day (5:00 PM):          400 calls  (5.3%)   - Final summary
└── Buffer/Retries:               1,100 calls (14.7%)  - For retries and manual

RATE LIMIT STRATEGY:
- Split 300 tickers into 3 batches of 100
- Process each batch at max 100 req/min (safe under 120 limit)
- Wait 65 seconds between batches (rate limit reset)
- Result: ALL tickers scanned, ZERO misses
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


class TimeWindow(Enum):
    """Trading day time windows with different API budgets."""
    PRE_MARKET = "pre_market"          # 4:00 AM - 9:30 AM
    OPENING_RANGE = "opening_range"    # 9:30 AM - 10:30 AM (CRITICAL)
    MID_MORNING = "mid_morning"        # 10:30 AM - 12:00 PM
    MIDDAY = "midday"                  # 12:00 PM - 2:00 PM (LOW PRIORITY)
    AFTERNOON = "afternoon"            # 2:00 PM - 3:30 PM (CRITICAL)
    CLOSE = "close"                    # 3:30 PM - 4:00 PM
    AFTER_HOURS = "after_hours"        # 4:00 PM - 4:00 AM


class TickerPriority(Enum):
    """Ticker priority levels for API allocation."""
    PRIORITY_1 = 1  # Index ETFs, Active signals (0.35+), DUI promoted
    PRIORITY_2 = 2  # High-beta groups, Watching (0.25-0.34)
    PRIORITY_3 = 3  # Everything else


@dataclass
class APIBudget:
    """Budget allocation for a time window."""
    window: TimeWindow
    total_calls: int
    priority_1_pct: float = 0.60  # 60% for P1
    priority_2_pct: float = 0.30  # 30% for P2
    priority_3_pct: float = 0.10  # 10% for P3
    
    @property
    def priority_1_budget(self) -> int:
        return int(self.total_calls * self.priority_1_pct)
    
    @property
    def priority_2_budget(self) -> int:
        return int(self.total_calls * self.priority_2_pct)
    
    @property
    def priority_3_budget(self) -> int:
        return int(self.total_calls * self.priority_3_pct)


# Budget allocation per time window (UPDATED FEB 7, 2026)
# 
# CRITICAL FIX: Previous budgets were causing 0 UW calls during market hours.
# On Feb 6, only 700/7,500 (9.3%) daily budget was used because:
#   1. can_call_uw() TypeError bug blocked all budget-tracked calls
#   2. P3 tier limits (10% of window) throttled most tickers
#   3. P3 skip during MIDDAY/AFTER_HOURS blocked scans entirely
#
# New allocation: More generous windows + force_scan support for EWS.
# EWS scans use force_scan=True which bypasses tier limits (uses total).
#
# Feb 7, 2026: Daily budget = 5,000. Window budgets distribute across 9 EWS scans.
# Note: Window budgets sum > daily limit intentionally — daily cap is the hard stop.
# EWS uses force_scan=True (bypasses tier limits, respects window cap).
# Each EWS scan: ~361 tickers × ~1-3 UW calls = ~400-1000 calls.
#
WINDOW_BUDGETS: Dict[TimeWindow, APIBudget] = {
    TimeWindow.PRE_MARKET: APIBudget(TimeWindow.PRE_MARKET, 1000),      # 8 AM EWS + 9 AM Weather AM
    TimeWindow.OPENING_RANGE: APIBudget(TimeWindow.OPENING_RANGE, 800), # 9:45 AM EWS + Market Direction
    TimeWindow.MID_MORNING: APIBudget(TimeWindow.MID_MORNING, 1000),    # 11 AM EWS + 12 PM EWS + Direction
    TimeWindow.MIDDAY: APIBudget(TimeWindow.MIDDAY, 1000),              # 1 PM EWS + 2 PM EWS + Direction
    TimeWindow.AFTERNOON: APIBudget(TimeWindow.AFTERNOON, 1000),        # 2:30 PM EWS + 3 PM Weather PM
    TimeWindow.CLOSE: APIBudget(TimeWindow.CLOSE, 500),                 # 3:30-4:00 PM close
    TimeWindow.AFTER_HOURS: APIBudget(TimeWindow.AFTER_HOURS, 800),     # 4:30 PM EWS + 10 PM EWS
}


@dataclass
class APIBudgetManager:
    """
    Manages Unusual Whales API call budget across trading day.
    
    Usage:
        manager = APIBudgetManager()
        
        # Before making UW calls for a ticker
        if manager.can_call_uw(symbol, priority):
            # Make the API call
            manager.record_call(symbol)
    """
    
    daily_limit: int = 7500  # Feb 7, 2026: Set to 7500 per user request
    _calls_today: int = 0
    _calls_reset_date: date = field(default_factory=date.today)
    _window_calls: Dict[TimeWindow, int] = field(default_factory=dict)
    _ticker_last_call: Dict[str, datetime] = field(default_factory=dict)
    _ticker_call_count: Dict[str, int] = field(default_factory=dict)
    _priority_cache: Dict[str, TickerPriority] = field(default_factory=dict)
    
    # Minimum time between UW calls for same ticker (seconds)
    # CRITICAL FIX: Reduced from 300/900/1800 to allow more frequent scanning
    # Previous settings blocked ALL data collection (system was blind!)
    TICKER_COOLDOWN = {
        TickerPriority.PRIORITY_1: 60,    # 1 minute (was 5 min)
        TickerPriority.PRIORITY_2: 180,   # 3 minutes (was 15 min)
        TickerPriority.PRIORITY_3: 300,   # 5 minutes (was 30 min!)
    }
    
    # Allow multiple calls within a "scan window" for same ticker
    # This fixes the bug where 2nd API call for same ticker was blocked
    SCAN_WINDOW_SECONDS = 30  # Allow all calls within 30 seconds
    
    # Max UW calls per ticker per day
    # INCREASED to support multiple scans - system was getting 0 data before!
    MAX_CALLS_PER_TICKER = {
        TickerPriority.PRIORITY_1: 50,   # Index ETFs, active signals (was 20)
        TickerPriority.PRIORITY_2: 25,   # High-beta, watching (was 8)
        TickerPriority.PRIORITY_3: 10,   # Low priority (was 3!)
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
        
        Priority 1: Index ETFs, Active signals (0.35+), DUI promoted
        Priority 2: High-beta groups, Watching (0.25-0.34)
        Priority 3: Everything else
        """
        # Check cache first
        if symbol in self._priority_cache:
            return self._priority_cache[symbol]
        
        # Index ETFs are always P1
        if is_index or symbol in {'SPY', 'QQQ', 'IWM', 'DIA'}:
            priority = TickerPriority.PRIORITY_1
        # Active signals (CLASS B and above)
        elif score >= 0.35:
            priority = TickerPriority.PRIORITY_1
        # DUI promoted
        elif is_dui:
            priority = TickerPriority.PRIORITY_1
        # Watching
        elif score >= 0.25:
            priority = TickerPriority.PRIORITY_2
        # Everything else
        else:
            priority = TickerPriority.PRIORITY_3
        
        self._priority_cache[symbol] = priority
        return priority
    
    def update_ticker_priority(self, symbol: str, score: float, is_dui: bool = False):
        """Update ticker priority based on new score."""
        # Clear cache to force re-evaluation
        if symbol in self._priority_cache:
            del self._priority_cache[symbol]
        return self.get_ticker_priority(symbol, score, is_dui)
    
    def can_call_uw(self, symbol: str, priority: TickerPriority = None, 
                   score: float = 0, is_dui: bool = False,
                   force_scan: bool = False) -> bool:
        """
        Check if we can make a UW API call for this ticker.
        
        Args:
            symbol: Ticker symbol
            priority: Ticker priority (P1/P2/P3)
            score: Ticker score for priority determination
            is_dui: Whether ticker was DUI-promoted
            force_scan: If True, bypass priority-tier window limits and cooldowns.
                       Only respects daily limit and TOTAL window budget.
                       Used for EWS discovery scans that must scan ALL tickers.
        
        Returns False if:
        - Daily budget exhausted
        - Window budget exhausted for this priority (skipped if force_scan)
        - Ticker on cooldown (skipped if force_scan)
        - Ticker hit daily max calls (relaxed if force_scan)
        """
        self._check_reset()
        
        # Get priority if not provided
        if priority is None:
            priority = self.get_ticker_priority(symbol, score, is_dui)
        
        # Check daily budget (ALWAYS enforced, even with force_scan)
        if self._calls_today >= self.daily_limit:
            logger.warning(f"API Budget: Daily limit reached ({self.daily_limit})")
            return False
        
        # Check window budget
        window = self.get_current_window()
        budget = WINDOW_BUDGETS[window]
        window_used = self._window_calls.get(window, 0)
        
        if force_scan:
            # FORCE SCAN MODE: Only check TOTAL window budget, not per-tier limits
            # This ensures EWS can scan all 361 tickers regardless of priority
            if window_used >= budget.total_calls:
                logger.debug(f"API Budget: Window {window.value} total budget exhausted ({window_used}/{budget.total_calls})")
                return False
        else:
            # NORMAL MODE: Check per-tier budget limits
            if priority == TickerPriority.PRIORITY_1:
                if window_used >= budget.priority_1_budget:
                    logger.debug(f"API Budget: Window {window.value} P1 budget exhausted")
                    return False
            elif priority == TickerPriority.PRIORITY_2:
                p1_used = min(window_used, budget.priority_1_budget)
                p2_used = window_used - p1_used
                if p2_used >= budget.priority_2_budget:
                    logger.debug(f"API Budget: Window {window.value} P2 budget exhausted")
                    return False
            else:  # P3
                if budget.priority_3_budget == 0:
                    return False  # P3 disabled for this window
                p1_p2_budget = budget.priority_1_budget + budget.priority_2_budget
                p3_used = max(0, window_used - p1_p2_budget)
                if p3_used >= budget.priority_3_budget:
                    return False
        
        # Check ticker cooldown (skipped in force_scan mode)
        if not force_scan:
            # CRITICAL FIX: Allow calls within SCAN_WINDOW to support multi-call analysis
            last_call = self._ticker_last_call.get(symbol)
            if last_call:
                elapsed = (datetime.now() - last_call).total_seconds()
                
                # Allow calls within scan window (supports multiple API calls per analysis)
                if elapsed < self.SCAN_WINDOW_SECONDS:
                    # Within scan window - allow the call (same scan session)
                    pass
                else:
                    # After scan window - check cooldown between scan sessions
                    cooldown = self.TICKER_COOLDOWN.get(priority, 300)
                    if elapsed < cooldown:
                        logger.debug(f"API Budget: {symbol} on cooldown ({int(cooldown - elapsed)}s remaining)")
                        return False
        
        # Check ticker daily max (relaxed in force_scan mode)
        ticker_calls = self._ticker_call_count.get(symbol, 0)
        if force_scan:
            # Force scan: higher daily max per ticker (50 for all tiers)
            if ticker_calls >= 50:
                logger.debug(f"API Budget: {symbol} hit force-scan daily max (50 calls)")
                return False
        else:
            max_calls = self.MAX_CALLS_PER_TICKER.get(priority, 3)
            if ticker_calls >= max_calls:
                logger.debug(f"API Budget: {symbol} hit daily max ({max_calls} calls)")
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
        if self._calls_today % 100 == 0:
            self._log_status()
    
    def _log_status(self):
        """Log current budget status."""
        window = self.get_current_window()
        budget = WINDOW_BUDGETS[window]
        window_used = self._window_calls.get(window, 0)
        
        logger.info(
            f"API Budget Status: "
            f"Daily: {self._calls_today}/{self.daily_limit} ({100*self._calls_today/self.daily_limit:.1f}%) | "
            f"Window ({window.value}): {window_used}/{budget.total_calls}"
        )
    
    def get_scannable_tickers(self, all_tickers: List[str], 
                             scores: Dict[str, float] = None,
                             dui_tickers: Set[str] = None) -> List[str]:
        """
        Get list of tickers that can be scanned with UW API right now.
        
        Returns tickers in priority order, filtered by budget availability.
        """
        scores = scores or {}
        dui_tickers = dui_tickers or set()
        
        # Categorize tickers by priority
        p1_tickers = []
        p2_tickers = []
        p3_tickers = []
        
        for symbol in all_tickers:
            score = scores.get(symbol, 0)
            is_dui = symbol in dui_tickers
            priority = self.get_ticker_priority(symbol, score, is_dui)
            
            if self.can_call_uw(symbol, priority, score, is_dui):
                if priority == TickerPriority.PRIORITY_1:
                    p1_tickers.append((symbol, score))
                elif priority == TickerPriority.PRIORITY_2:
                    p2_tickers.append((symbol, score))
                else:
                    p3_tickers.append((symbol, score))
        
        # Sort by score within each priority
        p1_tickers.sort(key=lambda x: x[1], reverse=True)
        p2_tickers.sort(key=lambda x: x[1], reverse=True)
        p3_tickers.sort(key=lambda x: x[1], reverse=True)
        
        # Return in priority order
        return (
            [t[0] for t in p1_tickers] +
            [t[0] for t in p2_tickers] +
            [t[0] for t in p3_tickers]
        )
    
    def get_status(self) -> Dict:
        """Get current budget status as dict."""
        self._check_reset()
        window = self.get_current_window()
        budget = WINDOW_BUDGETS[window]
        
        return {
            "daily_used": self._calls_today,
            "daily_limit": self.daily_limit,
            "daily_remaining": self.remaining_daily,
            "daily_pct": 100 * self._calls_today / self.daily_limit,
            "current_window": window.value,
            "window_used": self._window_calls.get(window, 0),
            "window_budget": budget.total_calls,
            "unique_tickers_called": len(self._ticker_call_count),
        }
    
    def skip_uw_use_alpaca_only(self, symbol: str, score: float = 0,
                               force_scan: bool = False) -> bool:
        """
        Determine if we should skip UW and use Alpaca-only scan.
        
        Skip UW for:
        - Very low scores (< 0.15) - unless force_scan
        - P3 tickers during midday - unless force_scan
        - When budget is critically low (< 10%) - unless force_scan
        
        Args:
            force_scan: If True, never skip (EWS discovery scans need all tickers)
        """
        # Force scan mode: never skip UW
        if force_scan:
            return False
        
        priority = self.get_ticker_priority(symbol, score)
        window = self.get_current_window()
        
        # Skip if score is very low (no point using expensive API)
        if score < 0.15 and priority == TickerPriority.PRIORITY_3:
            return True
        
        # Skip P3 during low-priority windows
        if priority == TickerPriority.PRIORITY_3 and window in {TimeWindow.MIDDAY, TimeWindow.AFTER_HOURS}:
            return True
        
        # Skip if budget critically low (save for P1)
        if self.remaining_daily < 500 and priority != TickerPriority.PRIORITY_1:
            return True
        
        return False


# Singleton instance
_budget_manager: Optional[APIBudgetManager] = None


def get_budget_manager() -> APIBudgetManager:
    """Get singleton API budget manager."""
    global _budget_manager
    if _budget_manager is None:
        _budget_manager = APIBudgetManager()
    return _budget_manager
