"""
Capital Ramp Protocol - Professional Risk Deployment

Before increasing size, trades must be tracked:

| Phase            | Trade Count | Size Multiplier |
|------------------|-------------|-----------------|
| First 10 trades  | 0-10        | 0.25× (25%)     |
| Next 20 trades   | 11-30       | 0.50× (50%)     |
| After 30+ trades | 31+         | 1.00× (100%)    |

This is professional risk deployment, not caution.
"""

from dataclasses import dataclass
from typing import Dict, Optional
from loguru import logger

from putsengine.attribution import load_attribution_history


@dataclass
class CapitalPhase:
    """Capital deployment phase."""
    name: str
    min_trades: int
    max_trades: int
    size_multiplier: float
    description: str


# Capital ramp phases
CAPITAL_PHASES = [
    CapitalPhase(
        name="VALIDATION",
        min_trades=0,
        max_trades=10,
        size_multiplier=0.25,
        description="First 10 trades - prove the system works"
    ),
    CapitalPhase(
        name="SCALING",
        min_trades=11,
        max_trades=30,
        size_multiplier=0.50,
        description="Trades 11-30 - build confidence"
    ),
    CapitalPhase(
        name="FULL_DEPLOYMENT",
        min_trades=31,
        max_trades=float('inf'),
        size_multiplier=1.00,
        description="30+ trades - full capital deployment"
    ),
]


def get_current_phase() -> CapitalPhase:
    """
    Get current capital deployment phase based on trade count.
    
    Returns:
        Current CapitalPhase with size multiplier
    """
    history = load_attribution_history()
    completed_trades = len([t for t in history.get("trades", []) if t.get("exit_date")])
    
    for phase in CAPITAL_PHASES:
        if phase.min_trades <= completed_trades <= phase.max_trades:
            return phase
    
    return CAPITAL_PHASES[-1]  # Default to full deployment


def get_capital_multiplier() -> float:
    """
    Get current capital size multiplier.
    
    This is applied ON TOP OF Vega Gate sizing.
    
    Total Size = Base × Vega Gate Multiplier × Capital Ramp Multiplier
    
    Example:
    - Base: 5 contracts
    - Vega Gate (IV 70%): 0.6×
    - Capital Ramp (15 trades): 0.5×
    - Final: 5 × 0.6 × 0.5 = 1.5 contracts → round to 2
    """
    return get_current_phase().size_multiplier


def get_ramp_status() -> Dict:
    """
    Get complete capital ramp status.
    
    Returns:
        Dict with phase info, trade counts, and recommendations
    """
    history = load_attribution_history()
    trades = history.get("trades", [])
    completed = [t for t in trades if t.get("exit_date")]
    open_trades = [t for t in trades if not t.get("exit_date")]
    
    current_phase = get_current_phase()
    
    # Calculate next phase threshold
    next_phase = None
    trades_to_next = 0
    for phase in CAPITAL_PHASES:
        if phase.min_trades > len(completed):
            next_phase = phase
            trades_to_next = phase.min_trades - len(completed)
            break
    
    # Win rate for quality gate
    wins = len([t for t in completed if t.get("outcome") in ["win", "big_win"]])
    win_rate = (wins / len(completed) * 100) if completed else 0
    
    # Quality gate: Don't advance phase if win rate < 40%
    quality_gate_passed = win_rate >= 40 or len(completed) < 5
    
    return {
        "current_phase": current_phase.name,
        "size_multiplier": current_phase.size_multiplier,
        "description": current_phase.description,
        "completed_trades": len(completed),
        "open_trades": len(open_trades),
        "win_rate": round(win_rate, 1),
        "quality_gate_passed": quality_gate_passed,
        "next_phase": next_phase.name if next_phase else "FULL_DEPLOYMENT",
        "trades_to_next_phase": max(0, trades_to_next),
        "can_advance": quality_gate_passed,
        "recommendation": _get_recommendation(current_phase, len(completed), win_rate)
    }


def _get_recommendation(phase: CapitalPhase, trade_count: int, win_rate: float) -> str:
    """Generate capital deployment recommendation."""
    
    if trade_count == 0:
        return "Start trading at 25% size to validate the system."
    
    if trade_count < 5:
        return f"Continue at {phase.size_multiplier:.0%} size. Need {5 - trade_count} more trades for initial assessment."
    
    if win_rate < 40:
        return f"⚠️ Win rate {win_rate:.0f}% is below 40%. Review trade selection before scaling."
    
    if phase.name == "VALIDATION":
        remaining = 10 - trade_count
        return f"Validation phase: {remaining} trades until 50% size."
    
    if phase.name == "SCALING":
        remaining = 30 - trade_count
        return f"Scaling phase: {remaining} trades until full deployment."
    
    return "✅ Full deployment authorized. Monitor for regime changes."


def calculate_position_size(
    base_contracts: int,
    vega_gate_multiplier: float,
    score: float = 0.65
) -> int:
    """
    Calculate final position size with all multipliers.
    
    Args:
        base_contracts: Maximum position size (e.g., 5)
        vega_gate_multiplier: From Vega Gate (0.3, 0.6, or 1.0)
        score: Conviction score (higher = more size)
    
    Returns:
        Final contract count (minimum 1)
    """
    capital_multiplier = get_capital_multiplier()
    
    # Score-based adjustment (CLASS A gets more)
    score_multiplier = 1.0
    if score >= 0.75:
        score_multiplier = 1.0  # Full
    elif score >= 0.60:
        score_multiplier = 0.8  # CLASS A
    elif score >= 0.45:
        score_multiplier = 0.5  # CLASS B
    else:
        score_multiplier = 0.3  # Monitoring
    
    raw_size = base_contracts * vega_gate_multiplier * capital_multiplier * score_multiplier
    
    # Round to nearest integer, minimum 1
    final_size = max(1, round(raw_size))
    
    logger.info(
        f"Position sizing: {base_contracts} base × "
        f"{vega_gate_multiplier:.1f} vega × "
        f"{capital_multiplier:.2f} ramp × "
        f"{score_multiplier:.1f} score = {final_size} contracts"
    )
    
    return final_size
