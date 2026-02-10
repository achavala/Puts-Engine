"""
Convergence Backtesting Metrics Framework (Gap 9)
==================================================
PURPOSE: Systematically measure convergence pick accuracy.
Answers: "When IPI > 0.70, how often did the stock drop 3%+ in 2 days?"

HOW IT WORKS:
1. snapshot_picks(): Called after each ConvergenceEngine run. Saves all Top 9 picks
   with their scores, sources, conviction tiers, and entry prices.
2. backfill_outcomes(): Scheduled at 5:30 PM ET daily (alongside weather backfill).
   Fetches T+1/T+2 close prices from Polygon and computes actual returns.
3. compute_metrics(): Generates calibration metrics by conviction tier, IPI threshold,
   source count, trifecta status, sector, etc.

TARGET METRICS (institutional-grade):
- TRADE (conv ≥ 0.55, 2+ sources): 55-65% drop ≥ 3% in T+2 = elite
- WATCH (conv ≥ 0.30, 1 source):   35-45% drop ≥ 3% in T+2 = good
- STAND DOWN (conv < 0.30):         20-30% = expected noise

SCHEDULED: 
- snapshot_picks(): After each convergence run (every 30 min during market)
- backfill_outcomes(): 5:30 PM ET daily
- compute_metrics(): After backfill

OUTPUT:
- logs/convergence/backtest/snapshots/YYYYMMDD_HHMM.json (per-run snapshots)
- logs/convergence/backtest/outcomes.json (aggregated outcomes)
- logs/convergence/backtest/metrics.json (calibration metrics)
"""

import json
import asyncio
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from loguru import logger
import pytz
from collections import defaultdict

ET = pytz.timezone("US/Eastern")

# ============================================================================
# PATHS
# ============================================================================
BACKTEST_DIR = Path("logs/convergence/backtest")
SNAPSHOTS_DIR = BACKTEST_DIR / "snapshots"
OUTCOMES_FILE = BACKTEST_DIR / "outcomes.json"
METRICS_FILE = BACKTEST_DIR / "metrics.json"

# ============================================================================
# THRESHOLDS
# ============================================================================
DROP_THRESHOLDS = [3.0, 5.0, 7.0, 10.0]  # % drop thresholds to track
MAX_SNAPSHOTS_DAYS = 90  # Keep 90 days of snapshots


def snapshot_picks(top9_report: Dict) -> Optional[Path]:
    """
    Record a convergence engine run for future backtesting.
    
    Called after each ConvergenceEngine.run() completes.
    Extracts all candidate data needed for outcome measurement.
    
    Args:
        top9_report: The full convergence report dict from ConvergenceEngine.run()
    
    Returns:
        Path to saved snapshot file, or None on error
    """
    try:
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        
        now = datetime.now(ET)
        timestamp = now.strftime("%Y%m%d_%H%M")
        
        candidates = top9_report.get("top_9_candidates", [])
        if not candidates:
            logger.debug("Backtest: No candidates in report, skipping snapshot")
            return None
        
        picks = []
        for c in candidates:
            picks.append({
                "symbol": c.get("symbol", ""),
                "rank": c.get("rank", 0),
                "convergence_score": c.get("convergence_score", 0.0),
                "permission_light": c.get("permission_light", ""),
                
                # Source scores
                "ews_score": c.get("ews_score", 0.0),
                "ews_level": c.get("ews_level", ""),
                "ews_footprints": c.get("ews_footprints", 0),
                "ews_days_building": c.get("ews_days_building", 0),
                
                "gamma_score": c.get("gamma_score", 0.0),
                "gamma_engine": c.get("gamma_engine", ""),
                "gamma_engines_count": c.get("gamma_engines_count", 0),
                "gamma_is_trifecta": c.get("gamma_is_trifecta", False),
                
                "weather_score": c.get("weather_score", 0.0),
                "weather_forecast": c.get("weather_forecast", ""),
                "weather_layers": c.get("weather_layers", 0),
                
                "direction_alignment": c.get("direction_alignment", 0.0),
                "direction_regime": c.get("direction_regime", ""),
                
                # Derived
                "sources_agreeing": c.get("sources_agreeing", 0),
                "source_list": c.get("source_list", []),
                "sector": c.get("sector", ""),
                "current_price": c.get("current_price", 0.0),
                "expected_drop": c.get("expected_drop", ""),
                "trajectory": c.get("trajectory", "NEW"),
                "days_on_list": c.get("days_on_list", 0),
                
                # Outcome fields (filled by backfill)
                "t1_close": None,
                "t2_close": None,
                "t1_return_pct": None,
                "t2_return_pct": None,
                "max_drop_pct": None,    # Maximum intraday drop in T+1/T+2
                "did_drop_3pct": None,
                "did_drop_5pct": None,
                "did_drop_10pct": None,
                "outcome_filled": False,
            })
        
        snapshot = {
            "timestamp": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
            "market_regime": top9_report.get("market_direction", {}).get("regime", ""),
            "pipeline_status": top9_report.get("pipeline_status", ""),
            "picks_count": len(picks),
            "picks": picks,
        }
        
        filepath = SNAPSHOTS_DIR / f"{timestamp}.json"
        filepath.write_text(json.dumps(snapshot, indent=2, default=str))
        logger.info(f"Backtest: Snapshot saved → {filepath} ({len(picks)} picks)")
        return filepath
    
    except Exception as e:
        logger.error(f"Backtest: Failed to save snapshot: {e}")
        return None


