"""
PutsEngine Scan History Manager

Stores and retrieves scan history for 48-hour frequency analysis.
Tracks which symbols appear across multiple engines over time.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict
import pytz
from loguru import logger

# History file path
SCAN_HISTORY_FILE = Path(__file__).parent.parent / "scan_history.json"
MAX_HISTORY_HOURS = 48  # Keep last 48 hours of data


def load_scan_history() -> Dict:
    """Load scan history from file."""
    if not SCAN_HISTORY_FILE.exists():
        return {"scans": [], "last_cleanup": None}
    
    try:
        with open(SCAN_HISTORY_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading scan history: {e}")
        return {"scans": [], "last_cleanup": None}


def save_scan_history(history: Dict):
    """Save scan history to file."""
    try:
        with open(SCAN_HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Error saving scan history: {e}")


def cleanup_old_scans(history: Dict) -> Dict:
    """Remove scans older than 48 hours."""
    est = pytz.timezone('US/Eastern')
    cutoff = datetime.now(est) - timedelta(hours=MAX_HISTORY_HOURS)
    
    valid_scans = []
    for scan in history.get("scans", []):
        try:
            scan_time = datetime.fromisoformat(scan.get("timestamp", ""))
            if scan_time.tzinfo is None:
                scan_time = est.localize(scan_time)
            
            if scan_time > cutoff:
                valid_scans.append(scan)
        except:
            pass  # Skip invalid entries
    
    history["scans"] = valid_scans
    history["last_cleanup"] = datetime.now(est).isoformat()
    return history


def add_scan_to_history(scan_results: Dict):
    """
    Add a new scan to history.
    
    Args:
        scan_results: Results from a scan containing gamma_drain, distribution, liquidity
    """
    history = load_scan_history()
    
    # Cleanup old scans
    history = cleanup_old_scans(history)
    
    est = pytz.timezone('US/Eastern')
    timestamp = scan_results.get("last_scan", datetime.now(est).isoformat())
    
    # Create scan entry
    scan_entry = {
        "timestamp": timestamp,
        "gamma_drain": [
            {"symbol": c.get("symbol"), "score": c.get("score", 0), "signals": c.get("signals", [])}
            for c in scan_results.get("gamma_drain", [])
            if c.get("score", 0) > 0
        ],
        "distribution": [
            {"symbol": c.get("symbol"), "score": c.get("score", 0), "signals": c.get("signals", [])}
            for c in scan_results.get("distribution", [])
            if c.get("score", 0) > 0
        ],
        "liquidity": [
            {"symbol": c.get("symbol"), "score": c.get("score", 0), "signals": c.get("signals", [])}
            for c in scan_results.get("liquidity", [])
            if c.get("score", 0) > 0
        ],
        "market_regime": scan_results.get("market_regime", "unknown")
    }
    
    history["scans"].append(scan_entry)
    save_scan_history(history)
    
    logger.info(f"Added scan to history. Total scans: {len(history['scans'])}")


def get_48hour_frequency_analysis() -> Dict:
    """
    Analyze scan history from last 48 hours.
    
    Returns:
        Dict with frequency analysis data including:
        - symbol_stats: Stats per symbol (appearances, engines, scores)
        - multi_engine_symbols: Symbols appearing in 2+ engines
        - top_symbols: Top symbols by total appearances
        - engine_counts: Count per engine
    """
    history = load_scan_history()
    history = cleanup_old_scans(history)
    
    # Track appearances per symbol per engine
    symbol_data = defaultdict(lambda: {
        "gamma_drain": {"count": 0, "scores": [], "signals": set()},
        "distribution": {"count": 0, "scores": [], "signals": set()},
        "liquidity": {"count": 0, "scores": [], "signals": set()},
        "total_appearances": 0,
        "first_seen": None,
        "last_seen": None
    })
    
    total_scans = len(history.get("scans", []))
    
    for scan in history.get("scans", []):
        timestamp = scan.get("timestamp")
        
        for engine in ["gamma_drain", "distribution", "liquidity"]:
            for candidate in scan.get(engine, []):
                symbol = candidate.get("symbol")
                if not symbol:
                    continue
                
                data = symbol_data[symbol]
                data[engine]["count"] += 1
                data[engine]["scores"].append(candidate.get("score", 0))
                data[engine]["signals"].update(candidate.get("signals", []))
                data["total_appearances"] += 1
                
                # Track first/last seen
                if data["first_seen"] is None:
                    data["first_seen"] = timestamp
                data["last_seen"] = timestamp
    
    # Calculate stats for each symbol
    symbol_stats = {}
    for symbol, data in symbol_data.items():
        engines_with_signals = sum(
            1 for e in ["gamma_drain", "distribution", "liquidity"]
            if data[e]["count"] > 0
        )
        
        # Calculate average scores per engine
        avg_scores = {}
        for engine in ["gamma_drain", "distribution", "liquidity"]:
            scores = data[engine]["scores"]
            avg_scores[engine] = sum(scores) / len(scores) if scores else 0
        
        symbol_stats[symbol] = {
            "symbol": symbol,
            "total_appearances": data["total_appearances"],
            "engines_count": engines_with_signals,
            "gamma_drain_count": data["gamma_drain"]["count"],
            "distribution_count": data["distribution"]["count"],
            "liquidity_count": data["liquidity"]["count"],
            "gamma_drain_avg_score": avg_scores["gamma_drain"],
            "distribution_avg_score": avg_scores["distribution"],
            "liquidity_avg_score": avg_scores["liquidity"],
            "all_signals": list(
                data["gamma_drain"]["signals"] | 
                data["distribution"]["signals"] | 
                data["liquidity"]["signals"]
            ),
            "first_seen": data["first_seen"],
            "last_seen": data["last_seen"]
        }
    
    # Filter for multi-engine symbols (2+ engines)
    multi_engine_symbols = {
        symbol: stats for symbol, stats in symbol_stats.items()
        if stats["engines_count"] >= 2
    }
    
    # Sort by total appearances
    sorted_symbols = sorted(
        symbol_stats.values(),
        key=lambda x: (x["engines_count"], x["total_appearances"]),
        reverse=True
    )
    
    # Engine totals
    engine_totals = {
        "gamma_drain": sum(s["gamma_drain_count"] for s in symbol_stats.values()),
        "distribution": sum(s["distribution_count"] for s in symbol_stats.values()),
        "liquidity": sum(s["liquidity_count"] for s in symbol_stats.values())
    }
    
    return {
        "total_scans": total_scans,
        "unique_symbols": len(symbol_stats),
        "total_appearances": sum(s["total_appearances"] for s in symbol_stats.values()),
        "multi_engine_count": len(multi_engine_symbols),
        "multi_engine_symbols": sorted(
            multi_engine_symbols.values(),
            key=lambda x: (x["engines_count"], x["total_appearances"]),
            reverse=True
        ),
        "all_symbols": sorted_symbols,
        "top_symbol": sorted_symbols[0] if sorted_symbols else None,
        "engine_totals": engine_totals,
        "history_hours": MAX_HISTORY_HOURS
    }


def initialize_history_from_current_scan():
    """
    Initialize history with current scan results if history is empty.
    Called on dashboard startup.
    """
    history = load_scan_history()
    
    # If history is empty, load from current scheduled_scan_results
    if not history.get("scans"):
        try:
            results_file = Path(__file__).parent.parent / "scheduled_scan_results.json"
            if results_file.exists():
                with open(results_file, 'r') as f:
                    current_results = json.load(f)
                
                add_scan_to_history(current_results)
                logger.info("Initialized scan history from current results")
        except Exception as e:
            logger.error(f"Error initializing history: {e}")
