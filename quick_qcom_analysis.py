#!/usr/bin/env python3
"""QCOM Institutional Analysis."""

import asyncio
from datetime import datetime, date, timedelta
import json
from pathlib import Path
import sys
sys.path.insert(0, '/Users/chavala/PutsEngine')

from putsengine.config import get_settings
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient

async def analyze():
    settings = get_settings()
    alpaca = AlpacaClient(settings)
    polygon = PolygonClient(settings)
    uw = UnusualWhalesClient(settings)
    
    symbol = 'QCOM'
    price = 160
    resistance = 175
    support = 150
    
    print('=' * 80)
    print('QUALCOMM (QCOM) INSTITUTIONAL ANALYSIS')
    print('=' * 80)
    print(f'Analysis Date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S ET")}')
    print('Analyst Lens: 30+ Years Trading + PhD Quant + Institutional Microstructure')
    print('=' * 80)
    
    # 1. PRICE ACTION
    print('\n[1] PRICE ACTION & TECHNICALS')
    print('=' * 80)
    
    try:
        price = await alpaca.get_current_price(symbol)
        print(f'\n   Current Price: ${price:.2f}')
    except Exception as e:
        print(f'   (Price API issue: {e})')
    
    price_bias = 'NEUTRAL'
    try:
        bars = await polygon.get_daily_bars(symbol, from_date=date.today() - timedelta(days=30))
        if bars and len(bars) >= 5:
            closes = [b.close for b in bars]
            volumes = [b.volume for b in bars]
            highs = [b.high for b in bars[-20:]]
            lows = [b.low for b in bars[-20:]]
            
            price = closes[-1]
            price_5d = closes[-6] if len(closes) >= 6 else closes[0]
            change_5d = ((closes[-1] - price_5d) / price_5d) * 100
            
            avg_vol = sum(volumes) / len(volumes)
            recent_vol = volumes[-1]
            rvol = recent_vol / avg_vol
            
            resistance = max(highs)
            support = min(lows)
            
            up_days = sum(1 for i in range(-5, 0) if closes[i] > closes[i-1])
            down_days = 5 - up_days
            
            ma_20 = sum(closes[-20:]) / min(20, len(closes))
            
            print(f'\n   Recent Performance:')
            print(f'      5-Day Change:  {change_5d:+.2f}%')
            print(f'      Last 5 Days:   {up_days} up, {down_days} down')
            rvol_status = "HIGH" if rvol > 1.5 else "LOW" if rvol < 0.7 else "NORMAL"
            print(f'      RVOL:          {rvol:.2f}x ({rvol_status})')
            
            print(f'\n   Key Levels:')
            print(f'      20-Day High (Resistance): ${resistance:.2f}')
            print(f'      20-Day Low (Support):     ${support:.2f}')
            print(f'      Distance to Resistance:   {((resistance - price) / price * 100):+.2f}%')
            print(f'      Distance to Support:      {((price - support) / price * 100):+.2f}%')
            print(f'      20-Day MA:                ${ma_20:.2f}')
            print(f'      Price vs 20-MA:           {((price - ma_20) / ma_20 * 100):+.2f}%')
            
            if price > resistance * 0.98:
                print(f'\n   Structure: AT RESISTANCE - reversal zone')
                price_bias = 'BEARISH'
            elif price < support * 1.02:
                print(f'\n   Structure: AT SUPPORT - bounce zone')
                price_bias = 'BULLISH'
            elif change_5d > 7:
                print(f'\n   Structure: EXTENDED RALLY - mean reversion likely')
                price_bias = 'BEARISH'
            elif change_5d < -7:
                print(f'\n   Structure: OVERSOLD - bounce possible')
                price_bias = 'BULLISH'
            elif price < ma_20 and change_5d < 0:
                print(f'\n   Structure: BELOW 20-MA & DECLINING - bearish')
                price_bias = 'BEARISH'
            elif price > ma_20 and change_5d > 0:
                print(f'\n   Structure: ABOVE 20-MA & RISING - bullish')
                price_bias = 'BULLISH'
            else:
                print(f'\n   Structure: MID-RANGE - no clear edge')
                price_bias = 'NEUTRAL'
    except Exception as e:
        print(f'   Error: {e}')
        price_bias = 'UNKNOWN'
    
    # 2. OPTIONS FLOW
    print('\n[2] OPTIONS FLOW INTELLIGENCE')
    print('=' * 80)
    
    flow_bias = 'UNKNOWN'
    try:
        flow = await uw.get_flow_alerts(symbol)
        if flow:
            print(f'\n   Total Flow Alerts: {len(flow)}')
            
            put_premium = 0
            call_premium = 0
            put_count = 0
            call_count = 0
            
            for f in flow:
                prem = getattr(f, 'premium', 0) or 0
                # Check various attribute names
                opt_type = getattr(f, 'option_type', None) or getattr(f, 'put_call', None) or ''
                opt_type = str(opt_type).upper()
                
                if 'PUT' in opt_type:
                    put_premium += prem
                    put_count += 1
                elif 'CALL' in opt_type:
                    call_premium += prem
                    call_count += 1
            
            print(f'      Put Alerts:  {put_count}')
            print(f'      Call Alerts: {call_count}')
            print(f'\n   Premium Analysis:')
            print(f'      Put Premium:  ${put_premium:,.0f}')
            print(f'      Call Premium: ${call_premium:,.0f}')
            
            if put_count > call_count * 1.3 or put_premium > call_premium * 1.5:
                flow_bias = 'BEARISH'
                print(f'\n   Flow Bias: BEARISH (heavy put activity)')
            elif call_count > put_count * 1.3 or call_premium > put_premium * 1.5:
                flow_bias = 'BULLISH'
                print(f'\n   Flow Bias: BULLISH (heavy call activity)')
            else:
                flow_bias = 'NEUTRAL'
                print(f'\n   Flow Bias: NEUTRAL')
        else:
            flow_bias = 'NEUTRAL'
            print('\n   No significant flow alerts')
    except Exception as e:
        flow_bias = 'UNKNOWN'
        print(f'   Error: {e}')
    
    # 3. DARK POOL
    print('\n[3] DARK POOL ACTIVITY')
    print('=' * 80)
    
    dp_bias = 'NEUTRAL'
    try:
        dp = await uw.get_dark_pool_flow(symbol)
        if dp:
            total_vol = sum(p.size for p in dp[:20] if p.size)
            avg_price = sum(p.price * p.size for p in dp[:20] if p.size and p.price) / total_vol if total_vol else 0
            
            print(f'\n   Dark Pool Summary:')
            print(f'      Recent DP Volume: {total_vol:,} shares')
            print(f'      DP VWAP:          ${avg_price:.2f}')
            print(f'      Current Price:    ${price:.2f}')
            
            if price and avg_price and avg_price < price * 0.995:
                dp_bias = 'BEARISH'
                print(f'\n   DP Signal: DISTRIBUTION - Institutions selling below market')
            elif price and avg_price and avg_price > price * 1.005:
                dp_bias = 'BULLISH'
                print(f'\n   DP Signal: ACCUMULATION - Institutions buying above market')
            else:
                dp_bias = 'NEUTRAL'
                print(f'\n   DP Signal: NEUTRAL')
        else:
            print('\n   No dark pool data available')
    except Exception as e:
        dp_bias = 'UNKNOWN'
        print(f'   Error: {e}')
    
    # 4. EWS CHECK
    print('\n[4] EARLY WARNING SYSTEM CHECK')
    print('=' * 80)
    
    ews_bias = 'NEUTRAL'
    ews_file = Path('/Users/chavala/PutsEngine/early_warning_alerts.json')
    if ews_file.exists():
        with open(ews_file) as f:
            ews = json.load(f)
        alerts = ews.get('alerts', {})
        
        qcom_alert = alerts.get('QCOM')
        if qcom_alert:
            ipi = qcom_alert.get('ipi', 0)
            level = qcom_alert.get('level', 'none')
            footprints = qcom_alert.get('unique_footprints', 0)
            days = qcom_alert.get('days_building', 0)
            
            print(f'\n   !!! QCOM IN EARLY WARNING SYSTEM !!!')
            print(f'      IPI Score:      {ipi:.2f}')
            print(f'      Alert Level:    {level.upper()}')
            print(f'      Footprints:     {footprints}')
            print(f'      Days Building:  {days}')
            
            fps = qcom_alert.get('footprints', [])
            if fps:
                print(f'\n      Footprint Details:')
                for fp in fps[:5]:
                    fp_type = fp.get('type', 'unknown').replace('_', ' ').title()
                    strength = fp.get('strength', 0)
                    print(f'         - {fp_type}: {strength:.2f}')
            
            if level == 'act':
                print(f'\n      >>> IMMINENT BREAKDOWN - Strong put setup!')
                ews_bias = 'STRONGLY BEARISH'
            elif level == 'prepare':
                print(f'\n      >>> ACTIVE DISTRIBUTION - Add to watchlist')
                ews_bias = 'BEARISH'
            else:
                print(f'\n      >>> EARLY SIGNALS - Monitor')
                ews_bias = 'WATCH'
        else:
            print(f'\n   QCOM NOT in Early Warning System')
            print(f'      No significant institutional distribution detected')
            ews_bias = 'NEUTRAL'
        
        print(f'\n   Last EWS Scan: {ews.get("timestamp", "Unknown")}')
    
    # 5. SECTOR CONTEXT
    print('\n[5] SECTOR & MARKET CONTEXT')
    print('=' * 80)
    
    sector_bias = 'NEUTRAL'
    try:
        soxx_bars = await polygon.get_daily_bars('SOXX', from_date=date.today() - timedelta(days=10))
        if soxx_bars and len(soxx_bars) >= 5:
            soxx_closes = [b.close for b in soxx_bars]
            soxx_change = ((soxx_closes[-1] - soxx_closes[-6]) / soxx_closes[-6]) * 100
            
            print(f'\n   Semiconductor Sector (SOXX):')
            print(f'      SOXX Price:     ${soxx_closes[-1]:.2f}')
            print(f'      5-Day Change:   {soxx_change:+.2f}%')
            
            if soxx_change > 3:
                sector_bias = 'BULLISH'
                print(f'      SEMIS RALLYING - Sector tailwind')
            elif soxx_change < -3:
                sector_bias = 'BEARISH'
                print(f'      SEMIS SELLING - Sector headwind')
            else:
                sector_bias = 'NEUTRAL'
                print(f'      NEUTRAL - Semis consolidating')
        
        qqq_bars = await polygon.get_daily_bars('QQQ', from_date=date.today() - timedelta(days=10))
        if qqq_bars and len(qqq_bars) >= 5:
            qqq_closes = [b.close for b in qqq_bars]
            qqq_change = ((qqq_closes[-1] - qqq_closes[-6]) / qqq_closes[-6]) * 100
            print(f'\n   Broader Tech (QQQ):')
            print(f'      QQQ Price:      ${qqq_closes[-1]:.2f}')
            print(f'      5-Day Change:   {qqq_change:+.2f}%')
            
            if qqq_change < -3 and sector_bias != 'BEARISH':
                sector_bias = 'BEARISH'
                print(f'      TECH SELLING - Risk-off environment')
    except Exception as e:
        print(f'   Error: {e}')
    
    # FINAL VERDICT
    print('\n' + '=' * 80)
    print('FINAL VERDICT')
    print('=' * 80)
    
    signals = {
        'Price Action': price_bias,
        'Options Flow': flow_bias,
        'Dark Pool': dp_bias,
        'EWS': ews_bias,
        'Sector': sector_bias,
    }
    
    print('\nSignal Summary:')
    for k, v in signals.items():
        if 'BEARISH' in str(v):
            icon = '[BEAR]'
        elif 'BULLISH' in str(v):
            icon = '[BULL]'
        elif 'WATCH' in str(v):
            icon = '[WATCH]'
        else:
            icon = '[-]'
        print(f'   {icon} {k}: {v}')
    
    bearish = sum(1 for v in signals.values() if 'BEARISH' in str(v))
    bullish = sum(1 for v in signals.values() if 'BULLISH' in str(v))
    
    print(f'\n   Bullish Signals: {bullish}')
    print(f'   Bearish Signals: {bearish}')
    
    print('\n' + '-' * 80)
    
    if bearish >= 3 or (bearish >= 2 and 'STRONGLY' in str(ews_bias)):
        print(f'''
>>> VERDICT: PUTS (Strong Bearish Setup) <<<

Multiple bearish signals converging. Institutional distribution detected.

TRADE STRUCTURE:
   Strike: ${price * 0.97:.0f} - ${price * 0.98:.0f} (2-3% OTM)
   Expiry: 7-14 DTE
   Delta: -0.30 to -0.40
   Size: 2-3% of portfolio max

ENTRY/EXIT:
   Entry: Wait for bounce toward ${resistance:.2f} (resistance)
   Target: 50-100% gain on premium
   Stop: Close if price breaks above ${resistance * 1.02:.2f}
   Time Stop: Close by 5 DTE if no movement
''')
    elif bullish >= 3:
        print(f'''
>>> VERDICT: CALLS (Strong Bullish Setup) <<<

Multiple bullish signals converging.

TRADE STRUCTURE:
   Strike: ${price:.0f} - ${price * 1.02:.0f} (ATM to 2% OTM)
   Expiry: 14-21 DTE
   Delta: 0.40 to 0.50
   Size: 2-3% of portfolio max
''')
    elif bearish >= 2:
        print(f'''
>>> VERDICT: PUTS (Moderate Bearish Setup) <<<

Bearish signals present. Proceed with caution/smaller size.

TRADE STRUCTURE:
   Strike: ${price * 0.95:.0f} - ${price * 0.97:.0f} (3-5% OTM)
   Expiry: 14-21 DTE
   Delta: -0.25 to -0.35
   Size: 1-2% of portfolio

KEY LEVELS:
   Resistance: ${resistance:.2f}
   Support:    ${support:.2f}

WAIT for confirmation (break below ${support:.2f})
''')
    elif bullish >= 2:
        print(f'''
>>> VERDICT: CALLS (Moderate Bullish Setup) <<<

Bullish signals present. Proceed with smaller size.

TRADE STRUCTURE:
   Strike: ${price * 1.03:.0f} - ${price * 1.05:.0f} (3-5% OTM)
   Expiry: 14-21 DTE
   Size: 1-2% of portfolio

WAIT for confirmation (break above ${resistance:.2f})
''')
    else:
        print(f'''
>>> VERDICT: WAIT (No Clear Edge) <<<

Signals are mixed. No high-conviction setup.

WHAT TO WATCH FOR:
   Break above ${resistance:.2f} -> Consider CALLS
   Break below ${support:.2f} -> Consider PUTS
   Watch EWS for institutional footprints
''')
    
    # QCOM-SPECIFIC CONTEXT
    print('\n' + '=' * 80)
    print('QCOM-SPECIFIC INSTITUTIONAL WISDOM')
    print('=' * 80)
    print('''
KEY FACTORS FOR QUALCOMM TRADES:

1. SMARTPHONE CYCLE
   - QCOM's bread & butter is mobile chips (Snapdragon)
   - Apple relationship is complex (modems, licensing)
   - Android OEM demand drives revenue
   - Seasonal: Q4 (holiday) typically strong

2. AUTOMOTIVE GROWTH
   - Automotive chips are the growth story
   - Infotainment, ADAS, connectivity
   - Watch for automotive revenue commentary

3. PC/AI EXPANSION  
   - Snapdragon X Elite for Windows laptops
   - AI PC narrative could be catalyst
   - Competing with Intel, AMD for laptop share

4. CHINA EXPOSURE (~60% of revenue)
   - Trade tensions = headline risk
   - Any tariff/sanction news moves QCOM
   - This is the biggest risk factor

5. LICENSING BUSINESS
   - High-margin IP licensing
   - Legal disputes can cause volatility

6. TYPICAL EARNINGS MOVES: 5-8%
   - Guidance matters more than beat/miss
   - Mobile outlook is key focus

7. SECTOR CORRELATION
   - Highly correlated with SOXX (semis)
   - Also moves with NVDA, AMD sentiment
   - Check sector before trading QCOM alone
''')
    
    await alpaca.close()
    await polygon.close()
    await uw.close()

if __name__ == "__main__":
    asyncio.run(analyze())