async def backfill_outcomes():
    """
    Fill T+1/T+2 outcomes for convergence snapshots.
    
    Scheduled at 5:30 PM ET daily (alongside weather_attribution_backfill).
    For each snapshot where outcomes are not yet filled:
    - If snapshot is >= T+1 old: fetch next-day close
    - If snapshot is >= T+2 old: fetch T+2 close + compute max drop
    - Compute return percentages and drop flags
    
    Returns summary dict.
    """
    from putsengine.config import get_settings
    from putsengine.clients.polygon_client import PolygonClient
    
    settings = get_settings()
    polygon = PolygonClient(settings)
    
    try:
        if not SNAPSHOTS_DIR.exists():
            logger.info("Backtest: No snapshots directory. Nothing to backfill.")
            return {"status": "no_data", "files_processed": 0}
        
        snapshot_files = sorted(SNAPSHOTS_DIR.glob("*.json"))
        if not snapshot_files:
            logger.info("Backtest: No snapshot files found.")
            return {"status": "no_data", "files_processed": 0}
        
        today = date.today()
        processed = 0
        updated = 0
        errors = 0
        
        for filepath in snapshot_files:
            try:
                snapshot = json.loads(filepath.read_text())
                snap_date_str = snapshot.get("date", "")
                if not snap_date_str:
                    continue
                
                snap_date = datetime.strptime(snap_date_str, "%Y-%m-%d").date()
                days_old = (today - snap_date).days
                
                # Need at least T+1 to fill anything
                if days_old < 1:
                    continue
                
                # Skip already fully filled snapshots
                all_filled = all(
                    p.get("outcome_filled", False) 
                    for p in snapshot.get("picks", [])
                )
                if all_filled:
                    continue
                
                processed += 1
                modified = False
                
                for pick in snapshot.get("picks", []):
                    if pick.get("outcome_filled", False):
                        continue
                    
                    symbol = pick.get("symbol", "")
                    entry_price = pick.get("current_price", 0.0)
                    
                    if not symbol or entry_price <= 0:
                        continue
                    
                    try:
                        # T+1 outcome
                        if days_old >= 1 and pick.get("t1_close") is None:
                            t1_date = _next_trading_day(snap_date)
                            bars = await polygon.get_daily_bars(
                                symbol, 
                                from_date=t1_date, 
                                to_date=t1_date
                            )
                            if bars:
                                t1_close = bars[0].get("c", 0.0)
                                pick["t1_close"] = t1_close
                                pick["t1_return_pct"] = round(
                                    ((t1_close - entry_price) / entry_price) * 100, 2
                                )
                                modified = True
                        
                        # T+2 outcome
                        if days_old >= 2 and pick.get("t2_close") is None:
                            t2_date = _next_trading_day(
                                _next_trading_day(snap_date)
                            )
                            bars = await polygon.get_daily_bars(
                                symbol, 
                                from_date=t2_date, 
                                to_date=t2_date
                            )
                            if bars:
                                t2_close = bars[0].get("c", 0.0)
                                pick["t2_close"] = t2_close
                                pick["t2_return_pct"] = round(
                                    ((t2_close - entry_price) / entry_price) * 100, 2
                                )
                                
                                # Compute max drop over T+1 to T+2
                                t1_ret = pick.get("t1_return_pct", 0.0) or 0.0
                                t2_ret = pick["t2_return_pct"]
                                max_drop = min(t1_ret, t2_ret)
                                pick["max_drop_pct"] = round(max_drop, 2)
                                
                                # Flag thresholds
                                pick["did_drop_3pct"] = max_drop <= -3.0
                                pick["did_drop_5pct"] = max_drop <= -5.0
                                pick["did_drop_10pct"] = max_drop <= -10.0
                                
                                pick["outcome_filled"] = True
                                modified = True
                                updated += 1
                    
                    except Exception as e:
                        logger.debug(f"Backtest: Error fetching outcome for {symbol}: {e}")
                        errors += 1
                
                if modified:
                    filepath.write_text(json.dumps(snapshot, indent=2, default=str))
            
            except Exception as e:
                logger.error(f"Backtest: Error processing {filepath.name}: {e}")
                errors += 1
        
        # After backfill, compute fresh metrics
        metrics = compute_metrics()
        
        summary = {
            "status": "completed",
            "files_processed": processed,
            "picks_updated": updated,
            "errors": errors,
            "metrics_computed": bool(metrics),
        }
        
        logger.info(
            f"Backtest backfill: {processed} files, {updated} picks updated, "
            f"{errors} errors"
        )
        return summary
    
    except Exception as e:
        logger.error(f"Backtest backfill failed: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        if hasattr(polygon, '_session') and polygon._session:
            await polygon._session.close()


def compute_metrics() -> Optional[Dict]:
    """
    Compute calibration metrics from all completed backtest snapshots.
    
    Groups outcomes by:
    - Conviction tier (TRADE / WATCH / STAND DOWN)
    - IPI threshold buckets (0-0.3, 0.3-0.5, 0.5-0.7, 0.7+)
    - Number of sources (1, 2, 3, 4)
    - Trifecta status
    - Trajectory (RISING, STABLE, FALLING, NEW)
    - Sector
    - Market regime
    
    Returns metrics dict (also saved to METRICS_FILE).
    """
    try:
        BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
        
        if not SNAPSHOTS_DIR.exists():
            return None
        
        all_picks = []
        snapshot_count = 0
        
        for filepath in sorted(SNAPSHOTS_DIR.glob("*.json")):
            try:
                snapshot = json.loads(filepath.read_text())
                snap_date = snapshot.get("date", "")
                snap_time = snapshot.get("time", "")
                regime = snapshot.get("market_regime", "")
                
                for pick in snapshot.get("picks", []):
                    if not pick.get("outcome_filled", False):
                        continue
                    
                    pick["_snap_date"] = snap_date
                    pick["_snap_time"] = snap_time
                    pick["_market_regime"] = regime
                    all_picks.append(pick)
                
                snapshot_count += 1
            except Exception:
                continue
        
        if not all_picks:
            logger.info("Backtest: No completed outcomes yet for metrics.")
            metrics = {
                "status": "insufficient_data",
                "snapshots_scanned": snapshot_count,
                "completed_picks": 0,
                "note": "Need at least 2 trading days of data. Accumulating...",
                "computed_at": datetime.now(ET).isoformat(),
            }
            METRICS_FILE.write_text(json.dumps(metrics, indent=2))
            return metrics
        
        # ── Compute metrics by various dimensions ──
        
        metrics = {
            "computed_at": datetime.now(ET).isoformat(),
            "snapshots_scanned": snapshot_count,
            "completed_picks": len(all_picks),
            "date_range": {
                "first": all_picks[0].get("_snap_date", ""),
                "last": all_picks[-1].get("_snap_date", ""),
            },
        }
        
        # Overall hit rates
        metrics["overall"] = _compute_bucket_stats(all_picks)
        
        # By conviction tier
        tiers = {
            "TRADE": [p for p in all_picks if _get_permission(p) == "TRADE"],
            "WATCH": [p for p in all_picks if _get_permission(p) == "WATCH"],
            "STAND_DOWN": [p for p in all_picks if _get_permission(p) == "STAND_DOWN"],
        }
        metrics["by_conviction"] = {
            k: _compute_bucket_stats(v) for k, v in tiers.items() if v
        }
        
        # By IPI bucket
        ipi_buckets = {
            "ipi_0_30": [p for p in all_picks if 0 <= p.get("ews_score", 0) < 0.3],
            "ipi_30_50": [p for p in all_picks if 0.3 <= p.get("ews_score", 0) < 0.5],
            "ipi_50_70": [p for p in all_picks if 0.5 <= p.get("ews_score", 0) < 0.7],
            "ipi_70_plus": [p for p in all_picks if p.get("ews_score", 0) >= 0.7],
        }
        metrics["by_ipi"] = {
            k: _compute_bucket_stats(v) for k, v in ipi_buckets.items() if v
        }
        
        # By source count
        src_buckets = {}
        for count in range(1, 5):
            key = f"sources_{count}"
            src_buckets[key] = [
                p for p in all_picks 
                if p.get("sources_agreeing", 0) == count
            ]
        metrics["by_sources"] = {
            k: _compute_bucket_stats(v) for k, v in src_buckets.items() if v
        }
        
        # By trifecta
        trifecta_picks = [p for p in all_picks if p.get("gamma_is_trifecta", False)]
        non_trifecta = [p for p in all_picks if not p.get("gamma_is_trifecta", False)]
        metrics["by_trifecta"] = {
            "trifecta": _compute_bucket_stats(trifecta_picks) if trifecta_picks else None,
            "non_trifecta": _compute_bucket_stats(non_trifecta) if non_trifecta else None,
        }
        
        # By trajectory
        traj_buckets = defaultdict(list)
        for p in all_picks:
            traj = p.get("trajectory", "NEW")
            traj_buckets[traj].append(p)
        metrics["by_trajectory"] = {
            k: _compute_bucket_stats(v) for k, v in traj_buckets.items() if v
        }
        
        # By sector
        sector_buckets = defaultdict(list)
        for p in all_picks:
            sector = p.get("sector", "unknown") or "unknown"
            sector_buckets[sector].append(p)
        metrics["by_sector"] = {
            k: _compute_bucket_stats(v) for k, v in sector_buckets.items() if v
        }
        
        # By market regime
        regime_buckets = defaultdict(list)
        for p in all_picks:
            regime = p.get("_market_regime", "unknown") or "unknown"
            regime_buckets[regime].append(p)
        metrics["by_regime"] = {
            k: _compute_bucket_stats(v) for k, v in regime_buckets.items() if v
        }
        
        # Score calibration: does higher score = higher hit rate?
        score_buckets = {
            "score_30_45": [p for p in all_picks if 0.30 <= p.get("convergence_score", 0) < 0.45],
            "score_45_55": [p for p in all_picks if 0.45 <= p.get("convergence_score", 0) < 0.55],
            "score_55_70": [p for p in all_picks if 0.55 <= p.get("convergence_score", 0) < 0.70],
            "score_70_plus": [p for p in all_picks if p.get("convergence_score", 0) >= 0.70],
        }
        metrics["by_score_bucket"] = {
            k: _compute_bucket_stats(v) for k, v in score_buckets.items() if v
        }
        
        # Save
        METRICS_FILE.write_text(json.dumps(metrics, indent=2, default=str))
        logger.info(
            f"Backtest metrics computed: {len(all_picks)} picks across "
            f"{snapshot_count} snapshots → {METRICS_FILE}"
        )
        return metrics
    
    except Exception as e:
        logger.error(f"Backtest: Failed to compute metrics: {e}")
        return None


# ============================================================================
# HELPERS
# ============================================================================

def _compute_bucket_stats(picks: List[Dict]) -> Dict:
    """Compute statistics for a bucket of picks."""
    if not picks:
        return {"count": 0}
    
    n = len(picks)
    
    t1_returns = [p["t1_return_pct"] for p in picks if p.get("t1_return_pct") is not None]
    t2_returns = [p["t2_return_pct"] for p in picks if p.get("t2_return_pct") is not None]
    
    drop_3 = sum(1 for p in picks if p.get("did_drop_3pct", False))
    drop_5 = sum(1 for p in picks if p.get("did_drop_5pct", False))
    drop_10 = sum(1 for p in picks if p.get("did_drop_10pct", False))
    
    stats = {
        "count": n,
        "hit_rate_3pct": round(drop_3 / n * 100, 1) if n else 0,
        "hit_rate_5pct": round(drop_5 / n * 100, 1) if n else 0,
        "hit_rate_10pct": round(drop_10 / n * 100, 1) if n else 0,
        "drops_3pct": drop_3,
        "drops_5pct": drop_5,
        "drops_10pct": drop_10,
    }
    
    if t1_returns:
        stats["t1_avg_return"] = round(sum(t1_returns) / len(t1_returns), 2)
        stats["t1_median_return"] = round(
            sorted(t1_returns)[len(t1_returns) // 2], 2
        )
        stats["t1_worst"] = round(min(t1_returns), 2)
        stats["t1_best"] = round(max(t1_returns), 2)
    
    if t2_returns:
        stats["t2_avg_return"] = round(sum(t2_returns) / len(t2_returns), 2)
        stats["t2_median_return"] = round(
            sorted(t2_returns)[len(t2_returns) // 2], 2
        )
        stats["t2_worst"] = round(min(t2_returns), 2)
        stats["t2_best"] = round(max(t2_returns), 2)
    
    return stats


def _get_permission(pick: Dict) -> str:
    """Derive conviction tier from permission light."""
    light = pick.get("permission_light", "")
    if "🟢" in light:
        return "TRADE"
    elif "🟡" in light:
        return "WATCH"
    return "STAND_DOWN"


def _next_trading_day(d: date) -> date:
    """Get next trading day (skip weekends, not holidays)."""
    next_d = d + timedelta(days=1)
    while next_d.weekday() >= 5:  # Saturday=5, Sunday=6
        next_d += timedelta(days=1)
    return next_d


def get_latest_metrics() -> Optional[Dict]:
    """Load the latest metrics file for dashboard display."""
    try:
        if METRICS_FILE.exists():
            return json.loads(METRICS_FILE.read_text())
        return None
    except Exception:
        return None
