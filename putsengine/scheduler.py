"""
PutsEngine Scheduled Scanner Service - ALWAYS-ON BACKGROUND DAEMON

FEB 1, 2026 UPDATE: PRE-BREAKDOWN SIGNAL PRIORITY
================================================
The system now prioritizes PRE-breakdown (predictive) signals over
POST-breakdown (reactive) signals. This ensures early detection.

PRE-BREAKDOWN signals (1.5x weight):
- Dark pool distribution, put OI accumulation, call selling at bid
- IV inversion, skew steepening, insider selling

POST-BREAKDOWN signals (0.7x weight):
- High RVOL red day, gap down no recovery, multi-day weakness
- Pump reversal, exhaustion patterns

FINAL SCHEDULE: 12 scans/day (ET):
#   Time (ET)    Label
1   4:15 AM      Pre-Market #1
2   6:15 AM      Pre-Market #2
3   8:15 AM      Pre-Market #3
4   9:15 AM      Pre-Market #4
5   10:15 AM     Regular
6   11:15 AM     Regular
7   12:45 PM     Regular
8   1:45 PM      Regular
9   2:45 PM      Regular
10  3:15 PM      Regular
11  4:00 PM      Market Close
12  5:00 PM      End of Day

BATCHED SCANNING STRATEGY:
- All tickers (universe + dynamic) scanned in EVERY scan
- Split into 3 batches of ~100 tickers
- Wait 65 seconds between batches (rate limit reset)
- Result: 0 tickers missed, complete coverage

DAEMON MODE:
- Runs independently of dashboard
- Use start_scheduler_daemon.py to manage
- Logs to logs/scheduler_daemon.log

This scheduler runs as a background service and saves results for the dashboard.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path

import pytz
from loguru import logger

# APScheduler for background scheduling
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
except ImportError:
    logger.error("APScheduler not installed. Run: pip install apscheduler")
    sys.exit(1)

from putsengine.config import get_settings, EngineConfig
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient
from putsengine.layers.market_regime import MarketRegimeLayer
from putsengine.layers.distribution import DistributionLayer
from putsengine.layers.liquidity import LiquidityVacuumLayer
from putsengine.layers.acceleration import AccelerationWindowLayer
from putsengine.scoring.scorer import PutScorer
from putsengine.models import PutCandidate, EngineType

# New scanners for after-hours, earnings, and pre-catalyst detection
from putsengine.afterhours_scanner import run_afterhours_scan, AfterHoursScanner
from putsengine.earnings_calendar import run_earnings_check, EarningsCalendar
from putsengine.precatalyst_scanner import run_precatalyst_scan, PreCatalystScanner

# ARCHITECT-4: Lead/Discovery Scanners (inject into DUI, NOT trade directly)
# These detect moves 1-2 days BEFORE they happen
from putsengine.gap_scanner import run_premarket_gap_scan, GapScanner
from putsengine.sector_correlation_scanner import run_sector_correlation_scan, SectorCorrelationScanner
from putsengine.multiday_weakness_scanner import run_multiday_weakness_scan, MultiDayWeaknessScanner

# NEW SCANNERS (Jan 29, 2026) - Would have caught 90% of missed puts
from putsengine.pump_dump_scanner import run_pump_dump_scan, inject_pump_dumps_to_dui
from putsengine.pre_earnings_flow import run_pre_earnings_flow_scan, inject_pre_earnings_to_dui
from putsengine.volume_price_divergence import run_volume_price_scan, inject_divergence_to_dui

# MarketPulse Engine (Feb 5, 2026) - Regime awareness, not prediction
# Consolidated from Architect-2,3,4,5 feedback
from putsengine.market_pulse_engine import analyze_market_direction, format_result
from putsengine.intraday_scanner import run_intraday_scan, IntradayScanner

# EARLY WARNING SYSTEM (Feb 1, 2026) - Detect institutional footprints 1-3 days before breakdown
from putsengine.early_warning_system import (
    run_early_warning_scan, 
    get_early_warning_summary,
    EarlyWarningScanner,
    InstitutionalPressure,
    PressureLevel
)

# ZERO-HOUR GAP SCANNER (Feb 1, 2026) - Day 0 execution confirmation
from putsengine.zero_hour_scanner import run_zero_hour_scan, get_zero_hour_summary, ZeroHourVerdict

# FLASH ALERTS (Feb 1, 2026) - Rapid IPI surge detection
from putsengine.flash_alerts import check_for_flash_alerts_in_ews_scan, get_flash_alerts

# EWS ATTRIBUTION (Feb 1, 2026) - Observation & measurement phase
from putsengine.ews_attribution import log_ews_detection

# EARNINGS PRIORITY SCANNER (Feb 3, 2026 FIX) - 14/15 crashes were earnings-related
from putsengine.earnings_priority_scanner import run_earnings_priority_scan, EarningsPriorityScanner

# Email Reporter for daily 3 PM scan
from putsengine.email_reporter import run_daily_report_scan, send_email_report, save_report_to_file


# Constants — timezone MUST be America/New_York (handles DST correctly)
EST = pytz.timezone('America/New_York')

# US market holidays (no market hours — skip weather reports)
US_MARKET_HOLIDAYS_2026 = {
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents' Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 7, 3),   # Independence Day (observed)
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving
    date(2026, 12, 25), # Christmas
}


def is_trading_day(d: date = None) -> bool:
    """Check if a given date is a US market trading day."""
    if d is None:
        d = datetime.now(EST).date()
    if d.weekday() >= 5:  # Saturday or Sunday
        return False
    if d in US_MARKET_HOLIDAYS_2026:
        return False
    return True
RESULTS_FILE = Path("scheduled_scan_results.json")
SCAN_LOG_FILE = Path("logs/scheduled_scans.log")


def get_signal_tier(score: float) -> str:
    """Get signal tier from score per ARCHITECT-4 Class System."""
    if score >= 0.75:
        return "🔥 EXPLOSIVE"
    elif score >= 0.68:
        return "🏛️ CLASS A"
    elif score >= 0.55:
        return "💪 STRONG"
    elif score >= 0.45:
        return "👀 MONITORING"
    elif score >= 0.35:
        return "🟡 CLASS B"
    elif score >= 0.25:
        return "📊 WATCHING"
    else:
        return "❌ BELOW THRESHOLD"


def get_next_friday(current_date: date, offset_weeks: int = 0) -> date:
    """Get the next Friday expiry date."""
    days_until_friday = (4 - current_date.weekday() + 7) % 7
    if days_until_friday == 0:
        days_until_friday = 7
    next_friday = current_date + timedelta(days=days_until_friday)
    return next_friday + timedelta(weeks=offset_weeks)


class PutsEngineScheduler:
    """
    Scheduled scanner service for PutsEngine.
    
    Automatically runs scans at predefined times and saves results
    for the dashboard to display.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.scheduler = AsyncIOScheduler(timezone=EST)
        self.is_running = False
        
        # Clients (initialized lazily)
        self._alpaca: Optional[AlpacaClient] = None
        self._polygon: Optional[PolygonClient] = None
        self._uw: Optional[UnusualWhalesClient] = None
        
        # Layers
        self._market_regime_layer: Optional[MarketRegimeLayer] = None
        self._distribution_layer: Optional[DistributionLayer] = None
        self._liquidity_layer: Optional[LiquidityVacuumLayer] = None
        self._acceleration_layer: Optional[AccelerationWindowLayer] = None
        self._scorer: Optional[PutScorer] = None
        
        # Results storage
        self.latest_results: Dict[str, Any] = {
            "gamma_drain": [],
            "distribution": [],
            "liquidity": [],
            "last_scan": None,
            "scan_type": None
        }
        
        # Setup logging
        self._setup_logging()
    
    def _setup_logging(self):
        """Configure logging for scheduler."""
        SCAN_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(SCAN_LOG_FILE),
            rotation="1 day",
            retention="7 days",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
        )
    
    async def _init_clients(self):
        """Initialize API clients."""
        if self._alpaca is None:
            self._alpaca = AlpacaClient(self.settings)
            self._polygon = PolygonClient(self.settings)
            self._uw = UnusualWhalesClient(self.settings)
            
            self._market_regime_layer = MarketRegimeLayer(
                self._alpaca, self._polygon, self._uw, self.settings
            )
            self._distribution_layer = DistributionLayer(
                self._alpaca, self._polygon, self._uw, self.settings
            )
            self._liquidity_layer = LiquidityVacuumLayer(
                self._alpaca, self._polygon, self.settings
            )
            self._acceleration_layer = AccelerationWindowLayer(
                self._alpaca, self._polygon, self._uw, self.settings
            )
            self._scorer = PutScorer(self.settings)
    
    async def _close_clients(self):
        """Close API clients."""
        if self._alpaca:
            await self._alpaca.close()
        if self._polygon:
            await self._polygon.close()
        if self._uw:
            await self._uw.close()
    
    def _schedule_jobs(self):
        """
        Configure all scheduled scan jobs.
        
        FINAL SCHEDULE (12 scans/day, ET):
        #   Time        Label
        1   4:15 AM     Pre-Market #1
        2   6:15 AM     Pre-Market #2
        3   8:15 AM     Pre-Market #3
        4   9:15 AM     Pre-Market #4
        5   10:15 AM    Regular
        6   11:15 AM    Regular
        7   12:45 PM    Regular
        8   1:45 PM     Regular
        9   2:45 PM     Regular
        10  3:15 PM     Regular
        11  4:00 PM     Market Close
        12  5:00 PM     End of Day
        """
        # Pre-market scans (4 scans at :15)
        # ============================================================================
        # OPTIMIZED SCHEDULE (Feb 4, 2026)
        # ============================================================================
        # REMOVED: 8:00 AM Pre-Market Full Scan - redundant with 9:00 AM scan
        # Saves ~1,000 UW API calls/day
        # ============================================================================
        
        # ============================================================================
        # PRE-MARKET FINAL SCAN - 9:00 AM ET (Feb 4, 2026)
        # ============================================================================
        # 30 minutes before market open - FINAL institutional positioning check
        # Uses full UW API (dark pool, options flow, IV, GEX)
        # Purpose: Same-day trading decisions based on overnight/pre-market trend
        # ============================================================================
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=9, minute=0, timezone=EST),
            args=["pre_market_final"],
            id="pre_market_final_9am",
            name="🎯 Pre-Market Final Scan (9:00 AM ET) - 361 tickers - UW API",
            replace_existing=True
        )
        
        # REMOVED: Pre-Market Scans #1-4 (4:15, 6:15, 8:15, 9:15 AM) - redundant
        # REMOVED: Regular Scans (10:15, 11:15, 12:45, 1:45, 2:45, 3:15) - heavy UW usage
        # REMOVED: Market Close Scan (4:00 PM) - redundant with After-Hours
        # REMOVED: End of Day Scan (5:00 PM) - redundant with EWS at 10 PM
        
        # ============================================================================
        # MARKET PULSE SCAN - Pre-Meta-Engine Data Collection (Feb 10, 2026)
        # ============================================================================
        # 2:45 PM ET — Moved from 3:00 PM → 2:45 PM so it finishes (~21 min)
        # BEFORE Meta Engine reads at 3:15 PM. This is the SINGLE combined
        # scan that feeds BOTH Meta Engine cross-analysis AND market direction.
        #
        # FEB 10 FIX: At 3:00 PM the scan took 21 min → finished at 3:21 PM,
        # but Meta Engine reads at 3:15 PM — ALWAYS reading stale 9 AM data.
        # Moving to 2:45 PM → finishes ~3:06 PM → 9 min buffer before 3:15 PM.
        #
        # Also removed: daily_report_3pm (was a DUPLICATE full scan at 3:00 PM)
        #               early_warning_3pm (saves 1,800 UW calls)
        # ============================================================================
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=14, minute=45, timezone=EST),
            args=["market_pulse"],
            id="market_pulse_245pm",
            name="📊 Market Pulse Full Scan (2:45 PM ET) - 361 tickers - Feeds Meta Engine 3:15 PM",
            replace_existing=True
        )
        
        # ============================================================================
        # NEW SCANNERS: After-Hours, Earnings Calendar, Pre-Catalyst
        # These would have caught MP (-10.68% AH), USAR (-13.31% AH), JOBY (-11.48% AH)
        # ============================================================================
        
        # After-Hours Scans (4:30 PM, 6:00 PM, 8:00 PM)
        self.scheduler.add_job(
            self._run_afterhours_scan_wrapper,
            CronTrigger(hour=16, minute=30, timezone=EST),
            id="afterhours_1",
            name="After-Hours Scan #1 (4:30 PM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_afterhours_scan_wrapper,
            CronTrigger(hour=18, minute=0, timezone=EST),
            id="afterhours_2",
            name="After-Hours Scan #2 (6:00 PM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_afterhours_scan_wrapper,
            CronTrigger(hour=20, minute=0, timezone=EST),
            id="afterhours_3",
            name="After-Hours Scan #3 (8:00 PM ET)",
            replace_existing=True
        )
        
        # Earnings Calendar Check (7:00 AM and 3:00 PM)
        self.scheduler.add_job(
            self._run_earnings_check_wrapper,
            CronTrigger(hour=7, minute=0, timezone=EST),
            id="earnings_morning",
            name="Earnings Calendar Check (7:00 AM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_earnings_check_wrapper,
            CronTrigger(hour=15, minute=0, timezone=EST),
            id="earnings_afternoon",
            name="Earnings AMC Alert (3:00 PM ET)",
            replace_existing=True
        )
        
        # Pre-Catalyst Scanner (6:00 PM - detect smart money positioning)
        self.scheduler.add_job(
            self._run_precatalyst_scan_wrapper,
            CronTrigger(hour=18, minute=0, timezone=EST),
            id="precatalyst",
            name="Pre-Catalyst Distribution Scan (6:00 PM ET)",
            replace_existing=True
        )
        
        # ============================================================================
        # GAP 5/6/7 FIX: FINVIZ BEARISH + SHORT INTEREST SCAN
        # ============================================================================
        # Runs 2x daily: 8:30 AM (pre-market) and 1:30 PM (midday)
        # Captures: insider selling, analyst downgrades, technical weakness,
        #           high short interest, sector performance — ALL from FinViz Elite
        # NO UW API calls — zero impact on UW budget
        # Output: logs/finviz_bearish.json, logs/finviz_short_interest.json
        # ============================================================================
        self.scheduler.add_job(
            self._run_finviz_bearish_scan_wrapper,
            CronTrigger(hour=8, minute=30, timezone=EST),
            id="finviz_bearish_830am",
            name="🔵 FinViz Bearish Scan (8:30 AM ET) - Insider/Downgrade/Short",
            replace_existing=True
        )
        self.scheduler.add_job(
            self._run_finviz_bearish_scan_wrapper,
            CronTrigger(hour=13, minute=30, timezone=EST),
            id="finviz_bearish_130pm",
            name="🔵 FinViz Bearish Scan (1:30 PM ET) - Insider/Downgrade/Short",
            replace_existing=True
        )
        
        # ============================================================================
        # FEB 3, 2026 FIX: EARNINGS PRIORITY SCANNER
        # 14/15 crashes were earnings-related - need dedicated scanner
        # Runs 3x daily: 7:00 AM, 12:00 PM, 4:30 PM ET
        # ============================================================================
        self.scheduler.add_job(
            self._run_earnings_priority_scan_wrapper,
            CronTrigger(hour=7, minute=0, timezone=EST),
            id="earnings_priority_7am",
            name="Earnings Priority Scan (7:00 AM ET) - Pre-Market",
            replace_existing=True
        )
        
        # FEB 8, 2026 OPTIMIZATION: Staggered +2 min after co-located EWS scans.
        # EWS at 12:00 PM caches dark_pool_flow, oi_change, flow_recent, iv_term_structure
        # for ALL 361 tickers. Earnings Priority calls the SAME 4 endpoints for earnings
        # stocks. Running 2 min later = GUARANTEED cache hits on 4/6 UW endpoints.
        # SAVINGS: ~80 UW calls per scan (4 cached × ~20 earnings stocks).
        self.scheduler.add_job(
            self._run_earnings_priority_scan_wrapper,
            CronTrigger(hour=12, minute=2, timezone=EST),
            id="earnings_priority_12pm",
            name="Earnings Priority Scan (12:02 PM ET) - Midday [cached from EWS]",
            replace_existing=True
        )
        
        # FEB 8, 2026: Staggered +2 min after 4:30 PM EWS for same cache benefit.
        self.scheduler.add_job(
            self._run_earnings_priority_scan_wrapper,
            CronTrigger(hour=16, minute=32, timezone=EST),
            id="earnings_priority_430pm",
            name="Earnings Priority Scan (4:32 PM ET) - Post-Market [cached from EWS]",
            replace_existing=True
        )
        
        # ============================================================================
        # MARKET DIRECTION ENGINE (Feb 4, 2026) — UPDATED Feb 6, 2026
        # Predicts market direction using GEX, VIX, dark pool, options flow
        # Pre-market: 8:00 AM and 9:00 AM ET
        # Intraday: Hourly from 10:00 AM to 3:00 PM ET (6 refreshes)
        # Uses Polygon (unlimited) + cached UW data — lightweight refresh
        # ============================================================================
        self.scheduler.add_job(
            self._run_market_direction_wrapper,
            CronTrigger(hour=8, minute=0, timezone=EST),
            id="market_direction_8am",
            name="🎯 Market Direction Analysis (8:00 AM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_market_direction_wrapper,
            CronTrigger(hour=9, minute=0, timezone=EST),
            id="market_direction_9am",
            name="🎯 Market Direction Analysis (9:00 AM ET) - Pre-Open",
            replace_existing=True
        )
        
        # INTRADAY MARKET DIRECTION REFRESH — Hourly during market hours
        # FEB 6, 2026 FIX: Market Direction was stuck at 8 AM all day because
        # no intraday refresh jobs existed. Dashboard auto-refresh reloads the
        # JSON every 30 min, but the JSON itself wasn't being updated.
        for md_hour in [10, 11, 12, 13, 14, 15]:
            self.scheduler.add_job(
                self._run_market_direction_wrapper,
                CronTrigger(hour=md_hour, minute=0, timezone=EST),
                id=f"market_direction_{md_hour}",
                name=f"🎯 Market Direction Refresh ({md_hour}:00 ET) - Intraday",
                replace_existing=True
            )
        
        # ============================================================================
        # ARCHITECT-4 LEAD/DISCOVERY SCANNERS
        # These detect moves 1-2 days BEFORE they happen via DUI injection
        # MP → USAR → LAC cascade would have been caught by these
        # ============================================================================
        
        # PRE-MARKET GAP SCANNER (would have caught UNH -20% pre-market)
        # Scans 800+ tickers for significant pre-market gaps
        self.scheduler.add_job(
            self._run_premarket_gap_scan_wrapper,
            CronTrigger(hour=4, minute=0, timezone=EST),
            id="gap_scan_4am",
            name="Pre-Market Gap Scan (4:00 AM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_premarket_gap_scan_wrapper,
            CronTrigger(hour=6, minute=0, timezone=EST),
            id="gap_scan_6am",
            name="Pre-Market Gap Scan (6:00 AM ET)",
            replace_existing=True
        )
        
        # 7:00 AM Gap Scan - CRITICAL for catching overnight earnings moves
        # FEB 4 FIX: AMD, BSX, APP crashed pre-market, need earlier detection
        self.scheduler.add_job(
            self._run_premarket_gap_scan_wrapper,
            CronTrigger(hour=7, minute=0, timezone=EST),
            id="gap_scan_7am",
            name="Pre-Market Gap Scan (7:00 AM ET) - Early Earnings Detection",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_premarket_gap_scan_wrapper,
            CronTrigger(hour=8, minute=0, timezone=EST),
            id="gap_scan_8am",
            name="Pre-Market Gap Scan (8:00 AM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_premarket_gap_scan_wrapper,
            CronTrigger(hour=9, minute=15, timezone=EST),
            id="gap_scan_915am",
            name="Pre-Market Gap Scan (9:15 AM ET) - Final Pre-Market",
            replace_existing=True
        )
        
        # MULTI-DAY WEAKNESS SCANNER (would have caught MP/JOBY patterns)
        # Detects 8 weakness patterns over 2-5 days
        # Run at end of day to prepare for next day's trading
        self.scheduler.add_job(
            self._run_multiday_weakness_scan_wrapper,
            CronTrigger(hour=17, minute=0, timezone=EST),
            id="multiday_weakness_5pm",
            name="Multi-Day Weakness Scan (5:00 PM ET)",
            replace_existing=True
        )
        
        # Also run in the morning to catch overnight developments
        self.scheduler.add_job(
            self._run_multiday_weakness_scan_wrapper,
            CronTrigger(hour=7, minute=30, timezone=EST),
            id="multiday_weakness_730am",
            name="Multi-Day Weakness Scan (7:30 AM ET)",
            replace_existing=True
        )
        
        # SECTOR CORRELATION SCANNER (would have caught MP → USAR → LAC cascade)
        # Run after regular scans to detect sector-wide weakness
        self.scheduler.add_job(
            self._run_sector_correlation_scan_wrapper,
            CronTrigger(hour=11, minute=0, timezone=EST),
            id="sector_correlation_11am",
            name="Sector Correlation Scan (11:00 AM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_sector_correlation_scan_wrapper,
            CronTrigger(hour=14, minute=0, timezone=EST),
            id="sector_correlation_2pm",
            name="Sector Correlation Scan (2:00 PM ET)",
            replace_existing=True
        )
        
        # ============================================================================
        # DAILY REPORT SCAN — REMOVED (Feb 10, 2026)
        # Was a DUPLICATE full 361-ticker scan at 3:00 PM overlapping market_pulse.
        # Meta Engine at 3:15 PM now handles all reporting (Email + Telegram + X).
        # Savings: ~2,200 UW API calls/day.
        # ============================================================================
        # self.scheduler.add_job(
        #     self._run_daily_report_scan_wrapper,
        #     CronTrigger(hour=15, minute=0, timezone=EST),
        #     id="daily_report_3pm",
        #     name="📧 Daily Report Scan (3:00 PM ET) - Email",
        #     replace_existing=True
        # )
        
        # ============================================================================
        # NEW SCANNERS (Jan 29, 2026) - Would have caught 90% of missed puts
        # ============================================================================
        
        # PUMP-DUMP REVERSAL SCANNER
        # Detects stocks that pumped +5%+ then show reversal signals
        # Would have caught OKLO, CLS, FSLR on Jan 28
        self.scheduler.add_job(
            self._run_pump_dump_scan_wrapper,
            CronTrigger(hour=10, minute=30, timezone=EST),
            id="pump_dump_1030am",
            name="Pump-Dump Reversal Scan (10:30 AM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_pump_dump_scan_wrapper,
            CronTrigger(hour=14, minute=30, timezone=EST),
            id="pump_dump_230pm",
            name="Pump-Dump Reversal Scan (2:30 PM ET)",
            replace_existing=True
        )
        
        # PRE-EARNINGS FLOW SCANNER
        # Detects smart money positioning before earnings
        # Would have caught MSFT, NOW, TEAM, WDAY, TWLO on Jan 26-27
        self.scheduler.add_job(
            self._run_pre_earnings_flow_wrapper,
            CronTrigger(hour=10, minute=0, timezone=EST),
            id="pre_earnings_10am",
            name="Pre-Earnings Flow Scan (10:00 AM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_pre_earnings_flow_wrapper,
            CronTrigger(hour=14, minute=0, timezone=EST),
            id="pre_earnings_2pm",
            name="Pre-Earnings Flow Scan (2:00 PM ET)",
            replace_existing=True
        )
        
        # VOLUME-PRICE DIVERGENCE SCANNER
        # Detects distribution patterns (high volume, flat/weak price)
        # Would have caught MSFT, NOW, TEAM, MSTR distribution on Jan 27
        self.scheduler.add_job(
            self._run_volume_price_scan_wrapper,
            CronTrigger(hour=11, minute=30, timezone=EST),
            id="vol_price_1130am",
            name="Volume-Price Divergence Scan (11:30 AM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_volume_price_scan_wrapper,
            CronTrigger(hour=15, minute=30, timezone=EST),
            id="vol_price_330pm",
            name="Volume-Price Divergence Scan (3:30 PM ET)",
            replace_existing=True
        )
        
        # INTRADAY BIG MOVER SCANNER (NEW FEB 2, 2026)
        # CRITICAL: Uses REAL-TIME quotes, not stale daily bars
        # This would have caught HOOD -9.62%, RMBS -15.50%, DIS -7.32% TODAY
        # Runs every hour during market hours
        
        self.scheduler.add_job(
            self._run_intraday_scan_wrapper,
            CronTrigger(hour=10, minute=0, timezone=EST),
            id="intraday_10am",
            name="🚨 Intraday Big Mover Scan (10:00 AM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_intraday_scan_wrapper,
            CronTrigger(hour=11, minute=0, timezone=EST),
            id="intraday_11am",
            name="🚨 Intraday Big Mover Scan (11:00 AM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_intraday_scan_wrapper,
            CronTrigger(hour=12, minute=0, timezone=EST),
            id="intraday_12pm",
            name="🚨 Intraday Big Mover Scan (12:00 PM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_intraday_scan_wrapper,
            CronTrigger(hour=13, minute=0, timezone=EST),
            id="intraday_1pm",
            name="🚨 Intraday Big Mover Scan (1:00 PM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_intraday_scan_wrapper,
            CronTrigger(hour=14, minute=0, timezone=EST),
            id="intraday_2pm",
            name="🚨 Intraday Big Mover Scan (2:00 PM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_intraday_scan_wrapper,
            CronTrigger(hour=15, minute=0, timezone=EST),
            id="intraday_3pm",
            name="🚨 Intraday Big Mover Scan (3:00 PM ET)",
            replace_existing=True
        )
        
        # ============================================================================
        # EARLY WARNING SYSTEM (Feb 1, 2026) - Institutional Footprint Detection
        # Detects the 7 institutional footprints 1-3 days BEFORE breakdown:
        # 1. Dark Pool Sequence - Smart money selling in staircases
        # 2. Put OI Accumulation - Quiet positioning before news
        # 3. IV Term Inversion - Premium for near-term protection
        # 4. Quote Degradation - Market makers reducing exposure
        # 5. Flow Divergence - Options leading stock by 1-2 days
        # 6. Multi-Day Distribution - Classic Wyckoff distribution
        # 7. Cross-Asset Divergence - Correlation breakdown
        # ============================================================================
        
        # ============================================================================
        # EARLY WARNING SYSTEM - FIXED (Feb 5, 2026)
        # ============================================================================
        # CRITICAL FIX: EWS data was 11+ hours stale at market open!
        # Added pre-market EWS scan to ensure fresh institutional footprint data
        # ============================================================================
        
        # 8:00 AM EWS - CRITICAL for market-open decisions
        # Scans 361 tickers for overnight institutional footprints
        # This ensures TOP 8 picks are fresh when you need them at 9:30 AM
        self.scheduler.add_job(
            self._run_early_warning_scan_wrapper,
            CronTrigger(hour=8, minute=0, timezone=EST),
            id="early_warning_8am",
            name="🚨 Early Warning Scan (8:00 AM ET) - PRE-MARKET CRITICAL",
            replace_existing=True
        )
        
        # 9:45 AM EWS - OPENING RANGE REFRESH (FEB 7, 2026)
        # Catches opening-range institutional flow within first 15 min of market open
        # Moved from 10:00 AM to capture early institutional prints
        self.scheduler.add_job(
            self._run_early_warning_scan_wrapper,
            CronTrigger(hour=9, minute=45, timezone=EST),
            id="early_warning_945am",
            name="🚨 Early Warning Scan (9:45 AM ET) - OPENING RANGE",
            replace_existing=True
        )
        
        # 11:00 AM EWS - MID-MORNING UPDATE (FEB 7, 2026)
        # Fills 9:45 AM → 12 PM gap for mid-morning institutional positioning
        self.scheduler.add_job(
            self._run_early_warning_scan_wrapper,
            CronTrigger(hour=11, minute=0, timezone=EST),
            id="early_warning_11am",
            name="🚨 Early Warning Scan (11:00 AM ET) - MID-MORNING",
            replace_existing=True
        )
        
        # 12:00 PM EWS — REMOVED (Feb 10, 2026)
        # Uses cached data from 11 AM EWS. Saves ~1,800 UW API calls/day.
        # The 11 AM → 1 PM gap is acceptable; 11 AM data is <2 hours stale.
        # self.scheduler.add_job(
        #     self._run_early_warning_scan_wrapper,
        #     CronTrigger(hour=12, minute=0, timezone=EST),
        #     id="early_warning_12pm",
        #     name="🚨 Early Warning Scan (12:00 PM ET) - MIDDAY UPDATE",
        #     replace_existing=True
        # )
        
        # 1:00 PM EWS - EARLY AFTERNOON (FEB 7, 2026)
        # Captures lunch-hour institutional accumulation/distribution
        self.scheduler.add_job(
            self._run_early_warning_scan_wrapper,
            CronTrigger(hour=13, minute=0, timezone=EST),
            id="early_warning_1pm",
            name="🚨 Early Warning Scan (1:00 PM ET) - EARLY AFTERNOON",
            replace_existing=True
        )
        
        # 2:00 PM EWS - AFTERNOON POSITIONING (FEB 7, 2026)
        # Captures pre-close institutional positioning build-up
        self.scheduler.add_job(
            self._run_early_warning_scan_wrapper,
            CronTrigger(hour=14, minute=0, timezone=EST),
            id="early_warning_2pm",
            name="🚨 Early Warning Scan (2:00 PM ET) - AFTERNOON POSITIONING",
            replace_existing=True
        )
        
        # 3:02 PM EWS — REMOVED (Feb 10, 2026)
        # Was staggered after daily_report_3pm for cache hits, but daily_report
        # is also removed. The 2:45 PM market_pulse full scan now covers this window.
        # Savings: ~1,800 UW API calls/day.
        # self.scheduler.add_job(
        #     self._run_early_warning_scan_wrapper,
        #     CronTrigger(hour=15, minute=2, timezone=EST),
        #     id="early_warning_3pm",
        #     name="🚨 Early Warning Scan (3:02 PM ET) - AFTERNOON CLOSE PREP",
        #     replace_existing=True
        # )
        
        # 4:30 PM EWS - After-hours positioning detection
        self.scheduler.add_job(
            self._run_early_warning_scan_wrapper,
            CronTrigger(hour=16, minute=30, timezone=EST),
            id="early_warning_430pm",
            name="🚨 Early Warning Scan (4:30 PM ET) - POST-MARKET",
            replace_existing=True
        )
        
        # 10:00 PM EWS - Overnight footprint detection
        # Scans 361 tickers for institutional footprints
        self.scheduler.add_job(
            self._run_early_warning_scan_wrapper,
            CronTrigger(hour=22, minute=0, timezone=EST),
            id="early_warning_10pm",
            name="🚨 Early Warning Scan (10:00 PM ET) - OVERNIGHT",
            replace_existing=True
        )
        
        # ============================================================================
        # ZERO-HOUR GAP SCANNER (Feb 1, 2026) - Day 0 Execution Confirmation
        # ARCHITECT-4 VALIDATED: This is the HIGHEST ROI remaining addition.
        # 
        # Why: Institutions accumulate footprints on Day -1 (EWS), 
        #      then execute via pre-market gaps on Day 0.
        # 
        # Schedule: 9:15 AM ET (15 minutes before market open)
        # Only checks: IPI ≥ 0.60 names from last EWS scan
        # 
        # Interpretation:
        # - IPI ≥ 0.60 AND gap down → "Vacuum is open" → ACT
        # - IPI ≥ 0.60 AND gap up → "Pressure absorbed" → WAIT
        # ============================================================================
        self.scheduler.add_job(
            self._run_zero_hour_scan_wrapper,
            CronTrigger(hour=9, minute=15, timezone=EST),
            id="zero_hour_915am",
            name="⚡ Zero-Hour Gap Scanner (9:15 AM ET) - Day 0 Confirmation",
            replace_existing=True
        )
        
        # =========================================================================
        # PATTERN SCAN - OPTIMIZED (Feb 4, 2026)
        # REMOVED: 14 pattern scans every 30 mins (9:30 AM - 4:00 PM)
        # KEPT: Just 1 pattern scan at 4:00 PM (post-market)
        # Reason: Pattern scans use Alpaca only, but still consume resources
        # =========================================================================
        self.scheduler.add_job(
            self._run_pattern_scan_wrapper,
            CronTrigger(hour=16, minute=0, timezone=EST),
            id="pattern_scan_16_00",
            name="Pattern Scan (4:00 PM ET - Post Market) - 361 tickers",
            replace_existing=True
        )
        
        # =========================================================================
        # MARKET WEATHER ENGINE v5.2 (Feb 6, 2026) — 30-Min Refresh Cycle
        # Architect 2-5 Consolidated: Gamma Flip Distance, Opening Flow Bias,
        # Liquidity Violence Score, storm_score (not probability), AM/PM modes
        #
        # FULL RUNS (9 AM, 3 PM): Live UW API + Polygon + EWS → save UW cache
        # REFRESH RUNS (every 30 min): Cached UW + fresh Polygon + fresh EWS
        #   → Reuses existing scan data, ZERO extra UW API calls
        #   → Polygon is unlimited, so fresh price/technical data every 30 min
        #   → Reads latest EWS alerts from other scheduled EWS scans
        # =========================================================================
        
        # 9:05 AM ET — FULL AM "Open Risk Forecast" (FEB 8 — staggered)
        # STAGGERED from 9:00→9:05 AM to maximize UW response cache hits.
        # pre_market_final_9am starts at 9:00 and calls 7+ UW endpoints per
        # ticker (flow_recent, oi_change, dark_pool, gex, skew, insider, etc.)
        # By 9:05, the cache is partially warm → Weather's gex_data +
        # flow_recent calls hit cache for tickers already processed.
        # SAVINGS: ~200 UW calls (gex + flow × top candidates already cached)
        self.scheduler.add_job(
            self._run_market_weather_am_wrapper,
            CronTrigger(hour=9, minute=5, timezone=EST),
            id="market_weather_0900",
            name="🌪️ Market Weather AM (9:05 AM ET) — FULL Open Risk Forecast",
            replace_existing=True
        )
        
        # 3:08 PM ET — FULL PM "Overnight Storm Build" (FEB 8 — staggered)
        # STAGGERED from 3:00→3:08 PM. daily_report (3:00 PM) + EWS (3:02 PM)
        # populate cache for all 361 tickers. By 3:08, Weather's UW calls
        # (gex_data, flow_recent per candidate) are mostly cached.
        # SAVINGS: ~40 UW calls (2 endpoints × top 20 candidates)
        self.scheduler.add_job(
            self._run_market_weather_pm_wrapper,
            CronTrigger(hour=15, minute=8, timezone=EST),
            id="market_weather_1500",
            name="🌪️ Market Weather PM (3:08 PM ET) — FULL Overnight Storm Build",
            replace_existing=True
        )
        
        # =========================================================================
        # 30-MINUTE WEATHER REFRESH CYCLE (9:30 AM — 3:30 PM ET)
        # Uses CACHED UW data + fresh Polygon (unlimited) + fresh EWS
        # NO additional UW API calls — reuses data from full runs + EWS scans
        # =========================================================================
        weather_refresh_times = [
            (9, 30), (10, 0), (10, 30), (11, 0), (11, 30),
            (12, 0), (12, 30), (13, 0), (13, 30),
            (14, 0), (14, 30), (15, 30),
        ]
        for hour, minute in weather_refresh_times:
            time_str = f"{hour}:{minute:02d}"
            job_id = f"weather_refresh_{hour:02d}{minute:02d}"
            self.scheduler.add_job(
                self._run_market_weather_refresh_wrapper,
                CronTrigger(hour=hour, minute=minute, timezone=EST),
                id=job_id,
                name=f"🔄 Market Weather Refresh ({time_str} ET) — Cached UW + Fresh Polygon",
                replace_existing=True
            )
        
        # 5:30 PM ET — Attribution Backfill (after market close)
        # Fills in T+1/T+2 actual outcomes for past weather forecasts
        # This is how we calibrate storm_score → actual probability over time
        self.scheduler.add_job(
            self._run_attribution_backfill_wrapper,
            CronTrigger(hour=17, minute=30, timezone=EST),
            id="weather_attribution_backfill",
            name="📊 Weather Attribution Backfill (5:30 PM ET) — Calibration Data",
            replace_existing=True
        )
        
        # Gap 9: 5:45 PM ET — Convergence Backtest Backfill
        # Fills in T+1/T+2 prices for Top 9 picks from past runs
        # Builds the calibration data: "convergence > 0.55 → X% hit rate"
        self.scheduler.add_job(
            self._run_convergence_backfill_wrapper,
            CronTrigger(hour=17, minute=45, timezone=EST),
            id="convergence_backtest_backfill",
            name="📊 Convergence Backtest Backfill (5:45 PM ET) — Calibration",
            replace_existing=True
        )
        
        # =========================================================================
        # 🎯 CONVERGENCE ENGINE — Automated 4-Step Decision Hierarchy
        #   EWS (35%) → Direction (15%) → Gamma Drain (25%) → Weather (25%)
        # Merges ALL four systems into a single Top 9 Scoreboard.
        #
        # RUNS: Every 30 min during market hours (8:00 AM — 4:00 PM ET)
        #   + After each EWS scan completes (triggered in _run_early_warning_scan_wrapper)
        # OUTPUT: logs/convergence/latest_top9.json
        # SELF-HEALING: Missing sources → partial data; crash → degraded status
        # =========================================================================
        convergence_times = [
            (8, 10), (8, 40),   # Pre-market (after 8AM EWS + Direction)
            (9, 10), (9, 50),   # Opening (after 9AM final + 9:45 EWS)
            (10, 10), (10, 40),
            (11, 10), (11, 40),
            (12, 10), (12, 40),
            (13, 10), (13, 40),
            (14, 10), (14, 40),
            (15, 10), (15, 40),
        ]
        for hour, minute in convergence_times:
            time_str = f"{hour}:{minute:02d}"
            job_id = f"convergence_{hour:02d}{minute:02d}"
            self.scheduler.add_job(
                self._run_convergence_wrapper,
                CronTrigger(hour=hour, minute=minute, timezone=EST),
                id=job_id,
                name=f"🎯 Convergence Top 9 ({time_str} ET) — 4-Step Decision Merge",
                replace_existing=True
            )
        
        logger.info("All scheduled jobs configured (OPTIMIZED Feb 8 — v5 Weather + Attribution + Convergence Engine)")
    
    def _safe_async_run(self, coro, name: str = "scan"):
        """
        DEPRECATED (Feb 9 FIX): All wrappers are now async — this is only
        kept as a fallback for any remaining sync callers.
        
        ROOT CAUSE (Feb 9 incident): When sync wrappers ran in APScheduler's
        thread pool, each call created a NEW event loop, then closed it.
        aiohttp sessions remained bound to the old closed loop, causing
        'Event loop is closed' for ALL subsequent API calls. The daemon ran
        7 AM – 3 PM with zero successful UW/Polygon/Alpaca calls.
        
        FIX: All wrapper methods are now async, so APScheduler runs them
        directly on its own stable event loop. No new loops, no session
        mismatch, no 'Event loop is closed' errors.
        
        This fallback now resets client sessions before creating a new loop,
        so even sync callers won't corrupt sessions.
        """
        import gc
        
        async def wrapped_coro():
            """Wrapper that handles errors and cleanup."""
            try:
                await self._init_clients()
                await coro
            except Exception as e:
                logger.error(f"Error in {name}: {e}")
                import traceback
                logger.error(traceback.format_exc())
            finally:
                gc.collect()
        
        try:
            # Try to get the running loop (APScheduler's loop)
            loop = asyncio.get_running_loop()
            if loop.is_running():
                # Schedule on the running loop
                loop.create_task(wrapped_coro())
            else:
                loop.run_until_complete(wrapped_coro())
        except RuntimeError:
            # No running loop — reset client sessions to prevent stale loop binding
            self._reset_client_sessions()
            try:
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    new_loop.run_until_complete(wrapped_coro())
                finally:
                    try:
                        pending = asyncio.all_tasks(new_loop)
                        for task in pending:
                            task.cancel()
                        if pending:
                            new_loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    except Exception:
                        pass
                    new_loop.close()
                    gc.collect()
            except Exception as e:
                logger.error(f"Failed to run {name} in new loop: {e}")
    
    def _reset_client_sessions(self):
        """
        Reset all client sessions so they recreate on the next event loop.
        
        FEB 9 FIX: When the event loop changes (e.g., _safe_async_run creates
        a new loop), old sessions bound to the previous loop must be discarded.
        The loop-aware _get_session() in each client will recreate them.
        """
        for client in [self._alpaca, self._polygon, self._uw]:
            if client is not None and hasattr(client, '_session'):
                client._session = None
                if hasattr(client, '_session_loop_id'):
                    client._session_loop_id = None
    
    async def _run_scan_wrapper(self, scan_type: str):
        """Wrapper to run scan — async so APScheduler uses its own event loop."""
        try:
            await self._init_clients()
            # Enable force_scan for PM scans (market_pulse, daily_report) so they
            # can access the reserved afternoon UW API budget (4,000 calls).
            is_pm_scan = scan_type.lower() in ("market_pulse", "daily_report")
            if is_pm_scan and hasattr(self, '_uw') and self._uw:
                self._uw.set_force_scan_mode(True)
                logger.info(f"Force scan mode ENABLED for {scan_type} (PM budget reservation)")
            try:
                await self.run_scan(scan_type)
            finally:
                if is_pm_scan and hasattr(self, '_uw') and self._uw:
                    self._uw.set_force_scan_mode(False)
                    logger.info(f"Force scan mode DISABLED after {scan_type}")
        except Exception as e:
            logger.error(f"Error in scan_{scan_type}: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_afterhours_scan_wrapper(self):
        """Wrapper to run after-hours scan — async for stable event loop."""
        try:
            await self._init_clients()
            await self.run_afterhours_scan()
        except Exception as e:
            logger.error(f"Error in afterhours_scan: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_earnings_check_wrapper(self):
        """Wrapper to run earnings calendar check — async for stable event loop."""
        try:
            await self._init_clients()
            await self.run_earnings_check()
        except Exception as e:
            logger.error(f"Error in earnings_check: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_precatalyst_scan_wrapper(self):
        """Wrapper to run pre-catalyst scan — async for stable event loop."""
        try:
            await self._init_clients()
            await self.run_precatalyst_scan()
        except Exception as e:
            logger.error(f"Error in precatalyst_scan: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_earnings_priority_scan_wrapper(self):
        """
        Wrapper to run earnings priority scan — async for stable event loop.
        FEB 3, 2026 FIX: 14/15 crashes were earnings-related.
        """
        try:
            await self._init_clients()
            await self.run_earnings_priority_scan()
        except Exception as e:
            logger.error(f"Error in earnings_priority_scan: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_market_direction_wrapper(self):
        """Wrapper to run market direction analysis — async for stable event loop."""
        try:
            await self._init_clients()
            await self.run_market_direction_analysis()
        except Exception as e:
            logger.error(f"Error in market_direction_analysis: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_premarket_gap_scan_wrapper(self):
        """Wrapper to run pre-market gap scan — async for stable event loop."""
        try:
            await self._init_clients()
            await self.run_premarket_gap_scan()
        except Exception as e:
            logger.error(f"Error in premarket_gap_scan: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_multiday_weakness_scan_wrapper(self):
        """Wrapper to run multi-day weakness scan — async for stable event loop."""
        try:
            await self._init_clients()
            await self.run_multiday_weakness_scan()
        except Exception as e:
            logger.error(f"Error in multiday_weakness_scan: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_sector_correlation_scan_wrapper(self):
        """Wrapper to run sector correlation scan — async for stable event loop."""
        try:
            await self._init_clients()
            await self.run_sector_correlation_scan()
        except Exception as e:
            logger.error(f"Error in sector_correlation_scan: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_daily_report_scan_wrapper(self):
        """Wrapper to run daily report scan (3 PM EST) — async for stable event loop."""
        try:
            await self._init_clients()
            await self.run_daily_report_scan()
        except Exception as e:
            logger.error(f"Error in daily_report_scan: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        # Auto-trigger Convergence Engine after daily report scan
        # Gamma Drain + Distribution + Liquidity scores just updated
        try:
            self._run_convergence_wrapper()
        except Exception as e:
            logger.warning(f"Post-DailyReport convergence trigger failed (non-fatal): {e}")
    
    def _run_pattern_scan_wrapper(self):
        """Wrapper to run pattern scan (pump-reversal, two-day rally, high vol run)."""
        try:
            import subprocess
            from pathlib import Path
            result = subprocess.run(
                ["python3", "integrate_patterns.py"],
                cwd=str(Path(__file__).parent.parent),
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode == 0:
                logger.info("Pattern scan completed successfully")
            else:
                logger.error(f"Pattern scan failed: {result.stderr}")
        except Exception as e:
            logger.error(f"Pattern scan error: {e}")
    
    async def _run_pump_dump_scan_wrapper(self):
        """Wrapper to run pump-dump reversal scan — async for stable event loop."""
        try:
            await self._init_clients()
            await self.run_pump_dump_scan()
        except Exception as e:
            logger.error(f"Error in pump_dump_scan: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_pre_earnings_flow_wrapper(self):
        """Wrapper to run pre-earnings flow scan — async for stable event loop."""
        try:
            await self._init_clients()
            await self.run_pre_earnings_flow_scan()
        except Exception as e:
            logger.error(f"Error in pre_earnings_flow_scan: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_volume_price_scan_wrapper(self):
        """Wrapper to run volume-price divergence scan — async for stable event loop."""
        try:
            await self._init_clients()
            await self.run_volume_price_scan()
        except Exception as e:
            logger.error(f"Error in volume_price_scan: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_intraday_scan_wrapper(self):
        """
        Wrapper to run REAL-TIME intraday big mover scan — async for stable event loop.
        
        FEB 2, 2026: Critical fix - uses quotes for live prices, not daily bars.
        This catches same-day drops that other scanners miss.
        """
        try:
            await self._init_clients()
            await self.run_intraday_scan()
        except Exception as e:
            logger.error(f"Error in intraday_scan: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_market_weather_am_wrapper(self):
        """
        Wrapper to run Market Weather AM FULL report (9:00 AM ET) — async for stable event loop.
        
        FULL run: Live UW API + Polygon + EWS → saves UW cache for refreshes.
        - 4 independent layers + gamma flip + flow quality + liquidity violence
        - Writes to logs/market_weather/latest_am.json
        - Same-day trading decisions
        """
        try:
            await self._init_clients()
            await self.run_market_weather_report("am", refresh=False)
        except Exception as e:
            logger.error(f"Error in market_weather_am: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_market_weather_pm_wrapper(self):
        """
        Wrapper to run Market Weather PM FULL report (3:00 PM ET) — async for stable event loop.
        
        FULL run: Live UW API + Polygon + EWS → saves UW cache for refreshes.
        - 4 independent layers + gamma flip + flow quality + liquidity violence
        - Writes to logs/market_weather/latest_pm.json
        - Next-day preparation (overnight storm build)
        """
        try:
            await self._init_clients()
            await self.run_market_weather_report("pm", refresh=False)
        except Exception as e:
            logger.error(f"Error in market_weather_pm: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_market_weather_refresh_wrapper(self):
        """
        Wrapper to run Market Weather REFRESH — async for stable event loop.
        
        v5.2: REFRESH mode — NO new UW API calls.
        - Reuses cached UW data (gamma flip + flow) from last full run
        - Fresh Polygon data (unlimited API) for latest prices + technicals
        - Fresh EWS data from latest scheduled EWS scans
        - Auto-detects AM/PM mode based on time of day
        """
        try:
            await self._init_clients()
            from datetime import datetime
            now_et = datetime.now(EST)
            mode = "pm" if now_et.hour >= 15 else "am"
            await self.run_market_weather_report(mode, refresh=True)
        except Exception as e:
            logger.error(f"Error in market_weather_refresh: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _run_convergence_wrapper(self):
        """
        Wrapper to run 🎯 Convergence Engine — Automated 4-Step Decision Hierarchy.
        
        Merges ALL 4 detection systems into unified Top 9 candidates:
          Step 1: EWS (35%)        — WHO is about to fall?
          Step 2: Direction (15%)  — Is the MARKET allowing puts?
          Step 3: Gamma Drain (25%)— Confirms with real-time scoring
          Step 4: Weather (25%)    — Cross-validates with storm_score
        
        Schedule: Every 30 min (8 AM – 4 PM ET)
        Also triggered automatically after each EWS scan completes.
        Output: logs/convergence/latest_top9.json
        
        SELF-HEALING:
        - If any source file missing/corrupt → uses available data, marks degraded
        - If engine crashes → writes status="degraded" with error message
        - Auto-recovers on next 30-min cycle
        """
        try:
            from putsengine.convergence_engine import run_convergence
            result = run_convergence()
            
            status = result.get("status", "unknown")
            top9_count = len(result.get("top9", []))
            sources = result.get("summary", {}).get("sources_available", 0)
            lights = result.get("summary", {}).get("permission_lights", {})
            
            logger.info(
                f"🎯 Convergence: status={status}, top9={top9_count}, "
                f"sources={sources}/4, "
                f"🟢{lights.get('green', 0)} 🟡{lights.get('yellow', 0)} 🔴{lights.get('red', 0)}"
            )
        except Exception as e:
            logger.error(f"Convergence Engine error: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_finviz_bearish_scan_wrapper(self):
        """
        Gap 5/6/7 Fix: Run FinViz bearish candidate scan — async for stable event loop.
        
        Scans for:
        - Insider selling (strongest individual bearish signal)
        - Analyst downgrades
        - Technical weakness (RSI < 30, below SMAs)
        - High short interest (>15% short float)
        - Sector performance (weakest sectors)
        
        Zero UW API calls. Uses FinViz Elite only.
        Output: logs/finviz_bearish.json, logs/finviz_short_interest.json
        """
        try:
            from putsengine.clients.finviz_client import FinvizClient
            from putsengine.config import Settings
            import json
            from pathlib import Path
            from datetime import datetime
            
            settings = Settings()
            client = FinvizClient(settings)
            
            try:
                # Get bearish candidates (insider selling + downgrades + technical)
                bearish = await client.get_bearish_candidates()
                
                # Get high short interest stocks
                short_interest_symbols = await client.screen_high_short_interest()
                
                # Get insider selling
                insider_selling = await client.screen_insider_selling()
                
                # Build combined results
                candidates = []
                all_symbols = set()
                
                for item in bearish:
                    sym = item.get("symbol", "")
                    if sym:
                        all_symbols.add(sym)
                        signals = item.get("signals", [])
                        if sym in insider_selling:
                            signals.append("insider_selling")
                        item["signals"] = signals
                        candidates.append(item)
                
                # Add insider selling stocks not already in bearish list
                for sym in insider_selling:
                    if sym not in all_symbols:
                        candidates.append({
                            "symbol": sym,
                            "signals": ["insider_selling"],
                            "score_boost": 0.04,
                        })
                
                # Save bearish candidates
                bearish_path = Path("logs/finviz_bearish.json")
                bearish_path.parent.mkdir(parents=True, exist_ok=True)
                with open(bearish_path, "w") as f:
                    json.dump({
                        "timestamp": datetime.now().isoformat(),
                        "candidates": candidates,
                        "count": len(candidates),
                    }, f, indent=2)
                
                # Save short interest data
                si_data = {}
                for sym in short_interest_symbols:
                    # Get quote to extract short float details
                    quote = await client.get_quote(sym)
                    if quote:
                        si_data[sym] = {
                            "short_float": quote.short_float,
                            "short_ratio": quote.short_ratio,
                            "relative_volume": quote.relative_volume,
                        }
                
                si_path = Path("logs/finviz_short_interest.json")
                with open(si_path, "w") as f:
                    json.dump({
                        "timestamp": datetime.now().isoformat(),
                        "data": si_data,
                        "count": len(si_data),
                    }, f, indent=2)
                
                logger.info(
                    f"🔵 FinViz Bearish Scan: {len(candidates)} bearish candidates, "
                    f"{len(si_data)} high short interest stocks"
                )
                
            finally:
                await client.close()
            
        except Exception as e:
            logger.error(f"FinViz bearish scan error: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_attribution_backfill_wrapper(self):
        """
        Wrapper to run Weather Attribution Backfill (5:30 PM ET) — async for stable event loop.
        
        Fills in T+1/T+2 actual outcomes for past weather forecasts.
        This is the "did it actually rain?" calibration loop.
        
        - Fetches actual close prices from Polygon
        - Computes T+1 return, T+2 return, max adverse excursion
        - Flags did_drop_5pct, did_drop_10pct
        - Generates calibration_summary.json
        """
        try:
            await self._run_attribution_backfill()
        except Exception as e:
            logger.error(f"Error in attribution_backfill: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_attribution_backfill(self):
        """Run the attribution backfill engine."""
        now_et = datetime.now(EST)
        
        # Guard: trading day check
        if now_et.weekday() >= 5:
            logger.info("Not a trading day (weekend). Skipping attribution backfill.")
            return
        
        try:
            from putsengine.weather_attribution_backfill import backfill_attribution
            result = await backfill_attribution()
            
            status = result.get("status", "unknown")
            files_updated = result.get("files_updated", 0)
            picks_backfilled = result.get("picks_backfilled", 0)
            
            logger.info(
                f"📊 Attribution Backfill complete: "
                f"status={status}, files={files_updated}, picks={picks_backfilled}"
            )
        except Exception as e:
            logger.error(f"Attribution Backfill error: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_convergence_backfill_wrapper(self):
        """
        Gap 9 Fix: Backfill T+1/T+2 actual prices — async for stable event loop.
        
        Runs daily at 5:45 PM ET (after attribution backfill at 5:30 PM).
        Fetches actual close prices via Polygon for past picks and computes
        whether predictions were correct (3%+ drop in 2 days).
        
        This builds the calibration data needed to compute:
        - "When convergence_score > 0.55, accuracy is X%"
        - "Trifecta picks hit 3%+ drop Y% of the time"
        """
        try:
            await self._run_convergence_backfill()
        except Exception as e:
            logger.error(f"Error in convergence_backfill: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _run_convergence_backfill(self):
        """Fill in T+1/T+2 actual prices in the convergence backtest ledger."""
        try:
            import json
            from pathlib import Path
            from datetime import timedelta
            
            ledger_path = Path("logs/convergence/backtest_ledger.json")
            if not ledger_path.exists():
                logger.info("No backtest ledger yet. Skipping backfill.")
                return
            
            with open(ledger_path) as f:
                ledger = json.load(f)
            
            if not ledger:
                return
            
            now_et = datetime.now(EST)
            updated_count = 0
            
            for entry in ledger:
                entry_date = entry.get("date", "")
                if not entry_date:
                    continue
                
                try:
                    entry_dt = datetime.strptime(entry_date, "%Y-%m-%d")
                except ValueError:
                    continue
                
                # Only backfill entries that are 1-3 days old (T+1 or T+2 available)
                days_ago = (now_et.date() - entry_dt.date()).days
                if days_ago < 1 or days_ago > 5:
                    continue
                
                for pick in entry.get("picks", []):
                    if pick.get("drop_t2") is not None:
                        continue  # Already backfilled
                    
                    symbol = pick.get("symbol", "")
                    entry_price = pick.get("current_price", 0)
                    if not symbol or entry_price <= 0:
                        continue
                    
                    try:
                        # Get daily bars for T+1 and T+2
                        t1_date = entry_dt + timedelta(days=1)
                        t2_date = entry_dt + timedelta(days=2)
                        # Skip weekends
                        while t1_date.weekday() >= 5:
                            t1_date += timedelta(days=1)
                        while t2_date.weekday() >= 5:
                            t2_date += timedelta(days=1)
                        
                        bars = await self._polygon.get_daily_bars(
                            symbol,
                            from_date=t1_date.strftime("%Y-%m-%d"),
                            to_date=t2_date.strftime("%Y-%m-%d")
                        )
                        
                        if bars and len(bars) >= 1:
                            t1_close = bars[0].get("close", bars[0].get("c", 0))
                            pick["price_t1"] = round(t1_close, 2)
                            pick["drop_t1"] = round((t1_close / entry_price - 1) * 100, 2)
                        
                        if bars and len(bars) >= 2:
                            t2_close = bars[1].get("close", bars[1].get("c", 0))
                            pick["price_t2"] = round(t2_close, 2)
                            pick["drop_t2"] = round((t2_close / entry_price - 1) * 100, 2)
                            
                            # Compute hit metrics
                            min_price = min(b.get("low", b.get("l", entry_price)) for b in bars[:2])
                            max_drop = (min_price / entry_price - 1) * 100
                            pick["max_drop"] = round(max_drop, 2)
                            pick["hit_3pct"] = max_drop <= -3.0
                            pick["hit_5pct"] = max_drop <= -5.0
                        
                        updated_count += 1
                        
                    except Exception as e:
                        logger.debug(f"Backfill failed for {symbol}: {e}")
                        continue
            
            # Save updated ledger
            with open(ledger_path, "w") as f:
                json.dump(ledger, f, indent=2, default=str)
            
            # Generate summary
            all_picks = [p for e in ledger for p in e.get("picks", []) if p.get("drop_t2") is not None]
            if all_picks:
                total = len(all_picks)
                hit_3 = sum(1 for p in all_picks if p.get("hit_3pct"))
                hit_5 = sum(1 for p in all_picks if p.get("hit_5pct"))
                logger.info(
                    f"📊 Convergence Backfill: {updated_count} picks updated, "
                    f"Total calibrated: {total}, "
                    f"Hit 3%: {hit_3}/{total} ({hit_3/total*100:.0f}%), "
                    f"Hit 5%: {hit_5}/{total} ({hit_5/total*100:.0f}%)"
                )
            else:
                logger.info(f"📊 Convergence Backfill: {updated_count} picks updated (no T+2 data yet)")
                
        except Exception as e:
            logger.error(f"Convergence backfill error: {e}")
    
    async def run_market_weather_report(self, mode: str = "am", refresh: bool = False):
        """
        Run Market Weather Report (v5.2 + 30-min refresh support).
        
        refresh=False: FULL run — live UW API + Polygon + EWS
        refresh=True:  REFRESH — cached UW + fresh Polygon + fresh EWS (no UW API waste)
        
        Non-negotiable guards:
        - If not a trading day (weekend + holidays) → exit
        - If data is stale / APIs fail → write status="degraded"
        - Health-check log line with data freshness summary
        """
        now_et = datetime.now(EST)
        mode_label = "AM — Open Risk Forecast" if mode == "am" else "PM — Overnight Storm Build"
        run_type = "REFRESH (cached UW + fresh Polygon)" if refresh else "FULL (live UW + Polygon)"
        
        logger.info("=" * 70)
        logger.info(f"🌪️ MARKET WEATHER ENGINE v5.2 — {mode_label}")
        logger.info(f"Run Type: {run_type}")
        logger.info(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info(f"Timezone: America/New_York (DST-aware)")
        logger.info(f"Python: {sys.executable}")
        logger.info("=" * 70)
        
        # Guard: trading day check (weekends + US market holidays)
        if not is_trading_day(now_et.date()):
            logger.info("Not a trading day (weekend or holiday). Skipping weather report.")
            return None
        
        try:
            await self._init_clients()
            
            from putsengine.predictive_engine import MarketWeatherEngine, ReportMode
            
            report_mode = ReportMode.PM if mode == "pm" else ReportMode.AM
            engine = MarketWeatherEngine(
                polygon_client=self._polygon,
                uw_client=self._uw if not refresh else None,  # No UW client on refresh
                settings=self.settings
            )
            result = await engine.run(report_mode, refresh=refresh)
            
            # Health-check log line
            summary = result.get('summary', {})
            n_picks = len(result.get('forecasts', []))
            freshness = result.get('data_freshness', {})
            logger.info(f"✅ Weather v5.2 [{mode.upper()}] [{run_type}] HEALTH CHECK:")
            logger.info(f"  Report generated: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
            logger.info(f"  Picks: {n_picks} | Status: {result.get('status', 'unknown')}")
            logger.info(f"  🌪️ Warnings: {summary.get('storm_warnings', 0)} | "
                        f"⛈️ Watches: {summary.get('storm_watches', 0)} | "
                        f"🌧️ Advisories: {summary.get('advisories', 0)} | "
                        f"☁️ Monitoring: {summary.get('monitoring', 0)}")
            logger.info(f"  Data freshness: EWS={freshness.get('ews', 'N/A')} | "
                        f"Polygon={freshness.get('polygon', 'N/A')} | "
                        f"UW={freshness.get('uw', 'N/A')} | "
                        f"Regime={freshness.get('regime', 'N/A')}")
            
            # Log top 3 forecasts with permission lights
            for i, fc in enumerate(result.get('forecasts', [])[:3], 1):
                perm = fc.get('permission_light', '⚪')
                logger.info(
                    f"  #{i} {perm} {fc['forecast']}: {fc['symbol']} | "
                    f"Storm: {fc['storm_score']:.2f} | Layers: {fc['layers_active']}/4 | "
                    f"Conf: {fc.get('confidence', 'LOW')}"
                )
            
            logger.info("=" * 70)
            return result
            
        except Exception as e:
            logger.error(f"Market Weather v5.2 [{mode.upper()}] [{run_type}] error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            # Write degraded status so dashboard knows pipes are broken
            from pathlib import Path
            degraded = {
                "timestamp": now_et.isoformat(),
                "generated_at_utc": datetime.utcnow().isoformat(),
                "engine_version": "v5.2_weather",
                "report_mode": mode,
                "status": "degraded",
                "error": str(e),
                "forecasts": [],
                "summary": {},
                "data_freshness": {"run_type": "REFRESH" if refresh else "FULL"}
            }
            weather_dir = Path("logs/market_weather")
            weather_dir.mkdir(parents=True, exist_ok=True)
            with open(weather_dir / f"latest_{mode}.json", 'w') as f:
                json.dump(degraded, f, indent=2)
            
            return None
    
    async def _run_early_warning_scan_wrapper(self):
        """
        Wrapper to run early warning institutional footprint scan — async for stable event loop.
        
        This is the KEY scan for 1-3 day early detection.
        Schedule (FEB 10 OPTIMIZED):
            8 AM, 9:45 AM, 11 AM, 1 PM, 2 PM, 4:30 PM, 10 PM ET
            (12 PM REMOVED — uses 11 AM cache, saves 1,800 UW calls)
            (3:02 PM REMOVED — 2:45 PM market_pulse covers this window)
        
        FEB 10 FIX: force_scan_mode is ONLY enabled for PM window (after 2 PM ET).
        Before 2 PM, EWS respects the budget ceiling so that 4,000 calls are
        reserved for the 2:45 PM market_pulse scan.
        After 2 PM, force_scan_mode is enabled so the 2 PM EWS can use
        the remaining budget freely alongside the market_pulse scan.
        
        FEB 9 FIX: Now async — runs on APScheduler's event loop directly.
        """
        await self._init_clients()
        
        # Only enable force_scan for PM EWS scans (after 2 PM ET)
        # Before 2 PM, respect the afternoon budget reservation
        import pytz as _pytz
        _now_et = datetime.now(_pytz.timezone('US/Eastern')).time()
        _is_pm = _now_et >= datetime.strptime("14:00", "%H:%M").time()
        if _is_pm and hasattr(self, '_uw') and self._uw is not None:
            self._uw.set_force_scan_mode(True)
            logger.info("EWS: Force scan mode ENABLED (PM window — budget released)")
        
        try:
            await self.run_early_warning_scan()
        except Exception as e:
            logger.error(f"Error in early_warning_scan: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            # Always disable force_scan mode after EWS scan
            if hasattr(self, '_uw') and self._uw is not None:
                self._uw.set_force_scan_mode(False)
            
            # Auto-trigger Convergence Engine after each EWS scan
            # EWS is the PRIMARY predictive signal — whenever it updates,
            # the Top 9 scoreboard should re-merge all 4 systems immediately.
            try:
                self._run_convergence_wrapper()
            except Exception as e:
                logger.warning(f"Post-EWS convergence trigger failed (non-fatal): {e}")
    
    async def _run_zero_hour_scan_wrapper(self):
        """
        Wrapper to run zero-hour gap scanner — async for stable event loop.
        
        ARCHITECT-4 VALIDATED: Highest ROI remaining addition.
        Runs at 9:15 AM ET to confirm Day 0 execution of Day -1 pressure.
        """
        try:
            await self._init_clients()
            await self.run_zero_hour_scan()
        except Exception as e:
            logger.error(f"Error in zero_hour_scan: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def run_scan(self, scan_type: str = "manual"):
        """
        Run a full scan of ALL tickers across all 3 engines.
        
        BATCHED SCANNING STRATEGY:
        - Split all tickers into 3 batches of ~100
        - Process each batch with 0.6s interval (100 req/min)
        - Wait 65 seconds between batches (rate limit reset)
        - Result: ALL tickers scanned, ZERO misses
        
        Args:
            scan_type: Type of scan (pre_market_1, market_open, regular, etc.)
        """
        now_et = datetime.now(EST)
        logger.info(f"=" * 60)
        logger.info(f"SCHEDULED SCAN: {scan_type.upper()}")
        logger.info(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info(f"=" * 60)
        
        try:
            await self._init_clients()
            
            # Get ALL tickers (universe + dynamic)
            all_tickers = EngineConfig.get_all_tickers()
            
            # Load DUI (Dynamic Universe Injection) tickers
            dui_tickers = self._load_dui_tickers()
            
            # Merge universe with DUI tickers (no duplicates)
            combined_tickers = list(set(all_tickers) | set(dui_tickers))
            total_tickers = len(combined_tickers)
            
            logger.info(f"Scanning {total_tickers} tickers (Universe: {len(all_tickers)}, DUI: {len(dui_tickers)})...")
            
            # BATCH CONFIGURATION
            BATCH_SIZE = 100  # Tickers per batch
            BATCH_WAIT = 65   # Seconds between batches (rate limit reset)
            
            # Split tickers into batches
            batches = [combined_tickers[i:i + BATCH_SIZE] for i in range(0, total_tickers, BATCH_SIZE)]
            num_batches = len(batches)
            
            logger.info(f"Split into {num_batches} batches of ~{BATCH_SIZE} tickers")
            
            # Results by engine
            gamma_drain_candidates = []
            distribution_candidates = []
            liquidity_candidates = []
            
            # Get market regime first (force API calls during scheduled scans)
            market_regime = await self._market_regime_layer.analyze(force_api_call=True)
            logger.info(f"Market Regime: {market_regime.regime.value}")
            # Gap 2 Fix: Log scan_allowed separately from tradeable
            scan_allowed = getattr(market_regime, 'is_scan_allowed', True)
            logger.info(f"Tradeable: {market_regime.is_tradeable} | Scan Allowed: {scan_allowed}")
            
            # Calculate expiry dates
            today = date.today()
            first_friday = get_next_friday(today)
            second_friday = get_next_friday(today, offset_weeks=1)
            
            # Process each batch
            total_processed = 0
            total_errors = 0
            
            for batch_num, batch in enumerate(batches, 1):
                batch_start = datetime.now(EST)
                logger.info(f"--- BATCH {batch_num}/{num_batches} ({len(batch)} tickers) ---")
                
                # Scan each ticker in batch
                for symbol in batch:
                    try:
                        # Run distribution analysis
                        distribution = await self._distribution_layer.analyze(symbol)
                        
                        # ARCHITECT-4: Show ALL Class B+ candidates (0.20+)
                        # Lowered threshold to catch more candidates
                        if distribution.score < self.settings.class_b_min_score:
                            total_processed += 1
                            continue
                        
                        # Get current price
                        try:
                            bars = await self._polygon.get_daily_bars(
                                symbol=symbol,
                                from_date=date.today() - timedelta(days=5)
                            )
                            current_price = bars[-1].close if bars else 0.0
                        except:
                            current_price = 0.0
                        
                        # Determine engine type based on signals
                        engine_type = self._determine_engine_type(distribution)
                        
                        # Determine expiry based on score
                        expiry_date = first_friday if distribution.score >= 0.45 else second_friday
                        dte = (expiry_date - today).days
                        
                        # Check if this is a DUI ticker
                        is_dui = symbol in dui_tickers
                        
                        # ======================================================================
                        # FEB 1, 2026 FIX: Add signal priority classification
                        # PRE-breakdown signals = predictive (early entry)
                        # POST-breakdown signals = reactive (late entry)
                        # ======================================================================
                        try:
                            from putsengine.signal_priority import (
                                classify_signals,
                                get_signal_priority_summary,
                                is_predictive_signal_dominant
                            )
                            priority_summary = get_signal_priority_summary(distribution.signals)
                            pre_signals = priority_summary.get("pre_signals", [])
                            post_signals = priority_summary.get("post_signals", [])
                            timing_rec = priority_summary.get("timing_recommendation", "BALANCED")
                            is_predictive = is_predictive_signal_dominant(distribution.signals)
                        except Exception as e:
                            pre_signals = []
                            post_signals = []
                            timing_rec = "UNKNOWN"
                            is_predictive = False
                        
                        # Create candidate data
                        candidate_data = {
                            "symbol": symbol,
                            "score": round(distribution.score, 4),
                            "tier": get_signal_tier(distribution.score),
                            "engine_type": engine_type.value,
                            "current_price": current_price,
                            "expiry": expiry_date.strftime("%b %d"),
                            "dte": dte,
                            "signals": [k for k, v in distribution.signals.items() if v],
                            "signal_count": sum(1 for v in distribution.signals.values() if v),
                            "scan_time": now_et.strftime("%H:%M ET"),
                            "scan_type": scan_type,
                            "is_dui": is_dui,
                            "batch": batch_num,
                            # NEW: Signal priority data (Feb 1, 2026)
                            "pre_signals": pre_signals,
                            "post_signals": post_signals,
                            "timing_recommendation": timing_rec,
                            "is_predictive": is_predictive,
                        }
                        
                        # Add to appropriate engine list
                        if engine_type == EngineType.GAMMA_DRAIN:
                            gamma_drain_candidates.append(candidate_data)
                        elif engine_type == EngineType.DISTRIBUTION_TRAP:
                            distribution_candidates.append(candidate_data)
                        else:
                            liquidity_candidates.append(candidate_data)
                        
                        total_processed += 1
                        
                    except Exception as e:
                        logger.debug(f"Error scanning {symbol}: {e}")
                        total_errors += 1
                        total_processed += 1
                
                # Batch completion log
                batch_elapsed = (datetime.now(EST) - batch_start).total_seconds()
                candidates_this_batch = sum([
                    len([c for c in gamma_drain_candidates if c.get("batch") == batch_num]),
                    len([c for c in distribution_candidates if c.get("batch") == batch_num]),
                    len([c for c in liquidity_candidates if c.get("batch") == batch_num])
                ])
                logger.info(f"Batch {batch_num} complete: {len(batch)} tickers in {batch_elapsed:.1f}s, {candidates_this_batch} candidates")
                
                # Wait between batches (except after last batch)
                if batch_num < num_batches:
                    logger.info(f"⏳ Waiting {BATCH_WAIT}s for rate limit reset before batch {batch_num + 1}...")
                    await asyncio.sleep(BATCH_WAIT)
            
            # Sort by score
            gamma_drain_candidates.sort(key=lambda x: x["score"], reverse=True)
            distribution_candidates.sort(key=lambda x: x["score"], reverse=True)
            liquidity_candidates.sort(key=lambda x: x["score"], reverse=True)
            
            # Update latest results
            self.latest_results = {
                "gamma_drain": gamma_drain_candidates,
                "distribution": distribution_candidates,
                "liquidity": liquidity_candidates,
                "last_scan": now_et.isoformat(),
                "scan_type": scan_type,
                "market_regime": market_regime.regime.value,
                "tickers_scanned": total_tickers,
                "batches": num_batches,
                "errors": total_errors,
                "total_candidates": len(gamma_drain_candidates) + len(distribution_candidates) + len(liquidity_candidates)
            }
            
            # Save results to file
            self._save_results()
            
            # Update scan history
            try:
                from putsengine.scan_history import ScanHistoryManager
                history_manager = ScanHistoryManager()
                history_manager.add_scan_to_history(self.latest_results)
            except Exception as e:
                logger.debug(f"Could not update scan history: {e}")
            
            # Log summary
            logger.info(f"=" * 60)
            logger.info(f"SCAN COMPLETE: {scan_type.upper()}")
            logger.info(f"Total tickers scanned: {total_tickers} in {num_batches} batches")
            logger.info(f"Processed: {total_processed}, Errors: {total_errors}")
            logger.info(f"Gamma Drain candidates: {len(gamma_drain_candidates)}")
            logger.info(f"Distribution candidates: {len(distribution_candidates)}")
            logger.info(f"Liquidity candidates: {len(liquidity_candidates)}")
            logger.info(f"0 TICKERS MISSED (batched scanning)")
            
            # Log top candidates
            if gamma_drain_candidates:
                top = gamma_drain_candidates[0]
                logger.info(f"Top Gamma Drain: {top['symbol']} ({top['score']:.2f})")
            if distribution_candidates:
                top = distribution_candidates[0]
                logger.info(f"Top Distribution: {top['symbol']} ({top['score']:.2f})")
            if liquidity_candidates:
                top = liquidity_candidates[0]
                logger.info(f"Top Liquidity: {top['symbol']} ({top['score']:.2f})")
            
            logger.info(f"=" * 60)
            
        except Exception as e:
            logger.error(f"Scan error: {e}")
            raise
        finally:
            # MEMORY LEAK FIX: Force garbage collection after each scan
            # This prevents memory buildup over long-running daemon sessions
            import gc
            gc.collect()
            logger.debug("Post-scan garbage collection completed")
    
    async def cleanup_resources(self):
        """
        MEMORY LEAK FIX: Cleanup all resources to prevent memory buildup.
        
        This should be called periodically (e.g., after every 10 scans) to
        reset API client sessions and clear caches.
        """
        import gc
        
        logger.info("Running resource cleanup...")
        
        # Close and recreate API clients to reset sessions
        try:
            await self.close_clients()
            
            # Clear any caches
            if hasattr(self, '_market_regime_layer') and self._market_regime_layer:
                # Clear regime cache
                if hasattr(self._market_regime_layer, '_cache'):
                    self._market_regime_layer._cache = {}
            
            # Force garbage collection
            gc.collect()
            
            # Reinitialize clients
            await self._init_clients()
            
            logger.info("Resource cleanup completed successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    def _load_dui_tickers(self) -> List[str]:
        """Load Dynamic Universe Injection tickers from JSON file."""
        dui_file = Path("dynamic_universe.json")
        if not dui_file.exists():
            return []
        
        try:
            with open(dui_file, "r") as f:
                dui_data = json.load(f)
            
            # Extract active tickers (not expired)
            now = datetime.now(EST)
            active_tickers = []
            
            for ticker, info in dui_data.items():
                if isinstance(info, dict):
                    # Check TTL if present
                    expires = info.get("expires")
                    if expires:
                        try:
                            exp_date = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                            if exp_date > now:
                                active_tickers.append(ticker)
                        except:
                            active_tickers.append(ticker)
                    else:
                        active_tickers.append(ticker)
                else:
                    active_tickers.append(ticker)
            
            logger.info(f"Loaded {len(active_tickers)} DUI tickers")
            return active_tickers
            
        except Exception as e:
            logger.debug(f"Could not load DUI tickers: {e}")
            return []
    
    def _determine_engine_type(self, distribution) -> EngineType:
        """
        Determine which engine type based on signals.
        
        FEB 10, 2026 FIX: GAMMA SIGNALS FIRST
        ======================================
        CRITICAL BUG: dark_pool_violence fires for ~95% of candidates and is
        classified as PRE_BREAKDOWN. The old logic checked is_predictive_signal_dominant()
        FIRST, which routed nearly everything to Distribution before the Gamma Drain
        check was reached. Result: 0 Gamma Drain candidates despite 53+ tickers having
        call_selling_at_bid and 15+ having put_buying_at_ask.
        
        FIX: Check gamma signals FIRST. Options flow signals (call selling,
        put buying, skew steepening, rising put OI) are the highest-conviction
        dealer execution signals. If a ticker has these, it belongs in Gamma Drain
        regardless of whether dark_pool_violence also fires.
        
        Decision hierarchy (institutional microstructure correct):
        1. GAMMA DRAIN: 2+ options flow signals = dealer forced execution
        2. GAMMA DRAIN: 1 flow signal + high score (>= 0.70) = strong flow conviction
        3. LIQUIDITY: VWAP loss + multi-day weakness = buyer disappearance
        4. DISTRIBUTION: Everything else (supply absorption / early warning)
        """
        signals = distribution.signals
        score = distribution.score
        
        # ======================================================================
        # STEP 1: COUNT GAMMA SIGNALS (OPTIONS FLOW = HIGHEST PRIORITY)
        # These indicate forced dealer execution — most actionable signals.
        # Must be checked BEFORE predictive classification because gamma signals
        # ARE predictive (PRE_BREAKDOWN) but need separate engine treatment.
        # ======================================================================
        gamma_signals = sum([
            signals.get("call_selling_at_bid", False),
            signals.get("put_buying_at_ask", False),
            signals.get("rising_put_oi", False),
            signals.get("skew_steepening", False),
            signals.get("volume_price_divergence", False),
            signals.get("skew_reversal", False),  # Skew reversal = gamma-relevant
        ])
        
        # 2+ gamma signals = pure dealer execution → Gamma Drain
        if gamma_signals >= 2 and score >= 0.45:
            active_gamma = [s for s in ["call_selling_at_bid", "put_buying_at_ask", 
                           "rising_put_oi", "skew_steepening", "volume_price_divergence",
                           "skew_reversal"] if signals.get(s, False)]
            logger.info(f"Engine assignment: GAMMA_DRAIN (2+ gamma signals: {', '.join(active_gamma)}, score={score:.3f})")
            return EngineType.GAMMA_DRAIN
        
        # 1 gamma signal + high score = strong flow conviction → Gamma Drain
        if gamma_signals >= 1 and score >= 0.70:
            active_gamma = [s for s in ["call_selling_at_bid", "put_buying_at_ask", 
                           "rising_put_oi", "skew_steepening", "volume_price_divergence",
                           "skew_reversal"] if signals.get(s, False)]
            logger.info(f"Engine assignment: GAMMA_DRAIN (1 gamma + high score: {', '.join(active_gamma)}, score={score:.3f})")
            return EngineType.GAMMA_DRAIN
        
        # ======================================================================
        # STEP 2: LIQUIDITY VACUUM DETECTION
        # VWAP loss + multi-day weakness = buyers disappearing
        # ======================================================================
        has_vwap_loss = signals.get("vwap_loss", False) or signals.get("below_vwap", False)
        has_weakness = signals.get("multi_day_weakness", False)
        has_sell_blocks = signals.get("repeated_sell_blocks", False)
        
        liq_signals = sum([has_sell_blocks, has_vwap_loss, has_weakness, 
                          signals.get("below_vwap", False)])
        
        if has_vwap_loss and has_weakness:
            logger.debug("Engine assignment: LIQUIDITY (VWAP loss + multi-day weakness)")
            return EngineType.SNAPBACK
        
        if liq_signals >= 3:
            logger.debug("Engine assignment: LIQUIDITY (3+ liquidity signals)")
            return EngineType.SNAPBACK
        
        # ======================================================================
        # STEP 3: EVERYTHING ELSE → DISTRIBUTION (early warning / supply detection)
        # This includes: pump_reversal, event-driven, dark_pool_violence,
        # exhaustion, topping_tail, etc.
        # ======================================================================
        logger.debug(f"Engine assignment: DISTRIBUTION (default: gamma={gamma_signals}, liq={liq_signals}, score={score:.3f})")
        return EngineType.DISTRIBUTION_TRAP
    
    def _save_results(self):
        """Save scan results to JSON file and history."""
        try:
            with open(RESULTS_FILE, 'w') as f:
                json.dump(self.latest_results, f, indent=2, default=str)
            logger.info(f"Results saved to {RESULTS_FILE}")
            
            # Also save to 48-hour history for frequency analysis
            from putsengine.scan_history import add_scan_to_history
            add_scan_to_history(self.latest_results)
            
        except Exception as e:
            logger.error(f"Error saving results: {e}")
    
    def load_results(self) -> Dict[str, Any]:
        """Load latest results from file."""
        try:
            if RESULTS_FILE.exists():
                with open(RESULTS_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading results: {e}")
        return self.latest_results
    
    # ==========================================================================
    # NEW SCANNER METHODS: After-Hours, Earnings, Pre-Catalyst
    # These would have caught MP, USAR, LAC, JOBY moves
    # ==========================================================================
    
    async def run_afterhours_scan(self):
        """
        Run after-hours scan to detect moves happening after 4 PM ET.
        
        This would have caught:
        - MP: -10.68% AH
        - USAR: -13.31% AH
        - LAC: -8.74% AH
        - JOBY: -11.48% AH
        """
        now_et = datetime.now(EST)
        logger.info("=" * 60)
        logger.info("AFTER-HOURS SCAN")
        logger.info(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info("=" * 60)
        
        try:
            await self._init_clients()
            
            # Get universe
            universe = set(EngineConfig.get_all_tickers())
            
            # Run after-hours scan (using Polygon/Massive for real-time data)
            results = await run_afterhours_scan(self._polygon, universe)
            
            # Log results
            summary = results.get("summary", {})
            logger.info(f"After-Hours Scan Complete:")
            logger.info(f"  Critical alerts (>5% down): {summary.get('critical_count', 0)}")
            logger.info(f"  High alerts (>3% down): {summary.get('high_count', 0)}")
            logger.info(f"  Watching alerts (>2% down): {summary.get('watching_count', 0)}")
            logger.info(f"  Injected to DUI: {summary.get('injected_to_dui', 0)}")
            
            # Log critical alerts
            for alert in results.get("critical", []):
                logger.warning(
                    f"  🔴 CRITICAL: {alert.symbol} {alert.ah_change_pct:+.2f}% | "
                    f"Close: ${alert.close_price:.2f} -> AH: ${alert.ah_price:.2f}"
                )
            
            logger.info("=" * 60)
            
            return results
            
        except Exception as e:
            logger.error(f"After-hours scan error: {e}")
            return {}
    
    async def run_earnings_check(self):
        """
        Run earnings calendar check to flag tickers reporting today.
        
        Identifies:
        - BMO (Before Market Open) - gap risk at open
        - AMC (After Market Close) - AH scan priority
        """
        now_et = datetime.now(EST)
        logger.info("=" * 60)
        logger.info("EARNINGS CALENDAR CHECK")
        logger.info(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info("=" * 60)
        
        try:
            await self._init_clients()
            
            # Get universe
            universe = set(EngineConfig.get_all_tickers())
            
            # Run earnings check
            results = await run_earnings_check(self._uw, universe)
            
            # Log results
            logger.info(f"Earnings Calendar Check Complete:")
            logger.info(f"  BMO tickers: {results.get('bmo_count', 0)}")
            logger.info(f"  AMC tickers: {results.get('amc_count', 0)}")
            
            if results.get("bmo_tickers"):
                logger.info(f"  BMO: {', '.join(results['bmo_tickers'])}")
            if results.get("amc_tickers"):
                logger.warning(f"  AMC (watch for AH moves): {', '.join(results['amc_tickers'])}")
            
            logger.info("=" * 60)
            
            return results
            
        except Exception as e:
            logger.error(f"Earnings check error: {e}")
            return {}
    
    async def run_precatalyst_scan(self):
        """
        Run pre-catalyst scan to detect smart money positioning.
        
        Detects 24-72 hours BEFORE moves:
        - Dark pool selling surge
        - Put OI accumulation
        - Call selling at bid (hedging)
        - IV term structure inversion
        - Price-volume divergence (distribution)
        
        This would have caught UNH the day before the 20% drop.
        """
        now_et = datetime.now(EST)
        logger.info("=" * 60)
        logger.info("PRE-CATALYST DISTRIBUTION SCAN")
        logger.info(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info("Detecting smart money positioning 24-72 hours before moves...")
        logger.info("=" * 60)
        
        try:
            await self._init_clients()
            
            # Run pre-catalyst scan (using Polygon/Massive for price data)
            results = await run_precatalyst_scan(self._uw, self._polygon)
            
            # Log results
            summary = results.get("summary", {})
            logger.info(f"Pre-Catalyst Scan Complete:")
            logger.info(f"  Critical alerts (4+ signals): {summary.get('critical_count', 0)}")
            logger.info(f"  High alerts (3 signals): {summary.get('high_count', 0)}")
            logger.info(f"  Medium alerts (2 signals): {summary.get('medium_count', 0)}")
            logger.info(f"  Injected to DUI: {summary.get('injected_to_dui', 0)}")
            
            # Log critical alerts
            for alert in results.get("critical", []):
                logger.warning(
                    f"  🔴 CRITICAL PRE-CATALYST: {alert.symbol} | "
                    f"Score: {alert.score:.2f} | Signals: {alert.signal_count}"
                )
            
            # Log high alerts
            for alert in results.get("high", []):
                logger.info(
                    f"  🟡 HIGH PRE-CATALYST: {alert.symbol} | "
                    f"Score: {alert.score:.2f} | Signals: {alert.signal_count}"
                )
            
            logger.info("=" * 60)
            
            return results
            
        except Exception as e:
            logger.error(f"Pre-catalyst scan error: {e}")
            return {}
    
    async def run_earnings_priority_scan(self):
        """
        Run earnings priority scan - FEB 3, 2026 FIX.
        
        14/15 Feb 3 crashes were earnings-related!
        This scanner prioritizes stocks with upcoming earnings:
        - Put OI accumulation (quiet building)
        - IV term structure inversion
        - Dark pool selling surge
        - Call selling at bid (hedge unwinding)
        - Unusual put sweeps
        - Negative GEX
        
        Runs 3x daily: 7:00 AM, 12:00 PM, 4:30 PM ET
        """
        now_et = datetime.now(EST)
        logger.info("=" * 60)
        logger.info("🎯 EARNINGS PRIORITY SCAN (FEB 3 FIX)")
        logger.info(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info("Scanning stocks with upcoming earnings for distribution signals...")
        logger.info("=" * 60)
        
        try:
            await self._init_clients()
            
            # Run earnings priority scan
            results = await run_earnings_priority_scan(self._uw, self._polygon)
            
            # Log results
            summary = results.get("summary", {})
            logger.info(f"Earnings Priority Scan Complete:")
            logger.info(f"  Total alerts: {summary.get('total_alerts', 0)}")
            logger.info(f"  Injected to DUI: {summary.get('injected_to_dui', 0)}")
            
            # Log today's alerts (D-0)
            for alert in results.get("today", []):
                logger.warning(
                    f"  🚨 EARNINGS TODAY: {alert.symbol} | "
                    f"Score: {alert.score:.2f} | Signals: {', '.join(alert.signals_detected)}"
                )
            
            # Log tomorrow's alerts (D-1)
            for alert in results.get("tomorrow", []):
                logger.info(
                    f"  ⚠️ EARNINGS TOMORROW: {alert.symbol} | "
                    f"Score: {alert.score:.2f} | Signals: {', '.join(alert.signals_detected)}"
                )
            
            logger.info("=" * 60)
            
            return results
            
        except Exception as e:
            logger.error(f"Earnings priority scan error: {e}")
            return {}
    
    # ==========================================================================
    # MARKET DIRECTION ENGINE (Feb 4, 2026)
    # ==========================================================================
    
    async def run_market_direction_analysis(self):
        """
        Run Market Direction Analysis.
        
        Uses GEX, VIX, dark pool, and options flow to predict market direction.
        Outputs 8 best plays based on direction.
        
        Schedule: 8:00 AM, 9:00 AM ET (pre-market)
                  10:00 AM, 11:00 AM, 12:00 PM, 1:00 PM, 2:00 PM, 3:00 PM ET (intraday refresh)
        (Intraday refresh added Feb 6, 2026 — was stuck at 8 AM with no updates)
        """
        now_et = datetime.now(EST)
        logger.info("=" * 60)
        logger.info("🌊 MARKETPULSE PRE-MARKET REGIME ANALYSIS")
        logger.info(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info("Regime awareness, not prediction. Edge: 52-58%")
        logger.info("=" * 60)
        
        try:
            # Import and run the analysis from market_pulse_engine
            # FEB 8, 2026: Pass shared clients to leverage UW response cache.
            # Previously created SEPARATE UW/Polygon clients per run, bypassing
            # the 30-min response cache. Now shares self._uw so cache hits are
            # guaranteed when Market Direction runs alongside EWS or other scans.
            await self._init_clients()
            from putsengine.market_pulse_engine import MarketPulseEngine
            engine = MarketPulseEngine(
                polygon_client=self._polygon,
                uw_client=self._uw
            )
            result = await engine.analyze()
            await engine.close()  # Safe: won't close shared clients (_owns_clients=False)
            
            # Log results
            logger.info(f"Regime: {result.regime.value}")
            logger.info(f"Score: {result.regime_score:.2f}")
            logger.info(f"Confidence: {result.confidence_pct:.0f}% ({result.confidence.value})")
            logger.info(f"Tradeability: {result.tradeability.value}")
            
            # Log component scores
            logger.info("-" * 40)
            logger.info("COMPONENT SCORES:")
            logger.info(f"  Futures (30%):   {result.futures_score:.2f}")
            logger.info(f"  VIX (25%):       {result.vix_score:.2f}")
            logger.info(f"  Gamma (20%):     {result.gamma_score:.2f}")
            logger.info(f"  Breadth (15%):   {result.breadth_score:.2f}")
            logger.info(f"  Sentiment (10%): {result.sentiment_score:.2f}")
            
            # Log notes
            logger.info("-" * 40)
            logger.info("KEY OBSERVATIONS:")
            for note in result.notes:
                logger.info(f"  {note}")
            
            # Log conditional picks if any
            if result.conditional_picks:
                logger.info("-" * 40)
                logger.info("CONDITIONAL PUT CANDIDATES:")
                for i, pick in enumerate(result.conditional_picks, 1):
                    logger.info(f"  {i}. {pick['symbol']:6} | {pick['reason']}")
            
            logger.info("=" * 60)
            
            # Save to file for dashboard
            import json
            from pathlib import Path
            output_file = Path("logs/market_direction.json")
            output_file.parent.mkdir(exist_ok=True)
            with open(output_file, "w") as f:
                json.dump({
                    "timestamp": result.timestamp.isoformat(),
                    "regime": result.regime.value,
                    "regime_score": result.regime_score,
                    "confidence": result.confidence.value,
                    "confidence_pct": result.confidence_pct,
                    "tradeability": result.tradeability.value,
                    "futures_score": result.futures_score,
                    "vix_score": result.vix_score,
                    "gamma_score": result.gamma_score,
                    "breadth_score": result.breadth_score,
                    "sentiment_score": result.sentiment_score,
                    "notes": result.notes,
                    "conditional_picks": result.conditional_picks,
                    "raw_data": result.raw_data,
                    # Legacy compatibility fields
                    "direction": result.regime.value,
                    "spy_signal": result.raw_data.get("futures", {}).get("spy_change", 0),
                    "qqq_signal": result.raw_data.get("futures", {}).get("qqq_change", 0),
                    "vix_signal": result.raw_data.get("vix", {}).get("vix_level", 20),
                    "gex_regime": result.raw_data.get("gamma", {}).get("gamma_regime", "NEUTRAL"),
                    "gex_value": result.raw_data.get("gamma", {}).get("gex_value", 0),
                    "best_plays": result.conditional_picks,
                    "avoid_plays": []
                }, f, indent=2, default=str)
            
            logger.info(f"MarketPulse results saved to {output_file}")
            return result
            
        except Exception as e:
            logger.error(f"MarketPulse analysis error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    # ==========================================================================
    # ARCHITECT-4 LEAD/DISCOVERY SCANNERS
    # These detect moves 1-2 days BEFORE they happen
    # They inject into DUI for confirmation, NOT direct trades
    # ==========================================================================
    
    async def run_premarket_gap_scan(self):
        """
        Run pre-market gap scan to detect significant price gaps.
        
        This would have caught UNH (-20% pre-market) immediately.
        
        ARCHITECT-4 RULE:
        - Gap down >= 5%: WATCHING
        - Gap down >= 8%: CLASS B candidate
        - Gap down >= 12%: CRITICAL (immediate attention)
        - Gap up >= 5% WITH RVOL >= 1.3: Potential reversal
        """
        now_et = datetime.now(EST)
        logger.info("=" * 60)
        logger.info("PRE-MARKET GAP SCAN (Lead/Discovery)")
        logger.info(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info("Scanning 800+ tickers for significant gaps...")
        logger.info("=" * 60)
        
        try:
            await self._init_clients()
            
            # Run pre-market gap scan
            results = await run_premarket_gap_scan(self._polygon)
            
            # Log results
            summary = results.get("summary", {})
            logger.info(f"Pre-Market Gap Scan Complete:")
            logger.info(f"  Critical gaps (>=12%): {summary.get('critical_count', 0)}")
            logger.info(f"  Class B gaps (>=8%): {summary.get('class_b_count', 0)}")
            logger.info(f"  Watching gaps (>=5%): {summary.get('watching_count', 0)}")
            logger.info(f"  Gap up reversals: {summary.get('gap_up_count', 0)}")
            logger.info(f"  Injected to DUI: {summary.get('injected_to_dui', 0)}")
            
            # Log critical gaps
            for gap in results.get("critical", []):
                logger.warning(
                    f"  🔴 CRITICAL GAP: {gap['symbol']} {gap['gap_pct']*100:+.1f}% | "
                    f"${gap['prior_close']:.2f} → ${gap['current_price']:.2f}"
                )
            
            # Log Class B gaps
            for gap in results.get("class_b", []):
                logger.info(
                    f"  🟡 CLASS B GAP: {gap['symbol']} {gap['gap_pct']*100:+.1f}% | "
                    f"${gap['prior_close']:.2f} → ${gap['current_price']:.2f}"
                )
            
            logger.info("=" * 60)
            
            return results
            
        except Exception as e:
            logger.error(f"Pre-market gap scan error: {e}")
            return {}
    
    async def run_multiday_weakness_scan(self):
        """
        Run multi-day weakness scan to detect deteriorating patterns.
        
        PATTERNS DETECTED (2-5 days):
        1. Lower highs (3-day) - Distribution
        2. Breaking 5-day low - Support failure
        3. Weak closes (2+ days) - Seller control
        4. Rising volume on red - Institution exit
        5. Lower lows + highs (3-day) - Downtrend
        6. Failed VWAP reclaim - Rejection
        7. Below all MAs - Bearish alignment
        8. Bearish engulfing - Reversal signal
        
        This would have caught MP, USAR, LAC, JOBY on Jan 26-27.
        """
        now_et = datetime.now(EST)
        logger.info("=" * 60)
        logger.info("MULTI-DAY WEAKNESS SCAN (Lead/Discovery)")
        logger.info(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info("Detecting weakness patterns 1-2 days before major moves...")
        logger.info("=" * 60)
        
        try:
            await self._init_clients()
            
            # Get all tickers to scan
            symbols = list(EngineConfig.get_all_tickers())
            
            # Run multi-day weakness scan
            results = await run_multiday_weakness_scan(self._polygon, symbols)
            
            # Log results
            actionable = results.get("actionable", {})
            logger.info(f"Multi-Day Weakness Scan Complete:")
            logger.info(f"  Symbols scanned: {results.get('symbols_scanned', 0)}")
            logger.info(f"  Actionable signals: {results.get('actionable_count', 0)}")
            
            # Inject actionable into DUI
            from putsengine.config import DynamicUniverseManager
            dui = DynamicUniverseManager()
            injected = 0
            
            for symbol, report in actionable.items():
                # Get pattern names for signals
                pattern_signals = [p.pattern_name for p in report.patterns]
                
                # Inject into DUI
                dui.promote_from_liquidity(
                    symbol=symbol,
                    score=min(0.50, report.total_score),  # Cap at 0.50 for lead signals
                    signals=pattern_signals
                )
                injected += 1
                
                logger.info(
                    f"  📉 WEAKNESS: {symbol} | Score: {report.total_score:.2f} | "
                    f"Patterns: {report.signal_count} | {report.recommendation}"
                )
            
            logger.info(f"  Injected to DUI: {injected}")
            logger.info("=" * 60)
            
            return results
            
        except Exception as e:
            logger.error(f"Multi-day weakness scan error: {e}")
            return {}
    
    async def run_sector_correlation_scan(self):
        """
        Run sector correlation scan to detect sector-wide weakness cascades.
        
        INSTITUTIONAL LOGIC:
        - High-beta sectors move TOGETHER
        - One weak name = entire sector at risk
        - Smart money exits leaders FIRST, then cascades to smaller names
        
        SECTORS TRACKED:
        - rare_earth: MP, USAR, LAC, ALB, LTHM, SQM
        - evtol: JOBY, ACHR, LILM, EVTL
        - crypto_miners: RIOT, MARA, CIFR, CLSK
        - cloud_security: NET, CRWD, ZS, PANW
        - nuclear_uranium: CCJ, UUUU, LEU, DNN
        - china_adr: BABA, JD, PDD, NIO
        - travel_airlines: DAL, UAL, AAL, CCL
        
        This would have caught MP → USAR → LAC cascade on Jan 28.
        """
        now_et = datetime.now(EST)
        logger.info("=" * 60)
        logger.info("SECTOR CORRELATION SCAN (Lead/Discovery)")
        logger.info(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info("Detecting sector-wide weakness cascades...")
        logger.info("=" * 60)
        
        try:
            # Get current DUI contents as candidates
            from putsengine.config import DynamicUniverseManager
            dui = DynamicUniverseManager()
            
            # Get all current candidates from DUI
            dui_contents = dui.get_dynamic_details()
            
            # Convert to format expected by sector correlation scanner
            candidates = {}
            for symbol, info in dui_contents.items():
                candidates[symbol] = {
                    "score": info.get("score", 0),
                    "signals": info.get("signals", [])
                }
            
            # Also include recent scan results if available
            if hasattr(self, 'latest_results'):
                for engine_key in ["gamma_drain", "distribution", "liquidity"]:
                    for candidate in self.latest_results.get(engine_key, []):
                        symbol = candidate.get("symbol")
                        if symbol and symbol not in candidates:
                            candidates[symbol] = {
                                "score": candidate.get("score", 0),
                                "signals": candidate.get("signals", [])
                            }
            
            # Run sector correlation scan
            results = await run_sector_correlation_scan(candidates)
            
            # Log results
            alerts = results.get("alerts", [])
            logger.info(f"Sector Correlation Scan Complete:")
            logger.info(f"  Sector alerts: {len(alerts)}")
            logger.info(f"  Peers injected to DUI: {results.get('injected_count', 0)}")
            
            # Log each alert
            for alert in alerts:
                logger.warning(
                    f"  🔗 SECTOR CASCADE: {alert.sector.upper()} | "
                    f"Leader: {alert.leader_symbol} (score {alert.leader_score:.2f}) | "
                    f"Affected: {', '.join(alert.affected_peers)}"
                )
            
            logger.info("=" * 60)
            
            return results
            
        except Exception as e:
            logger.error(f"Sector correlation scan error: {e}")
            return {}
    
    # ==========================================================================
    # NEW SCANNERS (Jan 29, 2026) - Would have caught 90% of missed puts
    # ==========================================================================
    
    async def run_pump_dump_scan(self):
        """
        Run pump-and-dump reversal scan.
        
        Detects stocks that had strong upward moves (+5%+) followed by reversal signals.
        
        This would have caught on Jan 28:
        - OKLO: +10.7% Jan 27 → -8.8% Jan 28
        - CLS: +3.6% Jan 27 → -13.1% Jan 28
        - FSLR: +6.1% Jan 27 → -10.2% Jan 28
        """
        now_et = datetime.now(EST)
        logger.info("=" * 60)
        logger.info("PUMP-DUMP REVERSAL SCAN")
        logger.info(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info("Detecting pump-and-dump reversal patterns...")
        logger.info("=" * 60)
        
        try:
            await self._init_clients()
            
            # Get all tickers to scan
            symbols = list(EngineConfig.get_all_tickers())
            
            # Run pump-dump scan
            results = await run_pump_dump_scan(self._polygon, symbols)
            
            # Log results
            summary = results.get("summary", {})
            logger.info(f"Pump-Dump Scan Complete:")
            logger.info(f"  Symbols scanned: {summary.get('scanned', 0)}")
            logger.info(f"  Alerts found: {summary.get('alerts_count', 0)}")
            logger.info(f"  Critical: {summary.get('critical_count', 0)}")
            logger.info(f"  High: {summary.get('high_count', 0)}")
            
            # Inject to DUI
            all_alerts = results.get("all", [])
            if all_alerts:
                injected = await inject_pump_dumps_to_dui(all_alerts)
                logger.info(f"  Injected to DUI: {injected}")
            
            logger.info("=" * 60)
            
            return results
            
        except Exception as e:
            logger.error(f"Pump-dump scan error: {e}")
            return {}
    
    async def run_pre_earnings_flow_scan(self):
        """
        Run pre-earnings options flow scan.
        
        Detects smart money positioning 1-3 days before earnings:
        - Put buying at ask (hedging)
        - Call selling at bid (exiting)
        - IV expansion (earnings premium)
        - Rising put OI (accumulation)
        
        This would have caught on Jan 26-27:
        - MSFT, NOW, TEAM, WDAY, TWLO (all crashed 8-13% after Jan 28 AMC earnings)
        """
        now_et = datetime.now(EST)
        logger.info("=" * 60)
        logger.info("PRE-EARNINGS OPTIONS FLOW SCAN")
        logger.info(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info("Detecting smart money positioning before earnings...")
        logger.info("=" * 60)
        
        try:
            await self._init_clients()
            
            # Get earnings calendar
            calendar = EarningsCalendar(uw_client=self._uw)
            await calendar.fetch_earnings_calendar(days_ahead=3)
            
            # Get all tickers to scan
            symbols = list(EngineConfig.get_all_tickers())
            
            # Run pre-earnings flow scan
            results = await run_pre_earnings_flow_scan(self._uw, calendar, symbols)
            
            # Log results
            summary = results.get("summary", {})
            logger.info(f"Pre-Earnings Flow Scan Complete:")
            logger.info(f"  Symbols scanned: {summary.get('scanned', 0)}")
            logger.info(f"  Alerts found: {summary.get('alerts_count', 0)}")
            logger.info(f"  Critical: {summary.get('critical_count', 0)}")
            logger.info(f"  High: {summary.get('high_count', 0)}")
            
            # Inject to DUI
            all_alerts = results.get("all", [])
            if all_alerts:
                injected = await inject_pre_earnings_to_dui(all_alerts)
                logger.info(f"  Injected to DUI: {injected}")
            
            logger.info("=" * 60)
            
            return results
            
        except Exception as e:
            logger.error(f"Pre-earnings flow scan error: {e}")
            return {}
    
    async def run_volume_price_scan(self):
        """
        Run volume-price divergence scan.
        
        Detects distribution patterns where volume is elevated but price doesn't progress:
        - Distribution: High volume + flat price = institutions exiting
        - Capitulation: Very high volume + falling price = forced selling
        - Compression: Volume expanding, price compressing = coiling for move
        
        This would have caught on Jan 27:
        - MSFT: High volume with flat price (distribution)
        - NOW: Volume spike with weakness (distribution)
        - TEAM: Multiple distribution days (sustained selling)
        """
        now_et = datetime.now(EST)
        logger.info("=" * 60)
        logger.info("VOLUME-PRICE DIVERGENCE SCAN")
        logger.info(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info("Detecting distribution and divergence patterns...")
        logger.info("=" * 60)
        
        try:
            await self._init_clients()
            
            # Get all tickers to scan
            symbols = list(EngineConfig.get_all_tickers())
            
            # Run volume-price scan
            results = await run_volume_price_scan(self._polygon, symbols)
            
            # Log results
            summary = results.get("summary", {})
            logger.info(f"Volume-Price Divergence Scan Complete:")
            logger.info(f"  Symbols scanned: {summary.get('scanned', 0)}")
            logger.info(f"  Alerts found: {summary.get('alerts_count', 0)}")
            logger.info(f"  Distribution: {summary.get('distribution_count', 0)}")
            logger.info(f"  Capitulation: {summary.get('capitulation_count', 0)}")
            logger.info(f"  Compression: {summary.get('compression_count', 0)}")
            
            # Inject to DUI
            all_alerts = results.get("all", [])
            if all_alerts:
                injected = await inject_divergence_to_dui(all_alerts)
                logger.info(f"  Injected to DUI: {injected}")
            
            logger.info("=" * 60)
            
            return results
            
        except Exception as e:
            logger.error(f"Volume-price scan error: {e}")
            return {}
    
    async def run_intraday_scan(self):
        """
        Run REAL-TIME intraday big mover scan.
        
        CRITICAL FEB 2, 2026 FIX:
        This scanner uses get_current_price() (quotes) instead of get_daily_bars()
        to detect SAME-DAY drops in real-time.
        
        Previous scanners only had data through previous close, missing:
        - HOOD: -9.62% (detected as -12.73% with real-time)
        - RMBS: -15.50% (detected as -22.75% with real-time)
        - DIS: -7.32% (detected as -4.29% with real-time)
        - BMNR: -8.94% (detected as -21.67% with real-time)
        
        Thresholds:
        - CRITICAL: > 10% drop
        - HIGH: 5-10% drop
        - MEDIUM: 3-5% drop
        """
        now_et = datetime.now(EST)
        logger.info("=" * 60)
        logger.info("🚨 INTRADAY BIG MOVER SCAN (REAL-TIME)")
        logger.info(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info("Detecting SAME-DAY drops using live quotes...")
        logger.info("=" * 60)
        
        try:
            # Get all tickers to scan
            symbols = list(EngineConfig.get_all_tickers())
            
            # Run intraday scan
            alerts = await run_intraday_scan(symbols)
            
            # Log results
            critical = [a for a in alerts if a.get("severity") == "CRITICAL"]
            high = [a for a in alerts if a.get("severity") == "HIGH"]
            medium = [a for a in alerts if a.get("severity") == "MEDIUM"]
            
            logger.info(f"Intraday Scan Complete:")
            logger.info(f"  Symbols scanned: {len(symbols)}")
            logger.info(f"  Total alerts: {len(alerts)}")
            logger.info(f"  🚨 CRITICAL (>10%): {len(critical)}")
            logger.info(f"  ⚠️  HIGH (5-10%): {len(high)}")
            logger.info(f"  📊 MEDIUM (3-5%): {len(medium)}")
            
            # Log critical alerts
            if critical:
                logger.warning("CRITICAL INTRADAY DROPS:")
                for a in critical[:10]:
                    logger.warning(f"  {a['symbol']}: {a['change_pct']:+.2f}% @ ${a['current_price']:.2f}")
            
            # Save to file for dashboard
            import json
            with open("intraday_alerts.json", "w") as f:
                json.dump({
                    "timestamp": now_et.isoformat(),
                    "alerts": alerts,
                    "critical_count": len(critical),
                    "high_count": len(high),
                    "medium_count": len(medium)
                }, f, indent=2)
            
            logger.info("=" * 60)
            
            return {"alerts": alerts, "critical": critical, "high": high}
            
        except Exception as e:
            logger.error(f"Intraday scan error: {e}")
            return {}
    
    async def run_daily_report_scan(self):
        """
        Run the daily 3 PM EST scan and send email report.
        
        This is the main daily report that:
        1. Scans all 253 tickers across all 3 engines
        2. Selects top 5 picks with 1x-5x return potential
        3. Saves HTML report to reports/ folder
        4. Sends email with picks (if configured)
        
        EMAIL SETUP:
        Set these environment variables:
        - PUTSENGINE_EMAIL_SENDER: Your Gmail address
        - PUTSENGINE_EMAIL_PASSWORD: Gmail app password (not regular password)
        - PUTSENGINE_EMAIL_RECIPIENT: Where to send reports
        
        To generate Gmail app password:
        1. Go to myaccount.google.com/security
        2. Enable 2-Step Verification
        3. Go to App passwords
        4. Generate password for "Mail" app
        """
        now_et = datetime.now(EST)
        logger.info("=" * 60)
        logger.info("📧 DAILY REPORT SCAN (3 PM EST)")
        logger.info(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info("Scanning all engines for best 1x-5x picks...")
        logger.info("=" * 60)
        
        try:
            # Run full scan
            await self.run_scan("daily_report")
            
            # Get results
            results = self.latest_results
            
            # Save report to file (always works)
            report_path = save_report_to_file(results)
            logger.info(f"📄 Report saved: {report_path}")
            
            # Send email (if configured)
            email_sent = send_email_report(results)
            
            if email_sent:
                logger.info("📧 Email sent successfully!")
            else:
                logger.warning("📧 Email not sent - check PUTSENGINE_EMAIL_* environment variables")
            
            logger.info("=" * 60)
            logger.info("DAILY REPORT COMPLETE")
            logger.info("=" * 60)
            
            return results
            
        except Exception as e:
            logger.error(f"Daily report scan error: {e}")
            return {}
    
    # ==========================================================================
    # EARLY WARNING SYSTEM (Feb 1, 2026)
    # Detects institutional footprints 1-3 DAYS BEFORE breakdown
    # This is the KEY to early detection
    # ==========================================================================
    
    async def run_early_warning_scan(self):
        """
        Run Early Warning scan to detect institutional footprints.
        
        THE 7 FOOTPRINTS (1-3 days before breakdown):
        1. Dark Pool Sequence - Smart money selling in staircases
        2. Put OI Accumulation - Quiet positioning before news
        3. IV Term Inversion - Premium for near-term protection
        4. Quote Degradation - Market makers reducing exposure
        5. Flow Divergence - Options leading stock by 1-2 days
        6. Multi-Day Distribution - Classic Wyckoff distribution
        7. Cross-Asset Divergence - Correlation breakdown
        
        PHILOSOPHY:
        We can't predict the catalyst, but we CAN detect the footprints
        of those who KNOW about the catalyst. Smart money leaves traces.
        """
        now_et = datetime.now(EST)
        logger.info("=" * 60)
        logger.info("🚨 EARLY WARNING SCAN - Institutional Footprint Detection")
        logger.info(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info("Detecting 7 institutional footprints 1-3 days before breakdown...")
        logger.info("=" * 60)
        
        try:
            await self._init_clients()
            
            # Get all tickers to scan
            all_tickers = EngineConfig.get_all_tickers()
            dui_tickers = self._load_dui_tickers()
            symbols = list(set(all_tickers) | set(dui_tickers))
            
            logger.info(f"Scanning {len(symbols)} symbols for institutional footprints...")
            
            # Run early warning scan
            results = await run_early_warning_scan(
                self._alpaca, 
                self._polygon, 
                self._uw,
                symbols
            )
            
            # Count by pressure level
            act_count = sum(1 for p in results.values() if p.level == PressureLevel.ACT)
            prepare_count = sum(1 for p in results.values() if p.level == PressureLevel.PREPARE)
            watch_count = sum(1 for p in results.values() if p.level == PressureLevel.WATCH)
            
            logger.info(f"Early Warning Scan Complete:")
            logger.info(f"  🔴 IMMINENT (ACT): {act_count}")
            logger.info(f"  🟡 ACTIVE (PREPARE): {prepare_count}")
            logger.info(f"  👀 EARLY (WATCH): {watch_count}")
            
            # Log critical alerts (ACT level) and record for attribution
            for symbol, pressure in results.items():
                if pressure.level == PressureLevel.ACT:
                    footprint_types = ", ".join(set(f.footprint_type.value for f in pressure.footprints[:5]))
                    logger.warning(
                        f"  🔴 {symbol}: IPI={pressure.ipi:.2f} | "
                        f"{pressure.unique_footprints} footprint types | "
                        f"{pressure.days_building} days building | "
                        f"Footprints: {footprint_types}"
                    )
                    
                    # Inject ACT-level symbols to DUI for immediate scanning
                    from putsengine.config import DynamicUniverseManager
                    dui = DynamicUniverseManager()
                    dui.inject_symbol(
                        symbol=symbol,
                        source="early_warning",
                        reason=f"IPI={pressure.ipi:.2f} ({pressure.unique_footprints} footprints)",
                        score=pressure.ipi,
                        signals=list(set(f.footprint_type.value for f in pressure.footprints)),
                        ttl_days=2
                    )
                    
                    # Log to attribution system (Architect-4 mandate: measure before scaling)
                    try:
                        log_ews_detection(
                            symbol=symbol,
                            ews_level=pressure.level.value,
                            ews_ipi=pressure.ipi,
                            footprints=list(set(f.footprint_type.value for f in pressure.footprints[:10]))
                        )
                    except Exception as e:
                        logger.debug(f"Attribution logging failed: {e}")
            
            # Also log PREPARE level
            for symbol, pressure in results.items():
                if pressure.level == PressureLevel.PREPARE:
                    logger.info(
                        f"  🟡 {symbol}: IPI={pressure.ipi:.2f} | "
                        f"{pressure.unique_footprints} footprints | "
                        f"{pressure.days_building} days"
                    )
            
            # Save early warning results to separate file
            early_warning_file = Path(__file__).parent.parent / "early_warning_alerts.json"
            try:
                alert_data = {
                    "timestamp": now_et.isoformat(),
                    "summary": {
                        "act_count": act_count,
                        "prepare_count": prepare_count,
                        "watch_count": watch_count,
                    },
                    "alerts": {
                        symbol: {
                            "ipi": pressure.ipi,
                            "level": pressure.level.value,
                            "unique_footprints": pressure.unique_footprints,
                            "days_building": pressure.days_building,
                            "recommendation": pressure.recommendation,
                            "footprints": [
                                {
                                    "type": f.footprint_type.value,
                                    "strength": f.strength,
                                    "details": f.details,
                                }
                                for f in pressure.footprints[:10]  # Top 10 footprints
                            ],
                        }
                        for symbol, pressure in results.items()
                    }
                }
                with open(early_warning_file, 'w') as f:
                    json.dump(alert_data, f, indent=2, default=str)
                logger.info(f"Early warning alerts saved to {early_warning_file}")
            except Exception as e:
                logger.warning(f"Could not save early warning alerts: {e}")
            
            # ================================================================
            # FLASH ALERTS (Architect-4 Feb 1, 2026)
            # Check for rapid IPI surges (≥ +0.30 in 60 min)
            # This is about ATTENTION, not trading
            # ================================================================
            try:
                flash_alerts = check_for_flash_alerts_in_ews_scan(results)
                if flash_alerts:
                    logger.warning(f"⚡ {len(flash_alerts)} FLASH ALERTS detected!")
                    for alert in flash_alerts[:3]:
                        logger.warning(f"  {alert.symbol}: IPI {alert.ipi_change:+.2f} in {alert.minutes_elapsed} min")
            except Exception as e:
                logger.debug(f"Flash alert check failed: {e}")
            
            logger.info("=" * 60)
            
            return results
            
        except Exception as e:
            logger.error(f"Early warning scan error: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    # ==========================================================================
    # ZERO-HOUR GAP SCANNER (Feb 1, 2026)
    # ARCHITECT-4 VALIDATED: Highest ROI remaining addition
    # Confirms Day 0 execution of Day -1 institutional pressure
    # ==========================================================================
    
    async def run_zero_hour_scan(self):
        """
        Run Zero-Hour Gap scan to confirm Day 0 execution.
        
        ARCHITECT-4 VALIDATED: This is the HIGHEST ROI remaining addition.
        
        Why it matters:
        - Institutions accumulate footprints on Day -1 (captured by EWS)
        - They execute the damage via pre-market gaps on Day 0
        
        Schedule: 9:15 AM ET (15 minutes before market open)
        Only checks: IPI ≥ 0.60 names from last EWS scan
        
        Interpretation:
        - IPI ≥ 0.60 AND gap down → "Vacuum is open" → ACT
        - IPI ≥ 0.60 AND gap up → "Pressure absorbed" → WAIT
        """
        now_et = datetime.now(EST)
        logger.info("=" * 60)
        logger.info("⚡ ZERO-HOUR GAP SCANNER (Day 0 Execution Confirmation)")
        logger.info(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info("Confirming institutional pressure → pre-market gap execution...")
        logger.info("=" * 60)
        
        try:
            await self._init_clients()
            
            # Run zero-hour scan
            results = await run_zero_hour_scan(self._polygon)
            
            # Log summary
            summary = results.get("summary", {})
            logger.info(f"Zero-Hour Scan Complete:")
            logger.info(f"  Checked: {summary.get('checked', 0)} high-pressure names (IPI ≥ 0.60)")
            logger.info(f"  🔴 VACUUM OPEN: {summary.get('vacuum_open', 0)}")
            logger.info(f"  🔴 SPREAD COLLAPSE: {summary.get('spread_collapse', 0)}")
            logger.info(f"  🟡 PRESSURE ABSORBED: {summary.get('pressure_absorbed', 0)}")
            logger.info(f"  👀 MONITORING: {summary.get('monitoring', 0)}")
            
            # Log actionable alerts
            alerts = results.get("alerts", {})
            actionable = [
                (sym, alert) for sym, alert in alerts.items() 
                if alert.get("is_actionable", False)
            ]
            
            for symbol, alert in actionable:
                logger.warning(
                    f"  ⚡ {symbol}: {alert['verdict'].upper()} | "
                    f"IPI={alert['ipi']:.2f} | Gap={alert['gap_pct']:+.2f}% | "
                    f"Spread={alert['spread_pct']:.2f}%"
                )
                
                # Inject VACUUM_OPEN symbols to DUI with high priority
                if alert.get("verdict") == "vacuum_open":
                    from putsengine.config import DynamicUniverseManager
                    dui = DynamicUniverseManager()
                    dui.inject_symbol(
                        symbol=symbol,
                        source="zero_hour",
                        reason=f"Vacuum open: IPI={alert['ipi']:.2f} + gap {alert['gap_pct']:+.2f}%",
                        score=alert['ipi'],
                        signals=["vacuum_open", "gap_confirmed"],
                        ttl_days=1  # Short TTL - Day 0 execution
                    )
            
            logger.info("=" * 60)
            
            return results
            
        except Exception as e:
            logger.error(f"Zero-hour scan error: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    def get_scheduled_jobs(self) -> List[Dict]:
        """Get list of all scheduled jobs."""
        jobs = []
        for job in self.scheduler.get_jobs():
            try:
                next_run = str(job.next_run_time) if hasattr(job, 'next_run_time') and job.next_run_time else "Not scheduled"
            except:
                next_run = "Pending"
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": next_run
            })
        return jobs
    
    async def start(self):
        """Start the scheduler as an always-on background service."""
        if self.is_running:
            logger.warning("Scheduler already running")
            return
        
        logger.info("=" * 60)
        logger.info("🚀 PUTSENGINE SCHEDULER DAEMON STARTING")
        logger.info("=" * 60)
        logger.info("")
        logger.info("FEB 1, 2026 UPDATE: PRE-BREAKDOWN SIGNAL PRIORITY")
        logger.info("================================================")
        logger.info("PRE-breakdown signals (predictive) now have 1.5x weight")
        logger.info("POST-breakdown signals (reactive) now have 0.7x weight")
        logger.info("This prioritizes EARLY detection over late confirmation")
        logger.info("")
        logger.info("DAEMON MODE: Running independently of dashboard")
        logger.info("Scheduler will run 24/7 until explicitly stopped")
        logger.info("")
        
        # Schedule all jobs
        self._schedule_jobs()
        
        # Start scheduler
        self.scheduler.start()
        self.is_running = True
        
        # Log scheduled jobs
        jobs = self.get_scheduled_jobs()
        logger.info(f"Scheduled {len(jobs)} scan jobs:")
        for job in jobs[:15]:  # Show first 15
            logger.info(f"  - {job['name']}: Next run at {job['next_run']}")
        if len(jobs) > 15:
            logger.info(f"  ... and {len(jobs) - 15} more jobs")
        
        logger.info("")
        logger.info("✅ Scheduler daemon started successfully!")
        logger.info("📊 All scans will run automatically at scheduled times")
        logger.info("🔄 Dashboard can be opened/closed without affecting scans")
        logger.info("=" * 60)
    
    async def stop(self):
        """Stop the scheduler."""
        if not self.is_running:
            return
        
        logger.info("Stopping scheduler...")
        self.scheduler.shutdown(wait=False)
        await self._close_clients()
        self.is_running = False
        logger.info("Scheduler stopped")


async def run_scheduler():
    """
    Run the scheduler as an always-on background service.
    
    This function runs indefinitely until:
    - SIGTERM or SIGINT received (graceful shutdown)
    - KeyboardInterrupt (Ctrl+C)
    
    The scheduler is NOT dependent on the dashboard being open.
    It can be started via:
    - python -m putsengine.scheduler (foreground)
    - python start_scheduler_daemon.py start (background daemon)
    """
    import signal as sig
    
    scheduler = PutsEngineScheduler()
    shutdown_requested = False
    
    def handle_shutdown(signum, frame):
        nonlocal shutdown_requested
        logger.info(f"Received shutdown signal ({signum})")
        shutdown_requested = True
    
    # Register signal handlers for graceful shutdown
    sig.signal(sig.SIGTERM, handle_shutdown)
    sig.signal(sig.SIGINT, handle_shutdown)
    
    try:
        await scheduler.start()
        
        logger.info("Scheduler daemon is now running...")
        logger.info("Press Ctrl+C or send SIGTERM to stop")
        
        # Track consecutive API failures for self-healing
        _consecutive_api_failures = 0
        _MAX_API_FAILURES_BEFORE_RESET = 5
        
        # Keep running until shutdown requested
        while not shutdown_requested:
            await asyncio.sleep(60)
            
            now_et = datetime.now(EST)
            
            # ================================================================
            # FEB 9 FIX: Event loop health probe + heartbeat file
            # The Feb 9 incident ran 8 hours with a broken event loop.
            # This probe writes a heartbeat file every minute so the
            # watchdog can detect dead loops. It also tests that the
            # event loop can actually perform async I/O.
            # ================================================================
            try:
                import json as _json
                loop = asyncio.get_running_loop()
                loop_alive = not loop.is_closed()
                
                # Quick connectivity test: verify aiohttp sessions are valid
                api_healthy = True
                if scheduler._uw is not None and hasattr(scheduler._uw, '_session'):
                    session = scheduler._uw._session
                    if session is not None and (session.closed or 
                        (hasattr(session, '_connector') and session._connector is not None and session._connector.closed)):
                        api_healthy = False
                        _consecutive_api_failures += 1
                        logger.warning(
                            f"⚠️ Event loop health: UW session stale/closed "
                            f"(failure {_consecutive_api_failures}/{_MAX_API_FAILURES_BEFORE_RESET})"
                        )
                    else:
                        _consecutive_api_failures = 0
                
                # Self-heal: reset client sessions if too many consecutive failures
                if _consecutive_api_failures >= _MAX_API_FAILURES_BEFORE_RESET:
                    logger.warning("🔧 Auto-healing: resetting all client sessions due to consecutive failures")
                    scheduler._reset_client_sessions()
                    _consecutive_api_failures = 0
                    api_healthy = True  # Will be re-created on next use
                
                # Write heartbeat file for watchdog
                health_data = {
                    "timestamp": now_et.isoformat(),
                    "loop_alive": loop_alive,
                    "api_healthy": api_healthy,
                    "pid": os.getpid(),
                    "consecutive_failures": _consecutive_api_failures,
                }
                health_path = Path("scheduler_loop_health.json")
                with open(health_path, "w") as _f:
                    _json.dump(health_data, _f, indent=2)
                
            except Exception as health_err:
                logger.warning(f"Health probe error (non-fatal): {health_err}")
            
            # Log heartbeat every 30 minutes
            if now_et.minute == 0 or now_et.minute == 30:
                logger.info(f"♥ Scheduler heartbeat: {now_et.strftime('%H:%M ET')} - Running")
            
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt (Ctrl+C)")
    except Exception as e:
        logger.error(f"Scheduler error: {e}")
        raise
    finally:
        logger.info("Shutting down scheduler daemon...")
        await scheduler.stop()
        logger.info("Scheduler daemon stopped gracefully")


async def run_single_scan(scan_type: str = "manual"):
    """Run a single scan without starting the scheduler."""
    scheduler = PutsEngineScheduler()
    await scheduler.run_scan(scan_type)
    await scheduler._close_clients()
    return scheduler.latest_results


async def run_single_scan(scan_type: str = "manual"):
    """Run a single scan without starting the scheduler."""
    scheduler = PutsEngineScheduler()
    await scheduler.run_scan(scan_type)
    await scheduler._close_clients()
    return scheduler.latest_results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="PutsEngine Scheduler")
    parser.add_argument(
        "--single", 
        action="store_true",
        help="Run a single scan instead of starting scheduler"
    )
    parser.add_argument(
        "--type",
        default="manual",
        help="Scan type (pre_market_1, market_open, regular, etc.)"
    )
    
    args = parser.parse_args()
    
    if args.single:
        asyncio.run(run_single_scan(args.type))
    else:
        asyncio.run(run_scheduler())
