#!/usr/bin/env python3
"""
REAL-TIME PATTERN SCANNER
Find stocks showing the SAME patterns NOW that led to big Jan 26-29 moves.
Goal: Detect 1-2 days BEFORE the move for Jan 30th and next week opportunities.
"""
import asyncio
import json
from datetime import datetime, timedelta
import pytz
from collections import defaultdict

# Import our clients
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.config import EngineConfig, get_settings

et = pytz.timezone('US/Eastern')


async def scan_for_patterns():
    """Scan for patterns that predict big moves."""
    now = datetime.now(et)
    settings = get_settings()
    alpaca = AlpacaClient(settings)
    all_tickers = EngineConfig.get_all_tickers()
    
    print("="*70)
    print(f"REAL-TIME PATTERN SCANNER - {now.strftime('%Y-%m-%d %H:%M:%S')} EST")
    print("Looking for Jan 30th & Next Week Put Opportunities")
    print("="*70)
    print()
    
    # Pattern results
    results = {
        "pump_reversal_watch": [],  # Up 3%+ in last 1-3 days - WATCH FOR CRASH
        "two_day_rally": [],         # Up 2 consecutive days - exhaustion setup
        "high_vol_run": [],          # High volume rallies (institutions exiting?)
        "scan_time": now.isoformat()
    }
    
    print(f"Scanning {len(all_tickers)} tickers for patterns...")
    print()
    
    # Focus on high-beta sectors that showed Jan 26-30 moves
    # UPDATED Jan 30: Added silver miners, gaming, AI datacenter after major misses
    priority_sectors = {
        "crypto": ["MSTR", "COIN", "RIOT", "MARA", "HUT", "CLSK", "CIFR", "WULF"],
        "uranium_nuclear": ["UUUU", "LEU", "OKLO", "SMR", "CCJ", "NNE", "UEC"],
        "evtol_space": ["JOBY", "RKLB", "LUNR", "ASTS", "RDW", "RCAT", "PL", "ACHR"],
        "quantum": ["RGTI", "QUBT", "IONQ", "QBTS"],
        "btc_miners": ["IREN", "APLD", "CIFR", "CLSK", "HUT", "NBIS"],
        "cloud_saas": ["NET", "CRWD", "ZS", "OKTA", "DDOG", "TEAM", "WDAY", "SNOW", "NOW"],
        "solar_clean": ["FSLR", "ENPH", "BE", "PLUG", "FCEL", "EOSE"],
        "rare_earth": ["MP", "USAR", "LAC", "ALB"],
        "semiconductors": ["CLS", "SWKS", "INTC", "AMD", "NVDA", "MU", "WDC", "STX"],
        "tech_mega": ["MSFT", "AAPL", "GOOGL", "META", "AMZN", "TSLA"],
        # NEW Jan 30 - CRITICAL ADDITIONS (missed -15% to -23% moves!)
        "silver_miners": ["AG", "CDE", "HL", "PAAS", "MAG", "EXK", "SVM", "FSM"],
        "gaming": ["U", "RBLX", "EA", "TTWO", "SKLZ", "PLTK"],
        "ai_datacenter": ["APP", "NBIS", "IREN", "AI", "BBAI", "SOUN", "CRWV"],
        "travel_cruise": ["CCL", "RCL", "NCLH", "LUV", "DAL", "UAL", "AAL"],
    }
    
    # Flatten priority list
    priority_tickers = set()
    for tickers in priority_sectors.values():
        priority_tickers.update(tickers)
    
    # Scan priority tickers first
    scan_order = list(priority_tickers) + [t for t in all_tickers if t not in priority_tickers]
    
    scanned = 0
    for symbol in scan_order[:150]:  # Limit to 150 for speed
        try:
            # Use get_bars with 1Day timeframe for daily data
            start_date = datetime.now() - timedelta(days=15)
            bars = await alpaca.get_bars(symbol, timeframe="1Day", start=start_date, limit=10)
            if not bars or len(bars) < 5:
                continue
            
            scanned += 1
            
            # Calculate returns
            returns = []
            for i in range(1, min(5, len(bars))):
                pct = ((bars[-i].close - bars[-(i+1)].close) / bars[-(i+1)].close) * 100
                returns.append(pct)
            
            if not returns:
                continue
            
            current_price = bars[-1].close
            day1 = returns[0] if len(returns) > 0 else 0
            day2 = returns[1] if len(returns) > 1 else 0
            day3 = returns[2] if len(returns) > 2 else 0
            
            # Calculate volume ratio
            if len(bars) >= 6:
                avg_vol = sum(b.volume for b in bars[-6:-1]) / 5
                curr_vol = bars[-1].volume
                vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0
            else:
                vol_ratio = 1.0
            
            # Get sector
            sector = "other"
            for sec, tickers in priority_sectors.items():
                if symbol in tickers:
                    sector = sec
                    break
            
            # PATTERN 1: Pump Reversal Watch (Up 3%+ in last 1-3 days)
            total_gain_3d = day1 + day2 + day3
            max_gain = max(day1, day2, day3) if returns else 0
            
            if max_gain >= 3.0 or total_gain_3d >= 5.0:
                # Check for reversal signals
                reversal_signals = []
                curr_bar = bars[-1]
                prev_bar = bars[-2] if len(bars) >= 2 else None
                
                # Close below day's high (exhaustion)
                if curr_bar.close < curr_bar.high * 0.97:
                    reversal_signals.append("exhaustion_candle")
                
                # Topping tail
                body = abs(curr_bar.close - curr_bar.open)
                upper_wick = curr_bar.high - max(curr_bar.close, curr_bar.open)
                if body > 0 and upper_wick > body * 1.5:
                    reversal_signals.append("topping_tail")
                
                # High volume on red candle
                if curr_bar.close < curr_bar.open and vol_ratio > 1.3:
                    reversal_signals.append("high_vol_red")
                
                # Close below prior day's low
                if prev_bar and curr_bar.close < prev_bar.low:
                    reversal_signals.append("close_below_prior_low")
                
                results["pump_reversal_watch"].append({
                    "symbol": symbol,
                    "sector": sector,
                    "current_price": round(current_price, 2),
                    "gain_1d": round(day1, 1),
                    "gain_2d": round(day2, 1),
                    "gain_3d": round(day3, 1),
                    "total_gain": round(total_gain_3d, 1),
                    "max_gain": round(max_gain, 1),
                    "vol_ratio": round(vol_ratio, 2),
                    "reversal_signals": reversal_signals,
                    "confidence": min(0.90, 0.40 + max_gain * 0.03 + len(reversal_signals) * 0.12)
                })
            
            # PATTERN 2: Two-Day Rally (Exhaustion Setup)
            if day1 > 1.0 and day2 > 1.0:  # Two consecutive up days
                total = day1 + day2
                results["two_day_rally"].append({
                    "symbol": symbol,
                    "sector": sector,
                    "current_price": round(current_price, 2),
                    "day1": round(day1, 1),
                    "day2": round(day2, 1),
                    "total_gain": round(total, 1),
                    "vol_ratio": round(vol_ratio, 2),
                    "confidence": min(0.80, 0.35 + total * 0.04)
                })
            
            # PATTERN 3: High Volume Run (Institutions may be exiting)
            if max_gain >= 5.0 and vol_ratio >= 1.5:
                results["high_vol_run"].append({
                    "symbol": symbol,
                    "sector": sector,
                    "current_price": round(current_price, 2),
                    "gain": round(max_gain, 1),
                    "vol_ratio": round(vol_ratio, 2),
                    "confidence": min(0.85, 0.45 + vol_ratio * 0.10)
                })
                
        except Exception as e:
            continue
    
    print(f"Scanned {scanned} tickers")
    print()
    
    # Sort by confidence
    for key in results:
        if isinstance(results[key], list):
            results[key].sort(key=lambda x: x.get("confidence", 0), reverse=True)
    
    return results


