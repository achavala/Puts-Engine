#!/usr/bin/env python3
"""Quick GOOGL Analysis - Fixed API compatibility."""

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
    
    symbol = 'GOOGL'
    price = 200  # Default
    resistance = 210
    support = 190
    
    print('=' * 80)
    print('🔍 GOOGLE (GOOGL) INSTITUTIONAL ANALYSIS')
    print('=' * 80)
    print(f'Analysis Date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S ET")}')
    print('Analyst Lens: 30+ Years Trading + PhD Quant + Institutional Microstructure')
    print('=' * 80)
    
    # 1. PRICE ACTION
    print('\n📊 1. PRICE ACTION & TECHNICALS')
    print('=' * 80)
    
    try:
        price = await alpaca.get_current_price(symbol)
        print(f'\n   💰 Current Price: ${price:.2f}')
    except Exception as e:
        print(f'   (Using estimated price due to API issue)')
    
    # Get historical bars via Polygon
    try:
        bars = await polygon.get_daily_bars(symbol, from_date=date.today() - timedelta(days=30))
        if bars and len(bars) >= 5:
            closes = [b.close for b in bars]
            volumes = [b.volume for b in bars]
            highs = [b.high for b in bars[-20:]]
            lows = [b.low for b in bars[-20:]]
            
            price = closes[-1]  # Use latest close
            price_5d = closes[-6] if len(closes) >= 6 else closes[0]
            change_5d = ((closes[-1] - price_5d) / price_5d) * 100
            
            avg_vol = sum(volumes) / len(volumes)
            recent_vol = volumes[-1]
            rvol = recent_vol / avg_vol
            
            resistance = max(highs)
            support = min(lows)
            
            # Trend analysis
            up_days = sum(1 for i in range(-5, 0) if closes[i] > closes[i-1])
            down_days = 5 - up_days
            
            print(f'\n   📈 Recent Performance:')
            print(f'      5-Day Change: {change_5d:+.2f}%')
            print(f'      Last 5 Days: {up_days} up, {down_days} down')
            print(f'      RVOL: {rvol:.2f}x {"🔥 HIGH" if rvol > 1.5 else "📉 LOW" if rvol < 0.7 else "➖ NORMAL"}')
            
            print(f'\n   📍 Key Levels:')
            print(f'      20-Day High (Resistance): ${resistance:.2f}')
            print(f'      20-Day Low (Support): ${support:.2f}')
            print(f'      Distance to Resistance: {((resistance - price) / price * 100):+.2f}%')
            print(f'      Distance to Support: {((price - support) / price * 100):+.2f}%')
            
            # Price structure assessment
            if price > resistance * 0.98:
                print(f'\n   🎯 Structure: AT RESISTANCE - potential reversal zone')
                price_bias = 'BEARISH'
            elif price < support * 1.02:
                print(f'\n   🎯 Structure: AT SUPPORT - potential bounce zone')
                price_bias = 'BULLISH'
            elif change_5d > 5:
                print(f'\n   🎯 Structure: EXTENDED RALLY - mean reversion likely')
                price_bias = 'BEARISH'
            elif change_5d < -5:
                print(f'\n   🎯 Structure: EXTENDED SELLOFF - bounce possible')
                price_bias = 'BULLISH'
            else:
                print(f'\n   🎯 Structure: MID-RANGE - no clear edge')
                price_bias = 'NEUTRAL'
        else:
            price_bias = 'UNKNOWN'
    except Exception as e:
        print(f'   Error: {e}')
        price_bias = 'UNKNOWN'
    
    # 2. OPTIONS FLOW
    print('\n🌊 2. OPTIONS FLOW INTELLIGENCE')
    print('=' * 80)
    
    try:
        flow = await uw.get_flow_alerts(symbol)
        if flow:
            puts = [f for f in flow if f.put_call == 'PUT']
            calls = [f for f in flow if f.put_call == 'CALL']
            
            print(f'\n   📊 Recent Flow Alerts:')
            print(f'      Put Alerts: {len(puts)}')
            print(f'      Call Alerts: {len(calls)}')
            
            # Premium analysis
            put_premium = sum(f.premium for f in puts if f.premium) if puts else 0
            call_premium = sum(f.premium for f in calls if f.premium) if calls else 0
            
            print(f'\n   💰 Premium Analysis:')
            print(f'      Put Premium: ${put_premium:,.0f}')
            print(f'      Call Premium: ${call_premium:,.0f}')
            
            # Large trades (smart money)
            large_puts = [f for f in puts if f.premium and f.premium > 100000]
            large_calls = [f for f in calls if f.premium and f.premium > 100000]
            
            print(f'\n   🐋 Large Trades (>$100K):')
            print(f'      Large Puts: {len(large_puts)}')
            print(f'      Large Calls: {len(large_calls)}')
            
            # Show top large trades
            if large_puts:
                print(f'\n      Top Put Trades:')
                for t in sorted(large_puts, key=lambda x: x.premium or 0, reverse=True)[:3]:
                    print(f'         ${t.strike_price} {t.expiration_date}: ${t.premium:,.0f}')
            
            if large_calls:
                print(f'\n      Top Call Trades:')
                for t in sorted(large_calls, key=lambda x: x.premium or 0, reverse=True)[:3]:
                    print(f'         ${t.strike_price} {t.expiration_date}: ${t.premium:,.0f}')
            
            # Flow bias
            if len(puts) > len(calls) * 1.5 and put_premium > call_premium:
                flow_bias = 'BEARISH'
                print(f'\n   🎯 Flow Bias: 🐻 BEARISH (heavy put activity)')
            elif len(calls) > len(puts) * 1.5 and call_premium > put_premium:
                flow_bias = 'BULLISH'
                print(f'\n   🎯 Flow Bias: 🐂 BULLISH (heavy call activity)')
            else:
                flow_bias = 'NEUTRAL'
                print(f'\n   🎯 Flow Bias: ➖ NEUTRAL')
        else:
            flow_bias = 'NEUTRAL'
            print('\n   No significant flow alerts')
    except Exception as e:
        flow_bias = 'UNKNOWN'
        print(f'   Error: {e}')
    
    # 3. DARK POOL
    print('\n🌑 3. DARK POOL ACTIVITY')
    print('=' * 80)
    
    try:
        dp = await uw.get_dark_pool_flow(symbol)
        if dp:
            total_vol = sum(p.size for p in dp[:20] if p.size)
            avg_price = sum(p.price * p.size for p in dp[:20] if p.size and p.price) / total_vol if total_vol else 0
            
            print(f'\n   📊 Dark Pool Summary:')
            print(f'      Recent DP Volume: {total_vol:,} shares')
            print(f'      DP VWAP: ${avg_price:.2f}')
            print(f'      Current Price: ${price:.2f}')
            
            if price and avg_price < price * 0.995:
                dp_bias = 'BEARISH'
                print(f'\n   🎯 DP Signal: 📉 DISTRIBUTION - Institutions selling below market')
            elif price and avg_price > price * 1.005:
                dp_bias = 'BULLISH'
                print(f'\n   🎯 DP Signal: 📈 ACCUMULATION - Institutions buying above market')
            else:
                dp_bias = 'NEUTRAL'
                print(f'\n   🎯 DP Signal: ➖ NEUTRAL - No clear institutional bias')
        else:
            dp_bias = 'NEUTRAL'
            print('\n   No dark pool data available')
    except Exception as e:
        dp_bias = 'UNKNOWN'
        print(f'   Error: {e}')
    
    # 4. EWS CHECK
    print('\n🚨 4. EARLY WARNING SYSTEM CHECK')
    print('=' * 80)
    
    ews_file = Path('/Users/chavala/PutsEngine/early_warning_alerts.json')
    if ews_file.exists():
        with open(ews_file) as f:
            ews = json.load(f)
        alerts = ews.get('alerts', {})
        
        googl_alert = alerts.get('GOOGL') or alerts.get('GOOG')
        if googl_alert:
            ipi = googl_alert.get('ipi', 0)
            level = googl_alert.get('level', 'none')
            footprints = googl_alert.get('unique_footprints', 0)
            
            print(f'\n   ⚠️ GOOGL IN EARLY WARNING SYSTEM!')
            print(f'      IPI Score: {ipi:.2f}')
            print(f'      Alert Level: {level.upper()}')
            print(f'      Footprints: {footprints}')
            
            if level == 'act':
                print(f'      🔴 IMMINENT BREAKDOWN - Consider puts on bounce')
                ews_bias = 'STRONGLY BEARISH'
            elif level == 'prepare':
                print(f'      🟡 ACTIVE DISTRIBUTION - Add to watchlist')
                ews_bias = 'BEARISH'
            else:
                print(f'      👀 EARLY SIGNALS - Monitor')
                ews_bias = 'WATCH'
        else:
            print(f'\n   ✅ GOOGL NOT in Early Warning System')
            print(f'      No significant institutional distribution detected')
            ews_bias = 'NEUTRAL'
        
        print(f'\n   Last EWS Scan: {ews.get("timestamp", "Unknown")}')
    else:
        ews_bias = 'UNKNOWN'
        print('\n   EWS data not available')
    
    # 5. SECTOR CONTEXT
    print('\n🌍 5. SECTOR & MARKET CONTEXT')
    print('=' * 80)
    
    try:
        qqq_bars = await polygon.get_daily_bars('QQQ', from_date=date.today() - timedelta(days=10))
        if qqq_bars and len(qqq_bars) >= 5:
            qqq_closes = [b.close for b in qqq_bars]
            qqq_change = ((qqq_closes[-1] - qqq_closes[-6]) / qqq_closes[-6]) * 100
            
            print(f'\n   📊 Tech Sector (QQQ):')
            print(f'      QQQ Price: ${qqq_closes[-1]:.2f}')
            print(f'      5-Day Change: {qqq_change:+.2f}%')
            
            if qqq_change > 3:
                sector_bias = 'BULLISH'
                print(f'      🐂 RISK-ON - Tech sector rallying')
            elif qqq_change < -3:
                sector_bias = 'BEARISH'
                print(f'      🐻 RISK-OFF - Tech sector selling')
            else:
                sector_bias = 'NEUTRAL'
                print(f'      ➖ NEUTRAL - Tech consolidating')
        else:
            sector_bias = 'NEUTRAL'
    except Exception as e:
        sector_bias = 'UNKNOWN'
        print(f'   Error: {e}')
    
    # ==========================================
    # FINAL VERDICT
    # ==========================================
    print('\n' + '=' * 80)
    print('🎯 FINAL VERDICT')
    print('=' * 80)
    
    signals = {
        'Price Action': price_bias,
        'Options Flow': flow_bias,
        'Dark Pool': dp_bias,
        'EWS': ews_bias,
        'Sector': sector_bias,
    }
    
    print('\n📊 Signal Summary:')
    for k, v in signals.items():
        if 'BEARISH' in v:
            icon = '🐻'
        elif 'BULLISH' in v:
            icon = '🐂'
        else:
            icon = '➖'
        print(f'   {icon} {k}: {v}')
    
    bearish = sum(1 for v in signals.values() if 'BEARISH' in v)
    bullish = sum(1 for v in signals.values() if 'BULLISH' in v)
    
    print(f'\n   📈 Bullish Signals: {bullish}')
    print(f'   📉 Bearish Signals: {bearish}')
    
    print('\n' + '-' * 80)
    
    if bearish >= 3:
        print(f'''
🐻 VERDICT: PUTS (Strong Bearish Setup)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Multiple bearish signals converging. Institutional selling detected.

📋 TRADE STRUCTURE:
   • Strike: ${price * 0.97:.0f} - ${price * 0.98:.0f} (2-3% OTM)
   • Expiry: 7-14 DTE (Feb 14-21 expiry)
   • Delta: -0.30 to -0.40
   • Size: 2-3% of portfolio max

📍 ENTRY/EXIT:
   • Entry: Wait for bounce toward ${resistance:.2f} (resistance)
   • Target: 50-100% gain on premium
   • Stop: Close if price breaks above ${resistance * 1.02:.2f}
   • Time Stop: Close by 5 DTE if no movement

⚠️ RISK MANAGEMENT:
   • Max loss = Premium paid
   • Never risk more than you can afford to lose
''')
        
    elif bullish >= 3:
        print(f'''
🐂 VERDICT: CALLS (Strong Bullish Setup)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Multiple bullish signals converging. Institutional buying detected.

📋 TRADE STRUCTURE:
   • Strike: ${price:.0f} - ${price * 1.02:.0f} (ATM to 2% OTM)
   • Expiry: 14-21 DTE (Feb 21-28 expiry)
   • Delta: 0.40 to 0.50
   • Size: 2-3% of portfolio max

📍 ENTRY/EXIT:
   • Entry: On pullback toward ${support:.2f} (support)
   • Target: 50-100% gain on premium
   • Stop: Close if price breaks below ${support * 0.98:.2f}
   • Time Stop: Close by 7 DTE if no movement

⚠️ RISK MANAGEMENT:
   • Max loss = Premium paid
   • Take profits when you have them
''')
        
    elif bearish >= 2:
        print(f'''
🐻 VERDICT: PUTS (Moderate Bearish Setup)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Bearish signals present but not overwhelming. Proceed with caution.

📋 TRADE STRUCTURE:
   • Strike: ${price * 0.95:.0f} - ${price * 0.97:.0f} (3-5% OTM for safety)
   • Expiry: 14-21 DTE
   • Delta: -0.25 to -0.35
   • Size: 1-2% of portfolio (smaller due to mixed signals)

📍 KEY LEVELS:
   • Resistance: ${resistance:.2f}
   • Support: ${support:.2f}

⚠️ CAUTION: Wait for confirmation (break below ${support:.2f})
''')
        
    elif bullish >= 2:
        print(f'''
🐂 VERDICT: CALLS (Moderate Bullish Setup)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Bullish signals present but not overwhelming. Proceed with caution.

📋 TRADE STRUCTURE:
   • Strike: ${price * 1.03:.0f} - ${price * 1.05:.0f} (3-5% OTM for safety)
   • Expiry: 14-21 DTE
   • Delta: 0.35 to 0.45
   • Size: 1-2% of portfolio (smaller due to mixed signals)

📍 KEY LEVELS:
   • Resistance: ${resistance:.2f}
   • Support: ${support:.2f}

⚠️ CAUTION: Wait for confirmation (break above ${resistance:.2f})
''')
        
    else:
        print(f'''
⏸️ VERDICT: WAIT (No Clear Edge)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Signals are mixed. No high-conviction setup.

🏛️ 30-YEAR TRADER'S RULE:
   "When in doubt, stay out. The market always gives another opportunity."

📋 WHAT TO WATCH FOR:
   • Break above ${resistance:.2f} → Consider CALLS
   • Break below ${support:.2f} → Consider PUTS
   • Watch for unusual options flow (large blocks)
   • Check EWS daily for institutional footprints

🎯 ALTERNATIVE STRATEGIES:
   • Iron Condor if expecting range-bound (${support:.0f} - ${resistance:.0f})
   • Straddle if expecting big move but unsure direction
   • Just WAIT for clearer setup
''')
    
    # GOOGL-SPECIFIC CONTEXT
    print('\n' + '=' * 80)
    print('🏛️ GOOGL-SPECIFIC INSTITUTIONAL WISDOM')
    print('=' * 80)
    print('''
KEY FACTORS FOR GOOGLE TRADES:

1. 📈 AI NARRATIVE
   Google's Gemini competes with OpenAI/Microsoft.
   Any AI news from competitors can gap GOOGL ±3-5%.
   Watch for product announcements, benchmark results.

2. 🔍 SEARCH MOAT
   90%+ search market share intact.
   BUT: ChatGPT/Bing integration is the existential threat.
   Any share loss headlines = sharp selloffs.

3. ⚖️ ANTITRUST RISK
   DOJ antitrust cases pending (could force breakup).
   Rulings can cause 5-10% gaps with NO warning.
   This is unhedgeable - size positions accordingly.

4. ☁️ CLOUD GROWTH (GCP)
   GCP is #3 behind AWS/Azure.
   Cloud revenue growth rates closely watched.
   Deceleration = selling pressure.

5. 📺 YOUTUBE & AD REVENUE
   Digital advertising is cyclical.
   Economic data (consumer confidence, retail sales) matters.
   Weak ad environment = GOOGL underperforms.

6. 💡 OPTIONS CHARACTERISTICS
   - Very liquid options (penny-wide spreads)
   - Weekly options available
   - Lower beta than NVDA/TSLA (moves slower)
   - Earnings moves typically 5-7%

7. 📅 EARNINGS PLAYBOOK
   - Q4 2025 likely reported late Jan/early Feb 2026
   - NEVER buy options into earnings (severe IV crush)
   - Post-earnings continuation trades are safer
   - Watch guidance MORE than the numbers
''')
    
    await alpaca.close()
    await polygon.close()
    await uw.close()

if __name__ == "__main__":
    asyncio.run(analyze())
