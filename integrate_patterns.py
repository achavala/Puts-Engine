#!/usr/bin/env python3
"""
PATTERN INTEGRATION SCRIPT

Purpose: Integrate pattern scan results into the existing scheduled scan results.
This boosts scores for candidates that match pump-reversal or exhaustion patterns.

Runs AFTER the regular scan to enhance results with pattern detection.
"""
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
import pytz

from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.config import EngineConfig, get_settings

ET = pytz.timezone('US/Eastern')
SCHEDULED_RESULTS_FILE = Path("scheduled_scan_results.json")
PATTERN_RESULTS_FILE = Path("pattern_scan_results.json")


async def scan_patterns():
    """Scan for pump-reversal and exhaustion patterns."""
    now = datetime.now(ET)
    settings = get_settings()
    alpaca = AlpacaClient(settings)
    all_tickers = EngineConfig.get_all_tickers()
    
    print("="*70)
    print(f"PATTERN SCANNER - {now.strftime('%Y-%m-%d %H:%M:%S')} EST")
    print("="*70)
    
    # Priority sectors from Jan 26-29 analysis
    priority_sectors = {
        "crypto": ["MSTR", "COIN", "RIOT", "MARA", "HUT", "CLSK", "CIFR", "WULF"],
        "uranium": ["UUUU", "LEU", "OKLO", "SMR", "CCJ", "NNE", "UEC"],
        "evtol": ["JOBY", "RKLB", "LUNR", "ASTS", "RDW", "RCAT", "PL", "ACHR"],
        "quantum": ["RGTI", "QUBT", "IONQ", "QBTS"],
        "cloud": ["NET", "CRWD", "ZS", "OKTA", "DDOG", "TEAM", "WDAY", "SNOW", "NOW"],
        "solar": ["FSLR", "ENPH", "BE", "PLUG", "FCEL", "EOSE"],
        "rare_earth": ["MP", "USAR", "LAC", "ALB"],
        "semis": ["CLS", "SWKS", "INTC", "AMD", "NVDA", "MU"],
        "mega": ["MSFT", "AAPL", "GOOGL", "META", "AMZN", "TSLA"],
    }
    
    # Flatten priority list
    priority_tickers = set()
    for tickers in priority_sectors.values():
        priority_tickers.update(tickers)
    
    scan_order = list(priority_tickers) + [t for t in all_tickers if t not in priority_tickers]
    
    results = {
        "pump_reversal": [],
        "two_day_rally": [],
        "high_vol_run": [],
        "scan_time": now.isoformat()
    }
    
    scanned = 0
    for symbol in scan_order[:150]:
        try:
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
            
            # Volume ratio
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
            
            # PATTERN 1: Pump Reversal Watch
            total_gain = day1 + day2 + day3
            max_gain = max(day1, day2, day3) if returns else 0
            
            if max_gain >= 3.0 or total_gain >= 5.0:
                reversal_signals = []
                curr_bar = bars[-1]
                prev_bar = bars[-2] if len(bars) >= 2 else None
                
                if curr_bar.close < curr_bar.high * 0.97:
                    reversal_signals.append("exhaustion")
                
                body = abs(curr_bar.close - curr_bar.open)
                upper_wick = curr_bar.high - max(curr_bar.close, curr_bar.open)
                if body > 0 and upper_wick > body * 1.5:
                    reversal_signals.append("topping_tail")
                
                if curr_bar.close < curr_bar.open and vol_ratio > 1.3:
                    reversal_signals.append("high_vol_red")
                
                if prev_bar and curr_bar.close < prev_bar.low:
                    reversal_signals.append("below_prior_low")
                
                results["pump_reversal"].append({
                    "symbol": symbol,
                    "sector": sector,
                    "price": round(current_price, 2),
                    "gain_1d": round(day1, 1),
                    "gain_2d": round(day2, 1),
                    "gain_3d": round(day3, 1),
                    "total_gain": round(total_gain, 1),
                    "vol_ratio": round(vol_ratio, 2),
                    "signals": reversal_signals,
                    "score_boost": min(0.20, 0.05 + len(reversal_signals) * 0.04 + max_gain * 0.01)
                })
            
            # PATTERN 2: Two-Day Rally
            if day1 > 1.0 and day2 > 1.0:
                total = day1 + day2
                results["two_day_rally"].append({
                    "symbol": symbol,
                    "sector": sector,
                    "price": round(current_price, 2),
                    "day1": round(day1, 1),
                    "day2": round(day2, 1),
                    "total": round(total, 1),
                    "score_boost": min(0.15, 0.05 + total * 0.02)
                })
            
            # PATTERN 3: High Volume Run
            if max_gain >= 5.0 and vol_ratio >= 1.5:
                results["high_vol_run"].append({
                    "symbol": symbol,
                    "sector": sector,
                    "price": round(current_price, 2),
                    "gain": round(max_gain, 1),
                    "vol_ratio": round(vol_ratio, 2),
                    "score_boost": min(0.15, 0.05 + vol_ratio * 0.03)
                })
                
        except Exception as e:
            continue
    
    print(f"Scanned {scanned} tickers")
    
    # Sort by score boost
    for key in results:
        if isinstance(results[key], list):
            results[key].sort(key=lambda x: x.get("score_boost", 0), reverse=True)
    
    return results


