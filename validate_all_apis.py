#!/usr/bin/env python3
"""
Comprehensive API Validation Script
Tests: Alpaca, Polygon, Unusual Whales, FinViz
Also checks scheduler status and recent scans.
"""

import asyncio
import os
from datetime import datetime, date, timedelta
import pytz
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

async def test_alpaca():
    """Test Alpaca API connection."""
    print("\n1️⃣  ALPACA (Stock Data):")
    try:
        from putsengine.clients.alpaca_client import AlpacaClient
        from putsengine.config import get_settings
        settings = get_settings()
        alpaca = AlpacaClient(settings)
        
        # Test real-time quote
        quote = await alpaca.get_current_price("AAPL")
        if quote and quote > 0:
            print(f"   ✅ Real-time quote: AAPL = ${quote:.2f}")
        else:
            print(f"   ⚠️  No quote returned (market may be closed)")
            
        # Test daily bars
        bars = await alpaca.get_daily_bars("AAPL", limit=5)
        if bars and len(bars) > 0:
            print(f"   ✅ Daily bars: {len(bars)} bars fetched")
            last_bar = bars[-1]
            print(f"      Last bar: {last_bar.timestamp.date()} - Close: ${last_bar.close:.2f}")
            return True
        else:
            print(f"   ⚠️  No bars returned")
            return 'partial'
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


async def test_polygon():
    """Test Polygon API connection."""
    print("\n2️⃣  POLYGON / MASSIVE (Options Data):")
    try:
        from putsengine.clients.polygon_client import PolygonClient
        from putsengine.config import get_settings
        settings = get_settings()
        polygon = PolygonClient(settings)
        
        # Test daily bars
        bars = await polygon.get_daily_bars("AAPL", from_date=date.today() - timedelta(days=10))
        if bars and len(bars) > 0:
            print(f"   ✅ Daily bars: {len(bars)} bars for AAPL")
            return True
        else:
            print(f"   ⚠️  No bars returned")
            return 'partial'
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


async def test_unusual_whales():
    """Test Unusual Whales API connection."""
    print("\n3️⃣  UNUSUAL WHALES (Options Flow):")
    try:
        from putsengine.clients.unusual_whales_client import UnusualWhalesClient
        from putsengine.config import get_settings
        settings = get_settings()
        uw = UnusualWhalesClient(settings)
        
        # Test flow
        flow = await uw.get_flow_recent("AAPL", limit=10)
        if flow and len(flow) > 0:
            print(f"   ✅ Options flow: {len(flow)} recent trades for AAPL")
            return True
        else:
            print(f"   ⚠️  No flow returned (may be rate limited)")
            return 'partial'
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


async def test_finviz():
    """Test FinViz API connection."""
    print("\n4️⃣  FINVIZ (Screener):")
    try:
        from putsengine.clients.finviz_client import FinVizClient
        from putsengine.config import get_settings
        settings = get_settings()
        finviz = FinVizClient(settings)
        
        # Test screener
        data = await finviz.get_ticker_data("AAPL")
        if data:
            company = data.get('Company', 'N/A')
            price = data.get('Price', 'N/A')
            print(f"   ✅ Ticker data: AAPL - {company}")
            print(f"      Price: ${price}")
            return True
        else:
            print(f"   ⚠️  No data returned")
            return 'partial'
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def check_scheduler_status():
    """Check scheduler daemon status."""
    print("\n5️⃣  SCHEDULER DAEMON:")
    
    pid_file = Path("scheduler.pid")
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            # Check if process is running
            import psutil
            if psutil.pid_exists(pid):
                process = psutil.Process(pid)
                mem_mb = process.memory_info().rss / (1024 * 1024)
                print(f"   ✅ Running (PID: {pid}, Memory: {mem_mb:.1f} MB)")
                return True
            else:
                print(f"   ❌ PID file exists but process not running")
                return False
        except Exception as e:
            print(f"   ⚠️  Error checking PID: {e}")
            return 'partial'
    else:
        print(f"   ❌ Scheduler not running (no PID file)")
        return False


