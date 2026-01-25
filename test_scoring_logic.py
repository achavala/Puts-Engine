#!/usr/bin/env python3
"""
Test the scoring logic piece by piece using simulated data
This validates that our scoring tiers work correctly
"""

import sys
sys.path.insert(0, '.')

from datetime import datetime, date, timedelta
from putsengine.models import (
    PutCandidate, DistributionSignal, LiquidityVacuum, 
    AccelerationWindow, GEXData, EngineType
)
from putsengine.scoring.scorer import PutScorer
from putsengine.config import get_settings

# Initialize scorer
settings = get_settings()
scorer = PutScorer(settings)

def create_test_candidate(
    symbol: str,
    # Distribution signals
    high_rvol_red_day: bool = False,
    gap_down_no_recovery: bool = False,
    multi_day_weakness: bool = False,
    failed_breakout: bool = False,
    vwap_loss: bool = False,
    flat_price_rising_volume: bool = False,
    lower_highs_flat_rsi: bool = False,
    # Options signals
    put_buying_at_ask: bool = False,
    call_selling_at_bid: bool = False,
    rising_put_oi: bool = False,
    skew_steepening: bool = False,
    # Dark pool
    repeated_sell_blocks: bool = False,
    # Insider/Congress
    c_level_selling: bool = False,
    insider_cluster: bool = False,
    congress_selling: bool = False,
    # Acceleration
    price_below_vwap: bool = False,
    price_below_ema20: bool = False,
    price_below_prior_low: bool = False,
    failed_reclaim: bool = False,
    net_delta_negative: bool = False,
    gamma_flipping_short: bool = False,
    # Liquidity
    bid_collapsing: bool = False,
    spread_widening: bool = False,
    volume_no_progress: bool = False,
    vwap_retest_failed: bool = False,
    # Dealer
    dealer_score: float = 0.5,
) -> PutCandidate:
    """Create a test candidate with specified signals."""
    
    # Create distribution signal
    distribution = DistributionSignal(
        symbol=symbol,
        timestamp=datetime.now(),
        score=0.0,
        flat_price_rising_volume=flat_price_rising_volume,
        failed_breakout=failed_breakout,
        lower_highs_flat_rsi=lower_highs_flat_rsi,
        vwap_loss=vwap_loss,
        call_selling_at_bid=call_selling_at_bid,
        put_buying_at_ask=put_buying_at_ask,
        rising_put_oi=rising_put_oi,
        skew_steepening=skew_steepening,
        repeated_sell_blocks=repeated_sell_blocks,
        signals={
            "high_rvol_red_day": high_rvol_red_day,
            "gap_down_no_recovery": gap_down_no_recovery,
            "multi_day_weakness": multi_day_weakness,
            "flat_price_rising_volume": flat_price_rising_volume,
            "failed_breakout": failed_breakout,
            "lower_highs_flat_rsi": lower_highs_flat_rsi,
            "vwap_loss": vwap_loss,
            "call_selling_at_bid": call_selling_at_bid,
            "put_buying_at_ask": put_buying_at_ask,
            "rising_put_oi": rising_put_oi,
            "skew_steepening": skew_steepening,
            "repeated_sell_blocks": repeated_sell_blocks,
            "c_level_selling": c_level_selling,
            "insider_cluster": insider_cluster,
            "congress_selling": congress_selling,
            "is_pre_earnings": False,
            "is_post_earnings_negative": False,
        }
    )
    
    # Create acceleration window
    acceleration = AccelerationWindow(
        symbol=symbol,
        timestamp=datetime.now(),
        price_below_vwap=price_below_vwap,
        price_below_ema20=price_below_ema20,
        price_below_prior_low=price_below_prior_low,
        failed_reclaim=failed_reclaim,
        put_volume_rising=False,
        iv_reasonable=True,
        net_delta_negative=net_delta_negative,
        gamma_flipping_short=gamma_flipping_short,
        is_late_entry=False,
        is_valid=True,
        engine_type=EngineType.GAMMA_DRAIN
    )
    
    # Create liquidity vacuum
    liquidity = LiquidityVacuum(
        symbol=symbol,
        timestamp=datetime.now(),
        score=0.0,
        bid_collapsing=bid_collapsing,
        spread_widening=spread_widening,
        volume_no_progress=volume_no_progress,
        vwap_retest_failed=vwap_retest_failed
    )
    liquidity.score = sum([bid_collapsing, spread_widening, volume_no_progress, vwap_retest_failed]) * 0.25
    
    # Create candidate
    candidate = PutCandidate(
        symbol=symbol,
        timestamp=datetime.now(),
        current_price=100.0,
        distribution=distribution,
        acceleration=acceleration,
        liquidity=liquidity,
        dealer_score=dealer_score,
        passed_all_gates=True
    )
    
    return candidate

