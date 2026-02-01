"""
PutsEngine Scan History Manager

Stores and retrieves scan history for 48-hour frequency analysis.
Tracks which symbols appear across multiple engines over time.

ARCHITECT-4 ENHANCEMENTS (Feb 2026):
1. Time-Decay Weighting: exp(-λ × hours), λ=0.04, half-life ~17h
2. Engine Diversity Bonus: 0.1 × (num_engines - 1)
3. Trifecta Detection: Alert when all 3 engines converge

Role: Strategic conviction layer ("Supreme Court")
- Does NOT generate new signals
- Aggregates & adjudicates between execution engines
- Used for position sizing, not entry timing
"""

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import pytz
from loguru import logger

# History file path
SCAN_HISTORY_FILE = Path(__file__).parent.parent / "scan_history.json"
MAX_HISTORY_HOURS = 48  # Keep last 48 hours of data

# ============================================================================
# ARCHITECT-4: TIME-DECAY WEIGHTING CONFIGURATION
# ============================================================================
# λ = 0.04 → half-life ≈ 17 hours
# Recent convergence matters more; old noise fades naturally
TIME_DECAY_LAMBDA = 0.04
DECAY_HALF_LIFE_HOURS = math.log(2) / TIME_DECAY_LAMBDA  # ~17.3 hours

# ============================================================================
# ARCHITECT-4: ENGINE DIVERSITY BONUS
# ============================================================================
# diversity_bonus = 0.1 × (num_engines - 1)
# 3 different engines > 3 hits from one engine
ENGINE_DIVERSITY_MULTIPLIER = 0.10


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


def _calculate_time_decay_weight(timestamp_str: str) -> float:
    """
    Calculate time-decay weight for a scan timestamp.
    
    ARCHITECT-4: Exponential decay with λ=0.04, half-life ~17h
    - Recent convergence matters more
    - Old noise fades naturally
    - weight = exp(-λ × hours_since_detection)
    
    Args:
        timestamp_str: ISO format timestamp
    
    Returns:
        Weight between 0 and 1 (1 = now, 0.5 = ~17h ago)
    """
    try:
        est = pytz.timezone('US/Eastern')
        now = datetime.now(est)
        
        scan_time = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        if scan_time.tzinfo is None:
            scan_time = est.localize(scan_time)
        
        hours_ago = (now - scan_time).total_seconds() / 3600
        
        # Exponential decay: weight = exp(-λ × hours)
        weight = math.exp(-TIME_DECAY_LAMBDA * hours_ago)
        
        return max(0.0, min(1.0, weight))  # Clamp to [0, 1]
    except Exception:
        return 0.5  # Default weight if parsing fails


def _calculate_diversity_bonus(engines_count: int) -> float:
    """
    Calculate engine diversity bonus.
    
    ARCHITECT-4: 0.1 × (num_engines - 1)
    - 1 engine: +0.0 (no bonus)
    - 2 engines: +0.1 (convergence)
    - 3 engines: +0.2 (trifecta)
    
    This mathematically enforces:
    3 different engines > 3 hits from one engine
    """
    if engines_count <= 1:
        return 0.0
    return ENGINE_DIVERSITY_MULTIPLIER * (engines_count - 1)


