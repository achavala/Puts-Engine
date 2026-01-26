#!/usr/bin/env python3
"""
PutsEngine Complete Startup Script.

This script starts:
1. The scheduled scanner service (runs in background)
2. The Streamlit dashboard (optional)

Usage:
    python start_putsengine.py                    # Start scheduler only
    python start_putsengine.py --dashboard        # Start scheduler + dashboard
    python start_putsengine.py --scan-now         # Run immediate scan + start scheduler
    python start_putsengine.py --single-scan      # Run one scan only (no scheduler)
"""

import asyncio
import argparse
import subprocess
import sys
import signal
import os
from datetime import datetime
from pathlib import Path

import pytz

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger

EST = pytz.timezone('US/Eastern')


def setup_logging():
    """Configure logging."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    logger.add(
        "logs/putsengine_startup.log",
        rotation="1 day",
        retention="7 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
    )


def print_banner():
    """Print startup banner."""
    now_et = datetime.now(EST)
    
    banner = f"""
╔══════════════════════════════════════════════════════════════════╗
║                    🏛️  PUTSENGINE STARTUP                        ║
╠══════════════════════════════════════════════════════════════════╣
║  Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}                              ║
║                                                                  ║
║  SCHEDULED SCANS:                                                ║
║    • 4:00 AM ET  → Pre-market scan #1                           ║
║    • 6:00 AM ET  → Pre-market scan #2                           ║
║    • 8:00 AM ET  → Pre-market scan #3                           ║
║    • 9:30 AM ET  → Market open scan                             ║
║    • 10:00-4:00  → Every 30 minutes                             ║
║    • 4:00 PM ET  → Market close scan                            ║
║                                                                  ║
║  ENGINES:                                                        ║
║    • Gamma Drain Engine (Flow-Driven)                           ║
║    • Distribution Engine (Event-Driven)                         ║
║    • Liquidity Engine (Vacuum Detection)                        ║
╚══════════════════════════════════════════════════════════════════╝
"""
    print(banner)


def start_dashboard(port: int = 8507):
    """Start the Streamlit dashboard in background."""
    logger.info(f"Starting dashboard on port {port}...")
    
    # Kill any existing process on the port
    try:
        os.system(f"lsof -ti:{port} | xargs kill -9 2>/dev/null")
    except:
        pass
    
    # Start dashboard
    cmd = [
        sys.executable, "-m", "streamlit", "run",
        "putsengine/dashboard.py",
        "--server.port", str(port),
        "--server.headless", "true"
    ]
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    logger.info(f"Dashboard started. Access at: http://localhost:{port}")
    return process


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="PutsEngine Startup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python start_putsengine.py                    # Start scheduler only
  python start_putsengine.py --dashboard        # Start scheduler + dashboard  
  python start_putsengine.py --scan-now         # Immediate scan + scheduler
  python start_putsengine.py --single-scan      # One scan only (no scheduler)
"""
    )
    
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Also start the Streamlit dashboard"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8507,
        help="Dashboard port (default: 8507)"
    )
    parser.add_argument(
        "--scan-now",
        action="store_true",
        help="Run an immediate scan before starting scheduler"
    )
    parser.add_argument(
        "--single-scan",
        action="store_true",
        help="Run one scan only (don't start scheduler)"
    )
    
    args = parser.parse_args()
    
    setup_logging()
    print_banner()
    
    # Import scheduler
    from putsengine.scheduler import PutsEngineScheduler, run_single_scan
    
    dashboard_process = None
    scheduler = None
    
    def shutdown_handler(signum, frame):
        """Handle shutdown gracefully."""
        logger.info("\nShutdown signal received...")
        
        if dashboard_process:
            logger.info("Stopping dashboard...")
            dashboard_process.terminate()
        
        if scheduler and scheduler.is_running:
            asyncio.create_task(scheduler.stop())
        
        sys.exit(0)
    
    # Register signal handlers
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    
    try:
        # Single scan mode
        if args.single_scan:
            logger.info("Running single scan...")
            results = await run_single_scan("manual")
            
            print("\n" + "=" * 60)
            print("SCAN RESULTS")
            print("=" * 60)
            print(f"Gamma Drain candidates: {len(results.get('gamma_drain', []))}")
            print(f"Distribution candidates: {len(results.get('distribution', []))}")
            print(f"Liquidity candidates: {len(results.get('liquidity', []))}")
            
            # Print top candidates
            for engine, candidates in [
                ("Gamma Drain", results.get('gamma_drain', [])),
                ("Distribution", results.get('distribution', [])),
                ("Liquidity", results.get('liquidity', []))
            ]:
                if candidates:
                    print(f"\nTop {engine}:")
                    for c in candidates[:3]:
                        print(f"  {c['symbol']}: {c['score']:.2f} ({c['tier']})")
            
            return
        
        # Start dashboard if requested
        if args.dashboard:
            dashboard_process = start_dashboard(args.port)
        
        # Create scheduler
        scheduler = PutsEngineScheduler()
        
        # Run immediate scan if requested
        if args.scan_now:
            logger.info("Running immediate scan...")
            await scheduler.run_scan("startup")
        
        # Start scheduler
        await scheduler.start()
        
        # Keep running
        logger.info("PutsEngine is now running. Press Ctrl+C to stop.")
        
        while True:
            await asyncio.sleep(60)
            
            # Log heartbeat every hour
            now_et = datetime.now(EST)
            if now_et.minute == 0:
                jobs = scheduler.get_scheduled_jobs()
                next_job = min(jobs, key=lambda x: x['next_run']) if jobs else None
                if next_job:
                    logger.info(f"Heartbeat: Next scan at {next_job['next_run']}")
    
    except KeyboardInterrupt:
        logger.info("Shutdown requested...")
    
    finally:
        if dashboard_process:
            logger.info("Stopping dashboard...")
            dashboard_process.terminate()
        
        if scheduler:
            await scheduler.stop()
        
        logger.info("PutsEngine stopped.")


if __name__ == "__main__":
    asyncio.run(main())
