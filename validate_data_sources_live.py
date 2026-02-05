#!/usr/bin/env python3
"""
Live validation of all PutsEngine data sources.
Run: python validate_data_sources_live.py
"""

import asyncio
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
load_dotenv()

async def validate_all_sources():
    print('=' * 60)
    print('LIVE DATA SOURCE VALIDATION - Feb 4, 2026')
    print('=' * 60)
    print()
    
    # Test tickers - the missed stocks
    test_tickers = ['AMD', 'PLTR', 'APP', 'COHR', 'SNDK']
    
    # 1. ALPACA
    print('1. ALPACA API (Stock Data)')
    print('-' * 40)
    try:
        from putsengine.clients.alpaca_client import AlpacaClient
        alpaca = AlpacaClient()
        
        for symbol in test_tickers[:2]:
            # Test quote
            quote = await alpaca.get_latest_quote(symbol)
            if quote:
                price = getattr(quote, 'bid_price', None) or getattr(quote, 'ap', 'N/A')
                print(f'   ✅ {symbol} quote: ${price}')
            else:
                print(f'   ⚠️ {symbol}: No quote data')
        
        # Test bars
        bars = await alpaca.get_daily_bars('AMD', limit=5)
        if bars:
            print(f'   ✅ Historical bars: {len(bars)} days')
            if bars:
                last_bar = bars[-1]
                print(f'      Latest: Close=${getattr(last_bar, "close", "N/A")}')
        else:
            print('   ⚠️ No historical bars')
    except Exception as e:
        print(f'   ❌ ALPACA Error: {e}')
    print()
    
    # 2. POLYGON
    print('2. POLYGON API (Options Data)')
    print('-' * 40)
    try:
        from putsengine.clients.polygon_client import PolygonClient
        polygon = PolygonClient()
        
        # Test options chain
        chain = await polygon.get_options_chain('AMD')
        if chain:
            print(f'   ✅ AMD options chain: {len(chain)} contracts')
            puts = [c for c in chain if getattr(c, 'contract_type', '').lower() == 'put']
            calls = [c for c in chain if getattr(c, 'contract_type', '').lower() == 'call']
            print(f'      Puts: {len(puts)}, Calls: {len(calls)}')
        else:
            print('   ⚠️ No options chain data')
    except Exception as e:
        print(f'   ❌ POLYGON Error: {e}')
    print()
    
    # 3. UNUSUAL WHALES (Critical!)
    print('3. UNUSUAL WHALES API (Options Flow + Dark Pool)')
    print('-' * 40)
    try:
        from putsengine.clients.unusual_whales_client import UnusualWhalesClient
        uw = UnusualWhalesClient()
        
        # Test flow - skip budget check
        print('   Testing AMD options flow...')
        flow = await uw.get_flow_recent('AMD')
        if flow:
            print(f'   ✅ Options flow: {len(flow)} trades')
            # Show sample
            if len(flow) > 0:
                f = flow[0]
                opt_type = getattr(f, 'option_type', '?')
                premium = getattr(f, 'premium', 0) or 0
                print(f'      Sample: {opt_type} ${premium:,.0f}')
                
            # Count puts vs calls
            puts = [f for f in flow if str(getattr(f, 'option_type', '')).upper() in ['PUT', 'P']]
            calls = [f for f in flow if str(getattr(f, 'option_type', '')).upper() in ['CALL', 'C']]
            print(f'      Puts: {len(puts)}, Calls: {len(calls)}')
        else:
            print('   ⚠️ No flow data returned - API may be blocked!')
        
        # Test dark pool
        print('   Testing AMD dark pool...')
        dp = await uw.get_dark_pool_flow('AMD')
        if dp:
            print(f'   ✅ Dark pool: {len(dp)} prints')
            total_value = sum(getattr(p, 'value', 0) or 0 for p in dp)
            print(f'      Total value: ${total_value:,.0f}')
        else:
            print('   ⚠️ No dark pool data returned')
            
    except Exception as e:
        print(f'   ❌ UW Error: {e}')
    print()
    
    # 4. Check budget status
    print('4. API BUDGET STATUS (Root Cause Analysis)')
    print('-' * 40)
    try:
        from putsengine.api_budget import get_budget_manager
        budget = get_budget_manager()
        status = budget.get_status()
        print(f'   Daily used: {status["daily_used"]}/{status["daily_limit"]}')
        print(f'   Daily remaining: {status["daily_remaining"]}')
        print(f'   Current window: {status["current_window"]}')
        print(f'   Window used: {status["window_used"]}/{status["window_budget"]}')
        print(f'   Unique tickers called: {status["unique_tickers_called"]}')
        
        # Check if we can call specific tickers
        print()
        print('   Cooldown Status for Missed Stocks:')
        for symbol in test_tickers:
            can_call = budget.can_call_uw(symbol)
            status_str = "✅ CAN CALL" if can_call else "❌ ON COOLDOWN"
            print(f'      {symbol}: {status_str}')
    except Exception as e:
        print(f'   ❌ Budget Error: {e}')
    print()
    
    # 5. FINVIZ
    print('5. FINVIZ (Screener Data)')
    print('-' * 40)
    try:
        from putsengine.clients.finviz_client import FinvizClient
        fv = FinvizClient()
        
        data = await fv.get_stock_data('AMD')
        if data:
            print(f'   ✅ AMD data: Price=${data.get("price", "N/A")}')
            print(f'      RSI: {data.get("rsi", "N/A")}')
            print(f'      Change: {data.get("change", "N/A")}')
        else:
            print('   ⚠️ No FinViz data')
    except Exception as e:
        print(f'   ❌ FinViz Error: {e}')
    print()
    
    print('=' * 60)
    print('VALIDATION COMPLETE')
    print('=' * 60)

if __name__ == '__main__':
    asyncio.run(validate_all_sources())