def check_recent_scans():
    """Check recent scan activity."""
    print("\n6️⃣  RECENT SCANS:")
    
    et = pytz.timezone('US/Eastern')
    now = datetime.now(et)
    
    # Check scan history
    history_file = Path("scan_history.json")
    if history_file.exists():
        try:
            with open(history_file, 'r') as f:
                history = json.load(f)
            
            scans = history.get("scans", [])
            if scans:
                recent_scans = scans[-10:]  # Last 10 scans
                print(f"   📊 Total scans in history: {len(scans)}")
                print(f"   📊 Last 5 scans:")
                for scan in recent_scans[-5:]:
                    ts = scan.get("timestamp", "N/A")
                    scan_type = scan.get("type", "unknown")
                    count = scan.get("candidates_found", 0)
                    print(f"      • {ts[:19]} - {scan_type}: {count} candidates")
                return True
            else:
                print(f"   ⚠️  No scans in history")
                return 'partial'
        except Exception as e:
            print(f"   ❌ Error reading history: {e}")
            return False
    else:
        print(f"   ⚠️  No scan history file found")
        return 'partial'


def check_premarket_scans():
    """Check if pre-market scans ran today."""
    print("\n7️⃣  PRE-MARKET SCANS (Today):")
    
    et = pytz.timezone('US/Eastern')
    now = datetime.now(et)
    today = now.date()
    
    # Check logs for today's pre-market scans
    log_files = list(Path("logs").glob("scheduler_daemon*.log")) + list(Path("logs").glob("putsengine_startup*.log"))
    
    premarket_scans_today = []
    
    for log_file in log_files:
        try:
            content = log_file.read_text()
            lines = content.split('\n')
            
            for line in lines:
                # Look for pre-market scan entries from today
                if str(today) in line and ('Pre-Market' in line or 'Gap Scan' in line or 'Earnings Priority' in line):
                    if 'Next run' not in line:  # Exclude "Next run at" messages
                        premarket_scans_today.append(line.strip()[:100])
        except Exception:
            pass
    
    if premarket_scans_today:
        print(f"   ✅ Found {len(premarket_scans_today)} pre-market scan entries today")
        for scan in premarket_scans_today[:5]:
            print(f"      • {scan[:80]}...")
        return True
    else:
        print(f"   ⚠️  No pre-market scan entries found for today")
        print(f"      (Pre-market scans run at 4:00, 6:00, 7:00, 8:00, 9:15 AM ET)")
        print(f"      Current time: {now.strftime('%H:%M ET')}")
        
        # Check what's scheduled next
        if now.hour < 16:  # During trading day
            return 'pending'
        return 'partial'


async def main():
    print("=" * 70)
    print("🔍 PUTSENGINE COMPREHENSIVE VALIDATION")
    print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    # Test all APIs
    results = {}
    
    results['alpaca'] = await test_alpaca()
    results['polygon'] = await test_polygon()
    results['unusual_whales'] = await test_unusual_whales()
    results['finviz'] = await test_finviz()
    results['scheduler'] = check_scheduler_status()
    results['recent_scans'] = check_recent_scans()
    results['premarket'] = check_premarket_scans()
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 VALIDATION SUMMARY")
    print("=" * 70)
    
    all_good = True
    for item, status in results.items():
        if status == True:
            icon = "✅"
        elif status == 'partial' or status == 'pending':
            icon = "⚠️ "
            all_good = False
        else:
            icon = "❌"
            all_good = False
        print(f"  {icon} {item.upper().replace('_', ' ')}")
    
    print("\n" + "=" * 70)
    if all_good:
        print("✅ ALL SYSTEMS OPERATIONAL")
    else:
        print("⚠️  SOME ISSUES DETECTED - See details above")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
