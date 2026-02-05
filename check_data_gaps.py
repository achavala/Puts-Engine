#!/usr/bin/env python3
"""Check available data sources to fill Market Direction Engine gaps."""

import asyncio
import sys
sys.path.insert(0, '/Users/chavala/PutsEngine')

from datetime import date, timedelta
from putsengine.config import get_settings
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient


async def check_sources():
    settings = get_settings()
    polygon = PolygonClient(settings)
    uw = UnusualWhalesClient(settings)
    
    print("=" * 60)
    print("CHECKING AVAILABLE DATA SOURCES FOR GAPS")
    print("=" * 60)
    
    results = {}
    
    # 1. Check Polygon News API
    print("\n1. POLYGON NEWS API")
    print("-" * 40)
    try:
        news = await polygon.get_ticker_news("SPY", limit=3)
        if news:
            print(f"   ✅ NEWS AVAILABLE: {len(news)} articles")
            for article in news[:2]:
                title = article.get('title', 'N/A')[:60]
                print(f"      - {title}...")
            results["news"] = True
        else:
            print("   ❌ No news data")
            results["news"] = False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        results["news"] = False
    
    # 2. Check Polygon Market Status
    print("\n2. POLYGON MARKET STATUS")
    print("-" * 40)
    try:
        status = await polygon.get_market_status()
        if status:
            print(f"   ✅ MARKET STATUS AVAILABLE")
            market = status.get('market', 'unknown')
            exchanges = status.get('exchanges', {})
            print(f"      Market: {market}")
            results["market_status"] = True
        else:
            print("   ❌ No market status")
            results["market_status"] = False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        results["market_status"] = False
    
    # 3. Check Polygon Gainers/Losers
    print("\n3. POLYGON TOP MOVERS (Pre-market indicator)")
    print("-" * 40)
    try:
        losers = await polygon.get_gainers_losers("losers")
        if losers:
            print(f"   ✅ TOP LOSERS: {len(losers)} tickers")
            for loser in losers[:3]:
                ticker = loser.get('ticker', 'N/A')
                change = loser.get('todaysChangePerc', 0)
                print(f"      - {ticker}: {change:.2f}%")
            results["movers"] = True
        else:
            print("   ⚠️ No losers data (may be after hours)")
            results["movers"] = False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        results["movers"] = False
    
    # 4. Check Polygon Historical Data Depth (for backtesting)
    print("\n4. POLYGON HISTORICAL DATA DEPTH")
    print("-" * 40)
    try:
        # Try to get 5 years of data
        old_date = date(2021, 1, 1)
        bars = await polygon.get_daily_bars("SPY", old_date, old_date + timedelta(days=30))
        if bars:
            print(f"   ✅ 5-YEAR+ HISTORICAL: Available")
            print(f"      Oldest bar: {bars[0].timestamp.strftime('%Y-%m-%d')}")
            results["historical_5yr"] = True
        else:
            print("   ❌ No historical data from 5 years ago")
            results["historical_5yr"] = False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        results["historical_5yr"] = False
    
    # Try 10 years
    try:
        old_date = date(2016, 1, 1)
        bars = await polygon.get_daily_bars("SPY", old_date, old_date + timedelta(days=30))
        if bars:
            print(f"   ✅ 10-YEAR HISTORICAL: Available")
            results["historical_10yr"] = True
        else:
            results["historical_10yr"] = False
    except Exception as e:
        results["historical_10yr"] = False
    
    # 5. Check UW for additional data
    print("\n5. UW ADDITIONAL ENDPOINTS")
    print("-" * 40)
    
    # Check flow alerts
    try:
        alerts = await uw.get_flow_alerts(limit=5)
        if alerts:
            print(f"   ✅ FLOW ALERTS: {len(alerts)} alerts available")
            results["uw_alerts"] = True
        else:
            print("   ⚠️ No flow alerts")
            results["uw_alerts"] = False
    except Exception as e:
        print(f"   ⚠️ Flow alerts: {e}")
        results["uw_alerts"] = False
    
    # Check skew data
    try:
        skew = await uw.get_skew("SPY")
        if skew:
            print(f"   ✅ OPTIONS SKEW: Available (sentiment indicator)")
            results["uw_skew"] = True
        else:
            print("   ⚠️ No skew data")
            results["uw_skew"] = False
    except Exception as e:
        print(f"   ⚠️ Skew: {e}")
        results["uw_skew"] = False
    
    # Check max pain
    try:
        max_pain = await uw.get_max_pain("SPY")
        if max_pain:
            print(f"   ✅ MAX PAIN: Available (key level indicator)")
            results["uw_max_pain"] = True
        else:
            print("   ⚠️ No max pain data")
            results["uw_max_pain"] = False
    except Exception as e:
        print(f"   ⚠️ Max pain: {e}")
        results["uw_max_pain"] = False
    
    await polygon.close()
    await uw.close()
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY: WHAT WE CAN USE TO FILL GAPS")
    print("=" * 60)
    
    print("\n📰 NEWS EVENTS:")
    if results.get("news"):
        print("   ✅ Polygon News API - AVAILABLE")
        print("   → Can integrate market-moving news into direction analysis")
    else:
        print("   ❌ Not available")
    
    print("\n📊 FUTURES PROXY:")
    if results.get("movers"):
        print("   ✅ Polygon Top Movers - AVAILABLE")
        print("   → Pre-market movers act as futures proxy")
    print("   ✅ SPY/QQQ Pre-market prices - AVAILABLE")
    print("   → Already using in Market Direction Engine")
    
    print("\n📈 BACKTESTING DATA:")
    if results.get("historical_10yr"):
        print("   ✅ 10-Year Historical Data - AVAILABLE")
    elif results.get("historical_5yr"):
        print("   ✅ 5-Year Historical Data - AVAILABLE")
    print("   → Can backtest price-based signals")
    print("   ⚠️ GEX historical: UW has ~1 year only")
    
    print("\n🎯 SENTIMENT INDICATORS:")
    if results.get("uw_skew"):
        print("   ✅ Options Skew - AVAILABLE (better than Reddit!)")
    if results.get("uw_max_pain"):
        print("   ✅ Max Pain - AVAILABLE (key magnet level)")
    
    print("\n" + "=" * 60)
    print("RECOMMENDATION: ADD THESE TO MARKET DIRECTION ENGINE")
    print("=" * 60)
    print("""
1. ✅ NEWS INTEGRATION (Polygon)
   - Check for market-moving news at 8 AM
   - Filter by keywords: Fed, CPI, Jobs, Earnings
   
2. ✅ TOP MOVERS (Polygon) - Futures Proxy
   - Pre-market losers indicate risk-off
   - Pre-market gainers indicate risk-on
   
3. ✅ OPTIONS SKEW (UW) - Better than Reddit!
   - Skew tells you what smart money expects
   - More reliable than social sentiment
   
4. ✅ MAX PAIN (UW)
   - Where market makers want price
   - Key magnet level for direction
   
5. ✅ 5+ YEAR BACKTEST
   - Can backtest SPY/QQQ patterns
   - VIX levels vs. outcomes
""")


if __name__ == "__main__":
    asyncio.run(check_sources())