def get_tier(score: float) -> str:
    if score >= 0.75:
        return "🔥 EXPLOSIVE"
    elif score >= 0.65:
        return "⚡ VERY STRONG"
    elif score >= 0.55:
        return "💪 STRONG"
    elif score >= 0.45:
        return "👀 MONITORING"
    return "❌ BELOW THRESHOLD"

def print_separator():
    print("=" * 80)

# Test Cases
print_separator()
print("  🔬 SCORING LOGIC VALIDATION TEST")
print("  Testing each scoring tier with simulated data")
print_separator()

# TEST 1: EXPLOSIVE Signal (-13.7% gap like SMCI)
print("\n📊 TEST 1: EXPLOSIVE Signal (like SMCI -13.7% gap)")
print("-" * 60)
candidate1 = create_test_candidate(
    "SMCI_TEST",
    # Strong distribution signals
    high_rvol_red_day=True,           # RVOL > 2x on red day
    gap_down_no_recovery=True,        # Gap down, failed to recover
    multi_day_weakness=True,          # 3+ lower closes
    failed_breakout=True,             # Failed at resistance
    vwap_loss=True,                   # Lost VWAP
    # Strong options signals
    put_buying_at_ask=True,           # Aggressive put buying
    call_selling_at_bid=True,         # Bulls exiting
    rising_put_oi=True,               # Put OI increasing
    skew_steepening=True,             # Puts getting expensive
    # Dark pool
    repeated_sell_blocks=True,         # Institutional selling
    # Insider
    c_level_selling=True,             # CEO/CFO selling
    insider_cluster=True,             # Multiple insiders
    # Technical
    price_below_vwap=True,
    price_below_ema20=True,
    price_below_prior_low=True,
    failed_reclaim=True,
    net_delta_negative=True,
    gamma_flipping_short=True,
    # Liquidity
    bid_collapsing=True,
    spread_widening=True,
    vwap_retest_failed=True,
    # Dealer
    dealer_score=0.9,
)
score1 = scorer.score_candidate(candidate1)
print(f"   Symbol: SMCI_TEST")
print(f"   Signals Active: ALL MAXIMUM BEARISH")
print(f"   Score: {score1:.4f}")
print(f"   Tier: {get_tier(score1)}")
print(f"   Expected: EXPLOSIVE (>= 0.75)")
print(f"   Result: {'✅ PASS' if score1 >= 0.75 else '❌ FAIL'}")

# TEST 2: VERY STRONG Signal
print("\n📊 TEST 2: VERY STRONG Signal")
print("-" * 60)
candidate2 = create_test_candidate(
    "VERY_STRONG_TEST",
    # Strong distribution signals
    high_rvol_red_day=True,           # RVOL > 2x on red day (+0.20)
    gap_down_no_recovery=True,        # Gap down (+0.15)
    multi_day_weakness=True,          # 3+ lower closes (+0.12)
    vwap_loss=True,                   # Lost VWAP (+0.08)
    failed_breakout=True,             # (+0.08)
    # Options signals
    put_buying_at_ask=True,           # Aggressive put buying
    call_selling_at_bid=True,         # Bulls exiting
    rising_put_oi=True,               # Put OI rising
    # Dark pool
    repeated_sell_blocks=True,         # Institutional selling
    # Technical
    price_below_vwap=True,
    price_below_ema20=True,
    price_below_prior_low=True,
    failed_reclaim=True,
    gamma_flipping_short=True,
    net_delta_negative=True,
    # Liquidity
    bid_collapsing=True,
    spread_widening=True,
    # Dealer
    dealer_score=0.75,
)
score2 = scorer.score_candidate(candidate2)
print(f"   Symbol: VERY_STRONG_TEST")
print(f"   Signals: RVOL + Gap + Weakness + Options + Dark pool + Technical")
print(f"   Score: {score2:.4f}")
print(f"   Tier: {get_tier(score2)}")
print(f"   Expected: VERY STRONG (0.65-0.74)")
print(f"   Result: {'✅ PASS' if 0.65 <= score2 < 0.75 else '❌ FAIL'}")

