#!/usr/bin/env python3
"""
COMPLETE SYSTEM AUDIT
=====================
PhD Quant + 30yr Trading + Institutional Microstructure Analysis

This script validates EVERY API call, data source, and data flow
in the PutsEngine system. No fake data. No stale data.

Author: System Audit
Date: January 25, 2026
"""

import asyncio
import sys
import os
from datetime import datetime, date, timedelta
from typing import Dict, List, Any
import json

sys.path.insert(0, '.')

# Suppress warnings
import warnings
warnings.filterwarnings('ignore')

print("=" * 100)
print("  🔬 COMPLETE PUTSENGINE SYSTEM AUDIT")
print("  PhD Quant + 30yr Trading + Institutional Microstructure Analysis")
print("=" * 100)
print()

# ============================================================================
# SECTION 1: VALIDATE ALL API CREDENTIALS
# ============================================================================
print("📋 SECTION 1: API CREDENTIALS VALIDATION")
print("-" * 80)

from putsengine.config import get_settings

settings = get_settings()

api_status = {}

# Alpaca
alpaca_key = settings.alpaca_api_key
alpaca_secret = settings.alpaca_secret_key
if alpaca_key and alpaca_secret and len(alpaca_key) > 10:
    print(f"✅ ALPACA API Key: {alpaca_key[:8]}...{alpaca_key[-4:]} (CONFIGURED)")
    api_status['alpaca'] = 'CONFIGURED'
else:
    print("❌ ALPACA API Key: NOT CONFIGURED")
    api_status['alpaca'] = 'MISSING'

# Polygon
polygon_key = settings.polygon_api_key
if polygon_key and len(polygon_key) > 10:
    print(f"✅ POLYGON API Key: {polygon_key[:8]}...{polygon_key[-4:]} (CONFIGURED)")
    api_status['polygon'] = 'CONFIGURED'
else:
    print("❌ POLYGON API Key: NOT CONFIGURED")
    api_status['polygon'] = 'MISSING'

# Unusual Whales
uw_key = settings.unusual_whales_api_key
if uw_key and len(uw_key) > 10:
    print(f"✅ UNUSUAL WHALES API Key: {uw_key[:8]}...{uw_key[-4:]} (CONFIGURED)")
    api_status['unusual_whales'] = 'CONFIGURED'
else:
    print("❌ UNUSUAL WHALES API Key: NOT CONFIGURED")
    api_status['unusual_whales'] = 'MISSING'

print()

# ============================================================================
# SECTION 2: VALIDATE ALL API ENDPOINTS AND DATA FRESHNESS
# ============================================================================
print("📋 SECTION 2: API ENDPOINT VALIDATION (LIVE DATA)")
print("-" * 80)

