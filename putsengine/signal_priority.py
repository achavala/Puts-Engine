"""
Signal Priority System - PRE vs POST Breakdown Classification

CRITICAL INSIGHT (Feb 1, 2026):
================================
The system was detecting moves AFTER they happened, not BEFORE.

This module classifies signals into:
- PRE-BREAKDOWN (PREDICTIVE): Signals that appear BEFORE price drops
- POST-BREAKDOWN (REACTIVE): Signals that appear AFTER price has already moved

PRE-breakdown signals should have HIGHER priority for trade entry timing.

SIGNAL CLASSIFICATION:
=======================
PRE-BREAKDOWN (PREDICTIVE) - Higher Weight:
- dark_pool_surge: Institutions selling quietly BEFORE announcement
- put_oi_accumulation: Smart money building put positions BEFORE news
- call_selling_at_bid: Hedging activity BEFORE downside
- iv_inversion: Term structure inversion BEFORE event
- distribution_day: Volume-price divergence BEFORE breakdown
- flat_price_rising_volume: Supply absorption BEFORE price fails
- lower_highs_flat_rsi: Distribution pattern BEFORE breakdown
- rising_put_oi: Put accumulation BEFORE move
- c_level_selling: Insider selling BEFORE news
- insider_cluster: Multiple insiders BEFORE announcement
- skew_steepening: Put IV expansion BEFORE drop
- repeated_sell_blocks: Dark pool distribution BEFORE breakdown

POST-BREAKDOWN (REACTIVE) - Lower Weight:
- high_rvol_red_day: High volume AFTER price already dropped
- gap_down_no_recovery: Gap AFTER news already out
- vwap_loss: Lost VWAP AFTER selling pressure
- multi_day_weakness: Multiple red days AFTER move started
- pump_reversal: Reversal AFTER pump already failed
- gap_up_reversal: Reversal AFTER gap already failed
- failed_breakout: Failure AFTER attempt already made
- exhaustion: Exhaustion AFTER run already happened
"""

from enum import Enum
from typing import Dict, List, Tuple
from dataclasses import dataclass


class SignalTiming(Enum):
    """Signal timing classification."""
    PRE_BREAKDOWN = "pre_breakdown"      # PREDICTIVE - before price moves
    POST_BREAKDOWN = "post_breakdown"    # REACTIVE - after price has moved
    NEUTRAL = "neutral"                  # Context-dependent


@dataclass
class SignalDefinition:
    """Definition of a trading signal with priority weighting."""
    name: str
    timing: SignalTiming
    base_weight: float
    priority_multiplier: float  # PRE signals get 1.5x, POST signals get 0.7x
    description: str
    
    @property
    def effective_weight(self) -> float:
        """Calculate effective weight with priority multiplier."""
        return self.base_weight * self.priority_multiplier


# ============================================================================
# SIGNAL DEFINITIONS WITH TIMING CLASSIFICATION
# ============================================================================