def get_trifecta_symbols() -> List[Dict]:
    """
    ARCHITECT-4: Trifecta Alert Function
    
    Returns symbols where ALL 3 engines have detected signals.
    This is the highest-conviction scenario:
    - Dealer stress (Gamma Drain)
    - Informed distribution (Distribution)
    - Liquidity withdrawal (Liquidity Vacuum)
    
    Returns:
        List of trifecta symbols with metadata for attention prioritization
    """
    analysis = get_48hour_frequency_analysis()
    
    trifectas = []
    for sym in analysis.get("multi_engine_symbols", []):
        if sym.get("engines_count") == 3:
            trifectas.append({
                "symbol": sym["symbol"],
                "engines": 3,
                "conviction_score": sym.get("conviction_score", 0),
                "weighted_score": sym.get("weighted_score", 0),
                "avg_score": (
                    sym.get("gamma_drain_avg_score", 0) +
                    sym.get("distribution_avg_score", 0) +
                    sym.get("liquidity_avg_score", 0)
                ) / 3,
                "last_seen": sym.get("last_seen"),
                "total_appearances": sym.get("total_appearances", 0),
                "alert_priority": "🚨 TRIFECTA - DROP EVERYTHING AND LOOK",
                # Position sizing guidance
                "position_guidance": "FULL SIZE (3 engines confirming)"
            })
    
    # Sort by conviction score
    trifectas.sort(key=lambda x: x.get("conviction_score", 0), reverse=True)
    
    if trifectas:
        logger.info(f"🚨 TRIFECTA ALERT: {len(trifectas)} symbols with ALL 3 engines converging")
        for t in trifectas:
            logger.info(f"   🎯 {t['symbol']}: conviction={t['conviction_score']:.2f}, last_seen={t['last_seen']}")
    
    return trifectas