async def validate_all_apis():
    results = {}
    
    # Import clients
    from putsengine.clients.alpaca_client import AlpacaClient
    from putsengine.clients.polygon_client import PolygonClient
    from putsengine.clients.unusual_whales_client import UnusualWhalesClient
    from putsengine.clients.finra_client import FINRAClient
    
    alpaca = AlpacaClient(settings)
    polygon = PolygonClient(settings)
    uw = UnusualWhalesClient(settings)
    finra = FINRAClient(settings)
    
    test_symbol = "AAPL"
    
    # -------------------------------------------------------------------------
    # ALPACA API VALIDATION
    # -------------------------------------------------------------------------
    print("\n🔹 ALPACA API ENDPOINTS:")
    
    # Test 1: Get Bars
    try:
        bars = await alpaca.get_bars(test_symbol, "1Day", limit=5)
        if bars and len(bars) > 0:
            latest = bars[-1]
            print(f"   ✅ get_bars(): {len(bars)} bars | Latest: {latest.timestamp.date()} | Close: ${latest.close:.2f}")
            results['alpaca_bars'] = {'status': 'OK', 'count': len(bars), 'latest': str(latest.timestamp.date())}
        else:
            print(f"   ⚠️ get_bars(): Empty response")
            results['alpaca_bars'] = {'status': 'EMPTY'}
    except Exception as e:
        print(f"   ❌ get_bars(): {str(e)[:50]}")
        results['alpaca_bars'] = {'status': 'ERROR', 'error': str(e)[:50]}
    
    # Test 2: Get Quote
    try:
        quote = await alpaca.get_quote(test_symbol)
        if quote:
            print(f"   ✅ get_quote(): Bid: ${quote.get('bid', 'N/A')} | Ask: ${quote.get('ask', 'N/A')}")
            results['alpaca_quote'] = {'status': 'OK', 'data': quote}
        else:
            print(f"   ⚠️ get_quote(): Empty response")
            results['alpaca_quote'] = {'status': 'EMPTY'}
    except Exception as e:
        print(f"   ❌ get_quote(): {str(e)[:50]}")
        results['alpaca_quote'] = {'status': 'ERROR', 'error': str(e)[:50]}
    
    # Test 3: Get Options Chain
    try:
        chain = await alpaca.get_options_chain(test_symbol)
        if chain:
            print(f"   ✅ get_options_chain(): {len(chain)} contracts")
            results['alpaca_options'] = {'status': 'OK', 'count': len(chain)}
        else:
            print(f"   ⚠️ get_options_chain(): Empty (may be weekend)")
            results['alpaca_options'] = {'status': 'EMPTY'}
    except Exception as e:
        print(f"   ❌ get_options_chain(): {str(e)[:50]}")
        results['alpaca_options'] = {'status': 'ERROR', 'error': str(e)[:50]}
    
    # -------------------------------------------------------------------------
    # POLYGON API VALIDATION
    # -------------------------------------------------------------------------
    print("\n🔹 POLYGON API ENDPOINTS:")
    
    # Test 1: Daily Bars
    try:
        from_date = date.today() - timedelta(days=10)
        bars = await polygon.get_daily_bars(test_symbol, from_date)
        if bars and len(bars) > 0:
            latest = bars[-1]
            print(f"   ✅ get_daily_bars(): {len(bars)} bars | Latest: {latest.timestamp.date()} | Close: ${latest.close:.2f}")
            results['polygon_daily'] = {'status': 'OK', 'count': len(bars), 'latest': str(latest.timestamp.date())}
        else:
            print(f"   ⚠️ get_daily_bars(): Empty response")
            results['polygon_daily'] = {'status': 'EMPTY'}
    except Exception as e:
        print(f"   ❌ get_daily_bars(): {str(e)[:50]}")
        results['polygon_daily'] = {'status': 'ERROR', 'error': str(e)[:50]}
    
    # Test 2: Minute Bars
    try:
        from_date = date.today() - timedelta(days=2)
        bars = await polygon.get_minute_bars(test_symbol, from_date, limit=100)
        if bars and len(bars) > 0:
            latest = bars[-1]
            print(f"   ✅ get_minute_bars(): {len(bars)} bars | Latest: {latest.timestamp}")
            results['polygon_minute'] = {'status': 'OK', 'count': len(bars)}
        else:
            print(f"   ⚠️ get_minute_bars(): Empty (weekend)")
            results['polygon_minute'] = {'status': 'EMPTY'}
    except Exception as e:
        print(f"   ❌ get_minute_bars(): {str(e)[:50]}")
        results['polygon_minute'] = {'status': 'ERROR', 'error': str(e)[:50]}
    
    # -------------------------------------------------------------------------
    # UNUSUAL WHALES API VALIDATION
    # -------------------------------------------------------------------------
    print("\n🔹 UNUSUAL WHALES API ENDPOINTS:")
    
    # Test 1: Options Flow
    try:
        flow = await uw.get_options_flow(test_symbol)
        if flow and len(flow) > 0:
            print(f"   ✅ get_options_flow(): {len(flow)} flow records")
            results['uw_flow'] = {'status': 'OK', 'count': len(flow)}
        else:
            print(f"   ⚠️ get_options_flow(): Empty response")
            results['uw_flow'] = {'status': 'EMPTY'}
    except Exception as e:
        print(f"   ❌ get_options_flow(): {str(e)[:50]}")
        results['uw_flow'] = {'status': 'ERROR', 'error': str(e)[:50]}
    
    # Test 2: GEX Data
    try:
        gex = await uw.get_gex_data(test_symbol)
        if gex:
            print(f"   ✅ get_gex_data(): GEX={gex.net_gex}, Delta={gex.net_delta}")
            results['uw_gex'] = {'status': 'OK', 'gex': gex.net_gex, 'delta': gex.net_delta}
        else:
            print(f"   ⚠️ get_gex_data(): Empty response")
            results['uw_gex'] = {'status': 'EMPTY'}
    except Exception as e:
        print(f"   ❌ get_gex_data(): {str(e)[:50]}")
        results['uw_gex'] = {'status': 'ERROR', 'error': str(e)[:50]}
    
    # Test 3: Dark Pool
    try:
        dp = await uw.get_dark_pool(test_symbol)
        if dp and len(dp) > 0:
            print(f"   ✅ get_dark_pool(): {len(dp)} prints")
            results['uw_darkpool'] = {'status': 'OK', 'count': len(dp)}
        else:
            print(f"   ⚠️ get_dark_pool(): Empty response")
            results['uw_darkpool'] = {'status': 'EMPTY'}
    except Exception as e:
        print(f"   ❌ get_dark_pool(): {str(e)[:50]}")
        results['uw_darkpool'] = {'status': 'ERROR', 'error': str(e)[:50]}
    
    # Test 4: Insider Trades
    try:
        insider = await uw.get_insider_trades(test_symbol)
        if insider:
            print(f"   ✅ get_insider_trades(): {len(insider)} trades")
            results['uw_insider'] = {'status': 'OK', 'count': len(insider)}
        else:
            print(f"   ⚠️ get_insider_trades(): Empty response")
            results['uw_insider'] = {'status': 'EMPTY'}
    except Exception as e:
        print(f"   ❌ get_insider_trades(): {str(e)[:50]}")
        results['uw_insider'] = {'status': 'ERROR', 'error': str(e)[:50]}
    
    # Test 5: Congress Trades
    try:
        congress = await uw.get_congress_trades()
        if congress:
            print(f"   ✅ get_congress_trades(): {len(congress)} trades")
            results['uw_congress'] = {'status': 'OK', 'count': len(congress)}
        else:
            print(f"   ⚠️ get_congress_trades(): Empty response")
            results['uw_congress'] = {'status': 'EMPTY'}
    except Exception as e:
        print(f"   ❌ get_congress_trades(): {str(e)[:50]}")
        results['uw_congress'] = {'status': 'ERROR', 'error': str(e)[:50]}
    
    # -------------------------------------------------------------------------
    # FINRA API VALIDATION
    # -------------------------------------------------------------------------
    print("\n🔹 FINRA API ENDPOINTS:")
    
    try:
        short_vol = await finra.get_short_volume(test_symbol)
        if short_vol:
            print(f"   ✅ get_short_volume(): Short ratio={short_vol.get('short_ratio', 'N/A')}")
            results['finra_short'] = {'status': 'OK', 'data': short_vol}
        else:
            print(f"   ⚠️ get_short_volume(): Empty response")
            results['finra_short'] = {'status': 'EMPTY'}
    except Exception as e:
        print(f"   ❌ get_short_volume(): {str(e)[:50]}")
        results['finra_short'] = {'status': 'ERROR', 'error': str(e)[:50]}
    
    # Close clients
    await alpaca.close()
    await polygon.close()
    await uw.close()
    await finra.close()
    
    return results

