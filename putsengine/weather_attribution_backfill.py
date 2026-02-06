"""
Market Weather Attribution Backfill Engine
==========================================
PURPOSE: Fill in T+1/T+2 actual outcomes for weather forecast attribution snapshots.
This is the "did it actually rain?" part of the weather system.

HOW IT WORKS:
1. Scans all files in logs/market_weather/attribution/
2. For each snapshot where outcomes are null:
   - If report is ≥ T+1 old → fetch next-day close, compute T+1 return
   - If report is ≥ T+2 old → fetch T+2 close, compute T+2 return
   - Compute max adverse excursion (highest close in the window)
   - Flag did_drop_5pct, did_drop_10pct
3. Updates the attribution file in-place
4. Generates a calibration summary

SCHEDULED: 5:30 PM ET daily (after market close, prices are final)

TARGET METRICS (institutional-grade):
- Storm Warning bucket: 55-60% bearish follow-through = elite
- Storm Watch bucket: 40-50% = good
- Advisory bucket: 30-40% = expected

DO NOT: Auto-adjust thresholds based on this data yet.
First: COLLECT 15-20 trading days. Then: CALIBRATE.
"""

import json
import asyncio
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from loguru import logger
import pytz

EST = pytz.timezone("America/New_York")

# Paths
WEATHER_DIR = Path("logs/market_weather")
ATTRIBUTION_DIR = WEATHER_DIR / "attribution"
CALIBRATION_FILE = WEATHER_DIR / "calibration_summary.json"


