#!/usr/bin/env python3
"""
Detailed Engine Analysis Script
Runs all 3 engines and provides piece-by-piece analysis
"""

import asyncio
import sys
from datetime import datetime, date
from typing import List, Dict

sys.path.insert(0, '.')

from putsengine.config import EngineConfig, get_settings
from putsengine.engine import PutsEngine
from putsengine.models import PutCandidate

# Scoring tier definitions
SCORING_TIERS = {
    "EXPLOSIVE": {"min": 0.75, "emoji": "🔥", "expected": "-10% to -15%"},
    "VERY_STRONG": {"min": 0.65, "emoji": "⚡", "expected": "-5% to -10%"},
    "STRONG": {"min": 0.55, "emoji": "💪", "expected": "-3% to -7%"},
    "MONITORING": {"min": 0.45, "emoji": "👀", "expected": "-2% to -5%"},
}

def get_tier(score: float) -> str:
    if score >= 0.75:
        return "EXPLOSIVE"
    elif score >= 0.65:
        return "VERY_STRONG"
    elif score >= 0.55:
        return "STRONG"
    elif score >= 0.45:
        return "MONITORING"
    return "BELOW_THRESHOLD"

def print_separator():
    print("=" * 80)

def print_candidate_detail(candidate: PutCandidate, rank: int):
    """Print detailed analysis of a single candidate."""
    tier = get_tier(candidate.composite_score)
    tier_info = SCORING_TIERS.get(tier, {"emoji": "❌", "expected": "N/A"})
    
    print(f"\n{'='*80}")
    print(f"  #{rank} | {candidate.symbol} | {tier_info['emoji']} {tier} | Score: {candidate.composite_score:.4f}")
    print(f"{'='*80}")
    
    # Price Info
    print(f"\n📊 PRICE INFO:")
    print(f"   Current Price: ${candidate.current_price:.2f}" if candidate.current_price else "   Current Price: N/A")
    if candidate.recommended_strike:
        print(f"   Recommended Strike: ${candidate.recommended_strike:.2f}")
    if candidate.recommended_expiration:
        dte = (candidate.recommended_expiration - date.today()).days
        print(f"   Expiration: {candidate.recommended_expiration} ({dte} DTE)")
    if candidate.entry_price:
        print(f"   Entry Price: ${candidate.entry_price:.2f}")
    
    # Individual Scores
    print(f"\n📈 SCORE BREAKDOWN:")
    print(f"   Distribution Score:  {candidate.distribution_score:.4f} (weight: 30%)")
    print(f"   Dealer Score:        {candidate.dealer_score:.4f} (weight: 20%)")
    print(f"   Liquidity Score:     {candidate.liquidity_score:.4f} (weight: 15%)")
    print(f"   Flow Score:          {getattr(candidate, 'flow_score', 0):.4f} (weight: 15%)")
    print(f"   Catalyst Score:      {getattr(candidate, 'catalyst_score', 0):.4f} (weight: 10%)")
    print(f"   Sentiment Score:     {getattr(candidate, 'sentiment_score', 0):.4f} (weight: 5%)")
    print(f"   Technical Score:     {getattr(candidate, 'technical_score', 0):.4f} (weight: 5%)")
    
    # Distribution Signals
    if candidate.distribution:
        print(f"\n🔍 DISTRIBUTION SIGNALS:")
        signals = candidate.distribution.signals or {}
        active_signals = [k for k, v in signals.items() if v]
        inactive_signals = [k for k, v in signals.items() if not v]
        
        if active_signals:
            print(f"   ✅ ACTIVE ({len(active_signals)}):")
            for sig in active_signals:
                print(f"      • {sig}")
        if inactive_signals and len(inactive_signals) <= 5:
            print(f"   ❌ INACTIVE ({len(inactive_signals)}):")
            for sig in inactive_signals[:5]:
                print(f"      • {sig}")
    
    # Liquidity Analysis
    if candidate.liquidity:
        print(f"\n💧 LIQUIDITY SIGNALS:")
        print(f"   • Bid Collapsing: {'✅' if candidate.liquidity.bid_collapsing else '❌'}")
        print(f"   • Spread Widening: {'✅' if candidate.liquidity.spread_widening else '❌'}")
        print(f"   • Volume No Progress: {'✅' if candidate.liquidity.volume_no_progress else '❌'}")
        print(f"   • VWAP Retest Failed: {'✅' if candidate.liquidity.vwap_retest_failed else '❌'}")
    
    # Acceleration Window
    if candidate.acceleration:
        print(f"\n⏱️ ACCELERATION WINDOW:")
        print(f"   • Below VWAP: {'✅' if candidate.acceleration.price_below_vwap else '❌'}")
        print(f"   • Below EMA20: {'✅' if candidate.acceleration.price_below_ema20 else '❌'}")
        print(f"   • Below Prior Low: {'✅' if candidate.acceleration.price_below_prior_low else '❌'}")
        print(f"   • Failed Reclaim: {'✅' if candidate.acceleration.failed_reclaim else '❌'}")
        print(f"   • Net Delta Negative: {'✅' if candidate.acceleration.net_delta_negative else '❌'}")
        print(f"   • Gamma Flipping Short: {'✅' if candidate.acceleration.gamma_flipping_short else '❌'}")
        print(f"   • RSI Overbought: {'✅' if getattr(candidate.acceleration, 'rsi_overbought', False) else '❌'}")
        print(f"   • Is Late Entry: {'⚠️ YES' if candidate.acceleration.is_late_entry else '✅ NO'}")
        print(f"   • Engine Type: {candidate.acceleration.engine_type.value if hasattr(candidate.acceleration, 'engine_type') else 'N/A'}")
    
    # GEX Data
    if candidate.gex_data:
        print(f"\n📉 GEX DATA:")
        print(f"   • Net GEX: {candidate.gex_data.net_gex:,.0f}" if candidate.gex_data.net_gex else "   • Net GEX: N/A")
        print(f"   • Dealer Delta: {candidate.gex_data.dealer_delta:,.0f}" if candidate.gex_data.dealer_delta else "   • Dealer Delta: N/A")
        if candidate.gex_data.put_wall:
            print(f"   • Put Wall: ${candidate.gex_data.put_wall:.2f}")
        if candidate.gex_data.gex_flip_level:
            print(f"   • GEX Flip Level: ${candidate.gex_data.gex_flip_level:.2f}")
    
    # Block Reasons
    if candidate.block_reasons:
        print(f"\n⛔ BLOCK REASONS:")
        for reason in candidate.block_reasons:
            print(f"   • {reason.value}")
    
    print(f"\n   Expected Move: {tier_info['expected']}")
    print(f"   Passed All Gates: {'✅ YES' if candidate.passed_all_gates else '❌ NO'}")