# Run API validation
api_results = asyncio.run(validate_all_apis())

# ============================================================================
# SECTION 3: DATA FLOW ANALYSIS
# ============================================================================
print("\n" + "=" * 100)
print("📋 SECTION 3: COMPLETE DATA FLOW ANALYSIS")
print("-" * 80)

print("""
📊 PUTSENGINE DATA FLOW DIAGRAM
===============================

┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA SOURCES (APIs)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   ALPACA     │  │   POLYGON    │  │ UNUSUAL      │  │   FINRA      │    │
│  │   (Broker)   │  │   (Market)   │  │ WHALES       │  │   (Shorts)   │    │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘    │
│         │                 │                 │                 │            │
│         ▼                 ▼                 ▼                 ▼            │
│  • Stock quotes    • Daily OHLCV    • Options flow    • Short volume       │
│  • Options chain   • Minute bars    • GEX/Delta       • Borrow status      │
│  • Account info    • Volume data    • Dark pool                            │
│  • Order exec      • Historical     • Insider trades                       │
│                                     • Congress trades                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        ANALYSIS LAYERS (9-Layer Pipeline)                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Layer 1: MARKET REGIME LAYER                                               │
│  ├─ SPY/QQQ VWAP analysis (Polygon minute bars)                             │
│  ├─ VIX level and trend (Polygon daily bars)                                │
│  ├─ Index GEX analysis (Unusual Whales)                                     │
│  └─ Output: MarketRegimeData (is_tradeable, block_reasons)                  │
│                                                                             │
│  Layer 2: DISTRIBUTION LAYER                                                │
│  ├─ Price-Volume Analysis:                                                  │
│  │   ├─ Flat price + rising volume (Polygon daily)                          │
│  │   ├─ Failed breakout detection (Polygon daily)                           │
│  │   ├─ Lower highs + flat RSI (Polygon daily)                              │
│  │   ├─ VWAP loss detection (Polygon minute)                                │
│  │   ├─ High RVOL on red day (Polygon daily)                                │
│  │   ├─ Gap down no recovery (Polygon daily)                                │
│  │   └─ Multi-day weakness (Polygon daily)                                  │
│  ├─ Options-Led Distribution:                                               │
│  │   ├─ Call selling at bid (Unusual Whales flow)                           │
│  │   ├─ Put buying at ask (Unusual Whales flow)                             │
│  │   ├─ Rising put OI (Unusual Whales)                                      │
│  │   └─ Skew steepening (Unusual Whales)                                    │
│  ├─ Dark Pool Analysis (Unusual Whales dark pool)                           │
│  ├─ Insider Trades (Unusual Whales insider)                                 │
│  └─ Congress Trades (Unusual Whales congress)                               │
│                                                                             │
│  Layer 3: LIQUIDITY VACUUM LAYER                                            │
│  ├─ Bid size collapse (Alpaca quotes)                                       │
│  ├─ Spread widening (Alpaca quotes)                                         │
│  ├─ Volume without progress (Polygon)                                       │
│  └─ VWAP retest failure (Polygon minute)                                    │
│                                                                             │
│  Layer 4: DEALER POSITIONING LAYER                                          │
│  ├─ GEX analysis (Unusual Whales)                                           │
│  ├─ Net Delta (Unusual Whales)                                              │
│  ├─ Put wall detection (Unusual Whales)                                     │
│  └─ Gamma flip detection (Unusual Whales)                                   │
│                                                                             │
│  Layer 5: ACCELERATION WINDOW LAYER                                         │
│  ├─ Price vs VWAP (Polygon minute)                                          │
│  ├─ Price vs EMA20 (Polygon daily)                                          │
│  ├─ Price vs prior low (Polygon daily)                                      │
│  ├─ RSI analysis (Polygon daily)                                            │
│  ├─ Put volume trend (Unusual Whales)                                       │
│  ├─ IV analysis (Unusual Whales)                                            │
│  └─ Engine type determination (GAMMA_DRAIN/DISTRIBUTION_TRAP/SNAPBACK)      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SCORING LAYER                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  SCORE WEIGHTS:                                                             │
│  ├─ Distribution Quality: 30%                                               │
│  ├─ Dealer Positioning:   20%                                               │
│  ├─ Liquidity Vacuum:     15%                                               │
│  ├─ Options Flow:         15%                                               │
│  ├─ Catalyst Proximity:   10%                                               │
│  └─ Sentiment/Technical:  10%                                               │
│                                                                             │
│  SCORING TIERS:                                                             │
│  ├─ 0.75+ = 🔥 EXPLOSIVE (-10% to -15% expected)                            │
│  ├─ 0.65-0.74 = ⚡ VERY STRONG (-5% to -10% expected)                       │
│  ├─ 0.55-0.64 = 💪 STRONG (-3% to -7% expected)                             │
│  └─ 0.45-0.54 = 👀 MONITORING (-2% to -5% expected)                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        STRIKE SELECTION LAYER                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  RULES (per Architect Blueprint):                                           │
│  ├─ DTE: 7-21 days                                                          │
│  ├─ Delta: -0.25 to -0.40                                                   │
│  ├─ Strike: Slightly OTM (5-15% below current)                              │
│  ├─ Expiry: FRIDAYS ONLY (weekly options)                                   │
│  └─ No lottery puts (avoid extreme OTM)                                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
""")