async def backfill_attribution():
    """
    Main backfill function.
    
    Scans all attribution snapshots, fetches actual prices from Polygon,
    and fills in T+1/T+2 outcomes.
    """
    from putsengine.config import get_settings
    from putsengine.clients.polygon_client import PolygonClient
    
    settings = get_settings()
    polygon = PolygonClient(settings)
    
    try:
        if not ATTRIBUTION_DIR.exists():
            logger.info("No attribution directory found. Nothing to backfill.")
            return {"status": "no_data", "files_processed": 0}
        
        files = sorted(ATTRIBUTION_DIR.glob("*.json"))
        if not files:
            logger.info("No attribution snapshots found.")
            return {"status": "no_data", "files_processed": 0}
        
        today = date.today()
        files_updated = 0
        picks_backfilled = 0
        errors = []
        
        logger.info(f"=" * 70)
        logger.info(f"🔄 ATTRIBUTION BACKFILL ENGINE")
        logger.info(f"   Scanning {len(files)} attribution files...")
        logger.info(f"   Today: {today.isoformat()}")
        logger.info(f"=" * 70)
        
        for filepath in files:
            try:
                with open(filepath, 'r') as f:
                    snapshot = json.load(f)
                
                report_date_str = snapshot.get("report_date", "")
                if not report_date_str:
                    continue
                
                report_date = datetime.strptime(report_date_str, "%Y%m%d").date()
                days_since = _trading_days_between(report_date, today)
                
                if days_since < 1:
                    # Too fresh — can't backfill yet (need at least T+1)
                    logger.debug(f"  {filepath.name}: Too fresh ({days_since} trading days). Skipping.")
                    continue
                
                picks = snapshot.get("picks", [])
                file_changed = False
                
                for pick in picks:
                    symbol = pick.get("symbol", "")
                    if not symbol:
                        continue
                    
                    current_price = pick.get("current_price", 0)
                    if current_price <= 0:
                        continue
                    
                    # T+1 backfill (need ≥ 1 trading day)
                    if days_since >= 1 and pick.get("t1_close") is None:
                        t1_date = _next_trading_day(report_date)
                        close = await _get_close_price(polygon, symbol, t1_date)
                        if close and close > 0:
                            pick["t1_close"] = round(close, 2)
                            pick["t1_return"] = round((close - current_price) / current_price * 100, 2)
                            file_changed = True
                            picks_backfilled += 1
                            logger.info(f"  ✅ {symbol} T+1: ${current_price:.2f} → ${close:.2f} ({pick['t1_return']:+.2f}%)")
                    
                    # T+2 backfill (need ≥ 2 trading days)
                    if days_since >= 2 and pick.get("t2_close") is None:
                        t1_date = _next_trading_day(report_date)
                        t2_date = _next_trading_day(t1_date)
                        close = await _get_close_price(polygon, symbol, t2_date)
                        if close and close > 0:
                            pick["t2_close"] = round(close, 2)
                            pick["t2_return"] = round((close - current_price) / current_price * 100, 2)
                            file_changed = True
                            picks_backfilled += 1
                            logger.info(f"  ✅ {symbol} T+2: ${current_price:.2f} → ${close:.2f} ({pick['t2_return']:+.2f}%)")
                    
                    # Max adverse excursion (worst close in T+1 to T+2 window)
                    if days_since >= 2 and pick.get("max_adverse") is None:
                        t1_date = _next_trading_day(report_date)
                        t2_date = _next_trading_day(t1_date)
                        bars = await _get_daily_bars(polygon, symbol, t1_date, t2_date)
                        if bars:
                            # For bearish predictions: max adverse = lowest low in window
                            min_low = min(b["low"] for b in bars)
                            max_drop = (min_low - current_price) / current_price * 100
                            pick["max_adverse"] = round(max_drop, 2)
                            
                            # Flags
                            pick["did_drop_5pct"] = max_drop <= -5.0
                            pick["did_drop_10pct"] = max_drop <= -10.0
                            file_changed = True
                            logger.info(f"  ✅ {symbol} MAE: {max_drop:+.2f}% | ≥5%: {pick['did_drop_5pct']} | ≥10%: {pick['did_drop_10pct']}")
                
                if file_changed:
                    snapshot["backfill_timestamp"] = datetime.now(EST).isoformat()
                    snapshot["backfill_status"] = "complete" if days_since >= 2 else "partial_t1_only"
                    with open(filepath, 'w') as f:
                        json.dump(snapshot, f, indent=2)
                    files_updated += 1
                    logger.info(f"  📝 Updated: {filepath.name}")
                    
            except Exception as e:
                errors.append(f"{filepath.name}: {str(e)}")
                logger.warning(f"  ❌ Error processing {filepath.name}: {e}")
        
        # Generate calibration summary
        calibration = _generate_calibration_summary()
        
        result = {
            "status": "complete",
            "timestamp": datetime.now(EST).isoformat(),
            "files_scanned": len(files),
            "files_updated": files_updated,
            "picks_backfilled": picks_backfilled,
            "errors": errors,
            "calibration": calibration,
        }
        
        logger.info(f"\n{'=' * 70}")
        logger.info(f"🔄 BACKFILL COMPLETE: {files_updated} files updated, {picks_backfilled} picks backfilled")
        if errors:
            logger.warning(f"   Errors: {len(errors)}")
        logger.info(f"{'=' * 70}")
        
        return result
        
    finally:
        await polygon.close()


async def _get_close_price(polygon, symbol: str, target_date: date) -> Optional[float]:
    """Get the closing price for a symbol on a specific date."""
    try:
        bars = await polygon.get_daily_bars(
            symbol=symbol,
            from_date=target_date,
            to_date=target_date + timedelta(days=1)
        )
        if bars:
            for bar in bars:
                bar_date = bar.timestamp.date() if hasattr(bar.timestamp, 'date') else bar.timestamp
                if bar_date == target_date:
                    return bar.close
            # If exact date not found, return the closest bar
            return bars[0].close if bars else None
        return None
    except Exception as e:
        logger.debug(f"Could not get close for {symbol} on {target_date}: {e}")
        return None


async def _get_daily_bars(polygon, symbol: str, from_date: date, to_date: date) -> List[Dict]:
    """Get daily bars for a symbol in a date range, returning dicts with high/low/close."""
    try:
        bars = await polygon.get_daily_bars(
            symbol=symbol,
            from_date=from_date,
            to_date=to_date + timedelta(days=1)
        )
        return [{"date": b.timestamp, "high": b.high, "low": b.low, "close": b.close} for b in bars]
    except Exception as e:
        logger.debug(f"Could not get bars for {symbol} ({from_date} to {to_date}): {e}")
        return []


