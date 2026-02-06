"""
🎯 PREDICTIVE SYSTEM TAB v3 - TRULY PREDICTIVE
==============================================
Isolated dashboard tab for PREDICTIVE crash detection

Goal: Display TOP 10 stocks PREDICTED to crash in next 1-2 days
Target: 8/10 success rate

CRITICAL DISTINCTION:
- REACTIVE (useless): Price patterns like exhaustion, breakdown (triggers AFTER crash)
- PREDICTIVE (valuable): IPI scores from dark pool + options flow (detects BEFORE crash)

THIS TAB USES ONLY PREDICTIVE DATA:
- EWS IPI (Institutional Pressure Index)
- Dark pool selling activity
- Options flow patterns

High IPI = institutions are selling NOW, but price hasn't dropped yet = OPPORTUNITY
"""

import streamlit as st
import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd


def load_predictive_data() -> Optional[Dict]:
    """Load predictive analysis from cache"""
    try:
        path = Path("logs/predictive_analysis.json")
        if path.exists():
            with open(path, 'r') as f:
                return json.load(f)
    except Exception as e:
        st.error(f"Error loading predictive data: {e}")
    return None


def run_predictive_engine():
    """Run the predictive engine (async wrapper)"""
    try:
        from putsengine.predictive_engine import PredictiveEngine
        engine = PredictiveEngine()
        return asyncio.run(engine.run())
    except Exception as e:
        st.error(f"Engine error: {e}")
        return None


def get_confidence_color(confidence: str) -> str:
    """Get color for confidence level"""
    colors = {
        "BULLETPROOF": "#ff0000",  # Bright red - highest
        "HIGH": "#ff4444",          # Red
        "MEDIUM": "#ffaa00",        # Orange
        "LOW": "#888888"            # Gray
    }
    return colors.get(confidence, "#888888")


def get_crash_bar(probability: float) -> str:
    """Create visual crash probability bar"""
    filled = int(probability * 10)
    bar = "█" * filled + "░" * (10 - filled)
    return bar


