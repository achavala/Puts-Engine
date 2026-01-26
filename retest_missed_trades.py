#!/usr/bin/env python3
"""
🔧 RETEST MISSED TRADES - After Bug Fixes

This script retests the missed trades after applying:
1. Fixed signals dict timing bug
2. Added missing tickers to universe
3. Lowered RVOL thresholds
4. Lowered score threshold

Let's see if we would have caught them now!
"""

import asyncio
import sys
from datetime import datetime, date, timedelta
from typing import Dict, List, Any
import json

sys.path.insert(0, '.')

from putsengine.config import get_settings, EngineConfig
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient
from putsengine.layers.distribution import DistributionLayer
from putsengine.layers.liquidity import LiquidityVacuumLayer
from putsengine.layers.acceleration import AccelerationWindowLayer
from putsengine.scoring.scorer import PutScorer
from putsengine.models import PutCandidate, EngineType, MarketRegimeData

# MISSED TRADES - These had significant moves
MISSED_TICKERS = [
    "RIOT",   # -5% (Crypto miner)
    "PL",     # -5% (Planet Labs)
    "INTC",   # -5% (Intel)
    "AMD",    # -3% (AMD)
    "UUUU",   # -11% (Energy Fuels - Uranium)
    "LUNR",   # -7% (Intuitive Machines)
    "ONDS",   # -7% (Ondas Holdings)
    "LMND",   # -6% (Lemonade)
    "CIFR",   # -5% (Cipher Mining)
    "PLUG",   # -6% (Plug Power)
    "ACHR",   # -5% (Archer Aviation)
]


def get_signal_tier(score: float) -> str:
    """Get signal tier from score."""
    if score >= 0.75:
        return "🔥 EXPLOSIVE"
    elif score >= 0.65:
        return "⚡ VERY STRONG"
    elif score >= 0.55:
        return "💪 STRONG"
    elif score >= 0.45:
        return "👀 MONITORING"
    elif score >= 0.40:
        return "📊 WATCHING"
    else:
        return "❌ BELOW THRESHOLD"


async def retest_missed_trades():
    """Retest missed trades with fixed code."""
    
    print("=" * 80)
    print("🔧 RETESTING MISSED TRADES - With Bug Fixes Applied")
    print("=" * 80)
    print()
    
    settings = get_settings()
    
    # Print current thresholds
    print("📋 CURRENT SETTINGS:")
    print(f"   Min Score Threshold: {settings.min_score_threshold}")
    print(f"   Volume Spike Threshold: {EngineConfig.VOLUME_SPIKE_THRESHOLD}")
    print(f"   RVOL High Threshold: {EngineConfig.RVOL_HIGH_THRESHOLD}")
    print(f"   RVOL Extreme Threshold: {EngineConfig.RVOL_EXTREME_THRESHOLD}")
    print()
    
    # Verify universe
    all_tickers = EngineConfig.get_all_tickers()
    print("📋 TICKER UNIVERSE CHECK:")
    for ticker in MISSED_TICKERS:
        in_universe = "✅" if ticker in all_tickers else "❌"
        print(f"   {in_universe} {ticker}")
    print(f"   Total tickers in universe: {len(all_tickers)}")
    print()
    
    alpaca = AlpacaClient(settings)
    polygon = PolygonClient(settings)
    uw = UnusualWhalesClient(settings)
    
    distribution_layer = DistributionLayer(alpaca, polygon, uw, settings)
    
    results = []
    caught_count = 0
    
    print("🔍 ANALYZING MISSED TRADES WITH FIXED CODE")
    print("-" * 80)
    
    for ticker in MISSED_TICKERS:
        print(f"\n{'='*60}")
        print(f"   {ticker}")
        print(f"{'='*60}")
        
        try:
            # Run distribution analysis with fixed code
            distribution = await distribution_layer.analyze(ticker)
            
            print(f"\n   📊 DISTRIBUTION SCORE: {distribution.score:.2f}")
            print(f"   📊 TIER: {get_signal_tier(distribution.score)}")
            
            # Count active signals
            active_signals = [k for k, v in distribution.signals.items() if v]
            print(f"   📊 ACTIVE SIGNALS ({len(active_signals)}):")
            for sig in active_signals:
                print(f"      ✅ {sig}")
            
            # Check if we would have caught it
            would_catch = distribution.score >= settings.min_score_threshold
            
            if would_catch:
                caught_count += 1
                print(f"\n   🎯 WOULD HAVE CAUGHT: YES! Score {distribution.score:.2f} >= {settings.min_score_threshold}")
            else:
                print(f"\n   ❌ WOULD HAVE CAUGHT: NO. Score {distribution.score:.2f} < {settings.min_score_threshold}")
            
            results.append({
                "symbol": ticker,
                "score": distribution.score,
                "tier": get_signal_tier(distribution.score),
                "active_signals": active_signals,
                "signal_count": len(active_signals),
                "would_catch": would_catch
            })
            
            # Small delay
            await asyncio.sleep(0.3)
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
            results.append({
                "symbol": ticker,
                "score": 0.0,
                "error": str(e),
                "would_catch": False
            })
    
    # Close clients
    await alpaca.close()
    await polygon.close()
    await uw.close()
    
    # Final summary
    print("\n" + "=" * 80)
    print("📋 FINAL SUMMARY")
    print("=" * 80)
    
    print(f"\n   Total Missed Trades: {len(MISSED_TICKERS)}")
    print(f"   Would Catch Now: {caught_count}/{len(MISSED_TICKERS)} ({caught_count/len(MISSED_TICKERS)*100:.0f}%)")
    
    print("\n   DETAILED RESULTS:")
    print("-" * 60)
    
    # Sort by score
    results_sorted = sorted(results, key=lambda x: x.get('score', 0), reverse=True)
    
    for r in results_sorted:
        status = "🎯" if r.get('would_catch') else "❌"
        print(f"   {status} {r['symbol']}: Score={r.get('score', 0):.2f}, Tier={r.get('tier', 'N/A')}, Signals={r.get('signal_count', 0)}")
    
    print("\n" + "=" * 80)
    print("💡 RECOMMENDATIONS")
    print("=" * 80)
    
    missed_still = [r for r in results if not r.get('would_catch')]
    if missed_still:
        print("\n   STILL MISSING (need further investigation):")
        for r in missed_still:
            print(f"      - {r['symbol']}: Score={r.get('score', 0):.2f}")
            if r.get('error'):
                print(f"        Error: {r['error']}")
            elif r.get('signal_count', 0) == 0:
                print(f"        Issue: No signals detected - check data availability")
            else:
                print(f"        Issue: Score too low despite {r.get('signal_count', 0)} signals")
    
    # Save results
    with open("retest_results.json", "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "settings": {
                "min_score_threshold": settings.min_score_threshold,
                "volume_spike_threshold": EngineConfig.VOLUME_SPIKE_THRESHOLD,
                "rvol_high_threshold": getattr(EngineConfig, 'RVOL_HIGH_THRESHOLD', 1.5),
                "rvol_extreme_threshold": getattr(EngineConfig, 'RVOL_EXTREME_THRESHOLD', 2.0),
            },
            "results": results,
            "summary": {
                "total": len(MISSED_TICKERS),
                "caught": caught_count,
                "catch_rate": caught_count / len(MISSED_TICKERS) * 100
            }
        }, f, indent=2, default=str)
    
    print(f"\n   Results saved to retest_results.json")
    
    return results


if __name__ == "__main__":
    asyncio.run(retest_missed_trades())
