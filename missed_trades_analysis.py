#!/usr/bin/env python3
"""
🔴 CRITICAL ANALYSIS: WHY DID WE MISS THESE TRADES?
====================================================

Stocks that moved significantly today (Jan 25/26, 2026):
- RIOT: -5%
- PL: -5%  
- INTC: -5%
- AMD: -3%
- UUUU: -11%
- LUNR: -7%
- ONDS: -7%
- LMND: -6%
- CIFR: -5%
- PLUG: -6%
- ACHR: -5%

This script will:
1. Fetch historical data for these tickers from FRIDAY (before the move)
2. Check what signals were present
3. Identify why our system missed them
4. Provide recommendations

PhD Quant + 30yr Trading + Institutional Microstructure Analysis
"""

import asyncio
import sys
from datetime import datetime, date, timedelta
from typing import Dict, List, Any
import json

sys.path.insert(0, '.')

from putsengine.config import get_settings
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient
from putsengine.layers.distribution import DistributionLayer
from putsengine.layers.liquidity import LiquidityVacuumLayer
from putsengine.layers.acceleration import AccelerationWindowLayer
from putsengine.scoring.scorer import PutScorer

# MISSED TRADES - These had significant moves
MISSED_TICKERS = [
    "RIOT",   # -5% (Crypto miner)
    "PL",     # -5% (Planet Labs)
    "INTC",   # -5% (Intel - we actually caught this!)
    "AMD",    # -3% (AMD)
    "UUUU",   # -11% (Energy Fuels - Uranium)
    "LUNR",   # -7% (Intuitive Machines)
    "ONDS",   # -7% (Ondas Holdings)
    "LMND",   # -6% (Lemonade)
    "CIFR",   # -5% (Cipher Mining)
    "PLUG",   # -6% (Plug Power)
    "ACHR",   # -5% (Archer Aviation)
]

# All tickers in our universe
ALL_TICKERS_IN_LIST = [
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
    "AMD", "INTC", "AVGO", "QCOM", "MU", "AMAT", "LRCX", "KLAC", "MRVL", "ON", "NXPI",
    "CRM", "ORCL", "ADBE", "NOW", "SNOW", "PLTR", "DDOG", "NET", "ZS", "CRWD", "PANW",
    "V", "MA", "PYPL", "SQ", "COIN", "HOOD", "AFRM", "SOFI",
    "SHOP", "ETSY", "EBAY", "CHWY", "W", "BABA", "JD", "PDD",
    "NFLX", "DIS", "WBD", "PARA", "ROKU", "SPOT",
    "RIVN", "LCID", "F", "GM", "TM", "XPEV", "NIO", "LI",
    "MRNA", "BNTX", "PFE", "JNJ", "LLY", "ABBV", "BMY", "GILD", "REGN", "VRTX", "BIIB",
    "UNH", "CVS", "HCA", "ISRG", "DXCM", "TDOC",
    "JPM", "BAC", "WFC", "C", "GS", "MS", "SCHW", "BLK",
    "XOM", "CVX", "COP", "SLB", "OXY", "HAL", "MPC", "VLO", "PSX",
    "BA", "CAT", "DE", "GE", "HON", "UPS", "FDX", "LMT", "RTX", "NOC",
    "WMT", "TGT", "COST", "HD", "LOW", "DG", "DLTR", "ROST", "TJX",
    "UAL", "DAL", "AAL", "LUV", "MAR", "HLT", "ABNB", "BKNG", "EXPE",
    "DKNG", "PENN", "MGM", "WYNN", "LVS", "EA", "TTWO", "RBLX",
    "MARA", "RIOT", "CLSK", "MSTR",
    "SPG", "O", "AMT", "CCI", "EQIX", "PLD",
    "T", "VZ", "TMUS",
    "KO", "PEP", "PG", "CL", "KMB", "GIS", "K", "CPB",
    "UBER", "LYFT", "DASH", "ZM", "DOCU", "OKTA", "TWLO", "MDB", "ESTC",
    "SPY", "QQQ", "IWM", "DIA",
]