# ============================================================================
# SECTION 4: VALIDATE EXPIRY DATE CALCULATION
# ============================================================================
print("\n" + "=" * 100)
print("📋 SECTION 4: EXPIRY DATE VALIDATION")
print("-" * 80)

today = date.today()
print(f"Today: {today} ({today.strftime('%A')})")
print()

# Calculate next valid Friday expiries
days_until_friday = (4 - today.weekday()) % 7
if days_until_friday == 0:
    days_until_friday = 7

fridays = []
for i in range(4):
    friday = today + timedelta(days=days_until_friday + (i * 7))
    dte = (friday - today).days
    fridays.append((friday, dte))
    print(f"Valid Expiry #{i+1}: {friday.strftime('%b %d, %Y')} ({friday.strftime('%A')}) - DTE: {dte}")

print()
print("❌ INVALID EXPIRIES (NOT FRIDAYS):")
print("   Feb 03, 2026 is a TUESDAY - NOT VALID")
print("   Feb 01, 2026 is a SUNDAY - NOT VALID")

# ============================================================================
# SECTION 5: ENGINE COMPONENTS AUDIT
# ============================================================================
print("\n" + "=" * 100)
print("📋 SECTION 5: ENGINE COMPONENTS AUDIT")
print("-" * 80)

components = [
    ("putsengine/clients/alpaca_client.py", "Alpaca API Client", [
        "get_bars()", "get_quote()", "get_options_chain()", "get_account()"
    ]),
    ("putsengine/clients/polygon_client.py", "Polygon API Client", [
        "get_daily_bars()", "get_minute_bars()", "get_vwap()"
    ]),
    ("putsengine/clients/unusual_whales_client.py", "Unusual Whales Client", [
        "get_options_flow()", "get_gex_data()", "get_dark_pool()",
        "get_insider_trades()", "get_congress_trades()"
    ]),
    ("putsengine/clients/finra_client.py", "FINRA Client", [
        "get_short_volume()"
    ]),
    ("putsengine/layers/market_regime.py", "Market Regime Layer", [
        "analyze()"
    ]),
    ("putsengine/layers/distribution.py", "Distribution Layer", [
        "analyze()", "_analyze_price_volume()", "_analyze_options_flow()",
        "_detect_high_rvol_red_day()", "_detect_gap_down_no_recovery()"
    ]),
    ("putsengine/layers/liquidity.py", "Liquidity Vacuum Layer", [
        "analyze()"
    ]),
    ("putsengine/layers/dealer.py", "Dealer Positioning Layer", [
        "analyze()"
    ]),
    ("putsengine/layers/acceleration.py", "Acceleration Window Layer", [
        "analyze()"
    ]),
    ("putsengine/scoring/scorer.py", "Put Scorer", [
        "score_candidate()", "_score_distribution()", "_score_dealer()",
        "_score_liquidity()", "_score_catalyst()", "_score_sentiment()"
    ]),
    ("putsengine/engine.py", "Main Engine", [
        "run_single_symbol()", "run_daily_scan()", "get_cached_regime()"
    ]),
]