SIGNAL_DEFINITIONS: Dict[str, SignalDefinition] = {
    # =========================================================================
    # PRE-BREAKDOWN SIGNALS (PREDICTIVE) - Priority Multiplier: 1.5x
    # These appear BEFORE the price drops - highest value for early detection
    # =========================================================================
    
    # Dark Pool & Institutional Signals (HIGHEST VALUE)
    "dark_pool_surge": SignalDefinition(
        name="dark_pool_surge",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.20,
        priority_multiplier=1.5,
        description="Dark pool volume surge - institutions exiting quietly BEFORE announcement"
    ),
    "repeated_sell_blocks": SignalDefinition(
        name="repeated_sell_blocks",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.18,
        priority_multiplier=1.5,
        description="Repeated dark pool sell blocks - distribution BEFORE breakdown"
    ),
    
    # Options Flow Signals (HIGH VALUE)
    "put_oi_accumulation": SignalDefinition(
        name="put_oi_accumulation",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.18,
        priority_multiplier=1.5,
        description="Put OI building quietly - smart money positioning BEFORE news"
    ),
    "rising_put_oi": SignalDefinition(
        name="rising_put_oi",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.15,
        priority_multiplier=1.5,
        description="Rising put open interest - accumulation BEFORE move"
    ),
    "call_selling_at_bid": SignalDefinition(
        name="call_selling_at_bid",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.15,
        priority_multiplier=1.5,
        description="Aggressive call selling - hedging activity BEFORE downside"
    ),
    "put_buying_at_ask": SignalDefinition(
        name="put_buying_at_ask",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.15,
        priority_multiplier=1.5,
        description="Aggressive put buying at ask - conviction BEFORE move"
    ),
    "skew_steepening": SignalDefinition(
        name="skew_steepening",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.12,
        priority_multiplier=1.5,
        description="Put IV rising faster than call IV - fear building BEFORE breakdown"
    ),
    "iv_inversion": SignalDefinition(
        name="iv_inversion",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.15,
        priority_multiplier=1.5,
        description="Near-term IV > far-term IV - event premium BEFORE catalyst"
    ),
    
    # Price-Volume Distribution Signals (MEDIUM-HIGH VALUE)
    "flat_price_rising_volume": SignalDefinition(
        name="flat_price_rising_volume",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.15,
        priority_multiplier=1.5,
        description="Price flat with rising volume - supply absorption BEFORE failure"
    ),
    "lower_highs_flat_rsi": SignalDefinition(
        name="lower_highs_flat_rsi",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.12,
        priority_multiplier=1.5,
        description="Lower highs with flat RSI - hidden distribution pattern"
    ),
    "distribution_day": SignalDefinition(
        name="distribution_day",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.15,
        priority_multiplier=1.5,
        description="High volume + flat price - classic distribution BEFORE breakdown"
    ),
    
    # Insider Signals (MEDIUM VALUE)
    "c_level_selling": SignalDefinition(
        name="c_level_selling",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.12,
        priority_multiplier=1.5,
        description="C-level executive selling - insider knowledge BEFORE news"
    ),
    "insider_cluster": SignalDefinition(
        name="insider_cluster",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.10,
        priority_multiplier=1.5,
        description="Multiple insider sells - cluster activity BEFORE event"
    ),
    "congress_selling": SignalDefinition(
        name="congress_selling",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.08,
        priority_multiplier=1.5,
        description="Congressional selling - regulatory insight"
    ),
    
    # Pre-Catalyst Specific
    "precatalyst_critical": SignalDefinition(
        name="precatalyst_critical",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.25,
        priority_multiplier=1.5,
        description="Critical pre-catalyst distribution (4+ signals)"
    ),
    "precatalyst_high": SignalDefinition(
        name="precatalyst_high",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.20,
        priority_multiplier=1.5,
        description="High pre-catalyst distribution (3 signals)"
    ),
    
    # =========================================================================
    # POST-BREAKDOWN SIGNALS (REACTIVE) - Priority Multiplier: 0.7x
    # These appear AFTER the price has already moved - late entry signals
    # =========================================================================
    
    "high_rvol_red_day": SignalDefinition(
        name="high_rvol_red_day",
        timing=SignalTiming.POST_BREAKDOWN,
        base_weight=0.15,
        priority_multiplier=0.7,
        description="High volume on red day - AFTER price already dropped"
    ),
    "gap_down_no_recovery": SignalDefinition(
        name="gap_down_no_recovery",
        timing=SignalTiming.POST_BREAKDOWN,
        base_weight=0.12,
        priority_multiplier=0.7,
        description="Gap down without recovery - AFTER news already out"
    ),
    "gap_up_reversal": SignalDefinition(
        name="gap_up_reversal",
        timing=SignalTiming.POST_BREAKDOWN,
        base_weight=0.15,
        priority_multiplier=0.7,
        description="Gap up then reversal - AFTER gap already failed"
    ),
    "vwap_loss": SignalDefinition(
        name="vwap_loss",
        timing=SignalTiming.POST_BREAKDOWN,
        base_weight=0.10,
        priority_multiplier=0.7,
        description="VWAP lost - AFTER selling pressure already present"
    ),
    "multi_day_weakness": SignalDefinition(
        name="multi_day_weakness",
        timing=SignalTiming.POST_BREAKDOWN,
        base_weight=0.10,
        priority_multiplier=0.7,
        description="Multiple red days - AFTER move already started"
    ),
    "pump_reversal": SignalDefinition(
        name="pump_reversal",
        timing=SignalTiming.POST_BREAKDOWN,
        base_weight=0.12,
        priority_multiplier=0.7,
        description="Pump then reversal - AFTER pump already failed"
    ),
    "failed_breakout": SignalDefinition(
        name="failed_breakout",
        timing=SignalTiming.POST_BREAKDOWN,
        base_weight=0.10,
        priority_multiplier=0.7,
        description="Failed breakout - AFTER attempt already made"
    ),
    "exhaustion": SignalDefinition(
        name="exhaustion",
        timing=SignalTiming.POST_BREAKDOWN,
        base_weight=0.10,
        priority_multiplier=0.7,
        description="Exhaustion pattern - AFTER run already happened"
    ),
    "two_day_rally": SignalDefinition(
        name="two_day_rally",
        timing=SignalTiming.POST_BREAKDOWN,
        base_weight=0.08,
        priority_multiplier=0.7,
        description="Two-day rally exhaustion - wait for reversal confirmation"
    ),
    "high_vol_run": SignalDefinition(
        name="high_vol_run",
        timing=SignalTiming.POST_BREAKDOWN,
        base_weight=0.08,
        priority_multiplier=0.7,
        description="High volume run - AFTER move already in progress"
    ),
    
    # =========================================================================
    # NEUTRAL/CONTEXT-DEPENDENT SIGNALS - Priority Multiplier: 1.0x
    # =========================================================================
    
    "is_post_earnings_negative": SignalDefinition(
        name="is_post_earnings_negative",
        timing=SignalTiming.NEUTRAL,
        base_weight=0.12,
        priority_multiplier=1.0,
        description="Post-earnings with negative guidance"
    ),
    "is_pre_earnings": SignalDefinition(
        name="is_pre_earnings",
        timing=SignalTiming.NEUTRAL,
        base_weight=-0.05,  # Penalty unless front-run detected
        priority_multiplier=1.0,
        description="Pre-earnings period - usually avoid unless front-run"
    ),
    "below_vwap": SignalDefinition(
        name="below_vwap",
        timing=SignalTiming.NEUTRAL,
        base_weight=0.08,
        priority_multiplier=1.0,
        description="Currently below VWAP"
    ),
    "below_prior_low": SignalDefinition(
        name="below_prior_low",
        timing=SignalTiming.NEUTRAL,
        base_weight=0.08,
        priority_multiplier=1.0,
        description="Below prior day low"
    ),
    "volume_price_divergence": SignalDefinition(
        name="volume_price_divergence",
        timing=SignalTiming.NEUTRAL,
        base_weight=0.10,
        priority_multiplier=1.0,
        description="Volume-price divergence"
    ),
}


