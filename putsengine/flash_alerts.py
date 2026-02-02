"""
Flash Alerts - Rapid IPI Surge Detection

ARCHITECT-4 VALIDATED (Feb 1, 2026):
=====================================
This is about ATTENTION, not trading.

CORRECT TRIGGER:
If IPI increases by ≥ +0.30 within 60 minutes
AND footprints come from ≥ 2 categories

Then:
- 🚨 "FLASH ALERT"
- Dashboard notification
- NO auto-trade

This mimics how institutional desks escalate urgency.

WHY IT MATTERS:
Rapid pressure accumulation suggests institutional consensus is forming.
This is a "drop everything and look" signal.
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path
import pytz
from loguru import logger


EST = pytz.timezone("US/Eastern")


@dataclass
class FlashAlert:
    """A flash alert for rapid IPI surge."""
    symbol: str
    current_ipi: float
    previous_ipi: float
    ipi_change: float
    minutes_elapsed: int
    unique_footprints: int
    footprint_types: List[str]
    timestamp: datetime
    recommendation: str = ""
    
    @property
    def is_critical(self) -> bool:
        """True if this is a critical flash alert."""
        return self.ipi_change >= 0.40 or (self.ipi_change >= 0.30 and self.unique_footprints >= 3)


# File paths
FOOTPRINT_HISTORY_FILE = Path(__file__).parent.parent / "footprint_history.json"
IPI_HISTORY_FILE = Path(__file__).parent.parent / "ipi_history.json"
FLASH_ALERTS_FILE = Path(__file__).parent.parent / "flash_alerts.json"

# Thresholds
MIN_IPI_CHANGE = 0.30          # Minimum IPI change to trigger alert
MIN_FOOTPRINT_TYPES = 2        # Minimum unique footprint categories
MAX_MINUTES_WINDOW = 60        # Time window for surge detection


def load_ipi_history() -> Dict[str, List[Dict]]:
    """Load IPI history for surge detection."""
    if not IPI_HISTORY_FILE.exists():
        return {}
    try:
        with open(IPI_HISTORY_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load IPI history: {e}")
        return {}


def save_ipi_history(history: Dict[str, List[Dict]]):
    """Save IPI history."""
    try:
        # Prune old entries (keep last 24 hours)
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        for symbol in list(history.keys()):
            history[symbol] = [
                h for h in history[symbol]
                if h.get("timestamp", "") > cutoff
            ]
            if not history[symbol]:
                del history[symbol]
        
        with open(IPI_HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2, default=str)
    except Exception as e:
        logger.warning(f"Could not save IPI history: {e}")


def record_ipi_snapshot(symbol: str, ipi: float, unique_footprints: int, footprint_types: List[str]):
    """
    Record an IPI snapshot for surge detection.
    
    Call this after each EWS scan to track IPI changes over time.
    """
    history = load_ipi_history()
    
    if symbol not in history:
        history[symbol] = []
    
    history[symbol].append({
        "timestamp": datetime.now().isoformat(),
        "ipi": ipi,
        "unique_footprints": unique_footprints,
        "footprint_types": footprint_types,
    })
    
    # Keep only last 24 entries per symbol
    history[symbol] = history[symbol][-24:]
    
    save_ipi_history(history)


def detect_flash_alerts() -> List[FlashAlert]:
    """
    Detect flash alerts by comparing current IPI to recent history.
    
    Returns list of FlashAlert for symbols with rapid IPI increases.
    """
    history = load_ipi_history()
    alerts = []
    
    now = datetime.now()
    
    for symbol, snapshots in history.items():
        if len(snapshots) < 2:
            continue
        
        # Get most recent snapshot
        current = snapshots[-1]
        current_ts = datetime.fromisoformat(current["timestamp"])
        current_ipi = current.get("ipi", 0)
        
        # Find snapshot from ~60 minutes ago
        comparison = None
        for snap in reversed(snapshots[:-1]):
            snap_ts = datetime.fromisoformat(snap["timestamp"])
            minutes_ago = (current_ts - snap_ts).total_seconds() / 60
            
            if 45 <= minutes_ago <= 90:  # Allow some flexibility
                comparison = snap
                break
        
        if not comparison:
            continue
        
        # Calculate IPI change
        prev_ipi = comparison.get("ipi", 0)
        ipi_change = current_ipi - prev_ipi
        
        # Get time elapsed
        comp_ts = datetime.fromisoformat(comparison["timestamp"])
        minutes_elapsed = int((current_ts - comp_ts).total_seconds() / 60)
        
        # Check if alert criteria met
        unique_footprints = current.get("unique_footprints", 0)
        footprint_types = current.get("footprint_types", [])
        
        if ipi_change >= MIN_IPI_CHANGE and unique_footprints >= MIN_FOOTPRINT_TYPES:
            # Generate recommendation
            if ipi_change >= 0.40:
                recommendation = (
                    f"🚨 CRITICAL FLASH ALERT: {symbol} IPI surged {ipi_change:+.2f} in {minutes_elapsed} min. "
                    f"INSTITUTIONAL CONSENSUS FORMING. Drop everything and analyze immediately."
                )
            else:
                recommendation = (
                    f"⚡ FLASH ALERT: {symbol} IPI surged {ipi_change:+.2f} in {minutes_elapsed} min. "
                    f"Rapid pressure accumulation detected. Review for potential entry timing."
                )
            
            alert = FlashAlert(
                symbol=symbol,
                current_ipi=current_ipi,
                previous_ipi=prev_ipi,
                ipi_change=ipi_change,
                minutes_elapsed=minutes_elapsed,
                unique_footprints=unique_footprints,
                footprint_types=footprint_types,
                timestamp=now,
                recommendation=recommendation,
            )
            alerts.append(alert)
            
            logger.warning(
                f"FLASH ALERT: {symbol} IPI {prev_ipi:.2f} → {current_ipi:.2f} "
                f"({ipi_change:+.2f} in {minutes_elapsed} min)"
            )
    
    # Sort by IPI change (largest first)
    alerts.sort(key=lambda a: a.ipi_change, reverse=True)
    
    # Save flash alerts
    if alerts:
        save_flash_alerts(alerts)
    
    return alerts


def save_flash_alerts(alerts: List[FlashAlert]):
    """Save flash alerts to file."""
    try:
        data = {
            "timestamp": datetime.now().isoformat(),
            "alerts_count": len(alerts),
            "critical_count": sum(1 for a in alerts if a.is_critical),
            "alerts": [
                {
                    "symbol": a.symbol,
                    "current_ipi": a.current_ipi,
                    "previous_ipi": a.previous_ipi,
                    "ipi_change": a.ipi_change,
                    "minutes_elapsed": a.minutes_elapsed,
                    "unique_footprints": a.unique_footprints,
                    "footprint_types": a.footprint_types,
                    "is_critical": a.is_critical,
                    "recommendation": a.recommendation,
                }
                for a in alerts
            ]
        }
        
        with open(FLASH_ALERTS_FILE, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        logger.info(f"Flash alerts saved to {FLASH_ALERTS_FILE}")
    except Exception as e:
        logger.warning(f"Could not save flash alerts: {e}")


def get_flash_alerts() -> Dict:
    """
    Get current flash alerts.
    
    Returns:
        Dict with alert data
    """
    if not FLASH_ALERTS_FILE.exists():
        return {"alerts": [], "alerts_count": 0, "critical_count": 0}
    
    try:
        with open(FLASH_ALERTS_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {"alerts": [], "alerts_count": 0, "critical_count": 0}


def check_for_flash_alerts_in_ews_scan(ews_results: Dict[str, any]):
    """
    Check for flash alerts after an EWS scan.
    
    Call this at the end of each EWS scan to record IPI history
    and detect surges.
    
    Args:
        ews_results: Dict of symbol -> InstitutionalPressure from EWS scan
    """
    # Record current IPI snapshots
    for symbol, pressure in ews_results.items():
        if hasattr(pressure, 'ipi'):
            record_ipi_snapshot(
                symbol=symbol,
                ipi=pressure.ipi,
                unique_footprints=pressure.unique_footprints if hasattr(pressure, 'unique_footprints') else 0,
                footprint_types=[f.footprint_type.value for f in pressure.footprints[:10]] if hasattr(pressure, 'footprints') else []
            )
    
    # Detect flash alerts
    alerts = detect_flash_alerts()
    
    if alerts:
        logger.warning(f"⚡ {len(alerts)} FLASH ALERTS detected!")
        for alert in alerts[:3]:  # Log top 3
            logger.warning(f"  {alert.recommendation}")
    
    return alerts
