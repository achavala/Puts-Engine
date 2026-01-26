"""
PutsEngine Scheduled Scanner Service.

Runs automated scans at predefined times throughout the trading day:
- 4:00 AM ET  → Pre-market scan #1
- 6:00 AM ET  → Pre-market scan #2  
- 8:00 AM ET  → Pre-market scan #3
- 9:30 AM ET  → Market open scan
- 10:00-4:00  → Regular scans every 30 min
- 4:00 PM ET  → Market close scan

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


# Constants
EST = pytz.timezone('US/Eastern')
RESULTS_FILE = Path("scheduled_scan_results.json")
SCAN_LOG_FILE = Path("logs/scheduled_scans.log")


def get_signal_tier(score: float) -> str:
    """Get signal tier from score."""
    if score >= 0.75:
        return "🔥 EXPLOSIVE"
    elif score >= 0.65:
        return "⚡ VERY STRONG"
    elif score >= 0.55:
        return "💪 STRONG"
    elif score >= 0.45:
        return "👀 MONITORING"
    elif score >= 0.35:
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
        
        Schedule (EST):
        - 4:00 AM  → Pre-market scan #1
        - 6:00 AM  → Pre-market scan #2
        - 8:00 AM  → Pre-market scan #3
        - 9:30 AM  → Market open scan
        - 10:00-16:00 → Every 30 minutes
        - 16:00    → Market close scan
        """
        # Pre-market scans
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=4, minute=0, timezone=EST),
            args=["pre_market_1"],
            id="pre_market_1",
            name="Pre-Market Scan #1 (4:00 AM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=6, minute=0, timezone=EST),
            args=["pre_market_2"],
            id="pre_market_2",
            name="Pre-Market Scan #2 (6:00 AM ET)",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=8, minute=0, timezone=EST),
            args=["pre_market_3"],
            id="pre_market_3",
            name="Pre-Market Scan #3 (8:00 AM ET)",
            replace_existing=True
        )
        
        # Market open scan
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=9, minute=30, timezone=EST),
            args=["market_open"],
            id="market_open",
            name="Market Open Scan (9:30 AM ET)",
            replace_existing=True
        )
        
        # Regular 30-minute scans (10:00 AM to 3:30 PM)
        for hour in range(10, 16):
            for minute in [0, 30]:
                if hour == 10 and minute == 0:
                    continue  # Skip duplicate at 10:00
                if hour == 15 and minute == 30:
                    continue  # Skip 3:30, close scan at 4:00
                    
                job_id = f"regular_{hour:02d}{minute:02d}"
                self.scheduler.add_job(
                    self._run_scan_wrapper,
                    CronTrigger(hour=hour, minute=minute, timezone=EST),
                    args=["regular"],
                    id=job_id,
                    name=f"Regular Scan ({hour:02d}:{minute:02d} ET)",
                    replace_existing=True
                )
        
        # Add 10:00 AM scan
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=10, minute=0, timezone=EST),
            args=["regular"],
            id="regular_1000",
            name="Regular Scan (10:00 ET)",
            replace_existing=True
        )
        
        # Market close scan
        self.scheduler.add_job(
            self._run_scan_wrapper,
            CronTrigger(hour=16, minute=0, timezone=EST),
            args=["market_close"],
            id="market_close",
            name="Market Close Scan (4:00 PM ET)",
            replace_existing=True
        )
        
        logger.info("All scheduled jobs configured")
    
    def _run_scan_wrapper(self, scan_type: str):
        """Wrapper to run async scan in scheduler context."""
        asyncio.create_task(self.run_scan(scan_type))
    
    async def run_scan(self, scan_type: str = "manual"):
        """
        Run a full scan of all tickers across all 3 engines.
        
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
            
            # Get all tickers
            all_tickers = EngineConfig.get_all_tickers()
            logger.info(f"Scanning {len(all_tickers)} tickers...")
            
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
            
            # Scan each ticker
            processed = 0
            errors = 0
            
            for symbol in all_tickers:
                try:
                    # Run distribution analysis
                    distribution = await self._distribution_layer.analyze(symbol)
                    
                    # Skip if no signals and low score
                    if distribution.score < self.settings.min_score_threshold:
                        processed += 1
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
                        "scan_type": scan_type
                    }
                    
                    # Add to appropriate engine list
                    if engine_type == EngineType.GAMMA_DRAIN:
                        gamma_drain_candidates.append(candidate_data)
                    elif engine_type == EngineType.DISTRIBUTION_TRAP:
                        distribution_candidates.append(candidate_data)
                    else:
                        liquidity_candidates.append(candidate_data)
                    
                    processed += 1
                    
                except Exception as e:
                    logger.debug(f"Error scanning {symbol}: {e}")
                    errors += 1
                    processed += 1
                
                # Progress logging every 25 tickers
                if processed % 25 == 0:
                    logger.info(f"Progress: {processed}/{len(all_tickers)}")
            
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
                "tickers_scanned": len(all_tickers),
                "errors": errors,
                "total_candidates": len(gamma_drain_candidates) + len(distribution_candidates) + len(liquidity_candidates)
            }
            
            # Save results to file
            self._save_results()
            
            # Log summary
            logger.info(f"=" * 60)
            logger.info(f"SCAN COMPLETE: {scan_type.upper()}")
            logger.info(f"Tickers scanned: {processed}")
            logger.info(f"Errors: {errors}")
            logger.info(f"Gamma Drain candidates: {len(gamma_drain_candidates)}")
            logger.info(f"Distribution candidates: {len(distribution_candidates)}")
            logger.info(f"Liquidity candidates: {len(liquidity_candidates)}")
            
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
    
    def _determine_engine_type(self, distribution) -> EngineType:
        """Determine which engine type based on signals."""
        signals = distribution.signals
        
        # Gamma Drain: Options flow + dealer positioning signals
        gamma_signals = sum([
            signals.get("call_selling_at_bid", False),
            signals.get("put_buying_at_ask", False),
            signals.get("rising_put_oi", False),
            signals.get("skew_steepening", False)
        ])
        
        # Distribution: Price-volume signals
        dist_signals = sum([
            signals.get("gap_up_reversal", False),
            signals.get("gap_down_no_recovery", False),
            signals.get("high_rvol_red_day", False),
            signals.get("flat_price_rising_volume", False),
            signals.get("failed_breakout", False)
        ])
        
        # Liquidity: Dark pool + institutional
        liq_signals = sum([
            signals.get("repeated_sell_blocks", False),
            signals.get("vwap_loss", False),
            signals.get("multi_day_weakness", False)
        ])
        
        # Determine engine by strongest signal set
        if gamma_signals >= dist_signals and gamma_signals >= liq_signals:
            return EngineType.GAMMA_DRAIN
        elif dist_signals >= liq_signals:
            return EngineType.DISTRIBUTION_TRAP
        else:
            return EngineType.SNAPBACK  # Maps to Liquidity in UI
    
    def _save_results(self):
        """Save scan results to JSON file."""
        try:
            with open(RESULTS_FILE, 'w') as f:
                json.dump(self.latest_results, f, indent=2, default=str)
            logger.info(f"Results saved to {RESULTS_FILE}")
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