def _populate_from_patterns(pattern_results):
    """Create scheduled results from pattern data when engines are empty."""
    gamma_candidates = []
    distribution_candidates = []
    liquidity_candidates = []
    
    # Pump reversal -> Distribution or Gamma based on signals
    for pr in pattern_results.get("pump_reversal", []):
        candidate = {
            "symbol": pr["symbol"],
            "score": round(0.45 + pr.get("score_boost", 0.1), 4),
            "tier": "🟡 CLASS B" if pr.get("score_boost", 0) >= 0.15 else "⚪ WATCH",
            "engine_type": "gamma_drain" if "exhaustion" in pr.get("signals", []) else "distribution_trap",
            "current_price": pr.get("price", 0),
            "close": pr.get("price", 0),
            "signals": pr.get("signals", []) + [f"pump_{pr.get('total_gain', 0):+.0f}%"],
            "pattern_enhanced": True,
            "pattern_boost": pr.get("score_boost", 0.1),
            "pattern_source": "pump_reversal",
            "sector": pr.get("sector", "other"),
            "total_gain": pr.get("total_gain", 0),
            "gain_1d": pr.get("gain_1d", 0),
            "gain_2d": pr.get("gain_2d", 0),
            "gain_3d": pr.get("gain_3d", 0),
            "vol_ratio": pr.get("vol_ratio", 1.0)
        }
        
        if "exhaustion" in pr.get("signals", []) or "high_vol_red" in pr.get("signals", []):
            gamma_candidates.append(candidate)
        else:
            distribution_candidates.append(candidate)
    
    # Two day rally -> Liquidity
    for pr in pattern_results.get("two_day_rally", []):
        candidate = {
            "symbol": pr["symbol"],
            "score": round(0.40 + pr.get("score_boost", 0.1), 4),
            "tier": "⚪ WATCH",
            "engine_type": "liquidity_vacuum",
            "current_price": pr.get("price", 0),
            "close": pr.get("price", 0),
            "signals": ["two_day_rally", "exhaustion_setup"],
            "pattern_enhanced": True,
            "pattern_boost": pr.get("score_boost", 0.1),
            "pattern_source": "two_day_rally",
            "sector": pr.get("sector", "other"),
            "day1": pr.get("day1", 0),
            "day2": pr.get("day2", 0),
            "total": pr.get("total", 0)
        }
        liquidity_candidates.append(candidate)
    
    # High vol run -> Gamma Drain
    for pr in pattern_results.get("high_vol_run", []):
        candidate = {
            "symbol": pr["symbol"],
            "score": round(0.42 + pr.get("score_boost", 0.1), 4),
            "tier": "⚪ WATCH",
            "engine_type": "gamma_drain",
            "current_price": pr.get("price", 0),
            "close": pr.get("price", 0),
            "signals": ["high_vol_run", f"vol_{pr.get('vol_ratio', 1):.1f}x"],
            "pattern_enhanced": True,
            "pattern_boost": pr.get("score_boost", 0.1),
            "pattern_source": "high_vol_run",
            "sector": pr.get("sector", "other"),
            "gain": pr.get("gain", 0),
            "vol_ratio": pr.get("vol_ratio", 1.0)
        }
        gamma_candidates.append(candidate)
    
    # Sort and limit
    gamma_candidates.sort(key=lambda x: x["score"], reverse=True)
    distribution_candidates.sort(key=lambda x: x["score"], reverse=True)
    liquidity_candidates.sort(key=lambda x: x["score"], reverse=True)
    
    return {
        "gamma_drain": gamma_candidates[:20],
        "distribution": distribution_candidates[:20],
        "liquidity": liquidity_candidates[:15],
        "last_scan": datetime.now(ET).isoformat(),
        "scan_type": "pattern_populated",
        "market_regime": {"is_tradeable": True, "regime": "pattern_based"},
        "tickers_scanned": len(pattern_results.get("pump_reversal", [])) + 
                          len(pattern_results.get("two_day_rally", [])) +
                          len(pattern_results.get("high_vol_run", [])),
        "errors": [],
        "total_candidates": len(gamma_candidates) + len(distribution_candidates) + len(liquidity_candidates)
    }