async def analyze_missed_trades():
    """Deep analysis of why we missed these trades."""
    
    print("=" * 80)
    print("🔴 CRITICAL ANALYSIS: WHY DID WE MISS THESE TRADES?")
    print("=" * 80)
    print()
    
    settings = get_settings()
    alpaca = AlpacaClient(settings)
    polygon = PolygonClient(settings)
    uw = UnusualWhalesClient(settings)
    
    distribution_layer = DistributionLayer(alpaca, polygon, uw, settings)
    liquidity_layer = LiquidityVacuumLayer(alpaca, polygon, settings)
    acceleration_layer = AccelerationWindowLayer(alpaca, polygon, uw, settings)
    scorer = PutScorer(settings)
    
    results = []
    
    # Check which missed tickers are NOT in our universe
    print("🔍 STEP 1: CHECK IF TICKERS ARE IN OUR UNIVERSE")
    print("-" * 80)
    
    missing_from_universe = []
    in_universe = []
    
    for ticker in MISSED_TICKERS:
        if ticker in ALL_TICKERS_IN_LIST:
            in_universe.append(ticker)
            print(f"   ✅ {ticker} - IN our universe")
        else:
            missing_from_universe.append(ticker)
            print(f"   ❌ {ticker} - NOT in our universe!")
    
    print()
    print(f"   SUMMARY: {len(in_universe)} in universe, {len(missing_from_universe)} MISSING")
    print(f"   MISSING: {missing_from_universe}")
    print()
    
    # Analyze each missed ticker
    print("🔍 STEP 2: ANALYZE FRIDAY'S DATA FOR EACH MISSED TICKER")
    print("-" * 80)
    
    for ticker in MISSED_TICKERS:
        print(f"\n{'='*60}")
        print(f"   ANALYZING: {ticker}")
        print(f"{'='*60}")
        
        try:
            # Get price data
            bars = await polygon.get_daily_bars(
                symbol=ticker,
                from_date=date.today() - timedelta(days=30)
            )
            
            if not bars or len(bars) < 5:
                print(f"   ❌ No price data available for {ticker}")
                results.append({
                    "symbol": ticker,
                    "in_universe": ticker in ALL_TICKERS_IN_LIST,
                    "data_available": False,
                    "error": "No price data"
                })
                continue
            
            # Friday's data (last trading day)
            friday_bar = bars[-1]
            thursday_bar = bars[-2] if len(bars) >= 2 else None
            
            friday_close = friday_bar.close
            friday_open = friday_bar.open
            friday_volume = friday_bar.volume
            friday_change = (friday_close - friday_open) / friday_open * 100
            
            # Calculate metrics
            # 1. RSI
            if len(bars) >= 14:
                changes = [bars[i].close - bars[i-1].close for i in range(1, len(bars))]
                gains = [c if c > 0 else 0 for c in changes[-14:]]
                losses = [-c if c < 0 else 0 for c in changes[-14:]]
                avg_gain = sum(gains) / 14
                avg_loss = sum(losses) / 14
                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    rsi = 100 - (100 / (1 + rs))
                else:
                    rsi = 100
            else:
                rsi = 50
            
            # 2. RVOL (Relative Volume)
            if len(bars) >= 20:
                avg_vol = sum(b.volume for b in bars[-20:-1]) / 19
                rvol = friday_volume / avg_vol if avg_vol > 0 else 1.0
            else:
                rvol = 1.0
            
            # 3. Gap analysis
            gap_pct = 0
            if thursday_bar:
                gap_pct = (friday_open - thursday_bar.close) / thursday_bar.close * 100
            
            # 4. Multi-day weakness
            multi_day_weakness = False
            if len(bars) >= 3:
                multi_day_weakness = bars[-1].close < bars[-2].close < bars[-3].close
            
            # 5. Lower highs pattern
            lower_highs = False
            if len(bars) >= 3:
                lower_highs = bars[-1].high < bars[-2].high < bars[-3].high
            
            print(f"   📊 FRIDAY DATA:")
            print(f"      Close: ${friday_close:.2f}")
            print(f"      Day Change: {friday_change:+.2f}%")
            print(f"      Gap from Thursday: {gap_pct:+.2f}%")
            print(f"      Volume: {friday_volume:,.0f}")
            print(f"      RVOL: {rvol:.2f}x")
            print(f"      RSI: {rsi:.1f}")
            print(f"      Multi-day Weakness: {'YES' if multi_day_weakness else 'NO'}")
            print(f"      Lower Highs: {'YES' if lower_highs else 'NO'}")
            
            # Run distribution analysis
            print(f"\n   🔍 DISTRIBUTION ANALYSIS:")
            try:
                distribution = await distribution_layer.analyze(ticker)
                print(f"      Score: {distribution.score:.2f}")
                print(f"      Active Signals: {sum(1 for v in distribution.signals.values() if v)}")
                
                active_signals = [k for k, v in distribution.signals.items() if v]
                if active_signals:
                    print(f"      Signals: {', '.join(active_signals)}")
                else:
                    print(f"      ⚠️ NO SIGNALS DETECTED!")
            except Exception as e:
                print(f"      ❌ Error: {e}")
                distribution = None
            
            # Run liquidity analysis
            print(f"\n   🔍 LIQUIDITY ANALYSIS:")
            try:
                liquidity = await liquidity_layer.analyze(ticker)
                print(f"      Score: {liquidity.score:.2f}")
                liq_signals = []
                if liquidity.bid_collapse:
                    liq_signals.append("bid_collapse")
                if liquidity.spread_widening:
                    liq_signals.append("spread_widening")
                if liquidity.vwap_retest_failed:
                    liq_signals.append("vwap_retest_failed")
                if liq_signals:
                    print(f"      Signals: {', '.join(liq_signals)}")
                else:
                    print(f"      ⚠️ NO LIQUIDITY SIGNALS!")
            except Exception as e:
                print(f"      ❌ Error: {e}")
                liquidity = None
            
            # Determine WHY we missed it
            print(f"\n   🎯 WHY WE MISSED IT:")
            
            reasons = []
            
            # Check if in universe
            if ticker not in ALL_TICKERS_IN_LIST:
                reasons.append("NOT IN TICKER UNIVERSE")
            
            # Check RSI
            if rsi < 70:
                reasons.append(f"RSI too low ({rsi:.1f}) - not overbought")
            
            # Check RVOL
            if rvol < 2.0:
                reasons.append(f"RVOL too low ({rvol:.2f}x) - not unusual volume")
            
            # Check if already down
            if friday_change < -2:
                reasons.append(f"Already dropped {friday_change:.1f}% on Friday - missed entry window")
            
            # Check distribution signals
            if distribution and sum(1 for v in distribution.signals.values() if v) < 2:
                reasons.append("Too few distribution signals")
            
            # Check if multi-day weakness was detected
            if not multi_day_weakness:
                reasons.append("No multi-day weakness pattern")
            
            if not reasons:
                reasons.append("UNKNOWN - Need deeper analysis")
            
            for reason in reasons:
                print(f"      ❌ {reason}")
            
            # Recommendations
            print(f"\n   💡 RECOMMENDATIONS:")
            if ticker not in ALL_TICKERS_IN_LIST:
                print(f"      ➤ ADD {ticker} to ticker universe!")
            if rvol >= 1.5 and friday_change < 0:
                print(f"      ➤ Lower RVOL threshold from 2.0 to 1.5")
            if multi_day_weakness or lower_highs:
                print(f"      ➤ Weight multi-day weakness pattern higher")
            
            results.append({
                "symbol": ticker,
                "in_universe": ticker in ALL_TICKERS_IN_LIST,
                "data_available": True,
                "friday_close": friday_close,
                "friday_change": friday_change,
                "gap_pct": gap_pct,
                "rvol": rvol,
                "rsi": rsi,
                "multi_day_weakness": multi_day_weakness,
                "lower_highs": lower_highs,
                "distribution_signals": sum(1 for v in distribution.signals.values() if v) if distribution else 0,
                "reasons_missed": reasons
            })
            
            # Small delay to avoid rate limits
            await asyncio.sleep(0.5)
            
        except Exception as e:
            print(f"   ❌ Error analyzing {ticker}: {e}")
            results.append({
                "symbol": ticker,
                "in_universe": ticker in ALL_TICKERS_IN_LIST,
                "data_available": False,
                "error": str(e)
            })
    
    # Close clients
    await alpaca.close()
    await polygon.close()
    await uw.close()
    
    # Final summary
    print("\n" + "=" * 80)
    print("📋 FINAL SUMMARY")
    print("=" * 80)
    
    print("\n🔴 ROOT CAUSES FOR MISSED TRADES:")
    
    not_in_universe = [r for r in results if not r.get("in_universe", True)]
    if not_in_universe:
        print(f"\n   1. TICKERS NOT IN UNIVERSE ({len(not_in_universe)}):")
        for r in not_in_universe:
            print(f"      - {r['symbol']}")
    
    low_rvol = [r for r in results if r.get("rvol", 0) < 2.0 and r.get("rvol", 0) >= 1.3]
    if low_rvol:
        print(f"\n   2. RVOL THRESHOLD TOO HIGH ({len(low_rvol)}):")
        for r in low_rvol:
            print(f"      - {r['symbol']}: RVOL={r['rvol']:.2f}x (threshold is 2.0)")
    
    already_falling = [r for r in results if r.get("friday_change", 0) < -2]
    if already_falling:
        print(f"\n   3. ALREADY FALLING ON FRIDAY ({len(already_falling)}):")
        for r in already_falling:
            print(f"      - {r['symbol']}: {r['friday_change']:.1f}% on Friday")
    
    weak_signals = [r for r in results if r.get("distribution_signals", 0) < 2]
    if weak_signals:
        print(f"\n   4. WEAK DISTRIBUTION SIGNALS ({len(weak_signals)}):")
        for r in weak_signals:
            print(f"      - {r['symbol']}: {r.get('distribution_signals', 0)} signals")
    
    print("\n" + "=" * 80)
    print("💡 RECOMMENDED FIXES")
    print("=" * 80)
    
    print("""
   1. ADD MISSING TICKERS TO UNIVERSE:
      - PL (Planet Labs)
      - UUUU (Energy Fuels - Uranium)
      - LUNR (Intuitive Machines)
      - ONDS (Ondas Holdings)
      - LMND (Lemonade)
      - CIFR (Cipher Mining)
      - PLUG (Plug Power)
      - ACHR (Archer Aviation)
      
   2. LOWER RVOL THRESHOLD:
      - Current: 2.0x
      - Recommended: 1.5x
      
   3. ADD SECTOR-BASED CORRELATION:
      - Crypto miners move together (RIOT, MARA, CIFR, CLSK)
      - EV/Tech move together (RIVN, LCID, ACHR)
      - Track Bitcoin/ETH for crypto plays
      
   4. ADD EARLY WARNING SIGNALS:
      - Track Friday's intraday weakness
      - Track after-hours movement
      - Track pre-market movement Monday
      
   5. WEIGHT MULTI-DAY PATTERNS HIGHER:
      - 3+ consecutive red days
      - Lower highs pattern
      - Declining volume on bounces
      
   6. ADD FRIDAY-SPECIFIC SCAN:
      - Run special scan Friday 3:30 PM
      - Focus on weekend gap risk
      - Identify "sell into weekend" patterns
""")
    
    # Save results
    with open("missed_trades_analysis.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    print("\n   Results saved to missed_trades_analysis.json")
    
    return results


if __name__ == "__main__":
    asyncio.run(analyze_missed_trades())