# TEST 3: STRONG Signal
print("\n📊 TEST 3: STRONG Signal")
print("-" * 60)
candidate3 = create_test_candidate(
    "STRONG_TEST",
    # Good distribution signals (needs more for 0.55+)
    high_rvol_red_day=True,           # RVOL > 2x (+0.20)
    gap_down_no_recovery=True,        # Gap down (+0.15)
    multi_day_weakness=True,          # 3+ lower closes (+0.12)
    vwap_loss=True,                   # Lost VWAP (+0.08)
    failed_breakout=True,             # Failed breakout (+0.08)
    # Options signals
    put_buying_at_ask=True,           # Put buying
    call_selling_at_bid=True,         # Call selling
    rising_put_oi=True,               # Put OI rising
    # Technical
    price_below_vwap=True,
    price_below_ema20=True,
    price_below_prior_low=True,
    failed_reclaim=True,
    gamma_flipping_short=True,
    # Liquidity - needs more signals
    bid_collapsing=True,
    spread_widening=True,
    # Dealer
    dealer_score=0.65,
)
score3 = scorer.score_candidate(candidate3)
print(f"   Symbol: STRONG_TEST")
print(f"   Signals: RVOL + Gap + Weakness + Failed breakout + Options + Liquidity")
print(f"   Score: {score3:.4f}")
print(f"   Tier: {get_tier(score3)}")
print(f"   Expected: STRONG (0.55-0.64)")
print(f"   Result: {'✅ PASS' if 0.55 <= score3 < 0.65 else '❌ FAIL'}")

# TEST 4: MONITORING Signal
print("\n📊 TEST 4: MONITORING Signal")
print("-" * 60)
candidate4 = create_test_candidate(
    "MONITORING_TEST",
    # Moderate distribution signals - enough for early warning
    high_rvol_red_day=True,           # RVOL > 2x (+0.20)
    gap_down_no_recovery=True,        # Gap down (+0.15)
    multi_day_weakness=True,          # 3+ lower closes (+0.12)
    vwap_loss=True,                   # Lost VWAP (+0.08)
    # Minimal options
    put_buying_at_ask=True,           # Some put buying
    call_selling_at_bid=True,         # Some call selling
    # Technical - some weakness
    price_below_vwap=True,
    price_below_ema20=True,
    failed_reclaim=True,
    # Liquidity - one signal
    bid_collapsing=True,
    spread_widening=True,
    # Dealer - neutral to slightly bearish
    dealer_score=0.55,
)
score4 = scorer.score_candidate(candidate4)
print(f"   Symbol: MONITORING_TEST")
print(f"   Signals: RVOL + Gap + Multi-day + VWAP + Options + Technicals + Liquidity")
print(f"   Score: {score4:.4f}")
print(f"   Tier: {get_tier(score4)}")
print(f"   Expected: MONITORING (0.45-0.54)")
print(f"   Result: {'✅ PASS' if 0.45 <= score4 < 0.55 else '❌ FAIL'}")

# TEST 5: BELOW THRESHOLD (should not trade)
print("\n📊 TEST 5: BELOW THRESHOLD (NO TRADE)")
print("-" * 60)
candidate5 = create_test_candidate(
    "NO_TRADE_TEST",
    # Minimal signals
    vwap_loss=True,                   # Only VWAP loss
    # Dealer
    dealer_score=0.5,
)
score5 = scorer.score_candidate(candidate5)
print(f"   Symbol: NO_TRADE_TEST")
print(f"   Signals: Only VWAP loss (insufficient)")
print(f"   Score: {score5:.4f}")
print(f"   Tier: {get_tier(score5)}")
print(f"   Expected: BELOW THRESHOLD (< 0.45)")
print(f"   Result: {'✅ PASS' if score5 < 0.45 else '❌ FAIL'}")

# Summary
print_separator()
print("\n📈 SCORING TIER VALIDATION SUMMARY")
print_separator()

tests = [
    ("EXPLOSIVE (0.75+)", score1 >= 0.75, score1),
    ("VERY STRONG (0.65-0.74)", 0.65 <= score2 < 0.75, score2),
    ("STRONG (0.55-0.64)", 0.55 <= score3 < 0.65, score3),
    ("MONITORING (0.45-0.54)", 0.45 <= score4 < 0.55, score4),
    ("BELOW THRESHOLD (<0.45)", score5 < 0.45, score5),
]

passed = 0
for name, result, score in tests:
    status = "✅ PASS" if result else "❌ FAIL"
    print(f"   {name}: {status} (score: {score:.4f})")
    if result:
        passed += 1

print(f"\n   Total: {passed}/5 tests passed")
print_separator()

# Score Component Breakdown for EXPLOSIVE
print("\n🔍 DETAILED SCORE BREAKDOWN (EXPLOSIVE Candidate)")
print_separator()
breakdown = scorer.get_score_breakdown(candidate1)
print(f"\n   Composite Score: {breakdown['composite']:.4f}")
print(f"\n   Component Scores (weighted):")
for comp, score in breakdown['components'].items():
    weight = breakdown['weights'].get(comp, 0)
    contribution = score * weight
    print(f"      • {comp}: {score:.2f} × {weight:.0%} = {contribution:.4f}")
print(f"\n   Is Actionable: {'✅ YES' if breakdown['is_actionable'] else '❌ NO'}")
print(f"   Threshold: {breakdown['threshold']}")
print_separator()
