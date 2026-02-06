"""
🌪️ MARKET WEATHER FORECAST TAB v5.1
=====================================
Displays TWO daily weather reports:
  • AM (9:00 AM ET) — "Open Risk Forecast" for same-day decisions
  • PM (3:00 PM ET) — "Overnight Storm Build" for next-day prep

v5.1 Architect Operational Additions:
  • 🏛️ Regime Panel (RISK_OFF/NEUTRAL/RISK_ON, TREND/CHOP, Fragility)
  • 🌡️ Pressure Systems Panel (SPY/QQQ VWAP, GEX, market regime)
  • 🟢🟡🔴 Permission Lights per pick (tradable/watch/stand-down)
  • 📡 Data Freshness stamps per provider
  • 📊 Attribution Logger for T+1/T+2 calibration
  • ❌ Missing inputs shown explicitly, not silently neutral
  • Top 8 (not 10) for actionability

Prior v5 Additions:
  • Storm Score (NOT probability — uncalibrated ranking)
  • Gamma Flip Distance + Fragility flag
  • Opening vs Closing Flow bias
  • Liquidity Violence flag (NORMAL/GAPPY/VIOLENT)
  • Confidence band (HIGH/MEDIUM/LOW) with similar_days_n

Visual metaphor:
- 🌪️ STORM WARNING = 4/4 layers (like a hurricane warning)
- ⛈️ STORM WATCH   = 3/4 layers (storm approaching)
- 🌧️ ADVISORY      = 2/4 layers (rain possible)
- ☁️ MONITORING    = 1/4 layers (clouds forming)
"""

import streamlit as st
import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd


WEATHER_DIR = Path("logs/market_weather")
LEGACY_PATH = Path("logs/predictive_analysis.json")


def load_weather_data(mode: str = "latest") -> Optional[Dict]:
    """Load weather forecast data.
    
    mode: "am", "pm", or "latest" (latest of either)
    """
    try:
        if mode == "am":
            path = WEATHER_DIR / "latest_am.json"
        elif mode == "pm":
            path = WEATHER_DIR / "latest_pm.json"
        else:
            # Try PM first (most recent if both exist), then AM, then legacy
            pm_path = WEATHER_DIR / "latest_pm.json"
            am_path = WEATHER_DIR / "latest_am.json"
            
            pm_data = None
            am_data = None
            
            if pm_path.exists():
                with open(pm_path) as f:
                    pm_data = json.load(f)
            if am_path.exists():
                with open(am_path) as f:
                    am_data = json.load(f)
            
            # Return whichever is newer
            if pm_data and am_data:
                pm_ts = pm_data.get('timestamp', '')
                am_ts = am_data.get('timestamp', '')
                return pm_data if pm_ts > am_ts else am_data
            elif pm_data:
                return pm_data
            elif am_data:
                return am_data
            
            # Fallback to legacy
            path = LEGACY_PATH
        
        if path.exists():
            with open(path, 'r') as f:
                return json.load(f)
    except Exception as e:
        st.error(f"Error loading weather data: {e}")
    return None


def run_weather_engine(mode: str = "am"):
    """Run the weather engine (async wrapper)"""
    try:
        from putsengine.predictive_engine import PredictiveEngine
        engine = PredictiveEngine()
        return asyncio.run(engine.run(mode))
    except Exception as e:
        st.error(f"Engine error: {e}")
        return None


def get_forecast_color(forecast: str) -> str:
    """Get color for forecast level"""
    colors = {
        "STORM WARNING": "#ff0000",
        "STORM WATCH": "#ff4400",
        "ADVISORY": "#ffaa00",
        "MONITORING": "#888888",
        "CLEAR": "#44cc44",
    }
    return colors.get(forecast, "#888888")


def get_forecast_bg(forecast: str) -> str:
    """Get background color for forecast level"""
    colors = {
        "STORM WARNING": "#4a0a0a",
        "STORM WATCH": "#3a1500",
        "ADVISORY": "#3a2a0a",
        "MONITORING": "#1a1a2a",
        "CLEAR": "#0a2a0a",
    }
    return colors.get(forecast, "#1a1a1a")


