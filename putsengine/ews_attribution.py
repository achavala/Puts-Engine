"""
EWS Attribution Logger - Observation & Measurement Phase

ARCHITECT-4 MANDATE (Feb 1, 2026):
===================================
For the next 20-30 Early Warning events, log:
- EWS level (WATCH / PREPARE / ACT)
- Zero-Hour confirmation (VACUUM_OPEN / NO_CONFIRMATION)
- Lead time (hours between EWS and price move)
- Engine confirmation
- Structure used
- Outcome (win/loss)
- Max return

This is how we answer:
1. How often does ACT → VACUUM_OPEN convert?
2. Optimal lead time window (12h vs 24h vs 48h)
3. Long Put vs Bear Call Spread performance by IV Rank

The NEXT layer of alpha lives here.

DO NOT:
- Lower IPI thresholds
- Add more footprints
- Auto-trade from EWS
- Introduce ML at this stage

We're past build phase. We're in MEASURE & REFINE phase.
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from pathlib import Path
from enum import Enum
import pytz
from loguru import logger


EST = pytz.timezone("US/Eastern")


class EWSLevel(Enum):
    """EWS pressure levels."""
    WATCH = "watch"
    PREPARE = "prepare"
    ACT = "act"


class ZeroHourVerdict(Enum):
    """Zero-hour confirmation verdicts."""
    VACUUM_OPEN = "vacuum_open"
    SPREAD_COLLAPSE = "spread_collapse"
    PRESSURE_ABSORBED = "pressure_absorbed"
    NO_CONFIRMATION = "no_confirmation"
    NOT_CHECKED = "not_checked"


class TradeOutcome(Enum):
    """Trade outcomes."""
    WIN = "win"
    LOSS = "loss"
    BREAK_EVEN = "break_even"
    OPEN = "open"
    NOT_TRADED = "not_traded"


@dataclass
class EWSEvent:
    """
    A single EWS event for attribution tracking.
    
    This captures the full lifecycle:
    EWS Detection → Zero-Hour → Engine → Structure → Outcome
    """
    # Identification
    event_id: str
    symbol: str
    
    # EWS Detection (Day -1 to -3)
    ews_level: str  # "watch", "prepare", "act"
    ews_ipi: float
    ews_timestamp: str
    ews_footprints: List[str] = field(default_factory=list)
    
    # Zero-Hour Confirmation (Day 0)
    zero_hour_verdict: str = "not_checked"  # "vacuum_open", "no_confirmation", etc.
    zero_hour_gap_pct: Optional[float] = None
    zero_hour_timestamp: Optional[str] = None
    
    # Engine Confirmation
    engines_confirmed: List[str] = field(default_factory=list)  # ["distribution", "gamma", etc.]
    engine_score: Optional[float] = None
    
    # Structure Selection (from Vega Gate)
    structure: str = ""  # "long_put", "bear_call_spread", "not_traded"
    iv_rank: Optional[float] = None
    ews_vega_override: bool = False  # True if EWS→Vega coupling was applied
    
    # Timing
    lead_time_hours: Optional[float] = None  # Hours from EWS to price move
    
    # Outcome
    outcome: str = "open"  # "win", "loss", "break_even", "not_traded"
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    max_return: Optional[float] = None  # e.g., 3.4 = 3.4x
    actual_return: Optional[float] = None
    
    # Notes
    notes: str = ""
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


# File path
EWS_ATTRIBUTION_FILE = Path(__file__).parent.parent / "ews_attribution.json"


def load_attribution_log() -> Dict[str, Any]:
    """Load attribution log from file."""
    if not EWS_ATTRIBUTION_FILE.exists():
        return {
            "version": "1.0",
            "created": datetime.now().isoformat(),
            "events": [],
            "summary": {
                "total_events": 0,
                "act_events": 0,
                "vacuum_open_confirmations": 0,
                "trades_taken": 0,
                "wins": 0,
                "losses": 0,
            }
        }
    
    try:
        with open(EWS_ATTRIBUTION_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load attribution log: {e}")
        return {"events": [], "summary": {}}


def save_attribution_log(data: Dict[str, Any]):
    """Save attribution log to file."""
    try:
        data["last_updated"] = datetime.now().isoformat()
        with open(EWS_ATTRIBUTION_FILE, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"Attribution log saved to {EWS_ATTRIBUTION_FILE}")
    except Exception as e:
        logger.warning(f"Could not save attribution log: {e}")


def log_ews_detection(
    symbol: str,
    ews_level: str,
    ews_ipi: float,
    footprints: List[str]
) -> str:
    """
    Log a new EWS detection event.
    
    Call this when EWS detects significant pressure (IPI ≥ 0.30).
    
    Args:
        symbol: Stock ticker
        ews_level: "watch", "prepare", or "act"
        ews_ipi: Institutional Pressure Index
        footprints: List of footprint types detected
        
    Returns:
        event_id for later updates
    """
    data = load_attribution_log()
    
    # Generate event ID
    event_id = f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    event = EWSEvent(
        event_id=event_id,
        symbol=symbol,
        ews_level=ews_level,
        ews_ipi=ews_ipi,
        ews_timestamp=datetime.now().isoformat(),
        ews_footprints=footprints,
    )
    
    data["events"].append(event.to_dict())
    
    # Update summary
    data["summary"]["total_events"] = len(data["events"])
    if ews_level == "act":
        data["summary"]["act_events"] = data["summary"].get("act_events", 0) + 1
    
    save_attribution_log(data)
    
    logger.info(f"EWS Event logged: {event_id} | {symbol} | {ews_level.upper()} | IPI={ews_ipi:.2f}")
    
    return event_id


def update_zero_hour(
    event_id: str,
    verdict: str,
    gap_pct: Optional[float] = None
):
    """
    Update an EWS event with Zero-Hour confirmation.
    
    Call this after Zero-Hour scan runs.
    """
    data = load_attribution_log()
    
    for event in data["events"]:
        if event["event_id"] == event_id:
            event["zero_hour_verdict"] = verdict
            event["zero_hour_gap_pct"] = gap_pct
            event["zero_hour_timestamp"] = datetime.now().isoformat()
            
            if verdict == "vacuum_open":
                data["summary"]["vacuum_open_confirmations"] = \
                    data["summary"].get("vacuum_open_confirmations", 0) + 1
            
            logger.info(f"Zero-Hour updated: {event_id} | {verdict.upper()}")
            break
    
    save_attribution_log(data)


def update_engine_confirmation(
    event_id: str,
    engines: List[str],
    score: float
):
    """
    Update an EWS event with engine confirmation.
    
    Call this after main engine scan runs.
    """
    data = load_attribution_log()
    
    for event in data["events"]:
        if event["event_id"] == event_id:
            event["engines_confirmed"] = engines
            event["engine_score"] = score
            logger.info(f"Engine confirmation updated: {event_id} | {engines}")
            break
    
    save_attribution_log(data)


def update_structure(
    event_id: str,
    structure: str,
    iv_rank: float,
    ews_override: bool = False
):
    """
    Update an EWS event with structure selection.
    
    Call this after Vega Gate runs.
    """
    data = load_attribution_log()
    
    for event in data["events"]:
        if event["event_id"] == event_id:
            event["structure"] = structure
            event["iv_rank"] = iv_rank
            event["ews_vega_override"] = ews_override
            logger.info(f"Structure updated: {event_id} | {structure} | IV={iv_rank:.0f}%")
            break
    
    save_attribution_log(data)


def update_trade_entry(
    event_id: str,
    entry_price: float,
    lead_time_hours: float
):
    """
    Update an EWS event when trade is entered.
    """
    data = load_attribution_log()
    
    for event in data["events"]:
        if event["event_id"] == event_id:
            event["entry_price"] = entry_price
            event["lead_time_hours"] = lead_time_hours
            event["outcome"] = "open"
            
            data["summary"]["trades_taken"] = data["summary"].get("trades_taken", 0) + 1
            logger.info(f"Trade entry logged: {event_id} | ${entry_price:.2f} | Lead={lead_time_hours:.1f}h")
            break
    
    save_attribution_log(data)


def update_trade_exit(
    event_id: str,
    exit_price: float,
    max_return: float,
    outcome: str,  # "win", "loss", "break_even"
    notes: str = ""
):
    """
    Update an EWS event when trade is exited.
    
    This completes the attribution cycle.
    """
    data = load_attribution_log()
    
    for event in data["events"]:
        if event["event_id"] == event_id:
            event["exit_price"] = exit_price
            event["max_return"] = max_return
            event["outcome"] = outcome
            event["notes"] = notes
            
            entry = event.get("entry_price", 0)
            if entry > 0:
                event["actual_return"] = exit_price / entry
            
            if outcome == "win":
                data["summary"]["wins"] = data["summary"].get("wins", 0) + 1
            elif outcome == "loss":
                data["summary"]["losses"] = data["summary"].get("losses", 0) + 1
            
            logger.info(
                f"Trade exit logged: {event_id} | {outcome.upper()} | "
                f"Max={max_return:.1f}x | Actual={event.get('actual_return', 0):.1f}x"
            )
            break
    
    save_attribution_log(data)


def get_attribution_report() -> Dict:
    """
    Generate attribution report for analysis.
    
    Returns insights on:
    1. ACT → VACUUM_OPEN conversion rate
    2. Optimal lead time window
    3. Structure performance by IV Rank
    """
    data = load_attribution_log()
    events = data.get("events", [])
    
    if not events:
        return {"message": "No events logged yet. Need 20-30 events for meaningful analysis."}
    
    # Calculate metrics
    total = len(events)
    act_events = [e for e in events if e.get("ews_level") == "act"]
    vacuum_opens = [e for e in events if e.get("zero_hour_verdict") == "vacuum_open"]
    
    # ACT → VACUUM_OPEN conversion
    act_to_vacuum = [e for e in act_events if e.get("zero_hour_verdict") == "vacuum_open"]
    act_vacuum_rate = len(act_to_vacuum) / len(act_events) if act_events else 0
    
    # Trade outcomes
    trades = [e for e in events if e.get("outcome") in ["win", "loss", "break_even"]]
    wins = [e for e in trades if e.get("outcome") == "win"]
    win_rate = len(wins) / len(trades) if trades else 0
    
    # Lead time analysis
    lead_times = [e.get("lead_time_hours") for e in events if e.get("lead_time_hours")]
    avg_lead_time = sum(lead_times) / len(lead_times) if lead_times else 0
    
    # Structure analysis
    long_puts = [e for e in trades if "long_put" in e.get("structure", "")]
    spreads = [e for e in trades if "spread" in e.get("structure", "")]
    
    long_put_wins = [e for e in long_puts if e.get("outcome") == "win"]
    spread_wins = [e for e in spreads if e.get("outcome") == "win"]
    
    long_put_rate = len(long_put_wins) / len(long_puts) if long_puts else 0
    spread_rate = len(spread_wins) / len(spreads) if spreads else 0
    
    # Average returns
    long_put_returns = [e.get("actual_return", 1) for e in long_puts if e.get("actual_return")]
    spread_returns = [e.get("actual_return", 1) for e in spreads if e.get("actual_return")]
    
    avg_long_put_return = sum(long_put_returns) / len(long_put_returns) if long_put_returns else 0
    avg_spread_return = sum(spread_returns) / len(spread_returns) if spread_returns else 0
    
    return {
        "total_events": total,
        "progress": f"{total}/30 events (target: 30)",
        "ready_for_scaling": total >= 30 and win_rate >= 0.5,
        
        "conversion_metrics": {
            "act_events": len(act_events),
            "act_to_vacuum_open": len(act_to_vacuum),
            "act_to_vacuum_rate": f"{act_vacuum_rate:.1%}",
        },
        
        "trade_metrics": {
            "trades_taken": len(trades),
            "wins": len(wins),
            "win_rate": f"{win_rate:.1%}",
        },
        
        "timing_metrics": {
            "avg_lead_time_hours": round(avg_lead_time, 1),
            "recommendation": (
                "12-24h" if avg_lead_time < 24 else
                "24-48h" if avg_lead_time < 48 else
                ">48h"
            ),
        },
        
        "structure_metrics": {
            "long_put_trades": len(long_puts),
            "long_put_win_rate": f"{long_put_rate:.1%}",
            "long_put_avg_return": f"{avg_long_put_return:.1f}x",
            "spread_trades": len(spreads),
            "spread_win_rate": f"{spread_rate:.1%}",
            "spread_avg_return": f"{avg_spread_return:.1f}x",
        },
        
        "summary": data.get("summary", {}),
    }


def print_attribution_summary():
    """Print attribution summary to console."""
    report = get_attribution_report()
    
    print("=" * 60)
    print("EWS ATTRIBUTION REPORT")
    print("=" * 60)
    print(f"Progress: {report.get('progress', 'N/A')}")
    print(f"Ready for scaling: {'✅ YES' if report.get('ready_for_scaling') else '❌ NO'}")
    print()
    print("CONVERSION METRICS:")
    conv = report.get("conversion_metrics", {})
    print(f"  ACT events: {conv.get('act_events', 0)}")
    print(f"  ACT → VACUUM_OPEN: {conv.get('act_to_vacuum_open', 0)} ({conv.get('act_to_vacuum_rate', '0%')})")
    print()
    print("TRADE METRICS:")
    trade = report.get("trade_metrics", {})
    print(f"  Trades taken: {trade.get('trades_taken', 0)}")
    print(f"  Wins: {trade.get('wins', 0)} ({trade.get('win_rate', '0%')})")
    print()
    print("STRUCTURE PERFORMANCE:")
    struct = report.get("structure_metrics", {})
    print(f"  Long Put: {struct.get('long_put_trades', 0)} trades, {struct.get('long_put_win_rate', '0%')} win rate, {struct.get('long_put_avg_return', '0x')} avg return")
    print(f"  Spread:   {struct.get('spread_trades', 0)} trades, {struct.get('spread_win_rate', '0%')} win rate, {struct.get('spread_avg_return', '0x')} avg return")
    print()
    print("TIMING:")
    timing = report.get("timing_metrics", {})
    print(f"  Avg lead time: {timing.get('avg_lead_time_hours', 0)} hours")
    print(f"  Optimal window: {timing.get('recommendation', 'N/A')}")
    print("=" * 60)


# CLI interface
if __name__ == "__main__":
    print_attribution_summary()
