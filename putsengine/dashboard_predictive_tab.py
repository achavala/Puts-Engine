"""
🌪️ MARKET WEATHER FORECAST TAB v5
==================================
Displays TWO daily weather reports:
  • AM (9:00 AM ET) — "Open Risk Forecast" for same-day decisions
  • PM (3:00 PM ET) — "Overnight Storm Build" for next-day prep

v5 Architect Additions displayed:
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
    """Render the Market Weather Forecast tab — v5"""
    
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
        <div class="weather-title">🌪️ MARKET WEATHER FORECAST v5</div>
        <div class="weather-subtitle">
            Architect 2-5 Consolidated — Storm Score (not probability) · Gamma Flip Distance · 
            Flow Quality · Liquidity Violence · Confidence Bands<br>
            Two daily reports: 9:00 AM (same-day) & 3:00 PM (next-day)
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # ── How it works (collapsible) ──
    with st.expander("🌤️ How This Works — v5 Architect Upgrades", expanded=False):
        st.markdown("""
        **4 independent data layers** + **3 institutional-grade overlays** from Architect 2-5:
        
        | Layer | Analogy | Lead Time | Source |
        |-------|---------|-----------|--------|
        | 🏔️ **Structural** | Jet Stream | 3-7 days | Polygon SMAs |
        | 🌀 **Institutional** | Pressure System | 1-3 days | EWS IPI |
        | 📡 **Technical** | Radar | 0-2 days | Polygon RSI/MACD |
        | ⚡ **Catalyst** | Known Fronts | Scheduled | Polygon News |
        
        **v5 Overlays:**
        | Metric | What It Tells You |
        |--------|-------------------|
        | ⚡ **Gamma Flip Distance** | How close to forced dealer cascading? (<0.5% = FRAGILE) |
        | 🔄 **Opening Flow Bias** | Are new bearish positions being opened? (vs closing) |
        | 💥 **Liquidity Violence** | If selling hits, will it cascade or get absorbed? |
        | 🎯 **Confidence** | Based on sample size: HIGH (≥50), MEDIUM (30-49), LOW (<30) |
        
        **Storm Score** is a 0-1 ranking, NOT calibrated probability. Treat as relative strength.
        
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
        available_reports.append(f"🌅 AM — Open Risk Forecast ({_format_age(am_ts)})")
    if pm_data and pm_data.get('engine_version', '').startswith('v5'):
        pm_ts = pm_data.get('timestamp', '')
        available_reports.append(f"🌆 PM — Overnight Storm Build ({_format_age(pm_ts)})")
    
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
    
    # ── Summary Cards ──
    st.divider()
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        count = summary.get('storm_warnings', 0)
        st.markdown(f"""
        <div style="background: #4a0a0a; padding: 14px; border-radius: 8px; text-align: center; border: 1px solid #ff0000;">
            <div style="font-size: 32px; color: #ff0000; font-weight: bold;">{count}</div>
            <div style="color: #ff6666; font-size: 12px;">🌪️ STORM WARNING</div>
            <div style="color: #888; font-size: 10px;">Highest storm score</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        count = summary.get('storm_watches', 0)
        st.markdown(f"""
        <div style="background: #3a1500; padding: 14px; border-radius: 8px; text-align: center; border: 1px solid #ff4400;">
            <div style="font-size: 32px; color: #ff4400; font-weight: bold;">{count}</div>
            <div style="color: #ff8844; font-size: 12px;">⛈️ STORM WATCH</div>
            <div style="color: #888; font-size: 10px;">High storm score</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        count = summary.get('advisories', 0)
        st.markdown(f"""
        <div style="background: #3a2a0a; padding: 14px; border-radius: 8px; text-align: center; border: 1px solid #ffaa00;">
            <div style="font-size: 32px; color: #ffaa00; font-weight: bold;">{count}</div>
            <div style="color: #ffcc66; font-size: 12px;">🌧️ ADVISORY</div>
            <div style="color: #888; font-size: 10px;">Moderate score</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        count = summary.get('monitoring', 0)
        st.markdown(f"""
        <div style="background: #1a1a2a; padding: 14px; border-radius: 8px; text-align: center; border: 1px solid #666;">
            <div style="font-size: 32px; color: #aaa; font-weight: bold;">{count}</div>
            <div style="color: #999; font-size: 12px;">☁️ MONITORING</div>
            <div style="color: #888; font-size: 10px;">Low score</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col5:
        mode_emoji = "🌅" if report_mode == "am" else "🌆" if report_mode == "pm" else "📊"
        st.markdown(f"""
        <div style="background: #0a1a2a; padding: 14px; border-radius: 8px; text-align: center; border: 1px solid #2a4a6a;">
            <div style="font-size: 16px; color: #44aaff; font-weight: bold;">{mode_emoji} {report_mode.upper()}</div>
            <div style="color: #88ccff; font-size: 11px;">{report_label}</div>
            <div style="color: #888; font-size: 10px;">Updated {age_str}</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.caption(
        f"EWS data from: {ews_timestamp} | Engine: {engine_version} | "
        f"Sources: EWS IPI + Polygon + UW GEX/Flow | "
        f"Footprint history: {summary.get('data_sources', {}).get('footprint_history_tickers', 0)} tickers"
    )
    
    st.divider()
    
    # ── Main Forecast Table ──
    st.markdown("### 🌪️ TOP 10 — MARKET WEATHER FORECAST")
    st.caption("Storm Score is a ranking (0-1), NOT calibrated probability. Higher = more layers converging.")
    
    forecasts = data.get('forecasts', [])
    
    if not forecasts:
        st.info("No significant weather systems detected. Markets look calm — for now.")
        return
    
    # Create summary table with v5 fields
    df_data = []
    for i, fc in enumerate(forecasts, 1):
        emoji = fc.get('forecast_emoji', '❓')
        traj_emoji = fc.get('trajectory_emoji', '')
        
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
        
        badge_str = " ".join(badges) if badges else "—"
        
        # Confidence
        confidence = fc.get('confidence', 'LOW')
        conf_emoji = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}.get(confidence, "⚪")
        
        df_data.append({
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
    st.markdown("### 📋 DETAILED LAYER ANALYSIS + v5 OVERLAYS")
    st.caption("Expand each forecast to see all 4 layers, v5 overlays, and trajectory")
    
    for i, fc in enumerate(forecasts[:10], 1):
        emoji = fc.get('forecast_emoji', '❓')
        traj_emoji = fc.get('trajectory_emoji', '')
        layers = fc.get('layers', {})
        confidence = fc.get('confidence', 'LOW')
        
        header = (
            f"#{i} {emoji} {fc['forecast']} — **{fc['symbol']}** — "
            f"Storm: {fc.get('storm_score', 0):.2f} | {fc['layers_active']}/4 layers | "
            f"{traj_emoji} {fc.get('trajectory', '')} | {fc['timing']}"
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
    st.markdown("""
    <div style="background: #0a0a1a; padding: 20px; border-radius: 10px; border: 1px solid #2a2a4a;">
        <div style="color: #8888ff; font-weight: bold; font-size: 16px; margin-bottom: 10px;">
            🌤️ WEATHER FORECAST LEGEND (v5)
        </div>
        <div style="color: #aaa; font-size: 12px; line-height: 2;">
            <b>Forecast Levels:</b><br>
            🌪️ <span style="color:#ff0000;">STORM WARNING</span> = 4/4 layers converging — All models agree<br>
            ⛈️ <span style="color:#ff4400;">STORM WATCH</span> = 3/4 layers — Strong convergence<br>
            🌧️ <span style="color:#ffaa00;">ADVISORY</span> = 2/4 layers — Moderate signals<br>
            ☁️ <span style="color:#aaa;">MONITORING</span> = 1/4 layers — Early signals<br><br>
            
            <b>v5 Overlays:</b><br>
            ⚡ <span style="color:#ff4488;">Gamma Flip Distance</span> — % to forced dealer cascade (FRAGILE if ≤0.5%)<br>
            🔻 <span style="color:#ff4444;">Opening Flow</span> — New bearish positions (vs closing / short covering)<br>
            💥 <span style="color:#ff0000;">Liquidity Violence</span> — Will selling cascade (VIOLENT) or get absorbed (NORMAL)?<br>
            🎯 <span style="color:#44ff44;">Confidence</span> — HIGH (≥50 similar days), MEDIUM (30-49), LOW (<30)<br><br>
            
            <b>⚠️ IMPORTANT:</b> Storm Score is a <u>ranking</u>, not a calibrated probability.<br>
            Treat as relative strength until backtested against actual outcomes.
        </div>
    </div>
    """, unsafe_allow_html=True)


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