def render_predictive_tab():
    """Render the Predictive System tab"""
    
    st.markdown("""
    <style>
    .pred-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 20px;
        border: 1px solid #e94560;
    }
    .pred-title {
        color: #e94560;
        font-size: 28px;
        font-weight: bold;
        margin-bottom: 5px;
    }
    .pred-subtitle {
        color: #aaa;
        font-size: 14px;
    }
    .engine-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 11px;
        margin-right: 4px;
    }
    .engine-gamma { background: #4a1a4a; color: #e94560; }
    .engine-dist { background: #1a3a4a; color: #4a9eff; }
    .engine-liq { background: #1a4a2a; color: #44ff88; }
    .bulletproof { background: #5a0a0a; color: #ff4444; font-weight: bold; }
    .high-conf { background: #4a1a1a; color: #ff6666; }
    .med-conf { background: #4a3a1a; color: #ffaa00; }
    .low-conf { background: #2a2a2a; color: #888888; }
    </style>
    """, unsafe_allow_html=True)
    
    # Header
    st.markdown("""
    <div class="pred-header">
        <div class="pred-title">🎯 PREDICTIVE SYSTEM v3 - TRULY PREDICTIVE</div>
        <div class="pred-subtitle">
            Uses ONLY predictive signals (EWS IPI) | Detects crashes BEFORE they happen | NOT reactive price patterns
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Explanation banner
    st.info("""
    **How this differs from other tabs:**
    - **Gamma Drain/Distribution/Liquidity** = REACTIVE (detect patterns AFTER price drops)
    - **This Predictive System** = Uses IPI scores (dark pool + options flow) to predict crashes BEFORE they happen
    
    High IPI means institutions are selling NOW, but price hasn't dropped yet. These are your TOMORROW picks.
    """)
    
    # Controls
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("🔄 Run Analysis", key="run_pred"):
            with st.spinner("Scanning IPI scores..."):
                result = run_predictive_engine()
                if result:
                    st.success("Analysis complete!")
                    st.rerun()
    with col2:
        auto_refresh = st.checkbox("Auto-refresh", value=False, key="pred_auto")
    with col3:
        st.caption("📡 Uses EWS IPI data (dark pool + options flow) - TRULY PREDICTIVE")
    
    # Load data
    data = load_predictive_data()
    
    if not data:
        st.warning("No predictive analysis data available. Click 'Run Analysis' to generate predictions.")
        
        # Load EWS stats
        try:
            with open("early_warning_alerts.json") as f:
                ews = json.load(f)
            ews_count = len(ews.get("alerts", {}))
            ews_ts = ews.get("timestamp", "Unknown")
            st.markdown("### 📊 Available EWS Data (Source for Predictions)")
            st.metric("EWS Alerts", f"{ews_count} tickers")
            st.caption(f"Last EWS scan: {ews_ts}")
        except Exception:
            pass
        return
    
    # Display timestamp
    timestamp = datetime.fromisoformat(data['timestamp'])
    age_seconds = (datetime.now() - timestamp).total_seconds()
    age_str = f"{int(age_seconds // 60)}m ago" if age_seconds < 3600 else f"{int(age_seconds // 3600)}h ago"
    
    # Get EWS timestamp (the actual data source)
    ews_timestamp = data.get('ews_timestamp', 'Unknown')
    methodology = data.get('methodology', 'EWS IPI Only')
    
    summary = data.get('summary', {})
    data_sources = summary.get('data_sources', {})
    
    # Data Source Info
    st.markdown("### 📊 Data Source: EWS IPI (Truly Predictive)")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("EWS Alerts", f"{data_sources.get('ews_alerts_count', 0)} tickers")
    with col2:
        st.metric("Analysis Updated", age_str)
    with col3:
        st.metric("Methodology", methodology[:15] + "...")
        
    st.caption(f"EWS data from: {ews_timestamp}")
    
    st.divider()
    
    # Confidence Summary - Based on IPI scores
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div style="background: #4a0a0a; padding: 15px; border-radius: 8px; text-align: center;">
            <div style="font-size: 36px; color: #ff0000; font-weight: bold;">{summary.get('very_high_confidence', summary.get('bulletproof', 0))}</div>
            <div style="color: #ff6666;">VERY HIGH</div>
            <div style="color: #888; font-size: 10px;">IPI > 85%</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div style="background: #3a0a0a; padding: 15px; border-radius: 8px; text-align: center;">
            <div style="font-size: 36px; color: #ff4444; font-weight: bold;">{summary.get('high_confidence', 0)}</div>
            <div style="color: #ff8888;">HIGH</div>
            <div style="color: #888; font-size: 10px;">IPI 70-85%</div>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
        <div style="background: #2a1a0a; padding: 15px; border-radius: 8px; text-align: center;">
            <div style="font-size: 36px; color: #ffaa00; font-weight: bold;">{summary.get('medium_confidence', 0)}</div>
            <div style="color: #ffcc66;">MEDIUM</div>
            <div style="color: #888; font-size: 10px;">IPI 55-70%</div>
        </div>
        """, unsafe_allow_html=True)
    with col4:
        st.markdown(f"""
        <div style="background: #0a2a0a; padding: 15px; border-radius: 8px; text-align: center;">
            <div style="font-size: 24px; color: #44ff44;">PREDICTIVE</div>
            <div style="color: #88ff88;">Not Reactive</div>
            <div style="color: #888; font-size: 10px;">IPI before crash</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    
    # Main predictions table
    st.markdown("### 🎯 TOP 10 PREDICTIVE CRASH CANDIDATES")
    st.caption("⚠️ These stocks show institutional selling NOW but haven't crashed yet. They are PREDICTED to drop.")
    
    predictions = data.get('predictions', [])
    
    if not predictions:
        st.info("No high-probability candidates found. Click 'Run Analysis' to scan IPI scores.")
        return
    
    # Create DataFrame for display
    df_data = []
    for i, pred in enumerate(predictions, 1):
        ipi = pred.get('combined_score', pred.get('scores', {}).get('ipi', 0))
        conf = pred['confidence']
        signals = pred.get('signals', [])
        
        df_data.append({
            "Rank": i,
            "Symbol": pred['symbol'],
            "IPI Score": f"{ipi:.0%}",
            "Confidence": conf,
            "Expected Drop": pred['expected_drop'],
            "Timeframe": pred.get('timeframe', '1-2 days'),
            "Top Signal": signals[0][:30] if signals else "Institutional pressure"
        })
    
    df = pd.DataFrame(df_data)
    
    # Style the dataframe
    def color_confidence(val):
        colors = {
            "VERY HIGH": "background-color: #4a0a0a; color: #ff0000; font-weight: bold",
            "HIGH": "background-color: #3a0a0a; color: #ff4444",
            "MEDIUM": "background-color: #3a2a0a; color: #ffaa00",
            "LOW": "background-color: #2a2a2a; color: #888888"
        }
        return colors.get(val, "")
    
    styled_df = df.style.applymap(color_confidence, subset=['Confidence'])
    st.dataframe(styled_df, use_container_width=True, height=420)
    
    st.divider()
    
    # Detailed view
    st.markdown("### 📋 WHY THESE ARE PREDICTIVE")
    
    # Show expandable details for each prediction
    for i, pred in enumerate(predictions[:5], 1):
        ipi = pred.get('combined_score', pred.get('scores', {}).get('ipi', 0))
        
        conf_emoji = "🔴🔴🔴" if pred['confidence'] == "VERY HIGH" else "🔴🔴" if pred['confidence'] == "HIGH" else "🟡" if pred['confidence'] == "MEDIUM" else "⚪"
        
        with st.expander(f"#{i} {conf_emoji} {pred['symbol']} - IPI {ipi:.0%} ({pred['confidence']})"):
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**Predictive Scores:**")
                scores = pred.get('scores', {})
                
                ipi_score = scores.get('ipi', ipi)
                dark_pool = scores.get('dark_pool', 0)
                options_flow = scores.get('options_flow', 0)
                
                st.progress(ipi_score, text=f"🎯 IPI (Institutional Pressure): {ipi_score:.0%}")
                if dark_pool > 0:
                    st.progress(dark_pool, text=f"🏦 Dark Pool Selling: {dark_pool:.0%}")
                if options_flow > 0:
                    st.progress(options_flow, text=f"📊 Options Flow: {options_flow:.0%}")
                
            with col2:
                st.markdown("**Why Predictive:**")
                st.markdown("• IPI measures institutional selling BEFORE price drops")
                st.markdown("• High IPI = smart money exiting NOW")
                st.markdown("• Price hasn't dropped yet = OPPORTUNITY")
                    
                st.markdown("**Signals:**")
                signals = pred.get('signals', [])
                for sig in signals[:3]:
                    st.markdown(f"• {sig}")
                    
                st.markdown("**Expected:**")
                st.markdown(f"• Drop: `{pred['expected_drop']}`")
                st.markdown(f"• Timeframe: `{pred.get('timeframe', '1-2 days')}`")
                st.markdown(f"• Potential: `{pred.get('potential_mult', '3x-10x')}`")
    
    # Disclaimer
    st.divider()
    st.markdown("""
    <div style="background: #0a2a1a; padding: 15px; border-radius: 8px; border: 1px solid #2a4a3a;">
        <div style="color: #44ff88; font-weight: bold;">🎯 WHY THIS IS PREDICTIVE (NOT REACTIVE)</div>
        <div style="color: #aaa; font-size: 12px; margin-top: 10px;">
            <b>REACTIVE signals (other tabs) = detect AFTER crash:</b><br>
            • exhaustion, below_prior_low, pump_reversal - triggered AFTER price drops<br><br>
            <b>PREDICTIVE signals (this tab) = detect BEFORE crash:</b><br>
            • IPI (Institutional Pressure Index) = dark pool selling BEFORE drop<br>
            • Options flow = put buying BEFORE drop<br><br>
            <b>How to use:</b><br>
            • 🔴🔴🔴 VERY HIGH (IPI > 85%) = Institutions selling heavily, crash imminent<br>
            • 🔴🔴 HIGH (IPI 70-85%) = Strong institutional selling, watch closely<br>
            • 🟡 MEDIUM (IPI 55-70%) = Moderate selling, potential drop<br><br>
            <b>Data Source:</b> EWS IPI scores from dark pool + options flow data
        </div>
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    st.set_page_config(page_title="Predictive System", layout="wide")
    render_predictive_tab()