def display_results(results):
    """Display scan results."""
    print("="*70)
    print("🎯 PUMP REVERSAL WATCH - These pumped recently, watch for crash")
    print("   (Similar to RR +44%, NET +8%, CLS +8% before their crashes)")
    print("="*70)
    if results["pump_reversal_watch"]:
        print(f"{'Symbol':<8} {'Sector':<15} {'Price':>8} {'1D':>7} {'2D':>7} {'3D':>7} {'Total':>7} {'Conf':>6} Signals")
        print("-" * 90)
        for r in results["pump_reversal_watch"][:20]:
            signals = ", ".join(r["reversal_signals"][:2]) if r["reversal_signals"] else "-"
            print(f"{r['symbol']:<8} {r['sector']:<15} ${r['current_price']:>6.2f} {r['gain_1d']:>+6.1f}% {r['gain_2d']:>+6.1f}% {r['gain_3d']:>+6.1f}% {r['total_gain']:>+6.1f}% {r['confidence']:.2f} {signals}")
    else:
        print("No pump reversal candidates found")

    print()
    print("="*70)
    print("↩️ TWO-DAY RALLY - Exhaustion setup (like OKLO, LEU, UUUU before crash)")
    print("="*70)
    if results["two_day_rally"]:
        print(f"{'Symbol':<8} {'Sector':<15} {'Price':>8} {'Day1':>7} {'Day2':>7} {'Total':>7} {'Conf':>6}")
        print("-" * 70)
        for r in results["two_day_rally"][:15]:
            print(f"{r['symbol']:<8} {r['sector']:<15} ${r['current_price']:>6.2f} {r['day1']:>+6.1f}% {r['day2']:>+6.1f}% {r['total_gain']:>+6.1f}% {r['confidence']:.2f}")
    else:
        print("No two-day rally candidates found")

    print()
    print("="*70)
    print("📈 HIGH VOLUME RUN - Big gains with volume (institutions exiting?)")
    print("="*70)
    if results["high_vol_run"]:
        print(f"{'Symbol':<8} {'Sector':<15} {'Price':>8} {'Gain':>7} {'Vol':>6} {'Conf':>6}")
        print("-" * 60)
        for r in results["high_vol_run"][:10]:
            print(f"{r['symbol']:<8} {r['sector']:<15} ${r['current_price']:>6.2f} {r['gain']:>+6.1f}% {r['vol_ratio']:>5.1f}x {r['confidence']:.2f}")
    else:
        print("No high volume run candidates found")


def save_results(results):
    """Save results for dashboard integration."""
    output = {
        "scan_time": results["scan_time"],
        "pump_reversal_watch": results["pump_reversal_watch"][:25],
        "two_day_rally": results["two_day_rally"][:20],
        "high_vol_run": results["high_vol_run"][:15],
        "summary": {
            "pump_reversal_count": len(results["pump_reversal_watch"]),
            "two_day_rally_count": len(results["two_day_rally"]),
            "high_vol_count": len(results["high_vol_run"])
        }
    }

    with open("pattern_scan_results.json", "w") as f:
        json.dump(output, f, indent=2)

    print()
    print("="*70)
    print("SCAN COMPLETE - Results saved to pattern_scan_results.json")
    total = len(results['pump_reversal_watch']) + len(results['two_day_rally']) + len(results['high_vol_run'])
    print(f"Total candidates: {total}")
    print("="*70)


async def main():
    results = await scan_for_patterns()
    display_results(results)
    save_results(results)
    return results


if __name__ == "__main__":
    asyncio.run(main())