def _next_trading_day(d: date) -> date:
    """Get the next trading day after date d (skip weekends)."""
    next_day = d + timedelta(days=1)
    while next_day.weekday() >= 5:  # Saturday=5, Sunday=6
        next_day += timedelta(days=1)
    return next_day


def _trading_days_between(start: date, end: date) -> int:
    """Count approximate trading days between two dates (excludes weekends)."""
    count = 0
    current = start
    while current < end:
        current += timedelta(days=1)
        if current.weekday() < 5:
            count += 1
    return count


def _generate_calibration_summary() -> Dict:
    """
    Generate calibration summary from all attribution snapshots.
    
    This is the core "did it rain?" analysis.
    """
    if not ATTRIBUTION_DIR.exists():
        return {"status": "no_data"}
    
    files = sorted(ATTRIBUTION_DIR.glob("*.json"))
    
    # Collect all picks with outcomes
    all_picks = []
    storm_warnings = []
    storm_watches = []
    advisories = []
    
    total_snapshots = 0
    snapshots_with_outcomes = 0
    
    for filepath in files:
        try:
            with open(filepath, 'r') as f:
                snapshot = json.load(f)
            
            total_snapshots += 1
            has_outcomes = False
            
            for pick in snapshot.get("picks", []):
                if pick.get("t1_return") is not None:
                    has_outcomes = True
                    pick_data = {
                        "symbol": pick["symbol"],
                        "storm_score": pick.get("storm_score", 0),
                        "forecast": pick.get("forecast", ""),
                        "layers_active": pick.get("layers_active", 0),
                        "convergence_score": pick.get("convergence_score", 0),
                        "confidence": pick.get("confidence", "LOW"),
                        "permission_light": pick.get("permission_light", "🟡"),
                        "current_price": pick.get("current_price", 0),
                        "t1_return": pick.get("t1_return"),
                        "t2_return": pick.get("t2_return"),
                        "max_adverse": pick.get("max_adverse"),
                        "did_drop_5pct": pick.get("did_drop_5pct", False),
                        "did_drop_10pct": pick.get("did_drop_10pct", False),
                        "report_date": snapshot.get("report_date", ""),
                        "report_mode": snapshot.get("report_mode", ""),
                    }
                    all_picks.append(pick_data)
                    
                    forecast = pick.get("forecast", "")
                    if "STORM WARNING" in forecast.upper() or "WARNING" in forecast.upper():
                        storm_warnings.append(pick_data)
                    elif "STORM WATCH" in forecast.upper() or "WATCH" in forecast.upper():
                        storm_watches.append(pick_data)
                    else:
                        advisories.append(pick_data)
            
            if has_outcomes:
                snapshots_with_outcomes += 1
                
        except Exception as e:
            logger.debug(f"Error reading {filepath.name}: {e}")
    
    # Calculate metrics
    calibration = {
        "generated_at": datetime.now(EST).isoformat(),
        "data_collection": {
            "total_snapshots": total_snapshots,
            "snapshots_with_outcomes": snapshots_with_outcomes,
            "total_picks_with_outcomes": len(all_picks),
            "target_snapshots": 30,
            "progress": f"{snapshots_with_outcomes}/30",
            "ready_for_calibration": snapshots_with_outcomes >= 15,
        },
        "overall": _calc_bucket_stats(all_picks, "ALL PICKS"),
        "storm_warning": _calc_bucket_stats(storm_warnings, "STORM WARNING"),
        "storm_watch": _calc_bucket_stats(storm_watches, "STORM WATCH"),
        "advisory": _calc_bucket_stats(advisories, "ADVISORY/OTHER"),
        "by_layers": {
            "4_layers": _calc_bucket_stats([p for p in all_picks if p["layers_active"] == 4], "4/4 Layers"),
            "3_layers": _calc_bucket_stats([p for p in all_picks if p["layers_active"] == 3], "3/4 Layers"),
            "2_layers": _calc_bucket_stats([p for p in all_picks if p["layers_active"] <= 2], "≤2/4 Layers"),
        },
        "by_confidence": {
            "high": _calc_bucket_stats([p for p in all_picks if p["confidence"] == "HIGH"], "HIGH conf"),
            "medium": _calc_bucket_stats([p for p in all_picks if p["confidence"] == "MEDIUM"], "MEDIUM conf"),
            "low": _calc_bucket_stats([p for p in all_picks if p["confidence"] == "LOW"], "LOW conf"),
        },
        "by_permission": {
            "green": _calc_bucket_stats([p for p in all_picks if "🟢" in str(p.get("permission_light", ""))], "🟢 Green"),
            "yellow": _calc_bucket_stats([p for p in all_picks if "🟡" in str(p.get("permission_light", ""))], "🟡 Yellow"),
            "red": _calc_bucket_stats([p for p in all_picks if "🔴" in str(p.get("permission_light", ""))], "🔴 Red"),
        },
    }
    
    # Save calibration summary
    WEATHER_DIR.mkdir(parents=True, exist_ok=True)
    with open(CALIBRATION_FILE, 'w') as f:
        json.dump(calibration, f, indent=2)
    
    logger.info(f"📊 Calibration summary saved to {CALIBRATION_FILE}")
    
    return calibration


