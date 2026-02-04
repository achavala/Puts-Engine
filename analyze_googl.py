#!/usr/bin/env python3
"""
Google (GOOGL) Comprehensive Institutional Analysis
===================================================

Analysis Framework (30+ Years Trading + PhD Quant + Institutional Microstructure):

1. PRICE ACTION & TECHNICALS
   - Recent price movement (5-day, 20-day)
   - Support/resistance levels
   - Volume analysis
   
2. OPTIONS FLOW INTELLIGENCE
   - Put/Call ratio
   - Large block trades
   - Smart money positioning
   
3. DARK POOL ACTIVITY
   - Institutional distribution patterns
   - Large block prints
   
4. IMPLIED VOLATILITY ANALYSIS
   - Current IV rank
   - Term structure (inversion = near-term fear)
   - Skew analysis
   
5. INSTITUTIONAL SIGNALS
   - Early Warning System (EWS) check
   - Distribution engine signals
   - Liquidity vacuum indicators

6. EARNINGS & CATALYSTS
   - Earnings date proximity
   - Recent news/events
   
7. FINAL VERDICT
   - Calls, Puts, or WAIT
   - Strike selection
   - Expiry recommendation
   - Position sizing
"""

import asyncio
import json
from datetime import datetime, date, timedelta
from pathlib import Path

# Set up path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from putsengine.config import get_settings
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient


async def analyze_googl():
    """Run comprehensive GOOGL analysis."""
    
    print("=" * 80)
    print("🔍 GOOGLE (GOOGL) INSTITUTIONAL ANALYSIS")
    print("=" * 80)
    print(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}")
    print(f"Analyst Lens: 30+ Years Trading + PhD Quant + Institutional Microstructure")
    print("=" * 80)
    
    settings = get_settings()
    alpaca = AlpacaClient(settings)
    polygon = PolygonClient(settings)
    uw = UnusualWhalesClient(settings)
    
    symbol = "GOOGL"
    
    try:
        # =====================================================================
        # 1. PRICE ACTION & TECHNICALS
        # =====================================================================
        print("\n" + "=" * 80)
        print("📊 1. PRICE ACTION & TECHNICALS")
        print("=" * 80)
        
        # Get current price
        try:
            quote = await alpaca.get_latest_quote(symbol)
            current_price = (quote.bid_price + quote.ask_price) / 2 if quote else 0
            bid = quote.bid_price if quote else 0
            ask = quote.ask_price if quote else 0
            spread = ask - bid
            spread_pct = (spread / current_price * 100) if current_price else 0
            print(f"\n💰 Current Price: ${current_price:.2f}")
            print(f"   Bid/Ask: ${bid:.2f} / ${ask:.2f} (spread: ${spread:.2f}, {spread_pct:.3f}%)")
        except Exception as e:
            print(f"   Error getting quote: {e}")
            current_price = 0
        
        # Get historical bars for analysis
        try:
            from_date = date.today() - timedelta(days=30)
            bars = await alpaca.get_daily_bars(symbol, from_date)
            
            if bars and len(bars) >= 5:
                # Recent price action
                closes = [b.close for b in bars]
                volumes = [b.volume for b in bars]
                
                # Calculate key metrics
                price_5d_ago = closes[-6] if len(closes) >= 6 else closes[0]
                price_20d_ago = closes[0] if len(closes) >= 20 else closes[0]
                
                change_5d = ((closes[-1] - price_5d_ago) / price_5d_ago) * 100
                change_20d = ((closes[-1] - price_20d_ago) / price_20d_ago) * 100
                
                avg_volume = sum(volumes) / len(volumes)
                recent_volume = volumes[-1]
                rvol = recent_volume / avg_volume if avg_volume > 0 else 1
                
                # Find support/resistance
                highs = [b.high for b in bars[-20:]]
                lows = [b.low for b in bars[-20:]]
                resistance = max(highs)
                support = min(lows)
                
                # Recent trend (last 5 days)
                up_days = sum(1 for i in range(-5, 0) if closes[i] > closes[i-1])
                down_days = 5 - up_days
                
                print(f"\n📈 Recent Performance:")
                print(f"   5-Day Change:  {change_5d:+.2f}%")
                print(f"   20-Day Change: {change_20d:+.2f}%")
                print(f"   Last 5 Days:   {up_days} up, {down_days} down")
                
                print(f"\n📊 Volume Analysis:")
                print(f"   Today's Volume: {recent_volume:,.0f}")
                print(f"   Avg Volume:     {avg_volume:,.0f}")
                print(f"   RVOL:           {rvol:.2f}x {'🔥 HIGH' if rvol > 1.5 else '📉 LOW' if rvol < 0.7 else '➖ NORMAL'}")
                
                print(f"\n📍 Key Levels:")
                print(f"   20-Day High (Resistance): ${resistance:.2f}")
                print(f"   20-Day Low (Support):     ${support:.2f}")
                print(f"   Current vs Resistance:    {((current_price - resistance) / resistance * 100):+.2f}%")
                print(f"   Current vs Support:       {((current_price - support) / support * 100):+.2f}%")
                
                # Price structure assessment
                if current_price > resistance * 0.98:
                    price_structure = "AT RESISTANCE - potential reversal zone"
                    price_bias = "BEARISH"
                elif current_price < support * 1.02:
                    price_structure = "AT SUPPORT - potential bounce zone"
                    price_bias = "BULLISH"
                elif change_5d > 5:
                    price_structure = "EXTENDED RALLY - mean reversion likely"
                    price_bias = "BEARISH"
                elif change_5d < -5:
                    price_structure = "EXTENDED SELLOFF - bounce possible"
                    price_bias = "BULLISH"
                else:
                    price_structure = "MID-RANGE - no clear edge"
                    price_bias = "NEUTRAL"
                
                print(f"\n🎯 Price Structure: {price_structure}")
                print(f"   Technical Bias: {price_bias}")
                
        except Exception as e:
            print(f"   Error getting historical data: {e}")
            change_5d = 0
            change_20d = 0
            price_bias = "UNKNOWN"
        
        # =====================================================================
        # 2. OPTIONS FLOW INTELLIGENCE
        # =====================================================================
        print("\n" + "=" * 80)
        print("🌊 2. OPTIONS FLOW INTELLIGENCE")
        print("=" * 80)
        
        try:
            flow = await uw.get_options_flow(symbol)
            
            if flow:
                put_volume = 0
                call_volume = 0
                put_premium = 0
                call_premium = 0
                large_puts = []
                large_calls = []
                
                for trade in flow[:100]:  # Analyze last 100 trades
                    side = trade.get('put_call', '').upper()
                    volume = trade.get('volume', 0) or 0
                    premium = trade.get('premium', 0) or 0
                    size = trade.get('size', 0) or 0
                    
                    if side == 'PUT':
                        put_volume += volume
                        put_premium += premium
                        if premium > 100000:  # >$100K premium
                            large_puts.append(trade)
                    elif side == 'CALL':
                        call_volume += volume
                        call_premium += premium
                        if premium > 100000:
                            large_calls.append(trade)
                
                total_volume = put_volume + call_volume
                pc_ratio = put_volume / call_volume if call_volume > 0 else 999
                
                print(f"\n📊 Volume Analysis:")
                print(f"   Put Volume:  {put_volume:,}")
                print(f"   Call Volume: {call_volume:,}")
                print(f"   P/C Ratio:   {pc_ratio:.2f} {'🐻 BEARISH' if pc_ratio > 1.2 else '🐂 BULLISH' if pc_ratio < 0.8 else '➖ NEUTRAL'}")
                
                print(f"\n💰 Premium Analysis:")
                print(f"   Put Premium:  ${put_premium:,.0f}")
                print(f"   Call Premium: ${call_premium:,.0f}")
                
                # Analyze large trades (smart money)
                print(f"\n🐋 Large Trades (>$100K):")
                print(f"   Large Put Trades:  {len(large_puts)}")
                print(f"   Large Call Trades: {len(large_calls)}")
                
                # Show top large trades
                if large_puts:
                    print(f"\n   Top Large PUTS:")
                    for trade in sorted(large_puts, key=lambda x: x.get('premium', 0), reverse=True)[:3]:
                        strike = trade.get('strike_price', 0)
                        exp = trade.get('expiration_date', '')
                        prem = trade.get('premium', 0)
                        print(f"      ${strike} {exp}: ${prem:,.0f}")
                
                if large_calls:
                    print(f"\n   Top Large CALLS:")
                    for trade in sorted(large_calls, key=lambda x: x.get('premium', 0), reverse=True)[:3]:
                        strike = trade.get('strike_price', 0)
                        exp = trade.get('expiration_date', '')
                        prem = trade.get('premium', 0)
                        print(f"      ${strike} {exp}: ${prem:,.0f}")
                
                # Flow bias
                if pc_ratio > 1.5 and len(large_puts) > len(large_calls):
                    flow_bias = "STRONGLY BEARISH"
                elif pc_ratio > 1.2:
                    flow_bias = "BEARISH"
                elif pc_ratio < 0.6 and len(large_calls) > len(large_puts):
                    flow_bias = "STRONGLY BULLISH"
                elif pc_ratio < 0.8:
                    flow_bias = "BULLISH"
                else:
                    flow_bias = "NEUTRAL"
                
                print(f"\n🎯 Flow Bias: {flow_bias}")
            else:
                print("   No options flow data available")
                flow_bias = "UNKNOWN"
                
        except Exception as e:
            print(f"   Error getting options flow: {e}")
            flow_bias = "UNKNOWN"
        
        # =====================================================================
        # 3. DARK POOL ACTIVITY
        # =====================================================================
        print("\n" + "=" * 80)
        print("🌑 3. DARK POOL ACTIVITY")
        print("=" * 80)
        
        try:
            dp_data = await uw.get_dark_pool_flow(symbol)
            
            if dp_data:
                total_dp_volume = 0
                large_prints = []
                
                for print_data in dp_data[:50]:
                    size = print_data.get('size', 0) or 0
                    price = print_data.get('price', 0) or 0
                    total_dp_volume += size
                    
                    if size > 10000:  # Large block
                        large_prints.append(print_data)
                
                print(f"\n📊 Dark Pool Summary:")
                print(f"   Total DP Volume: {total_dp_volume:,} shares")
                print(f"   Large Blocks (>10K): {len(large_prints)}")
                
                if large_prints:
                    total_block_volume = sum(p.get('size', 0) for p in large_prints)
                    avg_block_price = sum(p.get('price', 0) * p.get('size', 0) for p in large_prints) / total_block_volume if total_block_volume > 0 else 0
                    
                    print(f"   Block Volume: {total_block_volume:,} shares")
                    print(f"   VWAP of Blocks: ${avg_block_price:.2f}")
                    
                    # Check if blocks are below current price (distribution)
                    if current_price > 0 and avg_block_price < current_price * 0.995:
                        dp_signal = "DISTRIBUTION - Institutions selling into strength"
                        dp_bias = "BEARISH"
                    elif current_price > 0 and avg_block_price > current_price * 1.005:
                        dp_signal = "ACCUMULATION - Institutions buying"
                        dp_bias = "BULLISH"
                    else:
                        dp_signal = "NEUTRAL - No clear institutional bias"
                        dp_bias = "NEUTRAL"
                    
                    print(f"\n🎯 Dark Pool Signal: {dp_signal}")
                else:
                    dp_bias = "NEUTRAL"
                    print("   No significant dark pool activity")
            else:
                print("   No dark pool data available")
                dp_bias = "UNKNOWN"
                
        except Exception as e:
            print(f"   Error getting dark pool data: {e}")
            dp_bias = "UNKNOWN"
        
        # =====================================================================
        # 4. IMPLIED VOLATILITY ANALYSIS
        # =====================================================================
        print("\n" + "=" * 80)
        print("📈 4. IMPLIED VOLATILITY ANALYSIS")
        print("=" * 80)
        
        try:
            iv_data = await uw.get_iv_data(symbol)
            
            if iv_data:
                current_iv = iv_data.get('implied_volatility', 0) or iv_data.get('iv', 0) or 0
                iv_rank = iv_data.get('iv_rank', 0) or 0
                iv_percentile = iv_data.get('iv_percentile', 0) or 0
                
                print(f"\n📊 IV Metrics:")
                print(f"   Current IV:    {current_iv*100:.1f}%" if current_iv < 5 else f"   Current IV:    {current_iv:.1f}%")
                print(f"   IV Rank:       {iv_rank:.1f}%")
                print(f"   IV Percentile: {iv_percentile:.1f}%")
                
                # IV assessment
                if iv_rank > 70:
                    iv_assessment = "HIGH IV - Options are EXPENSIVE"
                    iv_strategy = "SELL premium (spreads) or AVOID buying"
                    iv_bias = "EXPENSIVE"
                elif iv_rank > 50:
                    iv_assessment = "ELEVATED IV - Moderately expensive"
                    iv_strategy = "Use spreads to reduce cost"
                    iv_bias = "ELEVATED"
                elif iv_rank > 30:
                    iv_assessment = "NORMAL IV - Fair pricing"
                    iv_strategy = "Standard directional plays OK"
                    iv_bias = "NORMAL"
                else:
                    iv_assessment = "LOW IV - Options are CHEAP"
                    iv_strategy = "Good time to buy premium"
                    iv_bias = "CHEAP"
                
                print(f"\n🎯 IV Assessment: {iv_assessment}")
                print(f"   Strategy Hint: {iv_strategy}")
            else:
                print("   No IV data available")
                iv_rank = 50  # Assume mid
                iv_bias = "UNKNOWN"
                
        except Exception as e:
            print(f"   Error getting IV data: {e}")
            iv_rank = 50
            iv_bias = "UNKNOWN"
        
        # =====================================================================
        # 5. EARLY WARNING SYSTEM CHECK
        # =====================================================================
        print("\n" + "=" * 80)
        print("🚨 5. EARLY WARNING SYSTEM (EWS) CHECK")
        print("=" * 80)
        
        try:
            ews_file = Path(__file__).parent / "early_warning_alerts.json"
            if ews_file.exists():
                with open(ews_file, 'r') as f:
                    ews_data = json.load(f)
                
                alerts = ews_data.get("alerts", {})
                
                # Check for GOOGL or GOOG
                googl_alert = alerts.get("GOOGL") or alerts.get("GOOG")
                
                if googl_alert:
                    ipi = googl_alert.get("ipi", 0)
                    level = googl_alert.get("level", "none")
                    footprints = googl_alert.get("unique_footprints", 0)
                    recommendation = googl_alert.get("recommendation", "")
                    
                    print(f"\n⚠️ GOOGL IN EARLY WARNING SYSTEM!")
                    print(f"   IPI Score:   {ipi:.2f}")
                    print(f"   Alert Level: {level.upper()}")
                    print(f"   Footprints:  {footprints}")
                    print(f"   Guidance:    {recommendation}")
                    
                    ews_bias = "BEARISH" if level in ['act', 'prepare'] else "WATCH"
                else:
                    print(f"\n✅ GOOGL NOT in Early Warning System")
                    print("   No significant institutional distribution detected")
                    ews_bias = "NEUTRAL"
                    
                # Check scan timestamp
                scan_time = ews_data.get("timestamp", "")
                print(f"\n   Last EWS Scan: {scan_time}")
            else:
                print("   EWS data not available")
                ews_bias = "UNKNOWN"
                
        except Exception as e:
            print(f"   Error checking EWS: {e}")
            ews_bias = "UNKNOWN"
        
        # =====================================================================
        # 6. EARNINGS & CATALYSTS
        # =====================================================================
        print("\n" + "=" * 80)
        print("📅 6. EARNINGS & CATALYSTS")
        print("=" * 80)
        
        try:
            # Check earnings calendar
            earnings = await uw.get_earnings_calendar(symbol)
            
            if earnings:
                next_earnings = earnings.get('date') or earnings.get('earnings_date', 'Unknown')
                earnings_time = earnings.get('time', 'Unknown')
                
                print(f"\n📆 Next Earnings: {next_earnings} ({earnings_time})")
                
                # Check if earnings is soon
                try:
                    if next_earnings and next_earnings != 'Unknown':
                        earnings_date = datetime.strptime(str(next_earnings)[:10], "%Y-%m-%d").date()
                        days_to_earnings = (earnings_date - date.today()).days
                        
                        print(f"   Days Until Earnings: {days_to_earnings}")
                        
                        if days_to_earnings <= 7:
                            earnings_warning = "⚠️ EARNINGS IMMINENT - High IV crush risk!"
                            earnings_bias = "AVOID OPTIONS"
                        elif days_to_earnings <= 14:
                            earnings_warning = "📊 Earnings approaching - Elevated IV"
                            earnings_bias = "CAUTION"
                        else:
                            earnings_warning = "✅ No imminent earnings risk"
                            earnings_bias = "CLEAR"
                        
                        print(f"   {earnings_warning}")
                    else:
                        earnings_bias = "UNKNOWN"
                except:
                    earnings_bias = "UNKNOWN"
            else:
                print("   No earnings data available")
                # Google typically reports in late January, April, July, October
                print("   Note: Alphabet typically reports late Jan, Apr, Jul, Oct")
                earnings_bias = "UNKNOWN"
                
        except Exception as e:
            print(f"   Error getting earnings data: {e}")
            earnings_bias = "UNKNOWN"
        
        # =====================================================================
        # 7. SECTOR & MARKET CONTEXT
        # =====================================================================
        print("\n" + "=" * 80)
        print("🌍 7. SECTOR & MARKET CONTEXT")
        print("=" * 80)
        
        # Check QQQ (tech sector proxy)
        try:
            qqq_quote = await alpaca.get_latest_quote("QQQ")
            qqq_price = (qqq_quote.bid_price + qqq_quote.ask_price) / 2 if qqq_quote else 0
            
            qqq_bars = await alpaca.get_daily_bars("QQQ", date.today() - timedelta(days=10))
            if qqq_bars and len(qqq_bars) >= 5:
                qqq_5d_change = ((qqq_bars[-1].close - qqq_bars[-6].close) / qqq_bars[-6].close) * 100
                
                print(f"\n📊 Tech Sector (QQQ):")
                print(f"   Current: ${qqq_price:.2f}")
                print(f"   5-Day Change: {qqq_5d_change:+.2f}%")
                
                if qqq_5d_change > 3:
                    sector_context = "RISK-ON - Tech rallying"
                    sector_bias = "BULLISH"
                elif qqq_5d_change < -3:
                    sector_context = "RISK-OFF - Tech selling"
                    sector_bias = "BEARISH"
                else:
                    sector_context = "NEUTRAL - Consolidating"
                    sector_bias = "NEUTRAL"
                
                print(f"   Sector Context: {sector_context}")
        except Exception as e:
            print(f"   Error getting sector data: {e}")
            sector_bias = "UNKNOWN"
        
        # =====================================================================
        # 8. FINAL VERDICT
        # =====================================================================
        print("\n" + "=" * 80)
        print("🎯 8. FINAL VERDICT")
        print("=" * 80)
        
        # Aggregate all signals
        signals = {
            'price_bias': price_bias if 'price_bias' in dir() else 'UNKNOWN',
            'flow_bias': flow_bias if 'flow_bias' in dir() else 'UNKNOWN',
            'dp_bias': dp_bias if 'dp_bias' in dir() else 'UNKNOWN',
            'ews_bias': ews_bias if 'ews_bias' in dir() else 'UNKNOWN',
            'sector_bias': sector_bias if 'sector_bias' in dir() else 'UNKNOWN',
        }
        
        print(f"\n📊 Signal Summary:")
        print(f"   Price Action:  {signals['price_bias']}")
        print(f"   Options Flow:  {signals['flow_bias']}")
        print(f"   Dark Pool:     {signals['dp_bias']}")
        print(f"   EWS Alert:     {signals['ews_bias']}")
        print(f"   Sector:        {signals['sector_bias']}")
        
        # Count bearish vs bullish signals
        bearish_count = sum(1 for v in signals.values() if 'BEARISH' in str(v))
        bullish_count = sum(1 for v in signals.values() if 'BULLISH' in str(v))
        
        print(f"\n📈 Signal Tally:")
        print(f"   Bullish Signals: {bullish_count}")
        print(f"   Bearish Signals: {bearish_count}")
        
        # Final recommendation
        print("\n" + "-" * 80)
        
        # Check for IV crush risk first
        if 'iv_rank' in dir() and iv_rank > 70:
            print("""
🚨 HIGH IV WARNING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

IV Rank is elevated (>70). Buying options is EXPENSIVE.
Even if direction is correct, IV crush can hurt returns.

RECOMMENDATION: Use SPREADS instead of naked options to reduce vega exposure.
""")
        
        if bearish_count >= 3:
            print("""
🐻 VERDICT: PUTS (Bearish Setup)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Multiple bearish signals are converging:
""")
            for k, v in signals.items():
                if 'BEARISH' in str(v):
                    print(f"   ✓ {k.replace('_', ' ').title()}: {v}")
            
            print(f"""
📋 TRADE STRUCTURE:
   • Expiry: 7-14 DTE (enough time, not too much theta decay)
   • Strike: 2-3% OTM (e.g., ${current_price * 0.97:.0f} - ${current_price * 0.98:.0f})
   • Delta: -0.30 to -0.40
   • Size: 2-3% of portfolio max
   • Entry: Wait for bounce to VWAP or prior support
   • Stop: Close if breaks above resistance (${resistance:.2f})
   
⚠️ RISK MANAGEMENT:
   • Max loss: Premium paid
   • Target: 50-100% gain
   • Time stop: Close by 5 DTE if no movement
""")
            
        elif bullish_count >= 3:
            print("""
🐂 VERDICT: CALLS (Bullish Setup)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Multiple bullish signals are converging:
""")
            for k, v in signals.items():
                if 'BULLISH' in str(v):
                    print(f"   ✓ {k.replace('_', ' ').title()}: {v}")
            
            print(f"""
📋 TRADE STRUCTURE:
   • Expiry: 14-21 DTE (more time for upside)
   • Strike: ATM to 2% OTM (e.g., ${current_price:.0f} - ${current_price * 1.02:.0f})
   • Delta: 0.40 to 0.50
   • Size: 2-3% of portfolio max
   • Entry: On pullback to support (${support:.2f})
   • Stop: Close if breaks below support
   
⚠️ RISK MANAGEMENT:
   • Max loss: Premium paid
   • Target: 50-100% gain
   • Time stop: Close by 7 DTE if no movement
""")
            
        else:
            print("""
⏸️ VERDICT: WAIT (No Clear Edge)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Signals are mixed or neutral. No high-conviction trade setup.

AS A 30-YEAR TRADER'S RULE:
"When in doubt, stay out. The market will always give another opportunity."

📋 WHAT TO WATCH FOR:
""")
            print(f"   • Break above ${resistance:.2f} → Bullish confirmation")
            print(f"   • Break below ${support:.2f} → Bearish confirmation")
            print(f"   • Watch for unusual options flow (large blocks)")
            print(f"   • Monitor EWS for institutional footprints")
            
            print("""
🎯 ALTERNATIVE STRATEGIES (Neutral View):
   • Iron Condor: Profit from range-bound movement
   • Straddle/Strangle: Bet on volatility (if IV is cheap)
   • Wait for clearer setup
""")
        
        print("\n" + "=" * 80)
        print("📝 INSTITUTIONAL WISDOM")
        print("=" * 80)
        print("""
🏛️ Key Principles for GOOGL:

1. MEGA-CAP BEHAVIOR: As a $2T+ company, GOOGL moves slower than growth stocks.
   Large moves (>5%) typically need significant catalysts.

2. AI NARRATIVE: Google is at the center of the AI narrative (Gemini, Bard).
   Any AI news from Microsoft/OpenAI can impact GOOGL.

3. ANTITRUST RISK: DOJ cases pending. Unexpected rulings can cause gaps.

4. AD REVENUE SENSITIVITY: Digital ad spending trends affect GOOGL heavily.
   Economic data (consumer confidence, retail sales) matters.

5. OPTIONS CHARACTERISTICS:
   - High liquidity in GOOGL options (tight spreads)
   - Weekly options available for short-term plays
   - Often follows QQQ but with lower beta

6. EARNINGS PLAYBOOK:
   - NEVER buy options into earnings (IV crush is severe)
   - Post-earnings continuation trades are safer
   - Watch for guidance more than the numbers
""")
        
    except Exception as e:
        print(f"\n❌ Analysis Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await alpaca.close()
        await polygon.close()
        await uw.close()


if __name__ == "__main__":
    asyncio.run(analyze_googl())