def get_signal_weight(signal_name: str) -> float:
    """
    Get the effective weight for a signal (with PRE/POST priority applied).
    
    Args:
        signal_name: Name of the signal
        
    Returns:
        Effective weight (base_weight * priority_multiplier)
    """
    if signal_name in SIGNAL_DEFINITIONS:
        return SIGNAL_DEFINITIONS[signal_name].effective_weight
    return 0.05  # Default weight for unknown signals


def get_signal_timing(signal_name: str) -> SignalTiming:
    """
    Get the timing classification for a signal.
    
    Args:
        signal_name: Name of the signal
        
    Returns:
        SignalTiming enum value
    """
    if signal_name in SIGNAL_DEFINITIONS:
        return SIGNAL_DEFINITIONS[signal_name].timing
    return SignalTiming.NEUTRAL


def classify_signals(signals: Dict[str, bool]) -> Tuple[List[str], List[str], List[str]]:
    """
    Classify active signals into PRE, POST, and NEUTRAL categories.
    
    Args:
        signals: Dict of signal_name -> is_active
        
    Returns:
        Tuple of (pre_breakdown_signals, post_breakdown_signals, neutral_signals)
    """
    pre = []
    post = []
    neutral = []
    
    for signal_name, is_active in signals.items():
        if not is_active:
            continue
            
        timing = get_signal_timing(signal_name)
        
        if timing == SignalTiming.PRE_BREAKDOWN:
            pre.append(signal_name)
        elif timing == SignalTiming.POST_BREAKDOWN:
            post.append(signal_name)
        else:
            neutral.append(signal_name)
    
    return pre, post, neutral