def _calc_bucket_stats(picks: List[Dict], label: str) -> Dict:
    """Calculate statistics for a bucket of picks."""
    if not picks:
        return {"count": 0, "label": label, "message": "No data yet"}
    
    n = len(picks)
    
    # T+1 stats
    t1_returns = [p["t1_return"] for p in picks if p.get("t1_return") is not None]
    t1_bearish = [r for r in t1_returns if r < 0]  # Negative return = bearish follow-through
    t1_bearish_rate = len(t1_bearish) / len(t1_returns) if t1_returns else 0
    t1_avg = sum(t1_returns) / len(t1_returns) if t1_returns else 0
    
    # T+2 stats
    t2_returns = [p["t2_return"] for p in picks if p.get("t2_return") is not None]
    t2_bearish = [r for r in t2_returns if r < 0]
    t2_bearish_rate = len(t2_bearish) / len(t2_returns) if t2_returns else 0
    t2_avg = sum(t2_returns) / len(t2_returns) if t2_returns else 0
    
    # Drop stats
    dropped_5pct = sum(1 for p in picks if p.get("did_drop_5pct"))
    dropped_10pct = sum(1 for p in picks if p.get("did_drop_10pct"))
    drop_5_rate = dropped_5pct / n if n else 0
    drop_10_rate = dropped_10pct / n if n else 0
    
    # Max adverse excursion stats
    mae_values = [p["max_adverse"] for p in picks if p.get("max_adverse") is not None]
    avg_mae = sum(mae_values) / len(mae_values) if mae_values else 0
    worst_mae = min(mae_values) if mae_values else 0
    
    return {
        "label": label,
        "count": n,
        "t1": {
            "measured": len(t1_returns),
            "bearish_follow_through": len(t1_bearish),
            "bearish_rate": round(t1_bearish_rate * 100, 1),
            "avg_return_pct": round(t1_avg, 2),
            "target": "55-60% for Storm Warning = elite",
        },
        "t2": {
            "measured": len(t2_returns),
            "bearish_follow_through": len(t2_bearish),
            "bearish_rate": round(t2_bearish_rate * 100, 1),
            "avg_return_pct": round(t2_avg, 2),
        },
        "drops": {
            "dropped_5pct": dropped_5pct,
            "drop_5pct_rate": round(drop_5_rate * 100, 1),
            "dropped_10pct": dropped_10pct,
            "drop_10pct_rate": round(drop_10_rate * 100, 1),
        },
        "max_adverse_excursion": {
            "avg_mae_pct": round(avg_mae, 2),
            "worst_mae_pct": round(worst_mae, 2),
        },
    }


