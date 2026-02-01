"""
Post-Trade Attribution System - Mandatory for Capital Scaling

PURPOSE: Track outcomes by structure to prove Vega Gate effectiveness.

TRACKS:
- Long Put vs Bear Call Spread win rate
- IV Rank vs realized return correlation
- Structure vs max favorable excursion (MFE)
- Engine convergence vs outcome

Schema per trade:
{
    "symbol": "ASTS",
    "trade_id": "uuid",
    "engine_convergence": 3,
    "iv_rank": 84,
    "structure": "bear_call_spread",
    "entry_score": 0.71,
    "entry_price": 2.45,
    "entry_date": "2026-02-01",
    "exit_price": 3.92,
    "exit_date": "2026-02-05",
    "max_return": "2.1x",
    "realized_return": "1.6x",
    "days_held": 4,
    "pnl_dollars": 147.00,
    "outcome": "win",
    "vega_gate_decision": "bear_call_spread"
}

This is how you PROVE the Vega Gate is doing its job.
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from enum import Enum
from loguru import logger
import statistics


class TradeOutcome(Enum):
    """Trade outcome classification."""
    WIN = "win"           # > 0% return
    LOSS = "loss"         # < 0% return
    BREAKEVEN = "breakeven"  # -5% to +5%
    BIG_WIN = "big_win"   # > 100% return
    BIG_LOSS = "big_loss"  # > -50% loss


class TradeStructure(Enum):
    """Trade structure types."""
    LONG_PUT = "long_put"
    LONG_PUT_REDUCED = "long_put_reduced"
    BEAR_CALL_SPREAD = "bear_call_spread"
    UNKNOWN = "unknown"


@dataclass
class TradeRecord:
    """Complete trade record for attribution analysis."""
    
    # Identification
    trade_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    symbol: str = ""
    
    # Engine & Conviction
    engine_convergence: int = 0  # 1, 2, or 3 engines
    engines_triggered: List[str] = field(default_factory=list)
    entry_score: float = 0.0
    conviction_tier: str = ""  # CLASS A, CLASS B, etc.
    
    # Vega Gate Data
    iv_rank: float = 0.0
    iv_percentile: float = 0.0
    vega_gate_decision: str = ""
    structure: str = "long_put"
    size_multiplier: float = 1.0
    
    # Entry Details
    entry_date: str = ""
    entry_price: float = 0.0
    entry_strike: float = 0.0
    entry_expiry: str = ""
    entry_dte: int = 0
    underlying_price_entry: float = 0.0
    
    # Exit Details
    exit_date: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""  # target_hit, stop_loss, expiry, manual
    underlying_price_exit: float = 0.0
    
    # Performance Metrics
    realized_return_pct: float = 0.0
    max_return_pct: float = 0.0  # MFE - Max Favorable Excursion
    max_drawdown_pct: float = 0.0  # MAE - Max Adverse Excursion
    days_held: int = 0
    pnl_dollars: float = 0.0
    
    # Classification
    outcome: str = ""  # win, loss, breakeven, big_win, big_loss
    
    # Metadata
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    notes: str = ""
    
    def calculate_outcome(self) -> str:
        """Classify trade outcome based on return."""
        if self.realized_return_pct >= 100:
            self.outcome = TradeOutcome.BIG_WIN.value
        elif self.realized_return_pct > 5:
            self.outcome = TradeOutcome.WIN.value
        elif self.realized_return_pct < -50:
            self.outcome = TradeOutcome.BIG_LOSS.value
        elif self.realized_return_pct < -5:
            self.outcome = TradeOutcome.LOSS.value
        else:
            self.outcome = TradeOutcome.BREAKEVEN.value
        return self.outcome
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON storage."""
        return asdict(self)


# ============================================================================
# ATTRIBUTION STORAGE
# ============================================================================

ATTRIBUTION_FILE = Path(__file__).parent.parent.parent / "trade_attribution.json"


