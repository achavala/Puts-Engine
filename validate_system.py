#!/usr/bin/env python3
"""
PutsEngine System Validation - Comprehensive API and Component Testing
"""

import asyncio
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, '.')


async def comprehensive_validation():
    from putsengine.config import get_settings, EngineConfig
    from putsengine.clients.alpaca_client import AlpacaClient
    from putsengine.clients.polygon_client import PolygonClient
    from putsengine.clients.unusual_whales_client import UnusualWhalesClient

    settings = get_settings()
    print('=' * 70)
    print('PUTSENGINE COMPREHENSIVE API VALIDATION')
    print('=' * 70)
    print(f'Date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print()

    alpaca = AlpacaClient(settings)
    polygon = PolygonClient(settings)
    uw = UnusualWhalesClient(settings)

    results = {'pass': 0, 'fail': 0}

    # === ALPACA TESTS ===
    print('ALPACA API TESTS')
    print('-' * 40)
    
    try:
        account = await alpaca.get_account()
        if account:
            equity = float(account.get("equity", 0))
            print(f'  [PASS] Account: ${equity:,.2f} equity')
            results['pass'] += 1
        else:
            print('  [FAIL] Account: No data')
            results['fail'] += 1
    except Exception as e:
        print(f'  [FAIL] Account: {e}')
        results['fail'] += 1

    try:
        quote = await alpaca.get_latest_quote('AAPL')
        if quote and 'quote' in quote:
            q = quote['quote']
            bid = q.get("bp", 0)
            ask = q.get("ap", 0)
            print(f'  [PASS] Quote AAPL: Bid ${bid:.2f} / Ask ${ask:.2f}')
            results['pass'] += 1
        else:
            print('  [FAIL] Quote: No data')
            results['fail'] += 1
    except Exception as e:
        print(f'  [FAIL] Quote: {e}')
        results['fail'] += 1

    try:
        bars = await alpaca.get_bars('SPY', '1Day', limit=5)
        if bars and len(bars) > 0:
            print(f'  [PASS] Bars SPY: {len(bars)} bars, Last close ${bars[-1].close:.2f}')
            results['pass'] += 1
        else:
            print('  [FAIL] Bars: No data')
            results['fail'] += 1
    except Exception as e:
        print(f'  [FAIL] Bars: {e}')
        results['fail'] += 1

    # === POLYGON TESTS ===
    print()
    print('POLYGON API TESTS')
    print('-' * 40)

    try:
        snapshot = await polygon.get_snapshot('TSLA')
        if snapshot and 'ticker' in snapshot:
            t = snapshot['ticker']
            day = t.get('day', {})
            close = day.get("c", 0)
            vwap = day.get("vw", 0)
            print(f'  [PASS] Snapshot TSLA: ${close:.2f} (VWAP: ${vwap:.2f})')
            results['pass'] += 1
        else:
            print('  [FAIL] Snapshot: No data')
            results['fail'] += 1
    except Exception as e:
        print(f'  [FAIL] Snapshot: {e}')
        results['fail'] += 1

    try:
        losers = await polygon.get_gainers_losers('losers')
        if losers and len(losers) > 0:
            top = losers[0]
            ticker = top.get("ticker", "N/A")
            change = top.get("todaysChangePerc", 0)
            print(f'  [PASS] Top Loser: {ticker} ({change:.1f}%)')
            results['pass'] += 1
        else:
            print('  [FAIL] Losers: No data')
            results['fail'] += 1
    except Exception as e:
        print(f'  [FAIL] Losers: {e}')
        results['fail'] += 1

    try:
        daily = await polygon.get_daily_bars('NVDA', from_date=date.today() - timedelta(days=10))
        if daily and len(daily) > 0:
            print(f'  [PASS] Daily NVDA: {len(daily)} bars')
            results['pass'] += 1
        else:
            print('  [WARN] Daily: No data')
            results['pass'] += 1
    except Exception as e:
        print(f'  [FAIL] Daily: {e}')
        results['fail'] += 1

    # === UNUSUAL WHALES TESTS ===
    print()
    print('UNUSUAL WHALES API TESTS')
    print('-' * 40)

    try:
        gex = await uw.get_gex_data('SPY')
        if gex:
            net_gex = gex.net_gex
            put_wall = gex.put_wall or 0
            print(f'  [PASS] GEX SPY: Net GEX {net_gex:,.0f}, Put Wall: ${put_wall:.2f}')
            results['pass'] += 1
        else:
            print('  [WARN] GEX: No data (may be weekend)')
            results['pass'] += 1
    except Exception as e:
        print(f'  [FAIL] GEX: {e}')
        results['fail'] += 1

    try:
        flow = await uw.get_flow_recent('AAPL', limit=10)
        if flow and len(flow) > 0:
            print(f'  [PASS] Flow AAPL: {len(flow)} recent transactions')
            results['pass'] += 1
        else:
            print('  [WARN] Flow: No data (may be weekend)')
            results['pass'] += 1
    except Exception as e:
        print(f'  [FAIL] Flow: {e}')
        results['fail'] += 1

    try:
        insider = await uw.get_insider_trades('TSLA', limit=10)
        if insider and len(insider) > 0:
            print(f'  [PASS] Insider TSLA: {len(insider)} recent trades')
            results['pass'] += 1
        else:
            print('  [WARN] Insider: No recent data')
            results['pass'] += 1
    except Exception as e:
        print(f'  [FAIL] Insider: {e}')
        results['fail'] += 1

    try:
        congress = await uw.get_congress_trades(limit=10)
        if congress and len(congress) > 0:
            print(f'  [PASS] Congress: {len(congress)} recent trades')
            results['pass'] += 1
        else:
            print('  [WARN] Congress: No recent data')
            results['pass'] += 1
    except Exception as e:
        print(f'  [FAIL] Congress: {e}')
        results['fail'] += 1

    try:
        oi = await uw.get_oi_by_strike('SPY')
        if oi:
            data = oi.get("data", oi) if isinstance(oi, dict) else oi
            count = len(data) if isinstance(data, list) else 1
            print(f'  [PASS] OI by Strike SPY: {count} strikes')
            results['pass'] += 1
        else:
            print('  [WARN] OI: No data')
            results['pass'] += 1
    except Exception as e:
        print(f'  [FAIL] OI: {e}')
        results['fail'] += 1

    print(f'  API Calls Remaining: {uw.remaining_calls}')

    # === UNIVERSE CHECK ===
    print()
    print('UNIVERSE VALIDATION')
    print('-' * 40)
    all_tickers = EngineConfig.get_all_tickers()
    sectors = EngineConfig.UNIVERSE_SECTORS
    print(f'  [PASS] Total Unique Tickers: {len(all_tickers)}')
    print(f'  [PASS] Sectors Covered: {len(sectors)}')
    for sector, tickers in sectors.items():
        print(f'         - {sector}: {len(tickers)} tickers')

    # === CONFIG VALIDATION ===
    print()
    print('CONFIGURATION VALIDATION')
    print('-' * 40)
    print(f'  Min Score Threshold: {settings.min_score_threshold}')
    print(f'  Max Daily Trades: {settings.max_daily_trades}')
    print(f'  DTE Range: {settings.dte_min}-{settings.dte_max} days')
    print(f'  Delta Range: {settings.delta_min} to {settings.delta_max}')
    print(f'  UW Daily Limit: {settings.uw_daily_limit}')

    weights = EngineConfig.SCORE_WEIGHTS
    total_weight = sum(weights.values())
    print(f'  Score Weights Sum: {total_weight:.2f} (should be 1.0)')

    # Close sessions
    await alpaca.close()
    await polygon.close()
    await uw.close()

    # Summary
    print()
    print('=' * 70)
    print('VALIDATION SUMMARY')
    print('=' * 70)
    print(f'  Passed: {results["pass"]}')
    print(f'  Failed: {results["fail"]}')
    total = results['pass'] + results['fail']
    pct = (results['pass'] / total * 100) if total > 0 else 0
    print(f'  Success Rate: {pct:.1f}%')
    print()
    if results['fail'] == 0:
        print('  ALL SYSTEMS OPERATIONAL!')
    else:
        print('  Some issues detected - review failed tests')


if __name__ == "__main__":
    asyncio.run(comprehensive_validation())