def print_calibration_report():
    """Print human-readable calibration report to console."""
    calibration = _generate_calibration_summary()
    
    dc = calibration.get("data_collection", {})
    print("=" * 78)
    print("📊 MARKET WEATHER — CALIBRATION REPORT")
    print("=" * 78)
    print(f"  Data Collection Progress: {dc.get('progress', '?')}")
    print(f"  Total picks with outcomes: {dc.get('total_picks_with_outcomes', 0)}")
    print(f"  Ready for calibration: {'✅ YES' if dc.get('ready_for_calibration') else '❌ NO (need 15+ snapshots)'}")
    print()
    
    for bucket_key in ["storm_warning", "storm_watch", "advisory"]:
        bucket = calibration.get(bucket_key, {})
        label = bucket.get("label", bucket_key)
        count = bucket.get("count", 0)
        
        if count == 0:
            print(f"  {label}: No data")
            continue
        
        t1 = bucket.get("t1", {})
        t2 = bucket.get("t2", {})
        drops = bucket.get("drops", {})
        mae = bucket.get("max_adverse_excursion", {})
        
        print(f"  ── {label} ({count} picks) ──")
        print(f"     T+1 Bearish Rate: {t1.get('bearish_rate', 0):.1f}% ({t1.get('bearish_follow_through', 0)}/{t1.get('measured', 0)})")
        print(f"     T+1 Avg Return:   {t1.get('avg_return_pct', 0):+.2f}%")
        print(f"     T+2 Bearish Rate: {t2.get('bearish_rate', 0):.1f}% ({t2.get('bearish_follow_through', 0)}/{t2.get('measured', 0)})")
        print(f"     T+2 Avg Return:   {t2.get('avg_return_pct', 0):+.2f}%")
        print(f"     Dropped ≥5%:      {drops.get('dropped_5pct', 0)} ({drops.get('drop_5pct_rate', 0):.1f}%)")
        print(f"     Dropped ≥10%:     {drops.get('dropped_10pct', 0)} ({drops.get('drop_10pct_rate', 0):.1f}%)")
        print(f"     Avg MAE:          {mae.get('avg_mae_pct', 0):+.2f}%")
        print(f"     Worst MAE:        {mae.get('worst_mae_pct', 0):+.2f}%")
        print()
    
    print("  ── BY LAYER COUNT ──")
    for layer_key in ["4_layers", "3_layers", "2_layers"]:
        bucket = calibration.get("by_layers", {}).get(layer_key, {})
        count = bucket.get("count", 0)
        if count == 0:
            continue
        t1 = bucket.get("t1", {})
        print(f"     {bucket.get('label', layer_key)}: {t1.get('bearish_rate', 0):.1f}% bearish ({count} picks, avg {t1.get('avg_return_pct', 0):+.2f}%)")
    
    print()
    print("  ── BY CONFIDENCE ──")
    for conf_key in ["high", "medium", "low"]:
        bucket = calibration.get("by_confidence", {}).get(conf_key, {})
        count = bucket.get("count", 0)
        if count == 0:
            continue
        t1 = bucket.get("t1", {})
        print(f"     {bucket.get('label', conf_key)}: {t1.get('bearish_rate', 0):.1f}% bearish ({count} picks, avg {t1.get('avg_return_pct', 0):+.2f}%)")
    
    print()
    print("  ── BY PERMISSION LIGHT ──")
    for light_key in ["green", "yellow", "red"]:
        bucket = calibration.get("by_permission", {}).get(light_key, {})
        count = bucket.get("count", 0)
        if count == 0:
            continue
        t1 = bucket.get("t1", {})
        print(f"     {bucket.get('label', light_key)}: {t1.get('bearish_rate', 0):.1f}% bearish ({count} picks, avg {t1.get('avg_return_pct', 0):+.2f}%)")
    
    print()
    print("=" * 78)
    print("  TARGET: Storm Warning bucket ≥ 55-60% bearish follow-through = ELITE")
    print("  STATUS: Collecting data. Calibration begins after 15 trading days.")
    print("=" * 78)


# ============================================================================
# STANDALONE RUNNER
# ============================================================================

async def run_backfill():
    """Run the backfill standalone (for scheduler or CLI)."""
    logger.info("Starting Market Weather Attribution Backfill...")
    result = await backfill_attribution()
    print_calibration_report()
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Market Weather Attribution Backfill")
    parser.add_argument("--report-only", action="store_true",
                        help="Only print calibration report, don't backfill")
    args = parser.parse_args()
    
    if args.report_only:
        print_calibration_report()
    else:
        asyncio.run(run_backfill())