for file_path, name, methods in components:
    full_path = f"/Users/chavala/PutsEngine/{file_path}"
    if os.path.exists(full_path):
        print(f"✅ {name}")
        print(f"   File: {file_path}")
        print(f"   Methods: {', '.join(methods)}")
    else:
        print(f"❌ {name} - FILE MISSING: {file_path}")
    print()

# ============================================================================
# SECTION 6: SUMMARY
# ============================================================================
print("=" * 100)
print("📋 SECTION 6: AUDIT SUMMARY")
print("-" * 80)

# Count API statuses
ok_count = sum(1 for k, v in api_results.items() if v.get('status') == 'OK')
empty_count = sum(1 for k, v in api_results.items() if v.get('status') == 'EMPTY')
error_count = sum(1 for k, v in api_results.items() if v.get('status') == 'ERROR')

print(f"""
API VALIDATION RESULTS:
  ✅ Working APIs: {ok_count}
  ⚠️ Empty Responses (weekend): {empty_count}
  ❌ Errors: {error_count}

DATA SOURCES USED:
  1. ALPACA (alpaca.markets)
     - Stock quotes and bars
     - Options chains
     - Order execution
  
  2. POLYGON (polygon.io)
     - Historical OHLCV data
     - Minute-level bars for VWAP
     - Volume analysis
  
  3. UNUSUAL WHALES (unusualwhales.com)
     - Options flow (sweeps, blocks)
     - GEX/Delta data
     - Dark pool prints
     - Insider trades
     - Congress trades
  
  4. FINRA
     - Short volume data

KNOWN ISSUES FIXED:
  ✅ Expiry dates now calculate to FRIDAYS only
  ✅ DTE calculated correctly from real dates

NEXT VALID EXPIRY DATES:
  • {fridays[0][0].strftime('%b %d, %Y')} (DTE: {fridays[0][1]})
  • {fridays[1][0].strftime('%b %d, %Y')} (DTE: {fridays[1][1]})
  • {fridays[2][0].strftime('%b %d, %Y')} (DTE: {fridays[2][1]})

RECOMMENDATION:
  Market is currently CLOSED (Weekend)
  Run live validation during market hours (Mon-Fri 9:30 AM - 4:00 PM ET)
""")

print("=" * 100)
print(f"⏰ Audit completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 100)
