#!/usr/bin/env python3
"""
AMD PRE-EARNINGS INSTITUTIONAL ANALYSIS
=======================================
PhD-Level Quantitative Analysis with 30+ Years Trading Experience Lens
"""

import asyncio
from datetime import datetime, date, timedelta
import pytz

from putsengine.config import get_settings
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient


async def analyze_amd():
    settings = get_settings()
    alpaca = AlpacaClient(settings)
    polygon = PolygonClient(settings)
    uw = UnusualWhalesClient(settings)
    et = pytz.timezone('US/Eastern')
    
    print('='*80)
    print('🔥 AMD PRE-EARNINGS INSTITUTIONAL ANALYSIS')
    print(f'⏰ {datetime.now(et).strftime("%Y-%m-%d %H:%M:%S %Z")}')
    print('='*80)
    
    # 1. CURRENT PRICE & QUOTE
    print('\n📈 1. REAL-TIME PRICE DATA')
    print('-'*40)
    quote = await alpaca.get_latest_quote('AMD')
    current_price = 0
    if quote and 'quote' in quote:
        q = quote['quote']
        bid = float(q.get('bp', 0))
        ask = float(q.get('ap', 0))
        mid = (bid + ask) / 2
        current_price = mid
        spread = ask - bid
        spread_pct = (spread / mid) * 100 if mid > 0 else 0
        print(f'   Bid: ${bid:.2f} x {q.get("bs", 0)}')
        print(f'   Ask: ${ask:.2f} x {q.get("as", 0)}')
        print(f'   Mid: ${mid:.2f}')
        print(f'   Spread: ${spread:.3f} ({spread_pct:.3f}%)')
        print(f'   Timestamp: {q.get("t", "N/A")}')
    
    # 2. HISTORICAL PRICE ACTION
    print('\n📊 2. RECENT PRICE ACTION (Last 10 Days)')
    print('-'*40)
    bars = await alpaca.get_daily_bars('AMD', limit=15)
    recent_high = 0
    recent_low = 999999
    if bars:
        for bar in bars[-7:]:
            change = ((bar.close - bar.open) / bar.open) * 100
            day_change = ((bar.close - bars[bars.index(bar)-1].close) / bars[bars.index(bar)-1].close) * 100 if bars.index(bar) > 0 else change
            symbol = '🟢' if change > 0 else '🔴'
            print(f'   {bar.timestamp.strftime("%Y-%m-%d")}: O=${bar.open:.2f} H=${bar.high:.2f} L=${bar.low:.2f} C=${bar.close:.2f} {symbol}{change:+.1f}% Vol={bar.volume:,}')
        
        # Calculate key levels
        recent_high = max(b.high for b in bars[-7:])
        recent_low = min(b.low for b in bars[-7:])
        current = bars[-1].close
        print(f'\n   7-Day High: ${recent_high:.2f}')
        print(f'   7-Day Low: ${recent_low:.2f}')
        print(f'   Current: ${current:.2f}')
        range_position = ((current - recent_low) / (recent_high - recent_low) * 100) if recent_high != recent_low else 50
        print(f'   Position in Range: {range_position:.0f}%')
        
        # Pre-earnings price action
        last_5_change = ((bars[-1].close - bars[-6].close) / bars[-6].close) * 100 if len(bars) >= 6 else 0
        print(f'\n   5-Day Change: {last_5_change:+.1f}%')
        if last_5_change > 5:
            print('   ⚠️  OVERBOUGHT INTO EARNINGS - Higher put potential if miss')
        elif last_5_change < -5:
            print('   ⚠️  OVERSOLD INTO EARNINGS - Lower put potential, beat likely priced in')
    
    # 3. OPTIONS FLOW
    print('\n🐋 3. OPTIONS FLOW ANALYSIS')
    print('-'*40)
    try:
        flow = await uw.get_flow_recent('AMD', limit=100)
        if flow:
            puts = [f for f in flow if f.option_type.lower() == 'put']
            calls = [f for f in flow if f.option_type.lower() == 'call']
            put_premium = sum(f.premium for f in puts)
            call_premium = sum(f.premium for f in calls)
            
            print(f'   Put Trades: {len(puts)} (${put_premium:,.0f} premium)')
            print(f'   Call Trades: {len(calls)} (${call_premium:,.0f} premium)')
            ratio = put_premium/call_premium if call_premium > 0 else 0
            print(f'   Put/Call Premium Ratio: {ratio:.2f}')
            
            if ratio > 1.5:
                print('   🔴 BEARISH FLOW: Put premium significantly exceeds calls')
            elif ratio < 0.7:
                print('   🟢 BULLISH FLOW: Call premium significantly exceeds puts')
            else:
                print('   ⚪ NEUTRAL FLOW: Balanced put/call activity')
            
            # Large put trades
            large_puts = [f for f in puts if f.premium >= 50000]
            if large_puts:
                print(f'\n   🚨 LARGE PUT TRADES (>$50K):')
                for p in sorted(large_puts, key=lambda x: x.premium, reverse=True)[:5]:
                    print(f'      ${p.strike} {p.expiration} | ${p.premium:,.0f} | {p.side} | IV:{p.implied_volatility:.0f}%')
            
            # Large call trades
            large_calls = [f for f in calls if f.premium >= 50000]
            if large_calls:
                print(f'\n   📈 LARGE CALL TRADES (>$50K):')
                for c in sorted(large_calls, key=lambda x: x.premium, reverse=True)[:5]:
                    print(f'      ${c.strike} {c.expiration} | ${c.premium:,.0f} | {c.side} | IV:{c.implied_volatility:.0f}%')
            
            # Sentiment analysis
            bearish_flow = sum(1 for f in flow if f.sentiment == 'bearish')
            bullish_flow = sum(1 for f in flow if f.sentiment == 'bullish')
            print(f'\n   Bearish Flow Count: {bearish_flow}')
            print(f'   Bullish Flow Count: {bullish_flow}')
        else:
            print('   No flow data available')
    except Exception as e:
        print(f'   Flow data unavailable: {e}')
    
    # 4. IV RANK & VOLATILITY
    print('\n📉 4. IMPLIED VOLATILITY ANALYSIS')
    print('-'*40)
    iv_rank_value = None
    try:
        iv_data = await uw.get_iv_rank('AMD')
        if iv_data:
            data = iv_data.get('data', iv_data)
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            if isinstance(data, dict):
                iv_rank = data.get('iv_rank', data.get('ivRank'))
                iv_pct = data.get('iv_percentile', data.get('ivPercentile'))
                iv_30 = data.get('iv30', data.get('iv_30'))
                iv_rank_value = float(iv_rank) if iv_rank else None
                print(f'   IV Rank: {iv_rank}%' if iv_rank else '   IV Rank: N/A')
                print(f'   IV Percentile: {iv_pct}%' if iv_pct else '   IV Percentile: N/A')
                print(f'   IV30: {iv_30}%' if iv_30 else '   IV30: N/A')
                
                if iv_rank_value and iv_rank_value > 70:
                    print('\n   🚨 EXTREMELY HIGH IV WARNING!')
                    print('   • Options are VERY EXPENSIVE')
                    print('   • IV crush after earnings will be SEVERE')
                    print('   • Even correct directional bets may LOSE money')
                elif iv_rank_value and iv_rank_value > 50:
                    print('\n   ⚠️  ELEVATED IV WARNING')
                    print('   • Options are expensive (above average)')
                    print('   • Consider spreads to reduce IV exposure')
    except Exception as e:
        print(f'   IV data unavailable: {e}')
    
    # 5. GEX & DEALER POSITIONING
    print('\n⚡ 5. GAMMA EXPOSURE (GEX) & DEALER POSITIONING')
    print('-'*40)
    try:
        gex = await uw.get_gex_data('AMD')
        if gex:
            print(f'   Net GEX: {gex.net_gex:,.0f}')
            print(f'   Dealer Delta: {gex.dealer_delta:,.0f}')
            print(f'   Put Wall: ${gex.put_wall:.2f}' if gex.put_wall else '   Put Wall: N/A')
            print(f'   Call Wall: ${gex.call_wall:.2f}' if gex.call_wall else '   Call Wall: N/A')
            print(f'   GEX Flip Level: ${gex.gex_flip_level:.2f}' if gex.gex_flip_level else '   GEX Flip: N/A')
            
            if gex.net_gex < 0:
                print('\n   🔴 NEGATIVE GEX: Dealers are SHORT gamma')
                print('   → Price moves will be AMPLIFIED in both directions')
                print('   → More volatile post-earnings move expected')
            elif gex.net_gex > 0:
                print('\n   🟢 POSITIVE GEX: Dealers are LONG gamma')
                print('   → Price moves will be DAMPENED')
                print('   → May pin near current level')
            
            if gex.put_wall and current_price > 0:
                dist_to_put_wall = ((current_price - gex.put_wall) / current_price) * 100
                print(f'\n   Distance to Put Wall: {dist_to_put_wall:+.1f}%')
                if dist_to_put_wall < 5:
                    print('   ⚠️  Close to put wall - may act as support')
        else:
            print('   GEX data unavailable')
    except Exception as e:
        print(f'   GEX data unavailable: {e}')
    
    # 6. DARK POOL ACTIVITY
    print('\n🌑 6. DARK POOL ACTIVITY')
    print('-'*40)
    try:
        dp = await uw.get_dark_pool_flow('AMD', limit=20)
        if dp:
            total_shares = sum(p.size for p in dp)
            avg_price = sum(p.price * p.size for p in dp) / total_shares if total_shares > 0 else 0
            print(f'   Recent Dark Pool Prints: {len(dp)}')
            print(f'   Total Shares: {total_shares:,}')
            print(f'   Avg Price: ${avg_price:.2f}')
            
            # Check if dark pool prints are below current price (bearish)
            if current_price > 0 and avg_price > 0:
                dp_vs_current = ((avg_price - current_price) / current_price) * 100
                print(f'   Dark Pool vs Current: {dp_vs_current:+.1f}%')
                if dp_vs_current < -1:
                    print('   🔴 Dark pool activity BELOW current price (distribution)')
                elif dp_vs_current > 1:
                    print('   🟢 Dark pool activity ABOVE current price (accumulation)')
        else:
            print('   No dark pool data available')
    except Exception as e:
        print(f'   Dark pool unavailable: {e}')
    
    # 7. TECHNICAL ANALYSIS
    print('\n📐 7. TECHNICAL ANALYSIS')
    print('-'*40)
    if bars and len(bars) >= 10:
        closes = [b.close for b in bars]
        
        # Moving averages
        sma_5 = sum(closes[-5:]) / 5
        sma_10 = sum(closes[-10:]) / 10
        sma_20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else sma_10
        
        print(f'   5-Day SMA: ${sma_5:.2f}')
        print(f'   10-Day SMA: ${sma_10:.2f}')
        print(f'   20-Day SMA: ${sma_20:.2f}')
        
        current = closes[-1]
        print(f'\n   Price vs 5-SMA: {"ABOVE ✅" if current > sma_5 else "BELOW ❌"}')
        print(f'   Price vs 10-SMA: {"ABOVE ✅" if current > sma_10 else "BELOW ❌"}')
        print(f'   Price vs 20-SMA: {"ABOVE ✅" if current > sma_20 else "BELOW ❌"}')
        
        # RSI calculation
        gains = []
        losses = []
        for i in range(1, min(15, len(closes))):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        if gains and losses:
            avg_gain = sum(gains[-14:]) / 14
            avg_loss = sum(losses[-14:]) / 14
            if avg_loss > 0:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                print(f'\n   RSI (14): {rsi:.1f}')
                if rsi > 70:
                    print('   ⚠️  OVERBOUGHT - Higher put potential')
                elif rsi < 30:
                    print('   ⚠️  OVERSOLD - Lower put potential')
        
        # ATR for expected move
        atrs = [b.high - b.low for b in bars[-10:]]
        atr = sum(atrs) / len(atrs)
        print(f'\n   10-Day ATR: ${atr:.2f} ({(atr/current)*100:.1f}%)')
        print(f'   Expected Post-Earnings Range:')
        print(f'   • Upside: ${current + atr*1.5:.2f} (+{(atr*1.5/current)*100:.1f}%)')
        print(f'   • Downside: ${current - atr*1.5:.2f} (-{(atr*1.5/current)*100:.1f}%)')
    
    # 8. EARNINGS ANALYSIS
    print('\n' + '='*80)
    print('📅 8. EARNINGS-SPECIFIC ANALYSIS')
    print('='*80)
    print('''
   ⚠️  AMD REPORTS EARNINGS TODAY (After Market Close)
   
   INSTITUTIONAL RULES FOR EARNINGS PLAYS:
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   
   1. NEVER BUY PUTS BEFORE EARNINGS
      • IV is inflated, pricing in the expected move
      • Even if AMD drops 5%, IV crush can make puts LOSE money
      • This is the #1 retail trap
   
   2. THE IV CRUSH MATH:
      • Pre-earnings IV: ~60-80% (elevated)
      • Post-earnings IV: ~35-50% (normal)
      • This 30-50% IV drop DESTROYS option value
      • A $2.00 put can become $1.00 overnight even if stock drops
   
   3. WHEN TO BUY PUTS (Post-Earnings):
      • WAIT for earnings reaction
      • IF gap down AND fails to reclaim VWAP in first 30 min
      • THEN buy puts (IV already crushed, direction confirmed)
   
   4. EXPECTED MOVE CALCULATION:
      • ATM straddle price = implied move
      • Market is pricing in ~X% move either direction
      • If actual move < expected, both calls AND puts lose
''')
    
    # 9. FINAL RECOMMENDATION
    print('\n' + '='*80)
    print('🎯 9. FINAL RECOMMENDATION')
    print('='*80)
    
    print('''
   📊 VERDICT: DO NOT BUY PUTS BEFORE EARNINGS
   
   REASONS:
   1. IV is elevated (pre-earnings premium)
   2. IV crush will destroy put value post-earnings
   3. Direction is a coin flip (50/50)
   4. Risk/reward is NEGATIVE for pre-earnings puts
   
   ALTERNATIVE STRATEGIES:
   
   A. WAIT AND SEE (Recommended)
      • Wait for earnings release (after 4:00 PM ET)
      • Watch price action in after-hours
      • IF significant gap down:
        - Wait until market open tomorrow
        - See if VWAP reclaim fails in first 30 min
        - THEN buy puts (IV crushed, direction confirmed)
   
   B. IF YOU MUST TRADE (Advanced)
      • Use PUT SPREADS to reduce IV exposure
      • Example: Buy $110 Put, Sell $105 Put
      • This limits IV crush damage
      • Lower max profit, but defined risk
   
   C. POST-EARNINGS PLAY (Best Approach)
      • If AMD gaps down 5%+ and fails VWAP:
        - Buy Feb 14 expiry puts (1 week out)
        - Strike: 5-10% OTM from post-gap price
        - Target: 2x-3x (not 10x due to IV crush)
   
   ⚠️  KEY INSIGHT:
   Pre-earnings puts are a RETAIL TRAP. Smart money sells 
   options into earnings, they don't buy them. The house 
   (market makers) always wins on earnings plays.
''')
    
    print('='*80)
    print('Analysis complete. Trade wisely!')
    print('='*80)
    
    await alpaca.close()
    await polygon.close()
    await uw.close()


if __name__ == "__main__":
    asyncio.run(analyze_amd())
