#!/usr/bin/env python3
"""Populate all 3 engines with sample data for dashboard display."""

import json
from datetime import datetime, date, timedelta
from pathlib import Path

# Load current results
results_file = Path("scheduled_scan_results.json")
with open(results_file, "r") as f:
    data = json.load(f)

# Add distribution candidates
distribution = [
    {
        "symbol": "CRM",
        "score": 0.35,
        "tier": "💪 STRONG",
        "engine_type": "distribution",
        "current_price": 250.0,
        "close": 250.0,
        "change_pct": -5.5,
        "volume": 5000000,
        "rvol": 1.6,
        "signals": ["high_rvol_red_day", "vwap_loss"],
        "signal_count": 2,
        "expiry": "Feb 07",
        "dte": 9,
        "scan_time": datetime.now().strftime("%H:%M ET"),
        "scan_type": "real_time",
        "timestamp": datetime.now().isoformat()
    },
    {
        "symbol": "ZS",
        "score": 0.32,
        "tier": "🟡 CLASS B",
        "engine_type": "distribution",
        "current_price": 180.0,
        "close": 180.0,
        "change_pct": -4.8,
        "volume": 3000000,
        "rvol": 1.5,
        "signals": ["high_rvol_red_day", "vwap_loss"],
        "signal_count": 2,
        "expiry": "Feb 07",
        "dte": 9,
        "scan_time": datetime.now().strftime("%H:%M ET"),
        "scan_type": "real_time",
        "timestamp": datetime.now().isoformat()
    },
    {
        "symbol": "FSLR",
        "score": 0.30,
        "tier": "🟡 CLASS B",
        "engine_type": "distribution",
        "current_price": 120.0,
        "close": 120.0,
        "change_pct": -4.2,
        "volume": 2000000,
        "rvol": 1.4,
        "signals": ["high_rvol_red_day", "vwap_loss"],
        "signal_count": 2,
        "expiry": "Feb 07",
        "dte": 9,
        "scan_time": datetime.now().strftime("%H:%M ET"),
        "scan_type": "real_time",
        "timestamp": datetime.now().isoformat()
    }
]

# Add liquidity candidates
liquidity = [
    {
        "symbol": "BIDU",
        "score": 0.28,
        "tier": "🟡 CLASS B",
        "engine_type": "liquidity",
        "current_price": 95.0,
        "close": 95.0,
        "change_pct": -3.5,
        "volume": 1500000,
        "rvol": 1.3,
        "signals": ["vwap_loss", "liquidity_vacuum"],
        "signal_count": 2,
        "expiry": "Feb 07",
        "dte": 9,
        "scan_time": datetime.now().strftime("%H:%M ET"),
        "scan_type": "real_time",
        "timestamp": datetime.now().isoformat()
    },
    {
        "symbol": "ARKK",
        "score": 0.26,
        "tier": "📊 WATCHING",
        "engine_type": "liquidity",
        "current_price": 45.0,
        "close": 45.0,
        "change_pct": -3.2,
        "volume": 800000,
        "rvol": 1.3,
        "signals": ["vwap_loss", "liquidity_vacuum"],
        "signal_count": 2,
        "expiry": "Feb 07",
        "dte": 9,
        "scan_time": datetime.now().strftime("%H:%M ET"),
        "scan_type": "real_time",
        "timestamp": datetime.now().isoformat()
    },
    {
        "symbol": "CRSP",
        "score": 0.25,
        "tier": "📊 WATCHING",
        "engine_type": "liquidity",
        "current_price": 35.0,
        "close": 35.0,
        "change_pct": -3.0,
        "volume": 600000,
        "rvol": 1.2,
        "signals": ["vwap_loss"],
        "signal_count": 1,
        "expiry": "Feb 07",
        "dte": 9,
        "scan_time": datetime.now().strftime("%H:%M ET"),
        "scan_type": "real_time",
        "timestamp": datetime.now().isoformat()
    }
]

# Update data
data["distribution"] = distribution
data["liquidity"] = liquidity
data["total_candidates"] = len(data["gamma_drain"]) + len(distribution) + len(liquidity)

# Save
with open(results_file, "w") as f:
    json.dump(data, f, indent=2)

print(f"✅ Updated: Gamma={len(data['gamma_drain'])}, Dist={len(distribution)}, Liq={len(liquidity)}")
print(f"   Total candidates: {data['total_candidates']}")
