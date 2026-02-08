#!/usr/bin/env python3
"""
QQQ 2-Week Outlook — Institutional Microstructure Analysis
Uses live data from Polygon + Unusual Whales APIs
"""
import asyncio
import sys
import os
import json
from datetime import datetime, date, timedelta
import math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from putsengine.config import Settings
from putsengine.clients.unusual_whales_client import UnusualWhalesClient
from putsengine.clients.polygon_client import PolygonClient

settings = Settings()

def _date_ago(days):
    """Get date N days ago."""
    return date.today() - timedelta(days=days)

async def main():
    uw = UnusualWhalesClient(settings)
    polygon = PolygonClient(settings)
    
    print("=" * 80)
    print("QQQ 2-WEEK INSTITUTIONAL MICROSTRUCTURE ANALYSIS")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M ET')}")
    print("=" * 80)
    
    # ======================================================================
    # 1. PRICE ACTION — Recent bars from Polygon
    # ======================================================================
    print("\n" + "=" * 80)
    print("📊 SECTION 1: PRICE ACTION & TECHNICAL STRUCTURE")
    print("=" * 80)
    
    bars = await polygon.get_daily_bars("QQQ", from_date=_date_ago(45), to_date=date.today())
    if bars:
        print(f"\nLast 10 trading days:")
        print(f"{'Date':12s} {'Open':>9s} {'High':>9s} {'Low':>9s} {'Close':>9s} {'Volume':>12s} {'Change':>8s}")
        print("-" * 72)
        for bar in bars[-10:]:
            chg = ((bar.close - bar.open) / bar.open) * 100
            print(f"{bar.timestamp.strftime('%Y-%m-%d'):12s} {bar.open:9.2f} {bar.high:9.2f} {bar.low:9.2f} {bar.close:9.2f} {bar.volume:12,.0f} {chg:+7.2f}%")
        
        # Key levels
        closes = [b.close for b in bars[-20:]]
        highs = [b.high for b in bars[-20:]]
        lows = [b.low for b in bars[-20:]]
        volumes = [b.volume for b in bars[-20:]]
        current = closes[-1]
        
        sma_5 = sum(closes[-5:]) / 5
        sma_10 = sum(closes[-10:]) / 10
        sma_20 = sum(closes[-20:]) / 20
        
        avg_vol = sum(volumes) / len(volumes)
        recent_vol = sum(volumes[-5:]) / 5
        vol_ratio = recent_vol / avg_vol
        
        # ATR (14-day)
        true_ranges = []
        for i in range(1, min(15, len(bars))):
            tr = max(
                bars[-i].high - bars[-i].low,
                abs(bars[-i].high - bars[-i-1].close),
                abs(bars[-i].low - bars[-i-1].close)
            )
            true_ranges.append(tr)
        atr_14 = sum(true_ranges) / len(true_ranges) if true_ranges else 0
        
        # RSI (14-day)
        gains, losses = [], []
        for i in range(1, min(15, len(closes))):
            delta = closes[-i] - closes[-i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        avg_gain = sum(gains) / len(gains) if gains else 0
        avg_loss = sum(losses) / len(losses) if losses else 0.001
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        # 20-day high/low
        high_20 = max(highs)
        low_20 = min(lows)
        range_20 = high_20 - low_20
        position_in_range = (current - low_20) / range_20 * 100 if range_20 > 0 else 50
        
        # Trend
        daily_returns = [(closes[i] - closes[i-1]) / closes[i-1] * 100 for i in range(1, len(closes))]
        realized_vol = (sum(r**2 for r in daily_returns[-10:]) / 10) ** 0.5 if len(daily_returns) >= 10 else 0
        
        print(f"\n--- KEY LEVELS ---")
        print(f"  Current Price:   ${current:.2f}")
        print(f"  5-day SMA:       ${sma_5:.2f} ({'above' if current > sma_5 else 'BELOW'})")
        print(f"  10-day SMA:      ${sma_10:.2f} ({'above' if current > sma_10 else 'BELOW'})")
        print(f"  20-day SMA:      ${sma_20:.2f} ({'above' if current > sma_20 else 'BELOW'})")
        print(f"  20-day High:     ${high_20:.2f}")
        print(f"  20-day Low:      ${low_20:.2f}")
        print(f"  Position in Range: {position_in_range:.1f}% (0=low, 100=high)")
        print(f"  ATR(14):         ${atr_14:.2f} ({atr_14/current*100:.2f}% of price)")
        print(f"  RSI(14):         {rsi:.1f}")
        print(f"  Vol Ratio (5d/20d): {vol_ratio:.2f}x")
        print(f"  10-day Realized Vol: {realized_vol:.2f}% daily")
    
    # ======================================================================
    # 2. VIX & VOLATILITY REGIME
    # ======================================================================
    print("\n" + "=" * 80)
    print("🌪️ SECTION 2: VOLATILITY REGIME (VIX)")
    print("=" * 80)
    
    vix_current = 0
    vix_5d_avg = 0
    vix_20d_avg = 0
    vix_high_20 = 0
    vix_low_20 = 0
    vix_regime = "UNKNOWN"
    
    # Try multiple VIX tickers
    for vix_sym in ["VIXY", "I:VIX", "VIX"]:
        vix_bars = await polygon.get_daily_bars(vix_sym, from_date=_date_ago(30), to_date=date.today())
        if vix_bars:
            break
    
    # Also try UW market overview for VIX
    if not vix_bars:
        try:
            uw_overview = await uw._request("/api/market/overview")
            if uw_overview:
                data = uw_overview.get("data", uw_overview)
                if isinstance(data, dict):
                    vix_val = data.get("vix") or data.get("cboe_vix")
                    if vix_val:
                        vix_current = float(vix_val)
                        print(f"  VIX (from UW market overview): {vix_current:.2f}")
        except:
            pass
    
    if vix_bars:
        vix_current = vix_bars[-1].close
        vix_5d_avg = sum(b.close for b in vix_bars[-5:]) / 5
        vix_20d_avg = sum(b.close for b in vix_bars[-20:]) / 20
        vix_high_20 = max(b.high for b in vix_bars[-20:])
        vix_low_20 = min(b.low for b in vix_bars[-20:])
        
        print(f"  VIX Current:     {vix_current:.2f}")
        print(f"  VIX 5-day Avg:   {vix_5d_avg:.2f}")
        print(f"  VIX 20-day Avg:  {vix_20d_avg:.2f}")
        print(f"  VIX 20-day Range: {vix_low_20:.2f} — {vix_high_20:.2f}")
        
        if vix_current < 15:
            vix_regime = "COMPLACENT (sub-15: low fear, potential complacency trap)"
        elif vix_current < 20:
            vix_regime = "NORMAL (15-20: healthy market anxiety)"
        elif vix_current < 25:
            vix_regime = "ELEVATED (20-25: hedging activity increasing)"
        elif vix_current < 30:
            vix_regime = "HIGH FEAR (25-30: institutional de-risking)"
        else:
            vix_regime = "PANIC (30+: forced liquidation territory)"
        print(f"  VIX Regime:      {vix_regime}")
        
        # VIX term structure (VIX vs VIX3M proxy)
        print(f"\n  VIX Trend (last 5 days):")
        for b in vix_bars[-5:]:
            chg = b.close - b.open
            print(f"    {b.timestamp.strftime('%Y-%m-%d')}: {b.close:.2f} ({chg:+.2f})")
    
    # ======================================================================
    # 3. GEX / DEALER POSITIONING
    # ======================================================================
    print("\n" + "=" * 80)
    print("🎰 SECTION 3: DEALER POSITIONING (GEX)")
    print("=" * 80)
    
    spy_gex = await uw.get_gex_data("SPY")
    qqq_gex = await uw.get_gex_data("QQQ")
    
    for label, gex in [("SPY", spy_gex), ("QQQ", qqq_gex)]:
        if gex:
            regime = "POSITIVE (dealers short gamma → dampen moves)" if gex.net_gex > 0 else "NEGATIVE (dealers long gamma → AMPLIFY moves)"
            print(f"\n  {label} GEX:")
            print(f"    Net GEX:       {gex.net_gex:,.0f}")
            print(f"    Call Gamma:    {gex.call_gex:,.0f}")
            print(f"    Put Gamma:     {gex.put_gex:,.0f}")
            print(f"    Dealer Delta:  {gex.dealer_delta:,.0f}")
            print(f"    GEX Regime:    {regime}")
            if gex.put_wall:
                print(f"    Put Wall:      ${gex.put_wall:.0f}")
            if gex.call_wall:
                print(f"    Call Wall:     ${gex.call_wall:.0f}")
            if gex.gex_flip_level:
                print(f"    GEX Flip:      ${gex.gex_flip_level:.2f}")
        else:
            print(f"\n  {label} GEX: Not available")
    
    # ======================================================================
    # 4. OPTIONS FLOW & SENTIMENT
    # ======================================================================
    print("\n" + "=" * 80)
    print("💰 SECTION 4: OPTIONS FLOW & INSTITUTIONAL SENTIMENT")
    print("=" * 80)
    
    flows = await uw.get_flow_recent("QQQ", limit=100)
    if flows:
        bearish = [f for f in flows if f.sentiment == "bearish"]
        bullish = [f for f in flows if f.sentiment == "bullish"]
        neutral = [f for f in flows if f.sentiment == "neutral"]
        
        bear_premium = sum(f.premium for f in bearish)
        bull_premium = sum(f.premium for f in bullish)
        total_premium = bear_premium + bull_premium
        
        puts = [f for f in flows if f.option_type.lower() == "put"]
        calls = [f for f in flows if f.option_type.lower() == "call"]
        put_premium = sum(f.premium for f in puts)
        call_premium = sum(f.premium for f in calls)
        
        sweeps = [f for f in flows if f.is_sweep]
        blocks = [f for f in flows if f.is_block]
        
        print(f"  Recent {len(flows)} flow records:")
        print(f"    Bearish:  {len(bearish)} trades, ${bear_premium:,.0f} premium")
        print(f"    Bullish:  {len(bullish)} trades, ${bull_premium:,.0f} premium")
        print(f"    Neutral:  {len(neutral)} trades")
        print(f"    Put/Call Premium Ratio: {put_premium/max(call_premium,1):.2f}")
        print(f"    Sweeps: {len(sweeps)} | Blocks: {len(blocks)}")
        
        if total_premium > 0:
            bear_pct = bear_premium / total_premium * 100
            print(f"    Bearish Premium %: {bear_pct:.1f}%")
        
        # Top 5 largest trades
        sorted_flows = sorted(flows, key=lambda f: f.premium, reverse=True)
        print(f"\n  TOP 5 LARGEST TRADES:")
        for i, f in enumerate(sorted_flows[:5]):
            sweep_tag = " [SWEEP]" if f.is_sweep else (" [BLOCK]" if f.is_block else "")
            print(f"    #{i+1}: {f.option_type} ${f.strike:.0f} exp={f.expiration} "
                  f"premium=${f.premium:,.0f} side={f.side} → {f.sentiment}{sweep_tag}")
    
    # ======================================================================
    # 5. IV TERM STRUCTURE
    # ======================================================================
    print("\n" + "=" * 80)
    print("📈 SECTION 5: IV TERM STRUCTURE & SKEW")
    print("=" * 80)
    
    iv = await uw.get_iv_term_structure("QQQ")
    if iv and isinstance(iv, dict):
        iv_7d = iv.get("7_day", 0)
        iv_30d = iv.get("30_day", 0)
        iv_60d = iv.get("60_day", 0)
        inverted = iv.get("iv_inverted", False)
        slope = iv.get("term_structure_slope", 0)
        
        print(f"  7-day IV:   {iv_7d*100:.1f}%" if iv_7d else "  7-day IV:   N/A")
        print(f"  30-day IV:  {iv_30d*100:.1f}%" if iv_30d else "  30-day IV:  N/A")
        print(f"  60-day IV:  {iv_60d*100:.1f}%" if iv_60d else "  60-day IV:  N/A")
        
        if inverted:
            print(f"  ⚠️  IV INVERSION: Near-term > Far-term = hedging activity!")
        else:
            print(f"  ✅ Normal contango (far-term > near-term)")
        
        if slope:
            print(f"  Term Structure Slope: {slope:.4f}")
    
    skew = await uw.get_skew("QQQ")
    if skew and isinstance(skew, dict):
        rr = skew.get("risk_reversal")
        sc = skew.get("skew_change")
        if rr is not None:
            print(f"\n  Risk Reversal:  {rr:.4f}")
            print(f"  Skew Change:    {sc:.4f}" if sc else "")
            if rr and rr < -2:
                print(f"  ⚠️  Negative skew: puts are EXPENSIVE relative to calls")
    
    # ======================================================================
    # 6. DARK POOL ACTIVITY
    # ======================================================================
    print("\n" + "=" * 80)
    print("🏦 SECTION 6: DARK POOL INSTITUTIONAL ACTIVITY")
    print("=" * 80)
    
    dp = await uw.get_dark_pool_flow("QQQ", limit=30)
    if dp:
        buys = [p for p in dp if p.is_buy is True]
        sells = [p for p in dp if p.is_buy is False]
        ambig = [p for p in dp if p.is_buy is None]
        
        buy_vol = sum(p.size for p in buys)
        sell_vol = sum(p.size for p in sells)
        total_vol = buy_vol + sell_vol
        
        print(f"  {len(dp)} dark pool prints:")
        print(f"    Buy-side:  {len(buys)} prints, {buy_vol:,} shares")
        print(f"    Sell-side: {len(sells)} prints, {sell_vol:,} shares")
        print(f"    Ambiguous: {len(ambig)} prints")
        if total_vol > 0:
            sell_pct = sell_vol / total_vol * 100
            print(f"    Sell Volume %: {sell_pct:.1f}%")
            if sell_pct > 60:
                print(f"    ⚠️  Institutional DISTRIBUTION detected (sell > 60%)")
            elif sell_pct < 40:
                print(f"    ✅ Institutional ACCUMULATION (buy > 60%)")
    
    # ======================================================================
    # 7. MARKET TIDE
    # ======================================================================
    print("\n" + "=" * 80)
    print("🌊 SECTION 7: MARKET TIDE & BROAD SENTIMENT")
    print("=" * 80)
    
    tide = await uw.get_market_tide()
    if tide:
        data = tide.get("data", tide) if isinstance(tide, dict) else tide
        if isinstance(data, list) and data:
            latest = data[-1] if isinstance(data[-1], dict) else data[0]
        elif isinstance(data, dict):
            latest = data
        else:
            latest = {}
        
        if latest:
            for key in sorted(latest.keys()):
                val = latest[key]
                if isinstance(val, (int, float)):
                    print(f"    {key}: {val:,.2f}" if isinstance(val, float) else f"    {key}: {val:,}")
                elif val:
                    print(f"    {key}: {val}")
    
    # ======================================================================
    # 8. OI CHANGE & MAX PAIN
    # ======================================================================
    print("\n" + "=" * 80)
    print("📋 SECTION 8: OPEN INTEREST & MAX PAIN")
    print("=" * 80)
    
    oi = await uw.get_oi_change("QQQ")
    if oi:
        data = oi.get("data", oi) if isinstance(oi, dict) else oi
        if isinstance(data, list) and data:
            latest = data[-1] if isinstance(data[-1], dict) else data[0]
            if isinstance(latest, dict):
                for key in ['call_oi', 'put_oi', 'call_oi_change', 'put_oi_change',
                           'total_oi', 'put_call_oi_ratio', 'call_volume', 'put_volume']:
                    val = latest.get(key)
                    if val is not None:
                        if isinstance(val, float):
                            print(f"    {key}: {val:,.4f}" if abs(val) < 10 else f"    {key}: {val:,.0f}")
                        else:
                            print(f"    {key}: {val:,}" if isinstance(val, int) else f"    {key}: {val}")
    
    max_pain = await uw.get_max_pain("QQQ")
    if max_pain:
        data = max_pain.get("data", max_pain) if isinstance(max_pain, dict) else max_pain
        if isinstance(data, list) and data:
            mp = data[0] if isinstance(data[0], dict) else {}
        elif isinstance(data, dict):
            mp = data
        else:
            mp = {}
        if mp:
            mp_price = mp.get("price", mp.get("max_pain", mp.get("strike")))
            if mp_price:
                print(f"\n  Max Pain Level: ${float(mp_price):.2f}")
                if bars and current:
                    dist = (current - float(mp_price)) / current * 100
                    print(f"  Distance from current: {dist:+.2f}%")
    
    # ======================================================================
    # 9. SECTOR ETF CHECK (Tech heavy = QQQ driver)
    # ======================================================================
    print("\n" + "=" * 80)
    print("🏭 SECTION 9: SECTOR & MEGA-CAP CONTEXT")
    print("=" * 80)
    
    sector_tickers = ["XLK", "SMH", "SOXX", "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA"]
    print(f"  {'Ticker':8s} {'Close':>9s} {'5d Chg':>8s} {'10d Chg':>9s}")
    print("  " + "-" * 40)
    for ticker in sector_tickers:
        try:
            tbars = await polygon.get_daily_bars(ticker, from_date=_date_ago(20), to_date=date.today())
            if tbars and len(tbars) >= 2:
                close = tbars[-1].close
                chg_1d = (close - tbars[-2].close) / tbars[-2].close * 100
                chg_5d = (close - tbars[-6].close) / tbars[-6].close * 100 if len(tbars) >= 6 else 0
                chg_10d = (close - tbars[-11].close) / tbars[-11].close * 100 if len(tbars) >= 11 else 0
                print(f"  {ticker:8s} ${close:8.2f} {chg_5d:+7.2f}% {chg_10d:+8.2f}%")
        except Exception:
            pass
    
    # ======================================================================
    # SYNTHESIS — 2-WEEK DAILY PROJECTION
    # ======================================================================
    print("\n" + "=" * 80)
    print("🎯 SECTION 10: 2-WEEK DAILY PROJECTION")
    print("=" * 80)
    
    if bars and current and atr_14:
        # Build daily expected move based on ATR and IV
        implied_daily_move = 0
        if iv and isinstance(iv, dict) and iv.get("30_day"):
            # Convert annualized IV to daily expected move
            implied_daily_move = current * iv["30_day"] / (252 ** 0.5)
        else:
            implied_daily_move = atr_14  # Fallback to ATR
        
        print(f"\n  Base Price:        ${current:.2f}")
        print(f"  ATR(14):           ${atr_14:.2f}")
        print(f"  Implied Daily Move: ${implied_daily_move:.2f} ({implied_daily_move/current*100:.2f}%)")
        
        # Collect all signals for bias
        signals = []
        
        # Technical signals
        if current > sma_20:
            signals.append(("TECH", "Above 20-SMA", +0.3))
        else:
            signals.append(("TECH", "Below 20-SMA", -0.3))
        
        if current > sma_5:
            signals.append(("TECH", "Above 5-SMA (short-term bullish)", +0.2))
        else:
            signals.append(("TECH", "Below 5-SMA (short-term bearish)", -0.2))
        
        if rsi > 70:
            signals.append(("TECH", f"RSI overbought ({rsi:.0f})", -0.3))
        elif rsi < 30:
            signals.append(("TECH", f"RSI oversold ({rsi:.0f})", +0.3))
        elif rsi > 60:
            signals.append(("TECH", f"RSI strong ({rsi:.0f})", +0.1))
        elif rsi < 40:
            signals.append(("TECH", f"RSI weak ({rsi:.0f})", -0.1))
        
        # GEX signals
        if qqq_gex:
            if qqq_gex.net_gex > 0:
                signals.append(("GEX", "Positive GEX (dealers dampen moves = range-bound)", +0.1))
            else:
                signals.append(("GEX", "Negative GEX (dealers amplify moves = trend)", -0.2))
        
        # Flow signals
        if flows:
            if bear_pct > 60:
                signals.append(("FLOW", f"Bearish flow dominant ({bear_pct:.0f}%)", -0.3))
            elif bear_pct < 40:
                signals.append(("FLOW", f"Bullish flow dominant ({100-bear_pct:.0f}%)", +0.3))
        
        # IV signals
        if iv and isinstance(iv, dict) and iv.get("iv_inverted"):
            signals.append(("IV", "IV term structure INVERTED (hedging activity)", -0.3))
        
        # VIX signals
        if vix_bars:
            if vix_current < 15:
                signals.append(("VIX", f"Complacent VIX ({vix_current:.1f}) — mean-reversion risk", -0.1))
            elif vix_current > 25:
                signals.append(("VIX", f"Elevated VIX ({vix_current:.1f}) — oversold bounce possible", +0.2))
            elif vix_current > vix_5d_avg:
                signals.append(("VIX", f"VIX rising ({vix_current:.1f} > 5d avg {vix_5d_avg:.1f})", -0.2))
            else:
                signals.append(("VIX", f"VIX stable/falling ({vix_current:.1f})", +0.1))
        
        # Dark pool
        if dp and total_vol > 0:
            if sell_pct > 60:
                signals.append(("DP", f"Dark pool selling ({sell_pct:.0f}%)", -0.2))
            elif sell_pct < 40:
                signals.append(("DP", f"Dark pool buying ({100-sell_pct:.0f}%)", +0.2))
        
        # Skew
        if skew and isinstance(skew, dict) and skew.get("risk_reversal"):
            rr_val = skew["risk_reversal"]
            if rr_val < -3:
                signals.append(("SKEW", f"Heavy put skew (RR={rr_val:.2f})", -0.2))
            elif rr_val < -1:
                signals.append(("SKEW", f"Moderate put skew (RR={rr_val:.2f})", -0.1))
            elif rr_val > 1:
                signals.append(("SKEW", f"Call skew (RR={rr_val:.2f})", +0.1))
        
        # Position in range
        if position_in_range > 80:
            signals.append(("RANGE", f"Near 20-day high ({position_in_range:.0f}%) — resistance risk", -0.2))
        elif position_in_range < 20:
            signals.append(("RANGE", f"Near 20-day low ({position_in_range:.0f}%) — support bounce", +0.2))
        
        # Volume
        if vol_ratio > 1.3:
            signals.append(("VOL", f"Elevated volume ({vol_ratio:.1f}x avg) — conviction move", 0))
        elif vol_ratio < 0.7:
            signals.append(("VOL", f"Low volume ({vol_ratio:.1f}x avg) — weak conviction", 0))
        
        # Print signal summary
        print(f"\n  --- SIGNAL SUMMARY ---")
        total_bias = 0
        for cat, desc, bias in signals:
            direction = "🟢" if bias > 0 else ("🔴" if bias < 0 else "⚪")
            print(f"    {direction} [{cat:5s}] {desc} (bias: {bias:+.1f})")
            total_bias += bias
        
        print(f"\n  AGGREGATE BIAS: {total_bias:+.2f}")
        if total_bias > 0.5:
            outlook = "MODERATELY BULLISH"
        elif total_bias > 0.2:
            outlook = "SLIGHTLY BULLISH"
        elif total_bias > -0.2:
            outlook = "NEUTRAL / RANGE-BOUND"
        elif total_bias > -0.5:
            outlook = "SLIGHTLY BEARISH"
        else:
            outlook = "MODERATELY BEARISH"
        print(f"  2-WEEK OUTLOOK: {outlook}")
        
        # Daily projection
        print(f"\n  --- DAILY PRICE PROJECTION (next 10 trading days) ---")
        print(f"  {'Day':5s} {'Date':12s} {'Expected':>10s} {'Bull Case':>10s} {'Bear Case':>10s} {'Key Event / Note'}")
        print("  " + "-" * 80)
        
        # Build a day-by-day projection with structural awareness
        proj_price = current
        
        # Bias decay: strongest in first 3 days, fades toward mean
        # math already imported at top
        
        trading_days = []
        d = date.today()
        while len(trading_days) < 10:
            d += timedelta(days=1)
            if d.weekday() < 5:  # Skip weekends
                trading_days.append(d)
        
        # Key events (earnings season Feb, FOMC, CPI, etc.)
        events = {
            date(2026, 2, 9): "Mon — Weekly open, positioning reset",
            date(2026, 2, 10): "Tue — Continuation day",
            date(2026, 2, 11): "Wed — Mid-week, watch for CPI/Fed speakers",
            date(2026, 2, 12): "Thu — COIN earnings AMC, tech sector rotation risk",
            date(2026, 2, 13): "Fri — Weekly options expiration, pin risk",
            date(2026, 2, 14): "Fri — Valentine's Day, low volume possible",
            date(2026, 2, 17): "Mon — Presidents' Day — MARKET CLOSED",
            date(2026, 2, 18): "Tue — Post-holiday catch-up, gap risk",
            date(2026, 2, 19): "Wed — FOMC Minutes (if scheduled), mid-week",
            date(2026, 2, 20): "Thu — Continuation, earnings tail effects",
            date(2026, 2, 21): "Fri — Monthly OpEx week begins, dealer hedging",
        }
        
        cumulative_move = 0
        for i, td in enumerate(trading_days):
            # Daily bias decays over time
            day_bias = total_bias * math.exp(-0.15 * i)  # Exponential decay
            
            # Mean reversion: if moved too far, pull back
            if cumulative_move > atr_14 * 2:
                day_bias -= 0.3  # Overbought pullback
            elif cumulative_move < -atr_14 * 2:
                day_bias += 0.3  # Oversold bounce
            
            # Friday pin effect
            if td.weekday() == 4:
                day_bias *= 0.5  # Reduced move on OpEx Fridays
            
            # Monday gap tendency
            if td.weekday() == 0:
                day_bias *= 1.2  # Monday gaps tend to be larger
            
            # Expected daily move
            daily_move = implied_daily_move * (0.3 * day_bias)  # Bias shifts the center
            
            # Scenarios
            bull_move = implied_daily_move * 0.8
            bear_move = -implied_daily_move * 0.8
            
            proj_price += daily_move
            cumulative_move += daily_move
            
            bull_price = proj_price + bull_move
            bear_price = proj_price + bear_move
            
            event = events.get(td, "")
            
            # Skip market closed days
            if "CLOSED" in event:
                print(f"  {i+1:3d}   {td.strftime('%Y-%m-%d'):12s} {'--- MARKET CLOSED ---':>10s} {'':>10s} {'':>10s} {event}")
                continue
            
            print(f"  {i+1:3d}   {td.strftime('%Y-%m-%d'):12s} ${proj_price:9.2f} ${bull_price:9.2f} ${bear_price:9.2f} {event}")
        
        # 2-week range
        max_bull_2w = current + implied_daily_move * 10 * 0.5 + current * total_bias * 0.02
        max_bear_2w = current - implied_daily_move * 10 * 0.5 + current * total_bias * 0.02
        
        print(f"\n  --- 2-WEEK RANGE ESTIMATE ---")
        print(f"  Bull Case (1σ):  ${max_bull_2w:.2f} ({(max_bull_2w/current-1)*100:+.2f}%)")
        print(f"  Base Case:       ${proj_price:.2f} ({(proj_price/current-1)*100:+.2f}%)")
        print(f"  Bear Case (1σ):  ${max_bear_2w:.2f} ({(max_bear_2w/current-1)*100:+.2f}%)")
        
        print(f"\n  --- KEY RISK FACTORS ---")
        print(f"  1. Earnings season spillover (COIN Feb 12, tech names reporting)")
        print(f"  2. FOMC minutes / Fed speakers → rate expectations shift")
        print(f"  3. Monthly OpEx (Feb 21) → dealer de-hedging → volatility expansion")
        if vix_current > 0:
            print(f"  4. VIX regime: {'complacency trap' if vix_current < 15 else 'elevated hedging' if vix_current > 20 else 'normal'}")
        else:
            print(f"  4. VIX data unavailable from Polygon (use IV term structure as proxy)")
        if qqq_gex and qqq_gex.net_gex < 0:
            print(f"  5. ⚠️  NEGATIVE GEX: Moves will be AMPLIFIED by dealer hedging")
        if iv and isinstance(iv, dict) and iv.get("iv_inverted"):
            print(f"  6. ⚠️  IV INVERTED: Someone is paying premium for near-term protection")
    
    print("\n" + "=" * 80)
    print("DISCLAIMER: This is a quantitative analysis based on current market microstructure.")
    print("It is NOT financial advice. Markets are inherently uncertain.")
    print("All projections assume no exogenous shocks (geopolitical, policy surprises).")
    print("=" * 80)
    
    await uw.close()
    await polygon.close()

if __name__ == "__main__":
    asyncio.run(main())
