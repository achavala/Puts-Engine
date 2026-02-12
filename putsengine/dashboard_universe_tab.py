"""
Universe Scanner Tab — Real-Time Price Monitor for All Static Universe Stocks.

Shows ALL tickers from EngineConfig.UNIVERSE_SECTORS sorted by most bearish
(biggest % drop) at the top. Auto-refreshes every 15 minutes via a file-based
cache with Polygon snapshot data (single API call for all tickers).

Data Sources:
  - Primary: Polygon.io get_all_tickers_snapshot() — 1 API call, UNLIMITED plan
  - The snapshot includes: current price, today's change %, prev close,
    pre-market data, volume, VWAP

Created: Feb 10, 2026
"""

import streamlit as st
import asyncio
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytz

from putsengine.config import Settings, EngineConfig

# ============================================================================
# CONSTANTS
# ============================================================================
UNIVERSE_CACHE_FILE = Path(__file__).parent.parent / "logs" / "universe_snapshot.json"
CACHE_TTL_SECONDS = 15 * 60  # 15 minutes

ET = pytz.timezone("US/Eastern")


# ============================================================================
# DATA FETCHING
# ============================================================================

def _run_async(coro):
    """Run an async coroutine from sync Streamlit context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=120)
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


async def _fetch_polygon_snapshots(tickers: List[str]) -> List[Dict]:
    """
    Fetch snapshots for all universe tickers from Polygon.
    
    Strategy: Use get_all_tickers_snapshot() which returns ALL US stock
    snapshots in a SINGLE API call, then filter to our universe.
    This is incredibly efficient — 1 call instead of 361.
    """
    from putsengine.clients.polygon_client import PolygonClient

    settings = Settings()
    polygon = PolygonClient(settings)

    results = []
    ticker_set = set(tickers)

    try:
        # ONE API call to get all US stock snapshots
        all_snapshots = await polygon.get_all_tickers_snapshot()

        if all_snapshots:
            for snap in all_snapshots:
                symbol = snap.get("ticker", "")
                if symbol in ticker_set:
                    day = snap.get("day", {})
                    prev = snap.get("prevDay", {})
                    last_trade = snap.get("lastTrade", {})

                    # ── Core prices ──
                    last_trade_price = float(last_trade.get("p", 0) or 0)
                    prev_close = float(prev.get("c", 0) or 0)
                    day_open = float(day.get("o", 0) or 0)
                    day_high = float(day.get("h", 0) or 0)
                    day_low = float(day.get("l", 0) or 0)
                    day_close = float(day.get("c", 0) or 0)
                    day_volume = int(day.get("v", 0) or 0)
                    day_vwap = float(day.get("vw", 0) or 0)
                    prev_volume = int(prev.get("v", 0) or 0)

                    # ── Live price = lastTrade (includes after-hours) ──
                    live_price = last_trade_price if last_trade_price > 0 else day_close

                    # ── Regular session change: day.c vs prevDay.c ──
                    # DO NOT use Polygon's todaysChangePerc — it includes
                    # after-hours trades and creates a mismatch with day.c
                    if prev_close > 0 and day_close > 0:
                        reg_change = day_close - prev_close
                        reg_change_pct = (reg_change / prev_close) * 100
                    else:
                        reg_change = 0.0
                        reg_change_pct = 0.0

                    # ── After-hours change: lastTrade vs day.c ──
                    if day_close > 0 and last_trade_price > 0:
                        ah_change = last_trade_price - day_close
                        ah_change_pct = (ah_change / day_close) * 100
                    else:
                        ah_change = 0.0
                        ah_change_pct = 0.0

                    # ── Total change (live price vs prev close) ──
                    if prev_close > 0 and live_price > 0:
                        total_change = live_price - prev_close
                        total_change_pct = (total_change / prev_close) * 100
                    else:
                        total_change = 0.0
                        total_change_pct = 0.0

                    # ── Pre-market gap: open vs prev close ──
                    if day_open > 0 and prev_close > 0:
                        premarket_change_pct = ((day_open - prev_close) / prev_close) * 100
                    else:
                        premarket_change_pct = 0.0

                    # ── Relative volume ──
                    rvol = (day_volume / prev_volume) if prev_volume > 0 else 0.0

                    results.append({
                        "symbol": symbol,
                        "live_price": round(live_price, 2),
                        "close": round(day_close, 2),
                        "prev_close": round(prev_close, 2),
                        "open": round(day_open, 2),
                        "high": round(day_high, 2),
                        "low": round(day_low, 2),
                        "reg_change": round(reg_change, 2),
                        "reg_change_pct": round(reg_change_pct, 2),
                        "ah_change": round(ah_change, 2),
                        "ah_change_pct": round(ah_change_pct, 2),
                        "total_change": round(total_change, 2),
                        "total_change_pct": round(total_change_pct, 2),
                        "premarket_pct": round(premarket_change_pct, 2),
                        "volume": day_volume,
                        "prev_volume": prev_volume,
                        "rvol": round(rvol, 2),
                        "vwap": round(day_vwap, 2),
                    })
                    ticker_set.discard(symbol)

        # For any tickers not in the bulk snapshot, fetch individually
        if ticker_set:
            for symbol in list(ticker_set)[:50]:  # Cap at 50 to avoid slowness
                try:
                    snap_data = await polygon.get_snapshot(symbol)
                    if snap_data and "ticker" in snap_data:
                        t = snap_data["ticker"]
                        day = t.get("day", {})
                        prev = t.get("prevDay", {})
                        last_trade = t.get("lastTrade", {})

                        last_trade_price = float(last_trade.get("p", 0) or 0)
                        prev_close = float(prev.get("c", 0) or 0)
                        day_open = float(day.get("o", 0) or 0)
                        day_close = float(day.get("c", 0) or 0)
                        day_high = float(day.get("h", 0) or 0)
                        day_low = float(day.get("l", 0) or 0)
                        day_volume = int(day.get("v", 0) or 0)
                        prev_volume = int(prev.get("v", 0) or 0)
                        live_price = last_trade_price if last_trade_price > 0 else day_close

                        reg_change = (day_close - prev_close) if prev_close > 0 and day_close > 0 else 0.0
                        reg_change_pct = (reg_change / prev_close * 100) if prev_close > 0 else 0.0
                        ah_change = (last_trade_price - day_close) if day_close > 0 and last_trade_price > 0 else 0.0
                        ah_change_pct = (ah_change / day_close * 100) if day_close > 0 else 0.0
                        total_change = (live_price - prev_close) if prev_close > 0 else 0.0
                        total_change_pct = (total_change / prev_close * 100) if prev_close > 0 else 0.0
                        premarket_pct = ((day_open - prev_close) / prev_close * 100) if prev_close > 0 and day_open > 0 else 0.0
                        rvol = (day_volume / prev_volume) if prev_volume > 0 else 0.0

                        results.append({
                            "symbol": symbol,
                            "live_price": round(live_price, 2),
                            "close": round(day_close, 2),
                            "prev_close": round(prev_close, 2),
                            "open": round(day_open, 2),
                            "high": round(day_high, 2),
                            "low": round(day_low, 2),
                            "reg_change": round(reg_change, 2),
                            "reg_change_pct": round(reg_change_pct, 2),
                            "ah_change": round(ah_change, 2),
                            "ah_change_pct": round(ah_change_pct, 2),
                            "total_change": round(total_change, 2),
                            "total_change_pct": round(total_change_pct, 2),
                            "premarket_pct": round(premarket_pct, 2),
                            "volume": day_volume,
                            "prev_volume": prev_volume,
                            "rvol": round(rvol, 2),
                            "vwap": 0.0,
                        })
                except Exception:
                    pass

    except Exception as e:
        st.error(f"Error fetching Polygon snapshots: {e}")
    finally:
        await polygon.close()

    return results


def _load_cached_data() -> Optional[Dict]:
    """Load cached universe snapshot if fresh."""
    try:
        if UNIVERSE_CACHE_FILE.exists():
            with open(UNIVERSE_CACHE_FILE, "r") as f:
                data = json.load(f)
            cached_time = data.get("timestamp", "")
            if cached_time:
                cached_dt = datetime.fromisoformat(cached_time)
                age_seconds = (datetime.now() - cached_dt).total_seconds()
                if age_seconds < CACHE_TTL_SECONDS:
                    return data
    except Exception:
        pass
    return None


def _save_cache(tickers_data: List[Dict]):
    """Save universe snapshot to cache."""
    try:
        UNIVERSE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        cache = {
            "timestamp": datetime.now().isoformat(),
            "ticker_count": len(tickers_data),
            "tickers": tickers_data,
        }
        with open(UNIVERSE_CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass


def _get_universe_data(force_refresh: bool = False) -> Tuple[List[Dict], str]:
    """
    Get universe data — from cache if fresh, otherwise fetch live.
    
    Returns:
        (list of ticker dicts, timestamp string)
    """
    if not force_refresh:
        cached = _load_cached_data()
        if cached:
            return cached.get("tickers", []), cached.get("timestamp", "")

    # Fetch fresh data
    all_tickers = EngineConfig.get_all_tickers()
    tickers_data = _run_async(_fetch_polygon_snapshots(all_tickers))

    if tickers_data:
        _save_cache(tickers_data)
        return tickers_data, datetime.now().isoformat()

    # Fallback to stale cache if fetch failed
    try:
        if UNIVERSE_CACHE_FILE.exists():
            with open(UNIVERSE_CACHE_FILE, "r") as f:
                data = json.load(f)
            return data.get("tickers", []), data.get("timestamp", "") + " (STALE)"
    except Exception:
        pass

    return [], ""


def _get_sector_for_ticker(symbol: str) -> str:
    """Get the sector name for a ticker."""
    for sector, tickers in EngineConfig.UNIVERSE_SECTORS.items():
        if symbol in tickers:
            # Format sector name: "mega_cap_tech" -> "Mega Cap Tech"
            return sector.replace("_", " ").title()
    return "Unknown"


# ============================================================================
# RENDERING
# ============================================================================

def render_universe_tab():
    """Render the Universe Scanner tab — all static universe stocks sorted by bearishness."""

    # ── Styles ──
    st.markdown("""
    <style>
    .universe-header {
        background: linear-gradient(135deg, #0a1628 0%, #0a2240 50%, #0a1628 100%);
        padding: 24px;
        border-radius: 12px;
        margin-bottom: 20px;
        border: 1px solid #1a3a5c;
    }
    .universe-title {
        color: #4a9eff;
        font-size: 28px;
        font-weight: bold;
    }
    .universe-subtitle {
        color: #aaa;
        font-size: 13px;
        margin-top: 4px;
    }
    .stats-row {
        display: flex;
        gap: 16px;
        margin: 12px 0;
    }
    .stat-card {
        background: rgba(255,255,255,0.05);
        border-radius: 8px;
        padding: 12px 20px;
        text-align: center;
        flex: 1;
        border: 1px solid rgba(255,255,255,0.1);
    }
    .stat-value {
        font-size: 24px;
        font-weight: bold;
    }
    .stat-label {
        font-size: 11px;
        color: #888;
        margin-top: 4px;
    }
    .bearish-val { color: #ff4444; }
    .bullish-val { color: #44ff44; }
    .neutral-val { color: #ffaa00; }
    </style>
    """, unsafe_allow_html=True)

    # ── Header ──
    st.markdown("""
    <div class="universe-header">
        <div class="universe-title">🌐 UNIVERSE SCANNER</div>
        <div class="universe-subtitle">
            All Static Universe Stocks · Sorted Most Bearish First · 
            15-Min Auto-Refresh · Polygon Real-Time Snapshots · 1 API Call
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Controls ──
    col1, col2, col3, col4 = st.columns([1, 1, 1, 2])

    with col1:
        force_refresh = st.button("🔄 Refresh Now", key="universe_refresh")

    with col2:
        sector_filter = st.selectbox(
            "Sector Filter",
            ["All Sectors"] + sorted([
                s.replace("_", " ").title()
                for s in EngineConfig.UNIVERSE_SECTORS.keys()
            ]),
            key="universe_sector_filter",
            label_visibility="collapsed",
        )

    with col3:
        direction_filter = st.selectbox(
            "Direction",
            ["All", "Bearish Only (Down)", "Bullish Only (Up)"],
            key="universe_direction_filter",
            label_visibility="collapsed",
        )

    with col4:
        search_query = st.text_input(
            "Search ticker",
            key="universe_search",
            placeholder="Search ticker (e.g., AAPL, TSLA)...",
            label_visibility="collapsed",
        )

    # ── Check 15-minute auto-refresh via session state ──
    now = datetime.now()
    last_universe_refresh = st.session_state.get("last_universe_refresh")
    auto_triggered = False
    if last_universe_refresh:
        elapsed = (now - last_universe_refresh).total_seconds()
        if elapsed >= CACHE_TTL_SECONDS:
            auto_triggered = True
    else:
        auto_triggered = True  # First load

    should_refresh = force_refresh or auto_triggered

    # ── Fetch Data ──
    tickers_data, timestamp = _get_universe_data(force_refresh=should_refresh)

    if should_refresh and tickers_data:
        st.session_state["last_universe_refresh"] = now

    if not tickers_data:
        st.warning("⚠️ No universe data available. Click 'Refresh Now' to fetch.")
        return

    # ── Parse timestamp ──
    try:
        data_time = datetime.fromisoformat(timestamp.replace(" (STALE)", ""))
        age_seconds = (now - data_time).total_seconds()
        age_str = f"{int(age_seconds // 60)}m {int(age_seconds % 60)}s ago"
        is_stale = "(STALE)" in timestamp
    except Exception:
        age_str = "unknown"
        is_stale = True

    # ── Statistics (use total_change_pct which includes after-hours) ──
    bearish_count = sum(1 for t in tickers_data if t.get("total_change_pct", 0) < 0)
    bullish_count = sum(1 for t in tickers_data if t.get("total_change_pct", 0) > 0)
    flat_count = sum(1 for t in tickers_data if t.get("total_change_pct", 0) == 0)
    avg_change = sum(t.get("total_change_pct", 0) for t in tickers_data) / max(len(tickers_data), 1)

    # Biggest movers (by total change including after-hours)
    sorted_by_change = sorted(tickers_data, key=lambda x: x.get("total_change_pct", 0))
    worst = sorted_by_change[0] if sorted_by_change else {}
    best = sorted_by_change[-1] if sorted_by_change else {}

    stale_badge = ' <span style="color:#ff4444;font-size:12px;">[STALE]</span>' if is_stale else ""

    worst_pct = worst.get('total_change_pct', 0)
    best_pct = best.get('total_change_pct', 0)
    worst_sym = worst.get('symbol', '?')
    best_sym = best.get('symbol', '?')

    st.markdown(f"""
    <div class="stats-row">
        <div class="stat-card">
            <div class="stat-value bearish-val">📉 {bearish_count}</div>
            <div class="stat-label">STOCKS DOWN</div>
        </div>
        <div class="stat-card">
            <div class="stat-value bullish-val">📈 {bullish_count}</div>
            <div class="stat-label">STOCKS UP</div>
        </div>
        <div class="stat-card">
            <div class="stat-value neutral-val">{avg_change:+.2f}%</div>
            <div class="stat-label">AVG CHANGE</div>
        </div>
        <div class="stat-card">
            <div class="stat-value bearish-val">{worst_sym} {worst_pct:+.2f}%</div>
            <div class="stat-label">BIGGEST LOSER</div>
        </div>
        <div class="stat-card">
            <div class="stat-value bullish-val">{best_sym} {best_pct:+.2f}%</div>
            <div class="stat-label">BIGGEST GAINER</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color:#4a9eff;">{len(tickers_data)}</div>
            <div class="stat-label">TOTAL TICKERS</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Data freshness bar ──
    next_refresh = (data_time + timedelta(seconds=CACHE_TTL_SECONDS)) if not is_stale else now
    time_to_refresh = max(0, (next_refresh - now).total_seconds())
    mins_to_refresh = int(time_to_refresh // 60)
    secs_to_refresh = int(time_to_refresh % 60)

    st.caption(
        f"📡 Data: Polygon Snapshot (1 API call) | "
        f"Updated: {age_str}{' ⚠️ STALE' if is_stale else ''} | "
        f"Next auto-refresh in: {mins_to_refresh}m {secs_to_refresh}s | "
        f"Tickers: {len(tickers_data)}/{len(EngineConfig.get_all_tickers())}"
    )

    # ── Apply filters ──
    filtered = tickers_data

    # Sector filter
    if sector_filter != "All Sectors":
        sector_key = sector_filter.lower().replace(" ", "_")
        sector_tickers = set(EngineConfig.UNIVERSE_SECTORS.get(sector_key, []))
        filtered = [t for t in filtered if t["symbol"] in sector_tickers]

    # Direction filter (use total change including after-hours)
    if direction_filter == "Bearish Only (Down)":
        filtered = [t for t in filtered if t.get("total_change_pct", 0) < 0]
    elif direction_filter == "Bullish Only (Up)":
        filtered = [t for t in filtered if t.get("total_change_pct", 0) > 0]

    # Search filter
    if search_query:
        q = search_query.upper().strip()
        filtered = [t for t in filtered if q in t["symbol"]]

    # ── Sort: most bearish first (by total change = reg + after-hours) ──
    filtered.sort(key=lambda x: x.get("total_change_pct", 0))

    # ── Build DataFrame ──
    import pandas as pd

    if not filtered:
        st.info("No tickers match the current filters.")
        return

    rows = []
    for t in filtered:
        sector = _get_sector_for_ticker(t["symbol"])
        reg_pct = t.get("reg_change_pct", 0)
        ah_pct = t.get("ah_change_pct", 0)
        total_pct = t.get("total_change_pct", 0)
        premarket_pct = t.get("premarket_pct", 0)
        rvol = t.get("rvol", 0)

        # Direction indicator based on TOTAL change (reg + after-hours)
        if total_pct < -5:
            direction = "🔴🔴🔴"
        elif total_pct < -3:
            direction = "🔴🔴"
        elif total_pct < -1:
            direction = "🔴"
        elif total_pct < 0:
            direction = "🟠"
        elif total_pct == 0:
            direction = "⚪"
        elif total_pct < 1:
            direction = "🟢"
        elif total_pct < 3:
            direction = "🟢🟢"
        else:
            direction = "🟢🟢🟢"

        # RVOL badge
        if rvol >= 3.0:
            rvol_badge = "🔥"
        elif rvol >= 2.0:
            rvol_badge = "⬆️"
        elif rvol >= 1.0:
            rvol_badge = ""
        else:
            rvol_badge = "⬇️"

        # After-hours indicator
        ah_str = ""
        if abs(ah_pct) >= 0.5:
            ah_str = "%+.1f%%" % ah_pct

        rows.append({
            "": direction,
            "Symbol": t["symbol"],
            "Sector": sector,
            "Live Price": t.get("live_price", 0),
            "Close": t.get("close", 0),
            "Prev Close": t.get("prev_close", 0),
            "$ Chg": t.get("reg_change", 0),
            "% Today": reg_pct,
            "After-Hrs %": ah_pct,
            "% Total": total_pct,
            "Pre-Mkt %": premarket_pct,
            "Open": t.get("open", 0),
            "High": t.get("high", 0),
            "Low": t.get("low", 0),
            "Volume": t.get("volume", 0),
            "RVOL": "%s%.1fx" % (rvol_badge, rvol),
        })

    df = pd.DataFrame(rows)

    # ── Column configuration ──
    column_config = {
        "": st.column_config.TextColumn("", width="small"),
        "Symbol": st.column_config.TextColumn("Symbol", width="small"),
        "Sector": st.column_config.TextColumn("Sector", width="medium"),
        "Live Price": st.column_config.NumberColumn("Live $", format="$%.2f"),
        "Close": st.column_config.NumberColumn("Close", format="$%.2f"),
        "Prev Close": st.column_config.NumberColumn("Prev Cls", format="$%.2f"),
        "$ Chg": st.column_config.NumberColumn("$ Chg", format="$%.2f"),
        "% Today": st.column_config.NumberColumn("% Today", format="%.2f%%"),
        "After-Hrs %": st.column_config.NumberColumn("AH %", format="%.2f%%"),
        "% Total": st.column_config.NumberColumn("% Total", format="%.2f%%"),
        "Pre-Mkt %": st.column_config.NumberColumn("Pre-Mkt", format="%.2f%%"),
        "Open": st.column_config.NumberColumn("Open", format="$%.2f"),
        "High": st.column_config.NumberColumn("High", format="$%.2f"),
        "Low": st.column_config.NumberColumn("Low", format="$%.2f"),
        "Volume": st.column_config.NumberColumn("Volume", format="%d"),
        "RVOL": st.column_config.TextColumn("RVOL", width="small"),
    }

    # ── Display table ──
    st.markdown(f"### {'🔴 Bearish' if direction_filter == 'Bearish Only (Down)' else '🌐 All'} Universe — {len(filtered)} Stocks")

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
        height=min(800, 40 + len(filtered) * 35),
    )

    # ── Sector Breakdown (collapsible) ──
    with st.expander("📊 Sector Breakdown", expanded=False):
        sector_stats = {}
        for t in tickers_data:
            sector = _get_sector_for_ticker(t["symbol"])
            if sector not in sector_stats:
                sector_stats[sector] = {"count": 0, "total_change": 0, "bearish": 0, "bullish": 0}
            sector_stats[sector]["count"] += 1
            sector_stats[sector]["total_change"] += t.get("total_change_pct", 0)
            if t.get("total_change_pct", 0) < 0:
                sector_stats[sector]["bearish"] += 1
            elif t.get("total_change_pct", 0) > 0:
                sector_stats[sector]["bullish"] += 1

        sector_rows = []
        for sector, stats in sorted(sector_stats.items(), key=lambda x: x[1]["total_change"] / max(x[1]["count"], 1)):
            avg = stats["total_change"] / max(stats["count"], 1)
            sector_rows.append({
                "Sector": sector,
                "Tickers": stats["count"],
                "Avg Change %": round(avg, 2),
                "Bearish": stats["bearish"],
                "Bullish": stats["bullish"],
                "Bear Ratio": f"{stats['bearish']/max(stats['count'],1)*100:.0f}%",
            })

        if sector_rows:
            sector_df = pd.DataFrame(sector_rows)
            st.dataframe(
                sector_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Avg Change %": st.column_config.NumberColumn("Avg %", format="%.2f%%"),
                },
                height=min(600, 40 + len(sector_rows) * 35),
            )