async def run_analysis():
    """Run complete engine analysis."""
    print("\n" + "="*80)
    print("  🔬 PUTSENGINE DETAILED ANALYSIS")
    print("  Running all 3 engines with piece-by-piece breakdown")
    print("="*80)
    print(f"\n⏰ Analysis started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Initialize engine
    engine = PutsEngine()
    
    # Get all tickers
    all_tickers = EngineConfig.get_all_tickers()
    print(f"📋 Total tickers to scan: {len(all_tickers)}")
    
    # Pre-cache market regime
    print("\n🌍 Checking Market Regime...")
    try:
        regime = await engine.get_cached_regime()
        print(f"   • Market Status: {'TRADEABLE ✅' if regime.is_tradeable else 'BLOCKED ⛔'}")
        print(f"   • Regime: {regime.regime.value}")
        print(f"   • VIX: {regime.vix_level:.1f} ({regime.vix_change:+.1f}%)")
        print(f"   • SPY Below VWAP: {'✅' if regime.spy_below_vwap else '❌'}")
        print(f"   • QQQ Below VWAP: {'✅' if regime.qqq_below_vwap else '❌'}")
        if regime.block_reasons:
            print(f"   • Block Reasons: {[r.value for r in regime.block_reasons]}")
    except Exception as e:
        print(f"   ⚠️ Error getting regime: {e}")
    
    # Scan all tickers
    print(f"\n🔄 Scanning {len(all_tickers)} tickers...")
    
    candidates: List[PutCandidate] = []
    scanned = 0
    errors = 0
    
    # Use semaphore for parallel scanning
    semaphore = asyncio.Semaphore(15)
    
    async def scan_ticker(symbol: str) -> PutCandidate:
        nonlocal scanned, errors
        async with semaphore:
            try:
                candidate = await asyncio.wait_for(
                    engine.run_single_symbol(symbol, fast_mode=True),
                    timeout=10.0
                )
                scanned += 1
                if scanned % 20 == 0:
                    print(f"   Progress: {scanned}/{len(all_tickers)} ({scanned/len(all_tickers)*100:.0f}%)")
                return candidate
            except Exception as e:
                errors += 1
                scanned += 1
                return None
    
    # Run all scans in parallel
    tasks = [scan_ticker(symbol) for symbol in all_tickers]
    results = await asyncio.gather(*tasks)
    
    # Filter valid candidates
    for result in results:
        if result and result.composite_score >= 0.45:
            candidates.append(result)
    
    # Sort by score
    candidates.sort(key=lambda x: x.composite_score, reverse=True)
    
    print(f"\n✅ Scan Complete!")
    print(f"   • Scanned: {scanned}")
    print(f"   • Errors: {errors}")
    print(f"   • Candidates (score >= 0.45): {len(candidates)}")
    
    # Categorize by tier
    tiers = {
        "EXPLOSIVE": [],
        "VERY_STRONG": [],
        "STRONG": [],
        "MONITORING": []
    }
    
    for c in candidates:
        tier = get_tier(c.composite_score)
        if tier in tiers:
            tiers[tier].append(c)
    
    # Summary
    print_separator()
    print("\n📊 SCORING TIER SUMMARY")
    print_separator()
    
    for tier_name, tier_candidates in tiers.items():
        tier_info = SCORING_TIERS[tier_name]
        print(f"\n{tier_info['emoji']} {tier_name} (>= {tier_info['min']}) - Expected: {tier_info['expected']}")
        print(f"   Count: {len(tier_candidates)}")
        if tier_candidates:
            print(f"   Symbols: {', '.join([c.symbol for c in tier_candidates[:10]])}")
            if len(tier_candidates) > 10:
                print(f"   ... and {len(tier_candidates) - 10} more")
    
    # Detailed breakdown of top candidates
    if candidates:
        print_separator()
        print("\n🔬 DETAILED CANDIDATE ANALYSIS (Top 10)")
        print_separator()
        
        for i, candidate in enumerate(candidates[:10], 1):
            print_candidate_detail(candidate, i)
    else:
        print("\n⚠️ No candidates found with score >= 0.45")
        print("   This could mean:")
        print("   • Market is closed (weekend/holiday)")
        print("   • No current bearish setups detected")
        print("   • Market regime is blocking")
    
    # Engine Analysis
    print_separator()
    print("\n🔧 ENGINE TYPE BREAKDOWN")
    print_separator()
    
    engine_types = {}
    for c in candidates:
        if c.acceleration and hasattr(c.acceleration, 'engine_type'):
            etype = c.acceleration.engine_type.value
            if etype not in engine_types:
                engine_types[etype] = []
            engine_types[etype].append(c.symbol)
    
    for etype, symbols in engine_types.items():
        print(f"\n{etype}:")
        print(f"   Count: {len(symbols)}")
        print(f"   Symbols: {', '.join(symbols[:10])}")
    
    # Signal Analysis
    print_separator()
    print("\n📈 MOST COMMON ACTIVE SIGNALS")
    print_separator()
    
    signal_counts = {}
    for c in candidates:
        if c.distribution and c.distribution.signals:
            for sig, active in c.distribution.signals.items():
                if active:
                    signal_counts[sig] = signal_counts.get(sig, 0) + 1
    
    sorted_signals = sorted(signal_counts.items(), key=lambda x: x[1], reverse=True)
    for sig, count in sorted_signals[:15]:
        pct = count / len(candidates) * 100 if candidates else 0
        print(f"   • {sig}: {count} ({pct:.0f}%)")
    
    print_separator()
    print(f"\n⏰ Analysis completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print_separator()
    
    await engine.close()


if __name__ == "__main__":
    asyncio.run(run_analysis())