def get_48hour_frequency_analysis() -> Dict:
    """
    Analyze scan history from last 48 hours with ARCHITECT-4 enhancements.
    
    ENHANCEMENTS:
    1. Time-Decay Weighting: Recent signals weighted higher (λ=0.04)
    2. Engine Diversity Bonus: Multi-engine convergence rewarded
    3. Conviction Score: Composite metric for ranking
    
    Returns:
        Dict with frequency analysis data including:
        - symbol_stats: Stats per symbol (appearances, engines, scores)
        - multi_engine_symbols: Symbols appearing in 2+ engines
        - trifecta_symbols: Symbols with ALL 3 engines (highest conviction)
        - top_symbols: Top symbols by conviction score
        - engine_counts: Count per engine
    """
    history = load_scan_history()
    history = cleanup_old_scans(history)
    
    est = pytz.timezone('US/Eastern')
    
    # Track appearances per symbol per engine WITH time-decay weighting
    symbol_data = defaultdict(lambda: {
        "gamma_drain": {"count": 0, "weighted_count": 0.0, "scores": [], "weighted_scores": [], "signals": set()},
        "distribution": {"count": 0, "weighted_count": 0.0, "scores": [], "weighted_scores": [], "signals": set()},
        "liquidity": {"count": 0, "weighted_count": 0.0, "scores": [], "weighted_scores": [], "signals": set()},
        "total_appearances": 0,
        "total_weighted_appearances": 0.0,
        "first_seen": None,
        "last_seen": None,
        "timestamps": []
    })
    
    total_scans = len(history.get("scans", []))
    
    for scan in history.get("scans", []):
        timestamp = scan.get("timestamp", "")
        
        # ARCHITECT-4: Calculate time-decay weight for this scan
        time_weight = _calculate_time_decay_weight(timestamp)
        
        for engine in ["gamma_drain", "distribution", "liquidity"]:
            for candidate in scan.get(engine, []):
                symbol = candidate.get("symbol")
                if not symbol:
                    continue
                
                score = candidate.get("score", 0)
                
                data = symbol_data[symbol]
                data[engine]["count"] += 1
                data[engine]["weighted_count"] += time_weight  # Time-weighted
                data[engine]["scores"].append(score)
                data[engine]["weighted_scores"].append(score * time_weight)  # Time-weighted
                data[engine]["signals"].update(candidate.get("signals", []))
                data["total_appearances"] += 1
                data["total_weighted_appearances"] += time_weight
                data["timestamps"].append(timestamp)
                
                # Track first/last seen
                if data["first_seen"] is None:
                    data["first_seen"] = timestamp
                data["last_seen"] = timestamp
    
    # Calculate stats for each symbol with ARCHITECT-4 enhancements
    symbol_stats = {}
    for symbol, data in symbol_data.items():
        engines_with_signals = sum(
            1 for e in ["gamma_drain", "distribution", "liquidity"]
            if data[e]["count"] > 0
        )
        
        # Calculate average scores per engine (both raw and weighted)
        avg_scores = {}
        weighted_avg_scores = {}
        for engine in ["gamma_drain", "distribution", "liquidity"]:
            scores = data[engine]["scores"]
            weighted_scores = data[engine]["weighted_scores"]
            avg_scores[engine] = sum(scores) / len(scores) if scores else 0
            weighted_avg_scores[engine] = sum(weighted_scores) / len(weighted_scores) if weighted_scores else 0
        
        # ARCHITECT-4: Engine Diversity Bonus
        diversity_bonus = _calculate_diversity_bonus(engines_with_signals)
        
        # ARCHITECT-4: Conviction Score (composite metric)
        # = (weighted_appearances × avg_weighted_score) + diversity_bonus
        avg_weighted_score = sum(weighted_avg_scores.values()) / max(engines_with_signals, 1)
        weighted_appearances = data["total_weighted_appearances"]
        
        conviction_score = (weighted_appearances * avg_weighted_score * 0.1) + diversity_bonus
        conviction_score = round(min(1.0, conviction_score), 3)  # Cap at 1.0
        
        # Calculate recency (hours since last seen)
        hours_since_last = 48.0  # Default
        if data["last_seen"]:
            try:
                last_dt = datetime.fromisoformat(data["last_seen"].replace("Z", "+00:00"))
                if last_dt.tzinfo is None:
                    last_dt = est.localize(last_dt)
                hours_since_last = (datetime.now(est) - last_dt).total_seconds() / 3600
            except:
                pass
        
        symbol_stats[symbol] = {
            "symbol": symbol,
            "total_appearances": data["total_appearances"],
            "weighted_appearances": round(data["total_weighted_appearances"], 2),
            "engines_count": engines_with_signals,
            "gamma_drain_count": data["gamma_drain"]["count"],
            "distribution_count": data["distribution"]["count"],
            "liquidity_count": data["liquidity"]["count"],
            "gamma_drain_avg_score": round(avg_scores["gamma_drain"], 3),
            "distribution_avg_score": round(avg_scores["distribution"], 3),
            "liquidity_avg_score": round(avg_scores["liquidity"], 3),
            # ARCHITECT-4: New weighted metrics
            "gamma_drain_weighted_score": round(weighted_avg_scores["gamma_drain"], 3),
            "distribution_weighted_score": round(weighted_avg_scores["distribution"], 3),
            "liquidity_weighted_score": round(weighted_avg_scores["liquidity"], 3),
            "diversity_bonus": round(diversity_bonus, 2),
            "conviction_score": conviction_score,
            "hours_since_last": round(hours_since_last, 1),
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
    
    # ARCHITECT-4: Identify trifecta symbols (ALL 3 engines)
    trifecta_symbols = {
        symbol: stats for symbol, stats in symbol_stats.items()
        if stats["engines_count"] == 3
    }
    
    # Sort by CONVICTION SCORE (ARCHITECT-4 enhancement)
    sorted_symbols = sorted(
        symbol_stats.values(),
        key=lambda x: (x["conviction_score"], x["engines_count"], x["weighted_appearances"]),
        reverse=True
    )
    
    # Sort multi-engine by conviction score
    sorted_multi_engine = sorted(
        multi_engine_symbols.values(),
        key=lambda x: (x["conviction_score"], x["engines_count"]),
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
        "trifecta_count": len(trifecta_symbols),  # ARCHITECT-4
        "multi_engine_symbols": sorted_multi_engine,
        "trifecta_symbols": sorted(  # ARCHITECT-4
            trifecta_symbols.values(),
            key=lambda x: x["conviction_score"],
            reverse=True
        ),
        "all_symbols": sorted_symbols,
        "top_symbol": sorted_symbols[0] if sorted_symbols else None,
        "engine_totals": engine_totals,
        "history_hours": MAX_HISTORY_HOURS,
        # ARCHITECT-4: Decay configuration
        "decay_lambda": TIME_DECAY_LAMBDA,
        "decay_half_life_hours": round(DECAY_HALF_LIFE_HOURS, 1)
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