def render_predictive_tab():
    """Render the Market Weather Forecast tab — v5.2 (30-min refresh)"""
    
    # ── Styles ──
    st.markdown("""
    <style>
    .weather-header {
        background: linear-gradient(135deg, #0a0a2e 0%, #1a0a2e 50%, #2a0a1e 100%);
        padding: 24px;
        border-radius: 12px;
        margin-bottom: 20px;
        border: 1px solid #4a2a6a;
    }
    .weather-title {
        color: #e94560;
        font-size: 28px;
        font-weight: bold;
    }
    .weather-subtitle {
        color: #aaa;
        font-size: 13px;
        margin-top: 4px;
    }
    .forecast-card {
        padding: 16px;
        border-radius: 10px;
        margin-bottom: 12px;
        border-left: 4px solid;
    }
    .v5-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 10px;
        font-weight: bold;
        margin-right: 4px;
    }
    .badge-frag { background: #5a0a2a; color: #ff4488; }
    .badge-violent { background: #5a0a0a; color: #ff0000; }
    .badge-gappy { background: #4a2a0a; color: #ffaa00; }
    .badge-opening { background: #0a2a3a; color: #44aaff; }
    .badge-closing { background: #0a3a0a; color: #44ff44; }
    </style>
    """, unsafe_allow_html=True)
    
    # ── Header ──
    st.markdown("""
    <div class="weather-header">
        <div class="weather-title">🌪️ MARKET WEATHER FORECAST v5.2</div>
        <div class="weather-subtitle">
            30-Min Auto-Refresh · Storm Score · Regime Panel · Pressure Systems · 
            Permission Lights (🟢/🟡/🔴) · Data Freshness · Attribution Logger<br>
            Full Runs: 9:00 AM & 3:00 PM (live UW) · Refreshes: Every 30 min (cached UW + fresh Polygon) · Top 8 picks
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # ── How it works (collapsible) ──
    with st.expander("🌤️ How This Works — v5.2 (30-Min Auto-Refresh)", expanded=False):
        st.markdown("""
        **4 independent data layers** + **institutional-grade overlays**:
        
        | Layer | Analogy | Lead Time | Source |
        |-------|---------|-----------|--------|
        | 🏔️ **Structural** | Jet Stream | 3-7 days | Polygon SMAs |
        | 🌀 **Institutional** | Pressure System | 1-3 days | EWS IPI |
        | 📡 **Technical** | Radar | 0-2 days | Polygon RSI/MACD |
        | ⚡ **Catalyst** | Known Fronts | Scheduled | Polygon News |
        
        **v5.1 Operational Fixes:**
        | Feature | Purpose |
        |---------|---------|
        | 🏛️ **Regime Panel** | Risk-off / Neutral / Risk-on + Tape type + Fragility at a glance |
        | 🌡️ **Pressure Systems** | SPY/QQQ vs VWAP, GEX, market regime context |
        | 🟢🟡🔴 **Permission Lights** | 🟢 tradable (aligned+confident) · 🟡 watch (missing data) · 🔴 stand down |
        | 📡 **Data Freshness** | Per-provider staleness check (EWS, Polygon, UW, Regime) |
        | 📊 **Attribution Logger** | Saves T+1/T+2 outcomes for future calibration |
        | 🔒 **Independence Check** | Structural + Technical overlap → 10% convergence damper |
        | ❌ **Missing Input Penalty** | Missing gamma/flow/liquidity → confidence drops, NEVER boosts score |
        
        **Storm Score** is a 0-1 ranking, NOT calibrated probability. Show **Top 8** for actionability.
        
        **Two Reports:**
        - **AM (9:00 AM ET)**: "Open Risk Forecast" — heavier weight on technical + catalyst (same-day)
        - **PM (3:00 PM ET)**: "Overnight Storm Build" — heavier weight on structural + institutional (next-day)
        """)
    
    # ── Controls ──
    col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
    with col1:
        if st.button("🌅 Run AM Scan", key="run_weather_am"):
            with st.spinner("Running AM Open Risk Forecast..."):
                result = run_weather_engine("am")
                if result:
                    st.success("AM forecast updated!")
                    st.rerun()
    with col2:
        if st.button("🌆 Run PM Scan", key="run_weather_pm"):
            with st.spinner("Running PM Overnight Storm Build..."):
                result = run_weather_engine("pm")
                if result:
                    st.success("PM forecast updated!")
                    st.rerun()
    with col3:
        st.checkbox("Auto-refresh", value=False, key="weather_auto")
    with col4:
        st.caption("📡 EWS IPI (cached) + Polygon (unlimited) + UW GEX/flow (minimal)")
    
    # ── Report Selector ──
    # Load both AM and PM data
    am_data = load_weather_data("am")
    pm_data = load_weather_data("pm")
    
    # Determine which reports are available
    available_reports = []
    if am_data and am_data.get('engine_version', '').startswith('v5'):
        am_ts = am_data.get('timestamp', '')
        am_ver = am_data.get('engine_version', 'v5')
        available_reports.append(f"🌅 AM — Open Risk Forecast ({_format_age(am_ts)}) [{am_ver}]")
    if pm_data and pm_data.get('engine_version', '').startswith('v5'):
        pm_ts = pm_data.get('timestamp', '')
        pm_ver = pm_data.get('engine_version', 'v5')
        available_reports.append(f"🌆 PM — Overnight Storm Build ({_format_age(pm_ts)}) [{pm_ver}]")
    
    # Also check legacy data
    legacy_data = None
    if not available_reports:
        legacy_data = load_weather_data("latest")
        if legacy_data:
            ver = legacy_data.get('engine_version', 'unknown')
            if ver.startswith('v4'):
                available_reports.append(f"📊 Latest (v4 — {_format_age(legacy_data.get('timestamp', ''))})")
            elif ver.startswith('v5'):
                available_reports.append(f"📊 Latest (v5 — {_format_age(legacy_data.get('timestamp', ''))})")
    
    if not available_reports:
        st.warning("No weather data available. Click 'Run AM Scan' or 'Run PM Scan' to generate forecast.")
        _show_ews_stats()
        return
    
    # Report selector
    if len(available_reports) > 1:
        selected_idx = st.radio(
            "Select Report", 
            range(len(available_reports)),
            format_func=lambda i: available_reports[i],
            horizontal=True,
            key="report_selector"
        )
    else:
        selected_idx = 0
    
    # Pick the right data
    selected_label = available_reports[selected_idx]
    if "AM" in selected_label:
        data = am_data
    elif "PM" in selected_label:
        data = pm_data
    else:
        data = legacy_data or load_weather_data("latest")
    
    if not data:
        st.warning("No data for selected report.")
        return
    
    # Check status
    if data.get('status') == 'degraded':
        st.error(f"⚠️ Report is DEGRADED — data pipes may be broken. Error: {data.get('error', 'Unknown')}")
        return
    
    # Check version compatibility
    engine_version = data.get('engine_version', '')
    if not engine_version.startswith('v5') and not engine_version.startswith('v4'):
        st.info("🔄 Old engine version detected. Click 'Run AM Scan' to generate v5 forecast.")
        _show_ews_stats()
        return
    
    # ── Metadata ──
    timestamp = datetime.fromisoformat(data['timestamp'])
    age_str = _format_age(data['timestamp'])
    ews_timestamp = data.get('ews_timestamp', 'Unknown')
    summary = data.get('summary', {})
    report_mode = data.get('report_mode', 'unknown')
    report_label = data.get('report_label', 'Weather Report')
    regime_ctx = data.get('regime_context', {})
    data_fresh = data.get('data_freshness', {})
    perm_lights = summary.get('permission_lights', {})
    run_type = data_fresh.get('run_type', 'FULL')
    
    # ── Freshness Banner ──
    run_type_color = "#44cc44" if run_type == "FULL" else "#44aaff"
    run_type_icon = "🔴" if run_type == "FULL" else "🔄"
    uw_fresh = data_fresh.get('uw', 'N/A')
    st.markdown(f"""
    <div style="background: #0a0a1a; padding: 10px 16px; border-radius: 8px; border: 1px solid #2a2a4a; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
        <span style="color: #aaa; font-size: 12px;">
            📊 <b style="color: {run_type_color};">{run_type_icon} {run_type}</b> · 
            Mode: <b>{report_mode.upper()}</b> · 
            Updated: <b>{age_str}</b> · 
            EWS: {ews_timestamp[:19] if len(str(ews_timestamp)) > 19 else ews_timestamp}
        </span>
        <span style="color: #aaa; font-size: 11px;">
            UW: <b style="color: {'#44cc44' if 'live' in str(uw_fresh) else '#44aaff'};">{uw_fresh}</b> · 
            Polygon: <b style="color: #44cc44;">Live</b> · 
            EWS: <b style="color: #44cc44;">Cached</b>
        </span>
    </div>
    """, unsafe_allow_html=True)
    
    # ══════════════════════════════════════════════════════════════════════
    # 1) REGIME PANEL — "What kind of day is it?"
    # ══════════════════════════════════════════════════════════════════════
    st.divider()
    st.markdown("### 🏛️ REGIME PANEL")
    
    rp1, rp2, rp3, rp4 = st.columns(4)
    
    # Risk Regime
    risk_regime = regime_ctx.get('risk_regime', 'UNKNOWN')
    risk_colors = {"RISK_OFF": "#ff0000", "NEUTRAL": "#ffaa00", "RISK_ON": "#44cc44", "UNKNOWN": "#666"}
    risk_bgs = {"RISK_OFF": "#4a0a0a", "NEUTRAL": "#3a2a0a", "RISK_ON": "#0a2a0a", "UNKNOWN": "#1a1a1a"}
    risk_color = risk_colors.get(risk_regime, "#666")
    risk_bg = risk_bgs.get(risk_regime, "#1a1a1a")
    
    with rp1:
        st.markdown(f"""
        <div style="background: {risk_bg}; padding: 14px; border-radius: 8px; text-align: center; border: 1px solid {risk_color};">
            <div style="color: #aaa; font-size: 11px;">RISK REGIME</div>
            <div style="font-size: 22px; color: {risk_color}; font-weight: bold;">{risk_regime}</div>
        </div>
        """, unsafe_allow_html=True)
    
    # Tape Type
    tape_type = regime_ctx.get('tape_type', 'UNKNOWN')
    tape_colors = {"TREND": "#ff4488", "CHOP": "#44aaff", "UNKNOWN": "#666"}
    tape_bgs = {"TREND": "#3a0a2a", "CHOP": "#0a1a3a", "UNKNOWN": "#1a1a1a"}
    tape_color = tape_colors.get(tape_type, "#666")
    tape_bg = tape_bgs.get(tape_type, "#1a1a1a")
    
    with rp2:
        st.markdown(f"""
        <div style="background: {tape_bg}; padding: 14px; border-radius: 8px; text-align: center; border: 1px solid {tape_color};">
            <div style="color: #aaa; font-size: 11px;">TAPE TYPE (GAMMA)</div>
            <div style="font-size: 22px; color: {tape_color}; font-weight: bold;">{tape_type}</div>
        </div>
        """, unsafe_allow_html=True)
    
    # Fragility
    fragility = regime_ctx.get('fragility', 'UNKNOWN')
    frag_colors = {"HIGH": "#ff0000", "LOW": "#44cc44", "UNKNOWN": "#666"}
    frag_bgs = {"HIGH": "#4a0a0a", "LOW": "#0a2a0a", "UNKNOWN": "#1a1a1a"}
    frag_color = frag_colors.get(fragility, "#666")
    frag_bg = frag_bgs.get(fragility, "#1a1a1a")
    
    with rp3:
        near_flip = "⚡ YES" if fragility == "HIGH" else "No"
        st.markdown(f"""
        <div style="background: {frag_bg}; padding: 14px; border-radius: 8px; text-align: center; border: 1px solid {frag_color};">
            <div style="color: #aaa; font-size: 11px;">NEAR GAMMA FLIP?</div>
            <div style="font-size: 22px; color: {frag_color}; font-weight: bold;">{near_flip}</div>
        </div>
        """, unsafe_allow_html=True)
    
    # VIX
    vix_level = regime_ctx.get('vix_level', 0.0)
    vix_change = regime_ctx.get('vix_change', 0.0)
    vix_color = "#ff0000" if vix_level > 25 else "#ffaa00" if vix_level > 18 else "#44cc44"
    vix_bg = "#4a0a0a" if vix_level > 25 else "#3a2a0a" if vix_level > 18 else "#0a2a0a"
    
    with rp4:
        st.markdown(f"""
        <div style="background: {vix_bg}; padding: 14px; border-radius: 8px; text-align: center; border: 1px solid {vix_color};">
            <div style="color: #aaa; font-size: 11px;">VIX LEVEL</div>
            <div style="font-size: 22px; color: {vix_color}; font-weight: bold;">{vix_level:.1f} ({vix_change:+.1%})</div>
        </div>
        """, unsafe_allow_html=True)
    
    # ══════════════════════════════════════════════════════════════════════
    # 2) PRESSURE SYSTEMS + DATA FRESHNESS
    # ══════════════════════════════════════════════════════════════════════
    ps1, ps2 = st.columns(2)
    
    with ps1:
        st.markdown("#### 🌡️ Pressure Systems")
        spy_below = "📉 Below" if regime_ctx.get('spy_below_vwap') else "📈 Above"
        qqq_below = "📉 Below" if regime_ctx.get('qqq_below_vwap') else "📈 Above"
        gex = regime_ctx.get('index_gex', 0.0)
        gex_label = "Negative (TREND)" if gex < 0 else "Positive (CHOP)" if gex > 0 else "Neutral"
        
        st.markdown(f"""
        | Indicator | State |
        |-----------|-------|
        | SPY vs VWAP | {spy_below} |
        | QQQ vs VWAP | {qqq_below} |
        | Index GEX | {gex_label} |
        | Regime | {regime_ctx.get('regime', 'unknown')} |
        """)
    
    with ps2:
        st.markdown("#### 📡 Data Freshness")
        ews_fresh = data_fresh.get('ews', 'MISSING')
        polygon_fresh = data_fresh.get('polygon', 'OK')
        uw_fresh = data_fresh.get('uw', 'MISSING')
        regime_fresh = data_fresh.get('regime', 'MISSING')
        
        ews_status = "🟢" if ews_fresh != "MISSING" else "🔴 MISSING"
        uw_status = "🟢" if uw_fresh != "MISSING" else "🔴 MISSING"
        regime_status = "🟢" if regime_fresh != "MISSING" else "🔴 MISSING"
        
        st.markdown(f"""
        | Provider | Status |
        |----------|--------|
        | EWS IPI | {ews_status} |
        | Polygon | 🟢 Unlimited |
        | UW GEX/Flow | {uw_status} |
        | Market Regime | {regime_status} |
        """)
        
        generated_utc = data.get('generated_at_utc', '')
        if generated_utc:
            st.caption(f"Generated (UTC): {generated_utc}")
    
    # ══════════════════════════════════════════════════════════════════════
    # 3) SUMMARY CARDS + PERMISSION LIGHTS
    # ══════════════════════════════════════════════════════════════════════
    st.divider()
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    with col1:
        count = summary.get('storm_warnings', 0)
        st.markdown(f"""
        <div style="background: #4a0a0a; padding: 12px; border-radius: 8px; text-align: center; border: 1px solid #ff0000;">
            <div style="font-size: 28px; color: #ff0000; font-weight: bold;">{count}</div>
            <div style="color: #ff6666; font-size: 11px;">🌪️ WARNING</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        count = summary.get('storm_watches', 0)
        st.markdown(f"""
        <div style="background: #3a1500; padding: 12px; border-radius: 8px; text-align: center; border: 1px solid #ff4400;">
            <div style="font-size: 28px; color: #ff4400; font-weight: bold;">{count}</div>
            <div style="color: #ff8844; font-size: 11px;">⛈️ WATCH</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        count = summary.get('advisories', 0)
        st.markdown(f"""
        <div style="background: #3a2a0a; padding: 12px; border-radius: 8px; text-align: center; border: 1px solid #ffaa00;">
            <div style="font-size: 28px; color: #ffaa00; font-weight: bold;">{count}</div>
            <div style="color: #ffcc66; font-size: 11px;">🌧️ ADVISORY</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        count = summary.get('monitoring', 0)
        st.markdown(f"""
        <div style="background: #1a1a2a; padding: 12px; border-radius: 8px; text-align: center; border: 1px solid #666;">
            <div style="font-size: 28px; color: #aaa; font-weight: bold;">{count}</div>
            <div style="color: #999; font-size: 11px;">☁️ MONITOR</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col5:
        g = perm_lights.get('green', 0)
        y = perm_lights.get('yellow', 0)
        r = perm_lights.get('red', 0)
        st.markdown(f"""
        <div style="background: #1a1a1a; padding: 12px; border-radius: 8px; text-align: center; border: 1px solid #444;">
            <div style="font-size: 14px; color: #44cc44;">🟢 {g}</div>
            <div style="font-size: 14px; color: #ffaa00;">🟡 {y}</div>
            <div style="font-size: 14px; color: #ff4444;">🔴 {r}</div>
            <div style="color: #888; font-size: 10px;">PERMISSIONS</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col6:
        mode_emoji = "🌅" if report_mode == "am" else "🌆" if report_mode == "pm" else "📊"
        st.markdown(f"""
        <div style="background: #0a1a2a; padding: 12px; border-radius: 8px; text-align: center; border: 1px solid #2a4a6a;">
            <div style="font-size: 16px; color: #44aaff; font-weight: bold;">{mode_emoji} {report_mode.upper()}</div>
            <div style="color: #88ccff; font-size: 11px;">{report_label}</div>
            <div style="color: #888; font-size: 10px;">{age_str}</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.caption(
        f"EWS: {ews_timestamp} | Engine: {engine_version} | "
        f"Footprints: {summary.get('data_sources', {}).get('footprint_history_tickers', 0)} tickers | "
        f"🟢=tradable 🟡=watch 🔴=stand down"
    )
    
    st.divider()
    
    # ══════════════════════════════════════════════════════════════════════
    # 4) TOP 8 FORECAST TABLE (actionable, not 10)
    # ══════════════════════════════════════════════════════════════════════
    st.markdown("### 🌪️ TOP 8 — MARKET WEATHER FORECAST")
    st.caption("Storm Score is a ranking (0-1), NOT calibrated probability. 🟢 = tradable, 🟡 = watch, 🔴 = stand down.")
    
    forecasts = data.get('forecasts', [])
    
    if not forecasts:
        st.info("No significant weather systems detected. Markets look calm — for now.")
        return
    
    # Show top 8 for actionability (keep 10 in data, show 8 in table)
    display_forecasts = forecasts[:8]
    
    # Create summary table with v5.1 fields (permission light + missing)
    df_data = []
    for i, fc in enumerate(display_forecasts, 1):
        emoji = fc.get('forecast_emoji', '❓')
        traj_emoji = fc.get('trajectory_emoji', '')
        
        # Permission light
        perm = fc.get('permission_light', '🟡')
        
        # v5 badges
        badges = []
        if fc.get('gamma_flip_fragile'):
            badges.append("⚡FRAG")
        liq_flag = fc.get('liquidity_violence_flag', 'NORMAL')
        if liq_flag == "VIOLENT":
            badges.append("💥VIOLENT")
        elif liq_flag == "GAPPY":
            badges.append("⚠️GAPPY")
        flow = fc.get('opening_flow_bias', 'UNKNOWN')
        if flow == "OPENING_BEARISH":
            badges.append("🔻OPEN")
        elif flow == "CLOSING_NEUTRAL":
            badges.append("🔼CLOSE")
        
        # Missing inputs (show clearly, not silently neutral)
        missing = fc.get('missing_inputs', [])
        if missing:
            badges.append(f"❌{len(missing)}miss")
        
        badge_str = " ".join(badges) if badges else "—"
        
        # Confidence
        confidence = fc.get('confidence', 'LOW')
        conf_emoji = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}.get(confidence, "⚪")
        
        df_data.append({
            "": perm,
            "Rank": f"#{i}",
            "Forecast": f"{emoji} {fc['forecast']}",
            "Symbol": fc['symbol'],
            "Storm": f"{fc.get('storm_score', 0):.2f}",
            "Layers": f"{fc['layers_active']}/4",
            "Timing": fc['timing'],
            "Traj.": f"{traj_emoji} {fc.get('trajectory', '')}",
            "Conf.": f"{conf_emoji} {confidence}",
            "Flags": badge_str,
            "Drop": fc['expected_drop'],
            "Price": f"${fc['current_price']:.2f}" if fc.get('current_price') else "—",
        })
    
    df = pd.DataFrame(df_data)
    
    # Style function for forecast column
    def style_forecast(val):
        if "STORM WARNING" in str(val):
            return "background-color: #4a0a0a; color: #ff0000; font-weight: bold"
        elif "STORM WATCH" in str(val):
            return "background-color: #3a1500; color: #ff4400; font-weight: bold"
        elif "ADVISORY" in str(val):
            return "background-color: #3a2a0a; color: #ffaa00"
        elif "MONITORING" in str(val):
            return "background-color: #1a1a2a; color: #aaa"
        return ""
    
    styled_df = df.style.applymap(style_forecast, subset=['Forecast'])
    st.dataframe(styled_df, use_container_width=True, height=min(420, 50 + len(forecasts) * 38))
    
    st.divider()
    
    # ── Detailed Forecast Cards ──
    st.markdown("### 📋 DETAILED LAYER ANALYSIS + v5.1 OVERLAYS")
    st.caption("Expand each forecast to see all 4 layers, permission light, overlays, and missing inputs")
    
    for i, fc in enumerate(display_forecasts, 1):
        emoji = fc.get('forecast_emoji', '❓')
        traj_emoji = fc.get('trajectory_emoji', '')
        layers = fc.get('layers', {})
        confidence = fc.get('confidence', 'LOW')
        perm = fc.get('permission_light', '🟡')
        missing = fc.get('missing_inputs', [])
        miss_str = f" | ❌ MISSING: {', '.join(missing)}" if missing else ""
        
        header = (
            f"#{i} {perm} {emoji} {fc['forecast']} — **{fc['symbol']}** — "
            f"Storm: {fc.get('storm_score', 0):.2f} | {fc['layers_active']}/4 layers | "
            f"{traj_emoji} {fc.get('trajectory', '')} | {fc['timing']}{miss_str}"
        )
        
        with st.expander(header, expanded=(i <= 3)):
            # Top-line metrics
            met_col1, met_col2, met_col3, met_col4 = st.columns(4)
            with met_col1:
                st.metric("Storm Score", f"{fc.get('storm_score', 0):.2f}")
            with met_col2:
                st.metric("Layers Active", f"{fc['layers_active']}/4")
            with met_col3:
                st.metric("Expected Drop", fc['expected_drop'])
            with met_col4:
                st.metric("Timing", fc['timing'])
            
            # ── v5 Overlays Row ──
            st.markdown("---")
            st.markdown("**v5 Architect Overlays:**")
            
            ov1, ov2, ov3, ov4 = st.columns(4)
            
            with ov1:
                gfd = fc.get('gamma_flip_distance')
                if gfd is not None:
                    frag_label = "⚡ FRAGILE" if fc.get('gamma_flip_fragile') else ""
                    gfd_color = "#ff4488" if fc.get("gamma_flip_fragile") else "#aaa"
                    st.markdown(
                        f"**Gamma Flip Distance**<br>"
                        f"<span style='font-size:20px; color:{gfd_color};'>"
                        f"{gfd:.1%}</span> {frag_label}",
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown("**Gamma Flip Distance**<br><span style='color:#666;'>N/A (no GEX data)</span>", unsafe_allow_html=True)
            
            with ov2:
                flow_bias = fc.get('opening_flow_bias', 'UNKNOWN')
                flow_colors = {
                    "OPENING_BEARISH": "#ff4444",
                    "CLOSING_NEUTRAL": "#44ff44",
                    "MIXED": "#ffaa00",
                    "UNKNOWN": "#666"
                }
                flow_labels = {
                    "OPENING_BEARISH": "🔻 OPENING (Bearish)",
                    "CLOSING_NEUTRAL": "🔼 CLOSING (Neutral)",
                    "MIXED": "🔄 MIXED",
                    "UNKNOWN": "❓ Unknown"
                }
                fc_color = flow_colors.get(flow_bias, "#666")
                fc_label = flow_labels.get(flow_bias, flow_bias)
                st.markdown(
                    f"**Flow Quality**<br>"
                    f"<span style='font-size:16px; color:{fc_color};'>"
                    f"{fc_label}</span>",
                    unsafe_allow_html=True
                )
            
            with ov3:
                liq_score = fc.get('liquidity_violence_score', 0)
                liq_flag = fc.get('liquidity_violence_flag', 'NORMAL')
                liq_colors = {"VIOLENT": "#ff0000", "GAPPY": "#ffaa00", "NORMAL": "#44ff44"}
                liq_emojis = {"VIOLENT": "💥", "GAPPY": "⚠️", "NORMAL": "✅"}
                liq_color = liq_colors.get(liq_flag, "#aaa")
                liq_emoji = liq_emojis.get(liq_flag, '')
                st.markdown(
                    f"**Liquidity Violence**<br>"
                    f"<span style='font-size:16px; color:{liq_color};'>"
                    f"{liq_emoji} {liq_flag} ({liq_score:.2f})</span>",
                    unsafe_allow_html=True
                )
            
            with ov4:
                conf_colors = {"HIGH": "#44ff44", "MEDIUM": "#ffaa00", "LOW": "#ff4444"}
                similar_n = fc.get('similar_days_n', 0)
                conf_color = conf_colors.get(confidence, "#aaa")
                st.markdown(
                    f"**Confidence**<br>"
                    f"<span style='font-size:16px; color:{conf_color};'>"
                    f"{confidence}</span> (n={similar_n} similar days)",
                    unsafe_allow_html=True
                )
            
            st.markdown("---")
            
            # 4-Layer Breakdown
            layer_configs = [
                ("🏔️ STRUCTURAL", "structural", "Jet Stream — SMA positions", "#4488ff"),
                ("🌀 INSTITUTIONAL", "institutional", "Pressure System — IPI/Dark Pool", "#ff4444"),
                ("📡 TECHNICAL", "technical", "Radar — RSI/MACD/Volume", "#ffaa00"),
                ("⚡ CATALYST", "catalyst", "Known Fronts — News/Earnings", "#44ff88"),
            ]
            
            for layer_label, layer_key, layer_desc, color in layer_configs:
                layer_data = layers.get(layer_key, {})
                score = layer_data.get('score', 0)
                active = layer_data.get('active', False)
                signals = layer_data.get('signals', [])
                
                # Visual bar
                filled = int(score * 20)
                bar_color = color if active else "#444"
                bar_html = f'<span style="color:{bar_color}; font-family:monospace; font-size:14px;">{"█" * filled}{"░" * (20 - filled)}</span>'
                
                status_color = color if active else "#666"
                status_label = "✅ ACTIVE" if active else "⬜ inactive"
                
                st.markdown(
                    f"**{layer_label}** — <span style='color:#888;font-size:12px;'>{layer_desc}</span><br>"
                    f"{bar_html} <span style='color:{status_color};font-weight:bold;'>{score:.0%}</span> "
                    f"<span style='color:{status_color};'>[{status_label}]</span>",
                    unsafe_allow_html=True
                )
                
                if signals:
                    for sig in signals[:4]:
                        st.markdown(f"<span style='color:#aaa;margin-left:20px;font-size:12px;'>• {sig}</span>", unsafe_allow_html=True)
                
                st.markdown("")  # spacer
            
            # Trajectory section
            st.markdown("---")
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                st.markdown(f"**Trajectory:** {traj_emoji} {fc.get('trajectory', 'NEW')}")
                st.markdown(f"**Days Building:** {fc.get('days_building', 0)} days")
                st.markdown(f"**Convergence Score:** {fc.get('convergence_score', 0):.3f}")
            with col_t2:
                if fc.get('current_price'):
                    st.markdown(f"**Current Price:** ${fc['current_price']:.2f}")
                st.markdown(f"**Sector:** {fc.get('sector', 'unknown')}")
    
    # ── Weather Legend ──
    st.divider()
    legend_html = (
        '<div style="background:#0a0a1a; padding:20px; border-radius:10px; border:1px solid #2a2a4a;">'
        '<div style="color:#8888ff; font-weight:bold; font-size:16px; margin-bottom:10px;">'
        '🌤️ WEATHER FORECAST LEGEND (v5)'
        '</div>'
        '<div style="color:#aaa; font-size:12px; line-height:2;">'
        '<b>Forecast Levels:</b><br>'
        '🌪️ <span style="color:#ff0000;">STORM WARNING</span> = 4/4 layers converging — All models agree<br>'
        '⛈️ <span style="color:#ff4400;">STORM WATCH</span> = 3/4 layers — Strong convergence<br>'
        '🌧️ <span style="color:#ffaa00;">ADVISORY</span> = 2/4 layers — Moderate signals<br>'
        '☁️ <span style="color:#aaa;">MONITORING</span> = 1/4 layers — Early signals<br><br>'
        '<b>v5 Overlays:</b><br>'
        '⚡ <span style="color:#ff4488;">Gamma Flip Distance</span> — % to forced dealer cascade (FRAGILE if ≤0.5%)<br>'
        '🔻 <span style="color:#ff4444;">Opening Flow</span> — New bearish positions (vs closing / short covering)<br>'
        '💥 <span style="color:#ff0000;">Liquidity Violence</span> — Will selling cascade (VIOLENT) or get absorbed (NORMAL)?<br>'
        '🎯 <span style="color:#44ff44;">Confidence</span> — HIGH (≥50 similar days), MEDIUM (30-49), LOW (&lt;30)<br><br>'
        '<b>⚠️ IMPORTANT:</b> Storm Score is a <u>ranking</u>, not a calibrated probability.<br>'
        'Treat as relative strength until backtested against actual outcomes.'
        '</div>'
        '</div>'
    )
    st.markdown(legend_html, unsafe_allow_html=True)


def _format_age(timestamp_str: str) -> str:
    """Format a timestamp as 'Xm ago' or 'Xh ago'"""
    try:
        ts = datetime.fromisoformat(timestamp_str)
        age = (datetime.now() - ts).total_seconds()
        if age < 3600:
            return f"{int(age // 60)}m ago"
        elif age < 86400:
            return f"{int(age // 3600)}h ago"
        else:
            return f"{int(age // 86400)}d ago"
    except Exception:
        return "unknown"


def _show_ews_stats():
    """Show EWS stats when no weather data available"""
    try:
        with open("early_warning_alerts.json") as f:
            ews = json.load(f)
        alerts = ews.get("alerts", {})
        ews_ts = ews.get("timestamp", "Unknown")
        
        act_count = len([s for s, d in alerts.items() if d.get('ipi', 0) >= 0.7])
        prep_count = len([s for s, d in alerts.items() if 0.5 <= d.get('ipi', 0) < 0.7])
        watch_count = len([s for s, d in alerts.items() if 0.3 <= d.get('ipi', 0) < 0.5])
        
        st.markdown("### 📊 Available EWS Data (Source for Weather Forecast)")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("🔴 ACT (IPI > 70%)", f"{act_count} tickers")
        with col2:
            st.metric("🟡 PREPARE (50-70%)", f"{prep_count} tickers")
        with col3:
            st.metric("👀 WATCH (30-50%)", f"{watch_count} tickers")
        st.caption(f"Last EWS scan: {ews_ts}")
        st.info("Click 'Run AM Scan' or 'Run PM Scan' above to generate full weather forecast.")
    except Exception:
        pass


if __name__ == "__main__":
    st.set_page_config(page_title="Market Weather Forecast v5", layout="wide")
    render_predictive_tab()