def _update_scan_history(scheduled):
    """Update scan history for 48-hour analysis."""
    history_file = Path("scan_history.json")
    
    if history_file.exists():
        with open(history_file) as f:
            history = json.load(f)
    else:
        history = {"scans": []}
    
    # Create history entry
    entry = {
        "timestamp": datetime.now(ET).isoformat(),
        "scan_type": scheduled.get("scan_type", "pattern"),
        "gamma_drain": [{"symbol": c["symbol"], "score": c["score"]} for c in scheduled.get("gamma_drain", [])],
        "distribution": [{"symbol": c["symbol"], "score": c["score"]} for c in scheduled.get("distribution", [])],
        "liquidity": [{"symbol": c["symbol"], "score": c["score"]} for c in scheduled.get("liquidity", [])]
    }
    
    history["scans"].append(entry)
    history["scans"] = history["scans"][-100:]  # Keep last 100
    
    with open(history_file, 'w') as f:
        json.dump(history, f, indent=2, default=str)


def integrate_with_scheduled_results(pattern_results):
    """Integrate pattern results with scheduled scan results.
    
    If scheduled results are empty, POPULATES from patterns.
    """
    
    # Load existing scheduled results or create empty structure
    if SCHEDULED_RESULTS_FILE.exists():
        with open(SCHEDULED_RESULTS_FILE, 'r') as f:
            scheduled = json.load(f)
    else:
        scheduled = {"gamma_drain": [], "distribution": [], "liquidity": []}
    
    # Check if ALL engines are empty - if so, POPULATE from patterns
    total_existing = sum(len(scheduled.get(e, [])) for e in ["gamma_drain", "distribution", "liquidity"])
    
    if total_existing == 0:
        print("  [INFO] Scheduled results empty - POPULATING from patterns...")
        scheduled = _populate_from_patterns(pattern_results)
        
        # Save and return early
        with open(SCHEDULED_RESULTS_FILE, 'w') as f:
            json.dump(scheduled, f, indent=2, default=str)
        
        print(f"  Populated: Gamma={len(scheduled.get('gamma_drain', []))}, " +
              f"Dist={len(scheduled.get('distribution', []))}, " +
              f"Liq={len(scheduled.get('liquidity', []))}")
        
        # Also update scan history
        _update_scan_history(scheduled)
        return scheduled
    
    # Create lookup of pattern symbols and their boosts
    pattern_boosts = {}
    pattern_signals = {}
    
    for pr in pattern_results.get("pump_reversal", []):
        symbol = pr["symbol"]
        pattern_boosts[symbol] = pattern_boosts.get(symbol, 0) + pr["score_boost"]
        pattern_signals.setdefault(symbol, []).append(f"pump_reversal_{pr['total_gain']:+.0f}%")
        if pr.get("signals"):
            pattern_signals[symbol].extend(pr["signals"])
    
    for pr in pattern_results.get("two_day_rally", []):
        symbol = pr["symbol"]
        pattern_boosts[symbol] = pattern_boosts.get(symbol, 0) + pr["score_boost"]
        pattern_signals.setdefault(symbol, []).append(f"two_day_rally_{pr['total']:+.0f}%")
    
    for pr in pattern_results.get("high_vol_run", []):
        symbol = pr["symbol"]
        pattern_boosts[symbol] = pattern_boosts.get(symbol, 0) + pr["score_boost"]
        pattern_signals.setdefault(symbol, []).append(f"high_vol_{pr['vol_ratio']:.1f}x")
    
    # Update scheduled results with pattern boosts
    updated_count = 0
    added_count = 0
    
    for engine in ["gamma_drain", "distribution", "liquidity"]:
        candidates = scheduled.get(engine, [])
        
        for candidate in candidates:
            symbol = candidate.get("symbol")
            if symbol in pattern_boosts:
                # Boost existing score
                old_score = candidate.get("score", 0)
                boost = min(pattern_boosts[symbol], 0.25)  # Cap boost at 0.25
                new_score = min(old_score + boost, 0.95)
                candidate["score"] = round(new_score, 4)
                
                # Add pattern signals
                existing_signals = candidate.get("signals", [])
                candidate["signals"] = existing_signals + pattern_signals.get(symbol, [])
                
                # Mark as pattern-enhanced
                candidate["pattern_enhanced"] = True
                candidate["pattern_boost"] = round(boost, 3)
                
                updated_count += 1
    
    # Add NEW candidates from patterns that aren't in scheduled results
    existing_symbols = set()
    for engine in ["gamma_drain", "distribution", "liquidity"]:
        for c in scheduled.get(engine, []):
            existing_symbols.add(c.get("symbol"))
    
    # Add top pump reversal candidates not in existing results
    for pr in pattern_results.get("pump_reversal", [])[:10]:
        symbol = pr["symbol"]
        if symbol not in existing_symbols and len(pr.get("signals", [])) >= 2:
            # This is a high-confidence pattern not in existing scan
            new_candidate = {
                "symbol": symbol,
                "score": round(0.35 + pr["score_boost"], 4),  # Base 0.35 + boost
                "tier": "🟡 CLASS B",
                "engine_type": "distribution_trap",
                "current_price": pr["price"],
                "expiry": "TBD",
                "dte": 7,
                "signals": pr["signals"] + [f"pump_{pr['total_gain']:+.0f}%"],
                "pattern_enhanced": True,
                "pattern_source": "pump_reversal"
            }
            scheduled.setdefault("distribution", []).append(new_candidate)
            added_count += 1
            existing_symbols.add(symbol)
    
    # Re-sort by score
    for engine in ["gamma_drain", "distribution", "liquidity"]:
        if engine in scheduled:
            scheduled[engine].sort(key=lambda x: x.get("score", 0), reverse=True)
    
    # Update metadata
    scheduled["pattern_integration_time"] = datetime.now(ET).isoformat()
    scheduled["pattern_updated_count"] = updated_count
    scheduled["pattern_added_count"] = added_count
    
    # Save updated results
    with open(SCHEDULED_RESULTS_FILE, 'w') as f:
        json.dump(scheduled, f, indent=2, default=str)
    
    # Update scan history for 48-hour analysis
    _update_scan_history(scheduled)
    
    print(f"\nIntegration complete:")
    print(f"  Updated {updated_count} existing candidates with pattern boosts")
    print(f"  Added {added_count} new pattern-based candidates")
    
    return scheduled


