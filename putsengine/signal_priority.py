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
    
    # Greek-Weighted Flow (FEB 8, 2026)
    "high_greek_weighted_flow": SignalDefinition(
        name="high_greek_weighted_flow",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.18,
        priority_multiplier=1.5,
        description="High bearish delta+gamma+vega exposure - institutional conviction BEFORE move"
    ),
    
    # Skew Reversal (FEB 8, 2026)
    "skew_reversal": SignalDefinition(
        name="skew_reversal",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.14,
        priority_multiplier=1.5,
        description="Risk reversal flipped sign day-over-day - regime shift in options skew"
    ),
    
    # Dark Pool Violence (FEB 8, 2026)
    "dark_pool_violence": SignalDefinition(
        name="dark_pool_violence",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.16,
        priority_multiplier=1.5,
        description="Large dark pool prints on thin NBBO books - violent absorption conditions"
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
    # =========================================================================
    # FEB 11, 2026 RECLASSIFICATION — Rally Exhaustion Signals
    # =========================================================================
    # CRITICAL INSIGHT: pump_reversal, exhaustion, topping_tail are NOT 
    # "reactive" when they appear on stocks that just rallied 10-30%.
    # They are PREDICTIVE — they signal the rally is ending and a reversal
    # is imminent. This is the "distribution after pump" pattern that
    # institutions use to exit positions (Wyckoff Distribution Phase C/D).
    #
    # The Feb 11 analysis proved this: U (+23% pump → -31%), ALAB (+27% → -18%),
    # HOOD (+17% → -11%) all had these signals but were ranked #245, #125, #206
    # because pump_reversal was penalized at 0.7x.
    # =========================================================================
    
    "pump_reversal": SignalDefinition(
        name="pump_reversal",
        timing=SignalTiming.PRE_BREAKDOWN,       # RECLASSIFIED: pump exhaustion IS predictive
        base_weight=0.18,                         # INCREASED from 0.12
        priority_multiplier=1.5,                  # CHANGED from 0.7x to 1.5x
        description="Pump then reversal — multi-day rally exhausting, institutions distributing into strength"
    ),
    "failed_breakout": SignalDefinition(
        name="failed_breakout",
        timing=SignalTiming.NEUTRAL,              # RECLASSIFIED from POST to NEUTRAL
        base_weight=0.12,                         # INCREASED from 0.10
        priority_multiplier=1.0,
        description="Failed breakout — bulls tried and failed, trapped longs will sell"
    ),
    "exhaustion": SignalDefinition(
        name="exhaustion",
        timing=SignalTiming.NEUTRAL,              # RECLASSIFIED from POST to NEUTRAL
        base_weight=0.12,                         # INCREASED from 0.10
        priority_multiplier=1.0,                  # CHANGED from 0.7x to 1.0x
        description="Rally exhaustion — momentum fading, reversal setup forming"
    ),
    "topping_tail": SignalDefinition(
        name="topping_tail",
        timing=SignalTiming.PRE_BREAKDOWN,         # NEW: was missing entirely (defaulted to 0.05)
        base_weight=0.14,
        priority_multiplier=1.5,
        description="Topping tail candlestick — rejection at highs, sellers overwhelming buyers (Nison 1991)"
    ),
    "two_day_rally": SignalDefinition(
        name="two_day_rally",
        timing=SignalTiming.NEUTRAL,              # RECLASSIFIED from POST to NEUTRAL
        base_weight=0.10,                         # INCREASED from 0.08
        priority_multiplier=1.0,                  # CHANGED from 0.7x to 1.0x
        description="Two-day rally — fast move creates trapped longs, mean-reversion setup"
    ),
    "high_vol_run": SignalDefinition(
        name="high_vol_run",
        timing=SignalTiming.POST_BREAKDOWN,
        base_weight=0.08,
        priority_multiplier=0.7,
        description="High volume run - AFTER move already in progress"
    ),
    # Handoff candidate (was missing — scored as unknown 0.05)
    "handoff_candidate": SignalDefinition(
        name="handoff_candidate",
        timing=SignalTiming.PRE_BREAKDOWN,
        base_weight=0.12,
        priority_multiplier=1.5,
        description="Handoff candidate — gap scanner → distribution engine pipeline, confirmed weakness"
    ),
    # Failure mode (was missing — scored as unknown 0.05)
    "failure_mode": SignalDefinition(
        name="failure_mode",
        timing=SignalTiming.NEUTRAL,
        base_weight=0.10,
        priority_multiplier=1.0,
        description="Failure mode — price structure breaking down, key supports failing"
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


def _normalize_signal_name(signal_name: str) -> str:
    """
    Normalize dynamic signal names to their base definition.
    
    Examples:
        pump_reversal_+23% → pump_reversal
        two_day_rally_+15% → two_day_rally
        high_vol_3.9x → high_vol_run
        pump_+20% → pump_reversal
    """
    # Direct match first
    if signal_name in SIGNAL_DEFINITIONS:
        return signal_name
    
    # Handle pump_reversal_+XX% or pump_reversal_-XX%
    if signal_name.startswith("pump_reversal_") or signal_name.startswith("pump_"):
        return "pump_reversal"
    
    # Handle two_day_rally_+XX%
    if signal_name.startswith("two_day_rally_"):
        return "two_day_rally"
    
    # Handle high_vol_X.Xx or high_vol_red
    if signal_name.startswith("high_vol_"):
        if "red" in signal_name:
            return "high_rvol_red_day"
        return "high_vol_run"
    
    # Handle below_prior_low variants
    if signal_name.startswith("below_prior"):
        return "below_prior_low"
    
    return signal_name


def _extract_pump_magnitude(signal_name: str) -> float:
    """
    Extract the pump magnitude percentage from dynamic signal names.
    
    Examples:
        pump_reversal_+23% → 23.0
        pump_+20% → 20.0
        pump_reversal_-14% → 14.0 (absolute value)
    """
    import re
    match = re.search(r'[+\-](\d+\.?\d*)', signal_name)
    if match:
        return float(match.group(1))
    return 0.0


def get_signal_weight(signal_name: str) -> float:
    """
    Get the effective weight for a signal (with PRE/POST priority applied).
    
    FEB 11 FIX: Now handles dynamic signal names (pump_reversal_+23%)
    and applies magnitude-based weight scaling for pump reversal signals.
    
    Args:
        signal_name: Name of the signal
        
    Returns:
        Effective weight (base_weight * priority_multiplier)
    """
    base_name = _normalize_signal_name(signal_name)
    
    if base_name in SIGNAL_DEFINITIONS:
        defn = SIGNAL_DEFINITIONS[base_name]
        weight = defn.effective_weight
        
        # MAGNITUDE SCALING for pump reversal signals
        # A 25%+ pump is far more predictive than a 5% pump
        if base_name == "pump_reversal":
            magnitude = _extract_pump_magnitude(signal_name)
            if magnitude >= 25:
                weight *= 1.30   # 30% bonus for massive pumps (25%+)
            elif magnitude >= 15:
                weight *= 1.15   # 15% bonus for strong pumps (15%+)
            elif magnitude >= 10:
                weight *= 1.0    # Normal weight for decent pumps
            elif magnitude > 0:
                weight *= 0.75   # Small pump — less predictive
        
        # Magnitude scaling for two_day_rally
        if base_name == "two_day_rally":
            magnitude = _extract_pump_magnitude(signal_name)
            if magnitude >= 15:
                weight *= 1.20
            elif magnitude >= 10:
                weight *= 1.10
        
        return weight
    
    return 0.05  # Default weight for unknown signals


def get_signal_timing(signal_name: str) -> SignalTiming:
    """
    Get the timing classification for a signal.
    
    FEB 11 FIX: Now handles dynamic signal names.
    
    Args:
        signal_name: Name of the signal
        
    Returns:
        SignalTiming enum value
    """
    base_name = _normalize_signal_name(signal_name)
    if base_name in SIGNAL_DEFINITIONS:
        return SIGNAL_DEFINITIONS[base_name].timing
    return SignalTiming.NEUTRAL


def classify_signals(signals: Dict[str, bool]) -> Tuple[List[str], List[str], List[str]]:
    """
    Classify active signals into PRE, POST, and NEUTRAL categories.
    
    FEB 11 FIX: Uses normalized signal names for classification.
    
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
