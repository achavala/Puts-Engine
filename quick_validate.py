#!/usr/bin/env python3
"""Quick data source validation."""

import asyncio
import sys
sys.path.insert(0, '/Users/chavala/PutsEngine')

from datetime import date, timedelta
from putsengine.config import get_settings
from putsengine.clients.unusual_whales_client import UnusualWhalesClient
from putsengine.clients.polygon_client import PolygonClient


async def test():
    settings = get_settings()
    uw = UnusualWhalesClient(settings)
    polygon = PolygonClient(settings)
    
    print('=' * 60)
    print('COMPREHENSIVE DATA SOURCE VALIDATION')
    print('=' * 60)
    
    tests_passed = {"polygon": 0, "uw": 0}
    tests_total = {"polygon": 0, "uw": 0}
    
    # === POLYGON TESTS ===
    print('\n📊 POLYGON (MASSIVE) API TESTS')
    print('-' * 40)
    
    # Polygon Snapshot
    tests_total["polygon"] += 1
    try:
        snap = await polygon.get_snapshot('AAPL')
        if snap and 'ticker' in snap:
            price = snap['ticker'].get('lastTrade', {}).get('p', 0)
            print(f'✅ Snapshot: AAPL @ ${price:.2f}')
            tests_passed["polygon"] += 1
        else:
            print('❌ Snapshot: No data')
    except Exception as e:
        print(f'❌ Snapshot: {e}')
    
    # Polygon Daily Bars
    tests_total["polygon"] += 1
    try:
        bars = await polygon.get_daily_bars('NVDA', date.today() - timedelta(days=7), date.today())
        if bars:
            print(f'✅ Daily Bars: {len(bars)} bars for NVDA')
            tests_passed["polygon"] += 1
        else:
            print('❌ Daily Bars: No data')
    except Exception as e:
        print(f'❌ Daily Bars: {e}')
    
    # Polygon Latest Quote
    tests_total["polygon"] += 1
    try:
        quote = await polygon.get_latest_quote('TSLA')
        if quote:
            print(f'✅ Latest Quote: TSLA price ${quote.get("price", 0):.2f}')
            tests_passed["polygon"] += 1
        else:
            print('❌ Latest Quote: No data')
    except Exception as e:
        print(f'❌ Latest Quote: {e}')
    
    # Polygon Latest Bar
    tests_total["polygon"] += 1
    try:
        bar = await polygon.get_latest_bar('META')
        if bar:
            print(f'✅ Latest Bar: META O:{bar.open:.2f} H:{bar.high:.2f} L:{bar.low:.2f} C:{bar.close:.2f}')
            tests_passed["polygon"] += 1
        else:
            print('❌ Latest Bar: No data')
    except Exception as e:
        print(f'❌ Latest Bar: {e}')
    
    # Polygon Intraday Change
    tests_total["polygon"] += 1
    try:
        change = await polygon.get_intraday_change('GOOGL')
        if change is not None:
            print(f'✅ Intraday Change: GOOGL {change:+.2f}%')
            tests_passed["polygon"] += 1
        else:
            print('❌ Intraday Change: No data')
    except Exception as e:
        print(f'❌ Intraday Change: {e}')
    
    # === UW TESTS ===
    print('\n🐋 UNUSUAL WHALES API TESTS')
    print('-' * 40)
    
    # UW Dark Pool
    tests_total["uw"] += 1
    try:
        dp = await uw.get_dark_pool_flow('AAPL', limit=5)
        if dp:
            print(f'✅ Dark Pool: {len(dp)} prints for AAPL')
            tests_passed["uw"] += 1
        else:
            print('⚠️ Dark Pool: No data (possible cooldown)')
    except Exception as e:
        print(f'❌ Dark Pool: {e}')
    
    # UW Put Flow
    tests_total["uw"] += 1
    try:
        puts = await uw.get_put_flow('SPY', limit=5)
        if puts:
            print(f'✅ Put Flow: {len(puts)} records for SPY')
            tests_passed["uw"] += 1
        else:
            print('⚠️ Put Flow: No data (possible cooldown)')
    except Exception as e:
        print(f'❌ Put Flow: {e}')
    
    # UW IV Rank
    tests_total["uw"] += 1
    try:
        iv = await uw.get_iv_rank('NVDA')
        if iv and iv.get('data'):
            latest = iv['data'][-1] if isinstance(iv['data'], list) else iv['data']
            iv_rank = latest.get('iv_rank_1y', 'N/A')
            print(f'✅ IV Rank: NVDA IV Rank = {iv_rank}')
            tests_passed["uw"] += 1
        else:
            print('⚠️ IV Rank: No data')
    except Exception as e:
        print(f'❌ IV Rank: {e}')
    
    # UW GEX Data
    tests_total["uw"] += 1
    try:
        gex = await uw.get_gex_data('SPY')
        if gex:
            print(f'✅ GEX Data: SPY GEX available')
            tests_passed["uw"] += 1
        else:
            print('⚠️ GEX Data: No data')
    except Exception as e:
        print(f'❌ GEX Data: {e}')
    
    # UW Market Tide
    tests_total["uw"] += 1
    try:
        tide = await uw.get_market_tide()
        if tide:
            print(f'✅ Market Tide: Data available')
            tests_passed["uw"] += 1
        else:
            print('⚠️ Market Tide: No data')
    except Exception as e:
        print(f'❌ Market Tide: {e}')
    
    # UW OI Change
    tests_total["uw"] += 1
    try:
        oi = await uw.get_oi_change('TSLA')
        if oi:
            print(f'✅ OI Change: TSLA data available')
            tests_passed["uw"] += 1
        else:
            print('⚠️ OI Change: No data')
    except Exception as e:
        print(f'❌ OI Change: {e}')
    
    # === SUMMARY ===
    print('\n' + '=' * 60)
    print('SUMMARY')
    print('=' * 60)
    print(f'📊 POLYGON: {tests_passed["polygon"]}/{tests_total["polygon"]} tests passed')
    print(f'🐋 UW:      {tests_passed["uw"]}/{tests_total["uw"]} tests passed')
    
    total_passed = tests_passed["polygon"] + tests_passed["uw"]
    total_tests = tests_total["polygon"] + tests_total["uw"]
    
    print(f'\n📋 OVERALL: {total_passed}/{total_tests} tests passed')
    
    if total_passed == total_tests:
        print('\n✅ ALL DATA SOURCES WORKING - System Ready!')
    elif total_passed >= total_tests * 0.7:
        print('\n⚠️ MOST DATA SOURCES WORKING - Minor issues detected')
    else:
        print('\n❌ DATA SOURCE ISSUES - Check individual tests above')
    
    # Budget Status
    print('\n' + '=' * 60)
    print('UW API BUDGET STATUS')
    print('=' * 60)
    status = uw.get_budget_status()
    print(f'   Daily Limit: {status.get("daily_limit", "N/A")}')
    print(f'   Calls Used: {status.get("calls_used", "N/A")}')
    print(f'   Calls Remaining: {status.get("calls_remaining", "N/A")}')
    
    await uw.close()
    await polygon.close()


if __name__ == "__main__":
    asyncio.run(test())
