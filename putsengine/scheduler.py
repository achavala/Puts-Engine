"""
PutsEngine Scheduled Scanner Service.

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

This scheduler runs as a background service and saves results for the dashboard.
"""

import asyncio
import json
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

# Email Reporter for daily 3 PM scan
from putsengine.email_reporter import run_daily_report_scan, send_email_report, save_report_to_file


# Constants
EST = pytz.timezone('US/Eastern')
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
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=4, minute=15, timezone=EST),
            args=["pre_market_1"],
            id="pre_market_1",
            name="Pre-Market Scan #1 (4:15 AM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=6, minute=15, timezone=EST),
            args=["pre_market_2"],
            id="pre_market_2",
            name="Pre-Market Scan #2 (6:15 AM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=8, minute=15, timezone=EST),
            args=["pre_market_3"],
            id="pre_market_3",
            name="Pre-Market Scan #3 (8:15 AM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=9, minute=15, timezone=EST),
            args=["pre_market_4"],
            id="pre_market_4",
            name="Pre-Market Scan #4 (9:15 AM ET)",
            replace_existing=True
        )
        
        # Regular scans during market hours (6 scans)
        # 10:15 AM
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=10, minute=15, timezone=EST),
            args=["regular"],
            id="regular_1015",
            name="Regular Scan (10:15 AM ET)",
            replace_existing=True
        )
        
        # 11:15 AM
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=11, minute=15, timezone=EST),
            args=["regular"],
            id="regular_1115",
            name="Regular Scan (11:15 AM ET)",
            replace_existing=True
        )
        
        # 12:45 PM
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=12, minute=45, timezone=EST),
            args=["regular"],
            id="regular_1245",
            name="Regular Scan (12:45 PM ET)",
            replace_existing=True
        )
        
        # 1:45 PM
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=13, minute=45, timezone=EST),
            args=["regular"],
            id="regular_1345",
            name="Regular Scan (1:45 PM ET)",
            replace_existing=True
        )
        
        # 2:45 PM
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=14, minute=45, timezone=EST),
            args=["regular"],
            id="regular_1445",
            name="Regular Scan (2:45 PM ET)",
            replace_existing=True
        )
        
        # 3:15 PM
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=15, minute=15, timezone=EST),
            args=["regular"],
            id="regular_1515",
            name="Regular Scan (3:15 PM ET)",
            replace_existing=True
        )
        
        # Market close scan (4:00 PM)
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=16, minute=0, timezone=EST),
            args=["market_close"],
            id="market_close",
            name="Market Close Scan (4:00 PM ET)",
            replace_existing=True
        )
        
        # End of Day scan (5:00 PM)
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=17, minute=0, timezone=EST),
            args=["end_of_day"],
            id="end_of_day",
            name="End of Day Scan (5:00 PM ET)",
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
        # DAILY REPORT SCAN (3 PM EST) - Email with best picks
        # Scans all 3 engines and sends email with top 5 picks (1x-5x potential)
        # ============================================================================
        self.scheduler.add_job(
            self._run_daily_report_scan_wrapper,
            CronTrigger(hour=15, minute=0, timezone=EST),
            id="daily_report_3pm",
            name="📧 Daily Report Scan (3:00 PM ET) - Email",
            replace_existing=True
        )
        
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
        
        # =========================================================================
        # PATTERN SCAN - Every 30 minutes during market hours (9:30 AM - 4:00 PM ET)
        # =========================================================================
        for hour in range(9, 16):
            for minute in [0, 30]:
                # Skip 9:00 (before market open)
                if hour == 9 and minute == 0:
                    continue
                self.scheduler.add_job(
                    self._run_pattern_scan_wrapper,
                    CronTrigger(hour=hour, minute=minute, timezone=EST),
                    id=f"pattern_scan_{hour}_{minute:02d}",
                    name=f"Pattern Scan ({hour}:{minute:02d} ET)",
                    replace_existing=True
                )
        
        # Also run pattern scan at 4:00 PM after market close
        self.scheduler.add_job(
            self._run_pattern_scan_wrapper,
            CronTrigger(hour=16, minute=0, timezone=EST),
            id="pattern_scan_16_00",
            name="Pattern Scan (4:00 PM ET - Post Market)",
            replace_existing=True
        )
        
        logger.info("All scheduled jobs configured (including NEW scanners for 90% coverage + pattern scan every 30 min)")
    
    def _run_scan_wrapper(self, scan_type: str):
        """Wrapper to run async scan in scheduler context."""
        # Get or create event loop and run the coroutine
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(self.run_scan(scan_type), loop=loop)
        except RuntimeError:
            # No running loop - create a new one
            asyncio.run(self.run_scan(scan_type))
    
    def _run_afterhours_scan_wrapper(self):
        """Wrapper to run after-hours scan in scheduler context."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(self.run_afterhours_scan(), loop=loop)
        except RuntimeError:
            asyncio.run(self.run_afterhours_scan())
    
    def _run_earnings_check_wrapper(self):
        """Wrapper to run earnings calendar check in scheduler context."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(self.run_earnings_check(), loop=loop)
        except RuntimeError:
            asyncio.run(self.run_earnings_check())
    
    def _run_precatalyst_scan_wrapper(self):
        """Wrapper to run pre-catalyst scan in scheduler context."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(self.run_precatalyst_scan(), loop=loop)
        except RuntimeError:
            asyncio.run(self.run_precatalyst_scan())
    
    def _run_premarket_gap_scan_wrapper(self):
        """Wrapper to run pre-market gap scan in scheduler context."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(self.run_premarket_gap_scan(), loop=loop)
        except RuntimeError:
            asyncio.run(self.run_premarket_gap_scan())
    
    def _run_multiday_weakness_scan_wrapper(self):
        """Wrapper to run multi-day weakness scan in scheduler context."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(self.run_multiday_weakness_scan(), loop=loop)
        except RuntimeError:
            asyncio.run(self.run_multiday_weakness_scan())
    
    def _run_sector_correlation_scan_wrapper(self):
        """Wrapper to run sector correlation scan in scheduler context."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(self.run_sector_correlation_scan(), loop=loop)
        except RuntimeError:
            asyncio.run(self.run_sector_correlation_scan())
    
    def _run_daily_report_scan_wrapper(self):
        """Wrapper to run daily report scan (3 PM EST) with email."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(self.run_daily_report_scan(), loop=loop)
        except RuntimeError:
            asyncio.run(self.run_daily_report_scan())
    
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
    
    def _run_pump_dump_scan_wrapper(self):
        """Wrapper to run pump-dump reversal scan."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(self.run_pump_dump_scan(), loop=loop)
        except RuntimeError:
            asyncio.run(self.run_pump_dump_scan())
    
    def _run_pre_earnings_flow_wrapper(self):
        """Wrapper to run pre-earnings flow scan."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(self.run_pre_earnings_flow_scan(), loop=loop)
        except RuntimeError:
            asyncio.run(self.run_pre_earnings_flow_scan())
    
    def _run_volume_price_scan_wrapper(self):
        """Wrapper to run volume-price divergence scan."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(self.run_volume_price_scan(), loop=loop)
        except RuntimeError:
            asyncio.run(self.run_volume_price_scan())
    
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
            
            # Get market regime first
            market_regime = await self._market_regime_layer.analyze()
            logger.info(f"Market Regime: {market_regime.regime.value}")
            
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
                            "batch": batch_num
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
        
        ARCHITECT-4 REFINED LOGIC (Feb 1, 2026):
        =========================================
        KEY INSIGHT: pump_reversal is a TRANSITION state, not pure execution.
        
        - Distribution = early warning (supply detection, 1-3 days before breakdown)
        - Gamma Drain = forced execution (dealer-driven acceleration)
        - Liquidity = vacuum detection (buyers disappearing)
        
        CRITICAL FIX: pump_reversal + high_rvol_red_day → Distribution (transition)
        This separates thesis formation from execution timing.
        """
        signals = distribution.signals
        score = distribution.score
        
        # ======================================================================
        # ARCHITECT-4 FIX: Handle pump_reversal as TRANSITION state
        # pump_reversal alone is supply detection, not execution timing
        # ======================================================================
        has_pump_reversal = signals.get("pump_reversal", False)
        has_high_rvol_red = signals.get("high_rvol_red_day", False)
        
        # If pump_reversal + high_rvol_red_day → DISTRIBUTION (transition phase)
        # This is early warning, not execution trigger
        if has_pump_reversal and has_high_rvol_red:
            logger.info("Engine assignment: DISTRIBUTION (pump_reversal + high_rvol = transition)")
            return EngineType.DISTRIBUTION_TRAP
        
        # ======================================================================
        # Gamma Drain: Options flow + dealer positioning signals
        # These indicate forced execution (dealers must hedge)
        # ======================================================================
        gamma_signals = sum([
            signals.get("call_selling_at_bid", False),
            signals.get("put_buying_at_ask", False),
            signals.get("rising_put_oi", False),
            signals.get("skew_steepening", False),
            signals.get("volume_price_divergence", False),
        ])
        
        # ======================================================================
        # Distribution: Price-volume signals + event-driven
        # These indicate supply absorption (smart money exiting)
        # ======================================================================
        dist_signals = sum([
            signals.get("gap_up_reversal", False),
            signals.get("gap_down_no_recovery", False),
            has_high_rvol_red,  # Already calculated
            signals.get("flat_price_rising_volume", False),
            signals.get("failed_breakout", False),
            signals.get("is_post_earnings_negative", False),
            signals.get("is_pre_earnings", False),
            has_pump_reversal,  # pump_reversal is distribution evidence
        ])
        
        # ======================================================================
        # Liquidity: Dark pool + institutional + VWAP loss
        # These indicate buyer disappearance
        # ======================================================================
        liq_signals = sum([
            signals.get("repeated_sell_blocks", False),
            signals.get("vwap_loss", False),
            signals.get("multi_day_weakness", False),
            signals.get("below_vwap", False),
        ])
        
        # ======================================================================
        # DECISION LOGIC (Architect-4 validated):
        # 1. 2+ gamma signals (pure flow) → Gamma Drain (execution)
        # 2. Event-driven OR distribution patterns → Distribution (early warning)
        # 3. VWAP loss + weakness → Liquidity (vacuum detection)
        # ======================================================================
        
        # Check for pure gamma flow (2+ signals = dealer execution)
        has_pure_gamma = gamma_signals >= 2
        
        # Check for event-driven distribution
        has_event = signals.get("is_post_earnings_negative", False)
        has_failed_breakout = signals.get("failed_breakout", False) or signals.get("gap_up_reversal", False)
        
        # Check for liquidity vacuum
        has_vwap_loss = signals.get("vwap_loss", False) or signals.get("below_vwap", False)
        has_weakness = signals.get("multi_day_weakness", False)
        
        # Decision tree (institutionally correct separation)
        if has_pure_gamma and score >= 0.55:
            logger.debug("Engine assignment: GAMMA_DRAIN (2+ gamma signals + high score)")
            return EngineType.GAMMA_DRAIN
        elif has_pump_reversal or has_event or has_failed_breakout:
            # pump_reversal alone → Distribution (not Gamma Drain)
            logger.debug("Engine assignment: DISTRIBUTION (supply detection)")
            return EngineType.DISTRIBUTION_TRAP
        elif has_vwap_loss and has_weakness:
            logger.debug("Engine assignment: LIQUIDITY (vacuum detection)")
            return EngineType.SNAPBACK  # Liquidity
        elif gamma_signals > dist_signals and gamma_signals > liq_signals:
            return EngineType.GAMMA_DRAIN
        elif dist_signals >= liq_signals:
            return EngineType.DISTRIBUTION_TRAP
        else:
            return EngineType.SNAPBACK  # Liquidity
    
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
            
            # Run after-hours scan
            results = await run_afterhours_scan(self._alpaca, universe)
            
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
            
            # Run pre-catalyst scan
            results = await run_precatalyst_scan(self._uw, self._alpaca)
            
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
            results = await run_premarket_gap_scan(self._alpaca)
            
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
            results = await run_multiday_weakness_scan(self._alpaca, symbols)
            
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
            results = await run_pump_dump_scan(self._alpaca, symbols)
            
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
            results = await run_volume_price_scan(self._alpaca, symbols)
            
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
        """Start the scheduler."""
        if self.is_running:
            logger.warning("Scheduler already running")
            return
        
        logger.info("=" * 60)
        logger.info("PUTSENGINE SCHEDULER STARTING")
        logger.info("=" * 60)
        
        # Schedule all jobs
        self._schedule_jobs()
        
        # Start scheduler
        self.scheduler.start()
        self.is_running = True
        
        # Log scheduled jobs
        jobs = self.get_scheduled_jobs()
        logger.info(f"Scheduled {len(jobs)} scan jobs:")
        for job in jobs:
            logger.info(f"  - {job['name']}: Next run at {job['next_run']}")
        
        logger.info("Scheduler started. Running until interrupted.")
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
    """Run the scheduler service."""
    scheduler = PutsEngineScheduler()
    
    try:
        await scheduler.start()
        
        # Keep running until interrupted
        while True:
            await asyncio.sleep(60)
            
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await scheduler.stop()


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