def load_attribution_history() -> Dict:
    """Load trade attribution history from file."""
    if not ATTRIBUTION_FILE.exists():
        return {
            "trades": [],
            "summary": {},
            "last_updated": None
        }
    
    try:
        with open(ATTRIBUTION_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading attribution history: {e}")
        return {"trades": [], "summary": {}, "last_updated": None}


def save_attribution_history(history: Dict):
    """Save trade attribution history to file."""
    try:
        history["last_updated"] = datetime.now().isoformat()
        with open(ATTRIBUTION_FILE, 'w') as f:
            json.dump(history, f, indent=2, default=str)
        logger.info(f"Attribution history saved: {len(history['trades'])} trades")
    except Exception as e:
        logger.error(f"Error saving attribution history: {e}")


def record_trade_entry(
    symbol: str,
    entry_price: float,
    entry_strike: float,
    entry_expiry: str,
    entry_dte: int,
    underlying_price: float,
    entry_score: float,
    engine_convergence: int,
    engines_triggered: List[str],
    iv_rank: float,
    vega_gate_decision: str,
    structure: str,
    size_multiplier: float = 1.0,
    conviction_tier: str = ""
) -> str:
    """
    Record a new trade entry.
    
    Returns:
        trade_id for tracking exit
    """
    history = load_attribution_history()
    
    trade = TradeRecord(
        symbol=symbol,
        entry_date=date.today().isoformat(),
        entry_price=entry_price,
        entry_strike=entry_strike,
        entry_expiry=entry_expiry,
        entry_dte=entry_dte,
        underlying_price_entry=underlying_price,
        entry_score=entry_score,
        engine_convergence=engine_convergence,
        engines_triggered=engines_triggered,
        iv_rank=iv_rank,
        vega_gate_decision=vega_gate_decision,
        structure=structure,
        size_multiplier=size_multiplier,
        conviction_tier=conviction_tier
    )
    
    history["trades"].append(trade.to_dict())
    save_attribution_history(history)
    
    logger.info(
        f"Trade entry recorded: {symbol} | "
        f"ID={trade.trade_id} | "
        f"Structure={structure} | "
        f"IV Rank={iv_rank:.0f}% | "
        f"Score={entry_score:.2f}"
    )
    
    return trade.trade_id


def record_trade_exit(
    trade_id: str,
    exit_price: float,
    underlying_price_exit: float,
    exit_reason: str = "manual",
    max_price_seen: Optional[float] = None,
    min_price_seen: Optional[float] = None,
    notes: str = ""
) -> Optional[TradeRecord]:
    """
    Record trade exit and calculate performance.
    
    Args:
        trade_id: ID from entry recording
        exit_price: Exit price
        underlying_price_exit: Underlying stock price at exit
        exit_reason: Reason for exit (target_hit, stop_loss, expiry, manual)
        max_price_seen: Maximum option price during trade (for MFE)
        min_price_seen: Minimum option price during trade (for MAE)
        notes: Additional notes
    
    Returns:
        Updated TradeRecord with performance metrics
    """
    history = load_attribution_history()
    
    # Find the trade
    trade_dict = None
    trade_idx = None
    for i, t in enumerate(history["trades"]):
        if t.get("trade_id") == trade_id:
            trade_dict = t
            trade_idx = i
            break
    
    if trade_dict is None:
        logger.error(f"Trade not found: {trade_id}")
        return None
    
    # Update exit details
    trade_dict["exit_date"] = date.today().isoformat()
    trade_dict["exit_price"] = exit_price
    trade_dict["exit_reason"] = exit_reason
    trade_dict["underlying_price_exit"] = underlying_price_exit
    trade_dict["notes"] = notes
    
    # Calculate performance
    entry_price = trade_dict["entry_price"]
    if entry_price > 0:
        realized_return = ((exit_price - entry_price) / entry_price) * 100
        trade_dict["realized_return_pct"] = round(realized_return, 2)
        
        # Calculate PnL (assuming 1 contract = 100 shares)
        trade_dict["pnl_dollars"] = round((exit_price - entry_price) * 100, 2)
    
    # Calculate MFE/MAE if data provided
    if max_price_seen and entry_price > 0:
        trade_dict["max_return_pct"] = round(
            ((max_price_seen - entry_price) / entry_price) * 100, 2
        )
    
    if min_price_seen and entry_price > 0:
        trade_dict["max_drawdown_pct"] = round(
            ((min_price_seen - entry_price) / entry_price) * 100, 2
        )
    
    # Calculate days held
    try:
        entry_dt = datetime.fromisoformat(trade_dict["entry_date"])
        exit_dt = datetime.fromisoformat(trade_dict["exit_date"])
        trade_dict["days_held"] = (exit_dt - entry_dt).days
    except:
        trade_dict["days_held"] = 0
    
    # Classify outcome
    realized_return = trade_dict.get("realized_return_pct", 0)
    if realized_return >= 100:
        trade_dict["outcome"] = "big_win"
    elif realized_return > 5:
        trade_dict["outcome"] = "win"
    elif realized_return < -50:
        trade_dict["outcome"] = "big_loss"
    elif realized_return < -5:
        trade_dict["outcome"] = "loss"
    else:
        trade_dict["outcome"] = "breakeven"
    
    # Update history
    history["trades"][trade_idx] = trade_dict
    
    # Recalculate summary
    history["summary"] = calculate_attribution_summary(history["trades"])
    
    save_attribution_history(history)
    
    logger.info(
        f"Trade exit recorded: {trade_dict['symbol']} | "
        f"Return={trade_dict['realized_return_pct']:.1f}% | "
        f"Outcome={trade_dict['outcome']} | "
        f"Structure={trade_dict['structure']}"
    )
    
    return trade_dict


# ============================================================================
# ATTRIBUTION ANALYTICS
# ============================================================================

def calculate_attribution_summary(trades: List[Dict]) -> Dict:
    """
    Calculate comprehensive attribution summary.
    
    This is what proves the Vega Gate is working.
    """
    # Filter to completed trades only
    completed = [t for t in trades if t.get("exit_date")]
    
    if not completed:
        return {"total_trades": 0, "message": "No completed trades yet"}
    
    summary = {
        "total_trades": len(completed),
        "total_pnl": sum(t.get("pnl_dollars", 0) for t in completed),
        "avg_return_pct": statistics.mean([t.get("realized_return_pct", 0) for t in completed]),
        "win_rate": len([t for t in completed if t.get("outcome") in ["win", "big_win"]]) / len(completed) * 100,
        
        # By Structure (CRITICAL for Vega Gate validation)
        "by_structure": {},
        
        # By IV Rank (CRITICAL for Vega Gate validation)
        "by_iv_regime": {},
        
        # By Engine Convergence
        "by_convergence": {},
        
        # Time Analysis
        "avg_days_held": statistics.mean([t.get("days_held", 0) for t in completed]),
    }
    
    # =========================================================================
    # BY STRUCTURE ANALYSIS (Vega Gate Validation)
    # =========================================================================
    structures = {}
    for t in completed:
        struct = t.get("structure", "unknown")
        if struct not in structures:
            structures[struct] = []
        structures[struct].append(t)
    
    for struct, struct_trades in structures.items():
        wins = len([t for t in struct_trades if t.get("outcome") in ["win", "big_win"]])
        summary["by_structure"][struct] = {
            "count": len(struct_trades),
            "win_rate": wins / len(struct_trades) * 100 if struct_trades else 0,
            "avg_return_pct": statistics.mean([t.get("realized_return_pct", 0) for t in struct_trades]),
            "total_pnl": sum(t.get("pnl_dollars", 0) for t in struct_trades),
        }
    
    # =========================================================================
    # BY IV REGIME ANALYSIS (Vega Gate Validation)
    # =========================================================================
    iv_regimes = {
        "optimal_0_60": [t for t in completed if t.get("iv_rank", 0) < 60],
        "elevated_60_80": [t for t in completed if 60 <= t.get("iv_rank", 0) <= 80],
        "extreme_80_plus": [t for t in completed if t.get("iv_rank", 0) > 80],
    }
    
    for regime, regime_trades in iv_regimes.items():
        if regime_trades:
            wins = len([t for t in regime_trades if t.get("outcome") in ["win", "big_win"]])
            summary["by_iv_regime"][regime] = {
                "count": len(regime_trades),
                "win_rate": wins / len(regime_trades) * 100,
                "avg_return_pct": statistics.mean([t.get("realized_return_pct", 0) for t in regime_trades]),
                "total_pnl": sum(t.get("pnl_dollars", 0) for t in regime_trades),
                "avg_iv_rank": statistics.mean([t.get("iv_rank", 0) for t in regime_trades]),
            }
    
    # =========================================================================
    # BY ENGINE CONVERGENCE
    # =========================================================================
    for conv in [1, 2, 3]:
        conv_trades = [t for t in completed if t.get("engine_convergence") == conv]
        if conv_trades:
            wins = len([t for t in conv_trades if t.get("outcome") in ["win", "big_win"]])
            summary["by_convergence"][f"{conv}_engines"] = {
                "count": len(conv_trades),
                "win_rate": wins / len(conv_trades) * 100,
                "avg_return_pct": statistics.mean([t.get("realized_return_pct", 0) for t in conv_trades]),
                "total_pnl": sum(t.get("pnl_dollars", 0) for t in conv_trades),
            }
    
    return summary


def get_vega_gate_effectiveness_report() -> str:
    """
    Generate Vega Gate effectiveness report.
    
    This is the key metric for proving the enhancement works.
    """
    history = load_attribution_history()
    trades = [t for t in history.get("trades", []) if t.get("exit_date")]
    
    if not trades:
        return "No completed trades to analyze. Start trading to build attribution data."
    
    summary = calculate_attribution_summary(trades)
    
    report = []
    report.append("=" * 60)
    report.append("VEGA GATE EFFECTIVENESS REPORT")
    report.append("=" * 60)
    report.append("")
    
    # Overall Stats
    report.append(f"Total Completed Trades: {summary['total_trades']}")
    report.append(f"Total P&L: ${summary['total_pnl']:,.2f}")
    report.append(f"Win Rate: {summary['win_rate']:.1f}%")
    report.append(f"Avg Return: {summary['avg_return_pct']:.1f}%")
    report.append(f"Avg Days Held: {summary['avg_days_held']:.1f}")
    report.append("")
    
    # By Structure (THE KEY METRIC)
    report.append("-" * 40)
    report.append("BY STRUCTURE (Vega Gate Validation)")
    report.append("-" * 40)
    for struct, data in summary.get("by_structure", {}).items():
        report.append(f"  {struct.upper()}:")
        report.append(f"    Trades: {data['count']}")
        report.append(f"    Win Rate: {data['win_rate']:.1f}%")
        report.append(f"    Avg Return: {data['avg_return_pct']:.1f}%")
        report.append(f"    Total P&L: ${data['total_pnl']:,.2f}")
    report.append("")
    
    # By IV Regime
    report.append("-" * 40)
    report.append("BY IV REGIME (When Vega Gate Triggered)")
    report.append("-" * 40)
    for regime, data in summary.get("by_iv_regime", {}).items():
        regime_label = regime.replace("_", " ").upper()
        report.append(f"  {regime_label}:")
        report.append(f"    Trades: {data['count']}")
        report.append(f"    Win Rate: {data['win_rate']:.1f}%")
        report.append(f"    Avg Return: {data['avg_return_pct']:.1f}%")
        report.append(f"    Avg IV Rank: {data['avg_iv_rank']:.0f}%")
    report.append("")
    
    # By Engine Convergence
    report.append("-" * 40)
    report.append("BY ENGINE CONVERGENCE")
    report.append("-" * 40)
    for conv, data in summary.get("by_convergence", {}).items():
        report.append(f"  {conv.upper()}:")
        report.append(f"    Trades: {data['count']}")
        report.append(f"    Win Rate: {data['win_rate']:.1f}%")
        report.append(f"    Avg Return: {data['avg_return_pct']:.1f}%")
    
    report.append("")
    report.append("=" * 60)
    
    return "\n".join(report)


def get_open_trades() -> List[Dict]:
    """Get all trades without exit (still open)."""
    history = load_attribution_history()
    return [t for t in history.get("trades", []) if not t.get("exit_date")]


def get_recent_trades(days: int = 30) -> List[Dict]:
    """Get trades from the last N days."""
    history = load_attribution_history()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    return [
        t for t in history.get("trades", [])
        if t.get("entry_date", "") >= cutoff[:10]
    ]
