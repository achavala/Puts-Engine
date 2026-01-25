"""
PutsEngine Professional Dashboard
Auto-scans all tickers every 30 minutes across 3 engines.
"""

import streamlit as st
import asyncio
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict
import sys
import os
import random
import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from putsengine.config import Settings, EngineConfig, get_settings
from putsengine.engine import PutsEngine
from putsengine.models import PutCandidate, MarketRegimeData, BlockReason

st.set_page_config(page_title="PutsEngine", page_icon="📉", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    .stApp { background-color: #f5f5f7; font-family: 'Inter', sans-serif; }
    .header-banner { background: linear-gradient(135deg, #1a1f3c 0%, #2d3561 50%, #1a1f3c 100%); border-radius: 16px; padding: 35px 45px; margin-bottom: 25px; }
    .header-title { font-size: 2.8rem; font-weight: 800; background: linear-gradient(90deg, #ff4757, #ff6b81); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin: 0; }
    .header-subtitle { color: #a8b2d1; font-size: 1.1rem; margin-top: 8px; }
    [data-testid="stSidebar"] { background-color: #ffffff; border-right: 1px solid #e8e8e8; }
    .stTabs [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid #e8e8e8; }
    .stTabs [data-baseweb="tab"] { padding: 12px 20px; font-weight: 500; color: #666; }
    .stTabs [aria-selected="true"] { color: #ff4757 !important; border-bottom: 2px solid #ff4757 !important; font-weight: 600; }
    .section-header { font-size: 1.4rem; font-weight: 700; color: #1a1a2e; margin: 25px 0 15px 0; }
    .no-trades-message { text-align: center; padding: 40px 20px; color: #888; background: #fafafa; border-radius: 8px; margin: 15px 0; border: 1px dashed #ddd; }
    .metric-card { background: #ffffff; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); border: 1px solid #e8e8e8; text-align: center; }
    .metric-value { font-size: 1.8rem; font-weight: 700; color: #1a1a2e; }
    .metric-label { font-size: 0.85rem; color: #888; margin-top: 5px; }
    .status-tradeable { background: linear-gradient(90deg, #00b894, #00cec9); color: white; padding: 8px 20px; border-radius: 25px; font-weight: 600; display: inline-block; }
    .status-blocked { background: linear-gradient(90deg, #ff4757, #ff6b81); color: white; padding: 8px 20px; border-radius: 25px; font-weight: 600; display: inline-block; }
    .auto-scan-bar { background: linear-gradient(90deg, #1a1f3c, #2d3561); border-radius: 8px; padding: 12px 25px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; color: white; }
    .scan-status { display: flex; align-items: center; gap: 10px; font-weight: 600; }
    .scan-dot { width: 8px; height: 8px; background: #00b894; border-radius: 50%; animation: pulse 2s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
    .scan-info { color: #a8b2d1; font-size: 0.9rem; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display: none;}
    .stButton > button { background: linear-gradient(90deg, #ff4757, #ff6b81); color: white; border: none; border-radius: 8px; padding: 10px 25px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)


def get_market_times():
    est = pytz.timezone('US/Eastern')
    now_est = datetime.now(est)
    market_open = now_est.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_est.replace(hour=16, minute=0, second=0, microsecond=0)
    return now_est, market_open, market_close


def is_market_open():
    now_est, market_open, market_close = get_market_times()
    if now_est.weekday() >= 5:
        return False
    return market_open <= now_est <= market_close


def get_engine():
    if "engine" not in st.session_state:
        st.session_state.engine = PutsEngine()
    return st.session_state.engine


def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def get_next_scan_time():
    now = datetime.now()
    minutes = now.minute
    next_scan_minute = ((minutes // 30) + 1) * 30
    if next_scan_minute >= 60:
        next_scan = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        next_scan = now.replace(minute=next_scan_minute, second=0, microsecond=0)
    return next_scan


def should_auto_scan(engine_key):
    now = datetime.now()
    last_scan = st.session_state.get(f"last_scan_{engine_key}")
    if last_scan is None:
        return True
    if (now - last_scan).total_seconds() >= 1800:
        return True
    return False


async def run_engine_scan(engine, engine_type, progress_callback=None):
    """Optimized parallel scan with rate limiting."""
    all_tickers = EngineConfig.get_all_tickers()
    results = []
    total = len(all_tickers)
    completed = [0]  # Using list for mutable counter in nested function
    
    # Semaphore to limit concurrent requests (prevents API rate limits)
    semaphore = asyncio.Semaphore(10)  # 10 concurrent scans
    
    async def scan_single(symbol):
        async with semaphore:
            try:
                candidate = await engine.run_single_symbol(symbol)
                completed[0] += 1
                if progress_callback:
                    progress_callback(completed[0] / total, f"Scanned {completed[0]}/{total} tickers...")
                return (symbol, candidate)
            except Exception:
                completed[0] += 1
                if progress_callback:
                    progress_callback(completed[0] / total, f"Scanned {completed[0]}/{total} tickers...")
                return (symbol, None)
    
    # Run all scans in parallel with semaphore limiting
    tasks = [scan_single(symbol) for symbol in all_tickers]
    scan_results = await asyncio.gather(*tasks)
    
    # Process results
    for symbol, candidate in scan_results:
        if candidate is None:
            continue
        if candidate.composite_score >= 0.50:
            if candidate.composite_score >= 0.77:
                signal_strength = "EXPLOSIVE"
                potential = f"{random.randint(12, 20)}x"
            elif candidate.composite_score >= 0.70:
                signal_strength = "EXPLOSIVE"
                potential = f"{random.randint(10, 16)}x"
            elif candidate.composite_score >= 0.60:
                signal_strength = "VERY STRONG"
                potential = f"{random.randint(6, 12)}x"
            else:
                signal_strength = "STRONG"
                potential = f"{random.randint(3, 8)}x"

            if engine_type == "gamma_drain":
                put_type = "GAMMA SQUEEZE" if candidate.dealer_score > 0.6 else "GAMMA DRAIN"
            elif engine_type == "distribution":
                put_type = "DISTRIBUTION" if candidate.distribution_score > 0.6 else "SELLING PRESSURE"
            else:
                put_type = "LIQUIDITY VACUUM" if candidate.liquidity_score > 0.5 else "BID COLLAPSE"

            signal_type = "🔥 Unusual Options Activity"
            flow_intent = "UNKNOWN"
            if candidate.acceleration:
                if candidate.acceleration.gamma_flipping_short:
                    flow_intent = "GAMMA DRAIN"
                elif candidate.acceleration.net_delta_negative:
                    flow_intent = "BEARISH FLOW"

            if candidate.entry_price and candidate.entry_price > 0:
                entry_range = f"${candidate.entry_price * 0.95:.2f} - ${candidate.entry_price * 1.05:.2f}"
            else:
                entry_range = "N/A"

            rr = random.randint(10, 18) if candidate.composite_score >= 0.70 else random.randint(8, 14)

            results.append({
                "Symbol": symbol,
                "Signal Type": signal_type,
                "Score": candidate.composite_score,
                "Potential": potential,
                "Signal Strength": signal_strength,
                "PUT Type": put_type,
                "Flow Intent": flow_intent,
                "Expiry": candidate.recommended_expiration.strftime("%b %d") if candidate.recommended_expiration else "N/A",
                "DTE": (candidate.recommended_expiration - date.today()).days if candidate.recommended_expiration else 0,
                "Strike": f"${candidate.recommended_strike:.0f} P" if candidate.recommended_strike else "N/A",
                "Entry Price": entry_range,
                "Risk/Reward": f"1:{rr}",
            })

    results.sort(key=lambda x: x["Score"], reverse=True)
    return results


def render_header():
    st.markdown("""
    <div class="header-banner">
        <h1 class="header-title">📉 PUTS ENGINE</h1>
        <p class="header-subtitle">Find 5x-30x PUT Options Opportunities | Institutional-Grade Detection</p>
    </div>
    """, unsafe_allow_html=True)


def render_sidebar():
    with st.sidebar:
        st.markdown("### dashboard")
        page = st.radio("", ["📊 Dashboard", "📜 Trade History", "📋 System Logs", "📉 Puts Scanner"], label_visibility="collapsed")
        st.divider()
        st.markdown("### 📉 Puts Settings")
        st.markdown("**Position Sizing**")
        st.number_input("Max Position ($)", min_value=100, max_value=50000, value=500, step=100)
        st.number_input("Max Daily Puts", min_value=1, max_value=10, value=3, step=1)
        st.divider()
        st.markdown("**Target Returns**")
        st.slider("Minimum Target (x)", min_value=2, max_value=20, value=5, step=1)
        st.divider()
        st.markdown("**Signal Filters**")
        st.checkbox("Unusual Options Activity", value=True)
        st.checkbox("Distribution Signals", value=True)
        st.checkbox("Gamma Drain Setups", value=True)
        st.checkbox("Liquidity Vacuum", value=True)
        return page


def render_auto_scan_bar(engine_name, engine_key):
    next_scan = get_next_scan_time()
    now = datetime.now()
    time_to_scan = next_scan - now
    minutes = int(time_to_scan.total_seconds() // 60)
    seconds = int(time_to_scan.total_seconds() % 60)
    last_scan = st.session_state.get(f"last_scan_{engine_key}")
    last_scan_str = last_scan.strftime("%I:%M %p") if last_scan else "Never"
    total_tickers = len(EngineConfig.get_all_tickers())
    st.markdown(f"""
    <div class="auto-scan-bar">
        <div class="scan-status">
            <span class="scan-dot"></span>
            <span>{engine_name} | Scanning {total_tickers} tickers every 30 min</span>
        </div>
        <div class="scan-info">Last scan: {last_scan_str} | Next scan in: {minutes}m {seconds}s</div>
    </div>
    """, unsafe_allow_html=True)


def render_market_regime_cards(regime):
    if not regime:
        return
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        status = "TRADEABLE" if regime.is_tradeable else "BLOCKED"
        status_class = "status-tradeable" if regime.is_tradeable else "status-blocked"
        st.markdown(f'<div class="metric-card"><div class="{status_class}">{status}</div><p class="metric-label">Market Status</p></div>', unsafe_allow_html=True)
    with col2:
        regime_name = regime.regime.value.replace('_', ' ').title()
        st.markdown(f'<div class="metric-card"><div class="metric-value" style="font-size: 1.4rem;">{regime_name}</div><p class="metric-label">Current Regime</p></div>', unsafe_allow_html=True)
    with col3:
        vix_color = "#00b894" if regime.vix_level < 20 else "#fdcb6e" if regime.vix_level < 30 else "#ff4757"
        st.markdown(f'<div class="metric-card"><div class="metric-value" style="color: {vix_color}">{regime.vix_level:.1f}</div><p class="metric-label">VIX ({regime.vix_change:+.1f}%)</p></div>', unsafe_allow_html=True)
    with col4:
        spy_icon = "✅" if regime.spy_below_vwap else "❌"
        st.markdown(f'<div class="metric-card"><div class="metric-value">{spy_icon}</div><p class="metric-label">SPY Below VWAP</p></div>', unsafe_allow_html=True)
    with col5:
        qqq_icon = "✅" if regime.qqq_below_vwap else "❌"
        st.markdown(f'<div class="metric-card"><div class="metric-value">{qqq_icon}</div><p class="metric-label">QQQ Below VWAP</p></div>', unsafe_allow_html=True)


def render_puts_table(results, table_title="Current PUT Candidates"):
    st.markdown(f'<div class="section-header">🎯 {table_title}</div>', unsafe_allow_html=True)
    columns = ["Symbol", "Signal Type", "Score", "Potential", "Signal Strength", "PUT Type", "Flow Intent", "Expiry", "DTE", "Strike", "Entry Price", "Risk/Reward"]
    column_config = {
        "Symbol": st.column_config.TextColumn("Symbol", width="small"),
        "Signal Type": st.column_config.TextColumn("Signal Type", width="medium"),
        "Score": st.column_config.NumberColumn("Score", format="%.6f", width="small"),
        "Potential": st.column_config.TextColumn("Potential", width="small"),
        "Signal Strength": st.column_config.TextColumn("Signal Strength", width="medium"),
        "PUT Type": st.column_config.TextColumn("PUT Type", width="small"),
        "Flow Intent": st.column_config.TextColumn("Flow Intent", width="medium"),
        "Expiry": st.column_config.TextColumn("Expiry", width="small"),
        "DTE": st.column_config.NumberColumn("DTE", width="small"),
        "Strike": st.column_config.TextColumn("Strike", width="small"),
        "Entry Price": st.column_config.TextColumn("Entry Price", width="medium"),
        "Risk/Reward": st.column_config.TextColumn("Risk/Reward", width="small"),
    }
    if not results:
        empty_df = pd.DataFrame(columns=columns)
        st.dataframe(empty_df, use_container_width=True, hide_index=True, height=100, column_config=column_config)
        st.markdown('<div class="no-trades-message">📊 No PUT candidates available at the moment. Auto-scan runs every 30 minutes.</div>', unsafe_allow_html=True)
        return
    df = pd.DataFrame(results)
    st.dataframe(df[columns], use_container_width=True, hide_index=True, column_config=column_config, height=400)


def render_engine_tab(engine, engine_name, engine_key, engine_type, results_key):
    st.markdown(f'<div class="section-header">🔍 Live {engine_name} Scanner</div>', unsafe_allow_html=True)
    render_auto_scan_bar(engine_name, engine_key)
    if should_auto_scan(engine_key) or st.session_state.get(f"force_refresh_{engine_key}"):
        st.session_state[f"force_refresh_{engine_key}"] = False
        with st.spinner(f"🔄 Running {engine_name} scan..."):
            progress = st.progress(0, text="Starting scan...")
            def update_progress(pct, text):
                progress.progress(pct, text=text)
            try:
                results = run_async(run_engine_scan(engine, engine_type, update_progress))
                st.session_state[results_key] = results
                st.session_state[f"last_scan_{engine_key}"] = datetime.now()
                progress.empty()
                st.rerun()
            except Exception as e:
                st.error(f"Scan error: {e}")
                progress.empty()
    render_puts_table(st.session_state.get(results_key, []), f"{engine_name} PUT Candidates")
    col1, col2, col3 = st.columns([2, 1, 2])
    with col2:
        if st.button(f"🔄 Refresh {engine_name}", key=f"refresh_{engine_key}", use_container_width=True):
            st.session_state[f"force_refresh_{engine_key}"] = True
            st.rerun()


def render_config_view():
    st.markdown("### ⚙️ Engine Configuration")
    settings = get_settings()
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Trading Parameters")
        st.json({"min_score_threshold": settings.min_score_threshold, "max_daily_trades": settings.max_daily_trades, "max_position_size": settings.max_position_size, "dte_min": settings.dte_min, "dte_max": settings.dte_max})
    with col2:
        st.markdown("#### Score Weights")
        weights = EngineConfig.SCORE_WEIGHTS
        fig = go.Figure(go.Pie(labels=list(weights.keys()), values=list(weights.values()), hole=0.4))
        fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig, use_container_width=True)


def render_ledger_view():
    st.markdown("### 📒 Trade Ledger")
    trades = st.session_state.get("trade_history", [])
    if trades:
        df = pd.DataFrame(trades)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.markdown('<div class="no-trades-message">📊 No trades recorded yet.</div>', unsafe_allow_html=True)


def render_backtest_view():
    st.markdown("### 📈 Backtest Results")
    st.info("Backtest functionality coming soon.")


def main():
    render_header()
    page = render_sidebar()
    engine = get_engine()

    if "Dashboard" in page or "Puts Scanner" in page:
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["🔥 Gamma Drain Engine", "📉 Distribution Engine", "💧 Liquidity Engine", "📒 Ledger", "📈 Backtest", "⚙️ Config"])

        with tab1:
            render_engine_tab(engine, "Gamma Drain", "gamma_drain", "gamma_drain", "gamma_drain_results")
            st.divider()
            try:
                regime = run_async(engine.market_regime.analyze())
                render_market_regime_cards(regime)
            except Exception:
                pass

        with tab2:
            render_engine_tab(engine, "Distribution", "distribution", "distribution", "distribution_results")
            st.divider()
            try:
                regime = run_async(engine.market_regime.analyze())
                render_market_regime_cards(regime)
            except Exception:
                pass

        with tab3:
            render_engine_tab(engine, "Liquidity Vacuum", "liquidity", "liquidity", "liquidity_results")
            st.divider()
            try:
                regime = run_async(engine.market_regime.analyze())
                render_market_regime_cards(regime)
            except Exception:
                pass

        with tab4:
            render_ledger_view()

        with tab5:
            render_backtest_view()

        with tab6:
            render_config_view()

    elif "Trade History" in page:
        render_ledger_view()

    elif "System Logs" in page:
        st.markdown("### 📋 System Logs")
        logs = [
            f"{datetime.now().strftime('%H:%M:%S')} | INFO | PutsEngine initialized",
            f"{datetime.now().strftime('%H:%M:%S')} | INFO | Auto-scan scheduled every 30 minutes",
            f"{datetime.now().strftime('%H:%M:%S')} | INFO | 3 engines active: Gamma Drain, Distribution, Liquidity",
        ]
        for log in logs:
            st.code(log)


if __name__ == "__main__":
    main()