def calculate_priority_score(signals: Dict[str, bool]) -> Tuple[float, Dict[str, float]]:
    """
    Calculate total score with PRE-breakdown priority weighting.
    
    Args:
        signals: Dict of signal_name -> is_active
        
    Returns:
        Tuple of (total_score, breakdown_by_signal)
    """
    total_score = 0.0
    breakdown = {}
    
    for signal_name, is_active in signals.items():
        if not is_active:
            continue
            
        weight = get_signal_weight(signal_name)
        total_score += weight
        breakdown[signal_name] = weight
    
    return min(total_score, 1.0), breakdown


def get_signal_priority_summary(signals: Dict[str, bool]) -> Dict:
    """
    Get a summary of signal priority analysis.
    
    Args:
        signals: Dict of signal_name -> is_active
        
    Returns:
        Dict with PRE/POST counts, weights, and recommendation
    """
    pre, post, neutral = classify_signals(signals)
    total_score, breakdown = calculate_priority_score(signals)
    
    pre_score = sum(breakdown.get(s, 0) for s in pre)
    post_score = sum(breakdown.get(s, 0) for s in post)
    neutral_score = sum(breakdown.get(s, 0) for s in neutral)
    
    # Determine timing recommendation
    if pre_score > post_score * 1.5:
        timing_rec = "EARLY_ENTRY"  # Strong PRE signals - enter now
        timing_desc = "Strong predictive signals - consider early entry"
    elif post_score > pre_score * 1.5:
        timing_rec = "LATE_ENTRY"  # Mostly POST signals - chase or wait for pullback
        timing_desc = "Mostly reactive signals - price already moved"
    else:
        timing_rec = "BALANCED"  # Mix of signals
        timing_desc = "Mixed PRE/POST signals - standard timing"
    
    return {
        "total_score": total_score,
        "pre_breakdown_count": len(pre),
        "post_breakdown_count": len(post),
        "neutral_count": len(neutral),
        "pre_breakdown_score": pre_score,
        "post_breakdown_score": post_score,
        "neutral_score": neutral_score,
        "pre_signals": pre,
        "post_signals": post,
        "neutral_signals": neutral,
        "timing_recommendation": timing_rec,
        "timing_description": timing_desc,
        "breakdown": breakdown,
    }


# ============================================================================
# HELPER FUNCTIONS FOR SCHEDULER AND SCORING
# ============================================================================

def is_predictive_signal_dominant(signals: Dict[str, bool]) -> bool:
    """
    Check if PRE-breakdown (predictive) signals dominate.
    
    Returns True if:
    - At least 2 PRE-breakdown signals active
    - PRE score > POST score
    
    This is used to prioritize early detection candidates.
    """
    pre, post, _ = classify_signals(signals)
    
    if len(pre) < 2:
        return False
    
    pre_score = sum(get_signal_weight(s) for s in pre)
    post_score = sum(get_signal_weight(s) for s in post)
    
    return pre_score > post_score


def get_entry_timing_multiplier(signals: Dict[str, bool]) -> float:
    """
    Get position sizing multiplier based on signal timing.
    
    - Strong PRE signals: 1.2x (enter with confidence)
    - Balanced: 1.0x (standard size)
    - Strong POST signals: 0.8x (reduced size - late entry)
    """
    summary = get_signal_priority_summary(signals)
    
    if summary["timing_recommendation"] == "EARLY_ENTRY":
        return 1.2
    elif summary["timing_recommendation"] == "LATE_ENTRY":
        return 0.8
    else:
        return 1.0