async def main():
    # Run pattern scan
    pattern_results = await scan_patterns()
    
    # Display results
    print("\n" + "="*70)
    print("🎯 PUMP REVERSAL WATCH (watch for crash)")
    print("="*70)
    for r in pattern_results.get("pump_reversal", [])[:15]:
        signals = ", ".join(r["signals"][:2]) if r["signals"] else "-"
        print(f"{r['symbol']:<8} ${r['price']:>7.2f} | {r['total_gain']:>+6.1f}% gain | boost: +{r['score_boost']:.2f} | {signals}")
    
    print("\n" + "="*70)
    print("↩️ TWO-DAY RALLY (exhaustion setup)")
    print("="*70)
    for r in pattern_results.get("two_day_rally", [])[:10]:
        print(f"{r['symbol']:<8} ${r['price']:>7.2f} | {r['day1']:>+.1f}% + {r['day2']:>+.1f}% = {r['total']:>+.1f}% | boost: +{r['score_boost']:.2f}")
    
    print("\n" + "="*70)
    print("📈 HIGH VOLUME RUN")
    print("="*70)
    for r in pattern_results.get("high_vol_run", [])[:10]:
        print(f"{r['symbol']:<8} ${r['price']:>7.2f} | {r['gain']:>+.1f}% on {r['vol_ratio']:.1f}x vol | boost: +{r['score_boost']:.2f}")
    
    # Save pattern results
    with open(PATTERN_RESULTS_FILE, 'w') as f:
        json.dump(pattern_results, f, indent=2)
    print(f"\nPattern results saved to {PATTERN_RESULTS_FILE}")
    
    # Integrate with scheduled results
    print("\n" + "="*70)
    print("INTEGRATING WITH SCHEDULED SCAN RESULTS")
    print("="*70)
    integrate_with_scheduled_results(pattern_results)


if __name__ == "__main__":
    asyncio.run(main())
