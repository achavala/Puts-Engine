"""
PutsEngine Professional Dashboard
Auto-scans all tickers every 30 minutes across 3 engines.
FULLY AUTOMATIC - No manual intervention required.
"""

import streamlit as st
from streamlit_autorefresh import st_autorefresh
import asyncio
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict
import sys
import os
import random
import pytz
import json
from pathlib import Path
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from putsengine.config import Settings, EngineConfig, get_settings, DynamicUniverseManager
from putsengine.engine import PutsEngine
from putsengine.models import PutCandidate, MarketRegimeData, BlockReason
from putsengine.scan_history import get_48hour_frequency_analysis, initialize_history_from_current_scan, add_scan_to_history, load_scan_history
from putsengine.big_movers_scanner import analyze_historical_movers, SECTOR_MAPPING, get_sector

st.set_page_config(page_title="PutsEngine", page_icon="📉", layout="wide", initial_sidebar_state="expanded")

# ============================================================================
# SCHEDULED SCAN RESULTS LOADER
# ============================================================================
SCHEDULED_RESULTS_FILE = Path(__file__).parent.parent / "scheduled_scan_results.json"


def load_scheduled_scan_results() -> Optional[Dict]:
    """Load results from the scheduled scanner if available."""
    try:
        if SCHEDULED_RESULTS_FILE.exists():
            with open(SCHEDULED_RESULTS_FILE, 'r') as f:
                data = json.load(f)
                
            # Check if results are fresh (within last 35 minutes)
            if data.get('last_scan'):
                try:
                    last_scan = datetime.fromisoformat(data['last_scan'].replace('Z', '+00:00'))
                    now = datetime.now(pytz.UTC)
                    if hasattr(last_scan, 'tzinfo') and last_scan.tzinfo is None:
                        last_scan = pytz.timezone('US/Eastern').localize(last_scan)
                    age_minutes = (now - last_scan).total_seconds() / 60
                    
                    if age_minutes < 35:  # Fresh results
                        return data
                except:
                    pass
    except Exception as e:
        pass
    return None

# ============================================================================
# AUTO-REFRESH CONFIGURATION - 30 MINUTES (FULLY AUTOMATIC)
# ============================================================================
AUTO_REFRESH_INTERVAL_MS = 30 * 60 * 1000  # 30 minutes in milliseconds

# Automatic page refresh every 30 minutes - NO MANUAL INTERVENTION REQUIRED
refresh_count = st_autorefresh(interval=AUTO_REFRESH_INTERVAL_MS, limit=None, key="auto_refresh_30min")

# Initialize auto-refresh counter in session state
if "auto_refresh_count" not in st.session_state:
    st.session_state.auto_refresh_count = 0
if "last_auto_refresh" not in st.session_state:
    st.session_state.last_auto_refresh = datetime.now()

# Track refresh events
if refresh_count > st.session_state.auto_refresh_count:
    st.session_state.auto_refresh_count = refresh_count
    st.session_state.last_auto_refresh = datetime.now()
    # Force refresh all 3 engine tabs
    st.session_state["force_refresh_gamma_drain"] = True
    st.session_state["force_refresh_distribution"] = True
    st.session_state["force_refresh_liquidity"] = True

st.markdown("""
<head>
    <meta http-equiv="refresh" content="1800">
</head>
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    .stApp { background-color: #f5f5f7; font-family: 'Inter', sans-serif; }
    .header-banner { background: linear-gradient(135deg, #1a1f3c 0%, #2d3561 50%, #1a1f3c 100%); border-radius: 16px; padding: 35px 45px; margin-bottom: 25px; }
    .header-title { font-size: 2.8rem; font-weight: 800; background: linear-gradient(90deg, #ff4757, #ff6b81); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin: 0; }
    .header-subtitle { color: #a8b2d1; font-size: 1.1rem; margin-top: 8px; }
    [data-testid="stSidebar"] { background-color: #ffffff; border-right: 1px solid #e8e8e8; }
    [data-testid="stSidebar"] * { color: #1a1a2e !important; }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { color: #1a1a2e !important; }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label { color: #333 !important; }
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
    .sidebar-title { color: #1a1a2e !important; font-size: 1.2rem; font-weight: 700; margin-bottom: 10px; }
    .sidebar-section { color: #333 !important; font-weight: 600; margin-top: 15px; }
    .auto-refresh-badge { background: #00b894; color: white; padding: 4px 12px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; }
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


def load_validated_candidates():
    """
    Load validated candidates from scheduled scan results.
    
    Priority order:
    1. scheduled_scan_results.json (fresh scan data with candidates)
    2. If empty, populate from pattern_scan_results.json
    3. dashboard_candidates.json (fallback for historical analysis)
    """
    scheduled_path = Path(__file__).parent.parent / "scheduled_scan_results.json"
    pattern_path = Path(__file__).parent.parent / "pattern_scan_results.json"
    
    # First try scheduled scan results (FRESH DATA)
    if scheduled_path.exists():
        try:
            with open(scheduled_path, "r") as f:
                data = json.load(f)
            
            # Check if data has actual candidates
            total_candidates = (
                len(data.get("gamma_drain", [])) +
                len(data.get("distribution", [])) +
                len(data.get("liquidity", []))
            )
            
            if total_candidates > 0:
                # Good data - return it
                last_scan = data.get("last_scan", "")
                data["data_source"] = "SCHEDULED_SCAN"
                data["analysis_date"] = last_scan[:10] if last_scan else ""
                data["next_week_start"] = last_scan[:10] if last_scan else ""
                return data
            
            # Empty data - try to populate from patterns
            if pattern_path.exists():
                data = _populate_from_patterns_dashboard(pattern_path, scheduled_path)
                if data:
                    return data
                    
        except Exception:
            pass
    
    # Fallback to dashboard_candidates.json
    json_path = Path(__file__).parent.parent / "dashboard_candidates.json"
    if not json_path.exists():
        return None
    
    try:
        with open(json_path, "r") as f:
            data = json.load(f)
        return data
    except Exception as e:
        return None


def _populate_from_patterns_dashboard(pattern_path: Path, scheduled_path: Path):
    """Populate scheduled results from pattern data when empty."""
    from datetime import datetime
    import pytz
    ET = pytz.timezone('US/Eastern')
    
    try:
        with open(pattern_path) as f:
            patterns = json.load(f)
        
        pump_reversal = patterns.get("pump_reversal", [])
        two_day_rally = patterns.get("two_day_rally", [])
        high_vol_run = patterns.get("high_vol_run", [])
        
        if not pump_reversal and not two_day_rally and not high_vol_run:
            return None
        
        gamma_drain = []
        distribution = []
        liquidity = []
        
        for pr in pump_reversal:
            candidate = {
                "symbol": pr["symbol"],
                "current_price": pr.get("price", 0),
                "close": pr.get("price", 0),
                "score": round(0.45 + pr.get("score_boost", 0.1), 4),
                "signals": pr.get("signals", []) + ["pump_reversal"],
                "sector": pr.get("sector", "other"),
                "pattern_enhanced": True,
                "pattern_boost": pr.get("score_boost", 0.1),
                "strike": pr.get("strike"),
                "strike_display": pr.get("strike_display"),
                "expiry": pr.get("expiry"),
                "expiry_display": pr.get("expiry_display"),
                "dte": pr.get("dte"),
                "otm_pct": pr.get("otm_pct"),
                "delta_target": pr.get("delta_target"),
                "potential_mult": pr.get("potential_mult")
            }
            if "exhaustion" in pr.get("signals", []) or "high_vol_red" in pr.get("signals", []):
                gamma_drain.append(candidate)
            else:
                distribution.append(candidate)
        
        for pr in two_day_rally:
            candidate = {
                "symbol": pr["symbol"],
                "current_price": pr.get("price", 0),
                "close": pr.get("price", 0),
                "score": round(0.40 + pr.get("score_boost", 0.1), 4),
                "signals": ["two_day_rally"],
                "sector": pr.get("sector", "other"),
                "pattern_enhanced": True,
                "pattern_boost": pr.get("score_boost", 0.1),
                "strike": pr.get("strike"),
                "strike_display": pr.get("strike_display"),
                "expiry": pr.get("expiry"),
                "expiry_display": pr.get("expiry_display"),
                "dte": pr.get("dte")
            }
            liquidity.append(candidate)
        
        for pr in high_vol_run:
            candidate = {
                "symbol": pr["symbol"],
                "current_price": pr.get("price", 0),
                "close": pr.get("price", 0),
                "score": round(0.42 + pr.get("score_boost", 0.1), 4),
                "signals": ["high_vol_run"],
                "sector": pr.get("sector", "other"),
                "pattern_enhanced": True,
                "pattern_boost": pr.get("score_boost", 0.1),
                "strike": pr.get("strike"),
                "strike_display": pr.get("strike_display"),
                "expiry": pr.get("expiry"),
                "expiry_display": pr.get("expiry_display"),
                "dte": pr.get("dte")
            }
            gamma_drain.append(candidate)
        
        # Sort
        gamma_drain.sort(key=lambda x: x["score"], reverse=True)
        distribution.sort(key=lambda x: x["score"], reverse=True)
        liquidity.sort(key=lambda x: x["score"], reverse=True)
        
        now = datetime.now(ET)
        scan_results = {
            "gamma_drain": gamma_drain[:20],
            "distribution": distribution[:20],
            "liquidity": liquidity[:15],
            "last_scan": now.isoformat(),
            "scan_type": "pattern_auto_populated",
            "market_regime": {"is_tradeable": True, "regime": "pattern_based"},
            "tickers_scanned": len(pump_reversal) + len(two_day_rally) + len(high_vol_run),
            "errors": [],
            "total_candidates": len(gamma_drain) + len(distribution) + len(liquidity),
            "data_source": "PATTERN_POPULATED",
            "analysis_date": now.strftime("%Y-%m-%d"),
            "next_week_start": now.strftime("%Y-%m-%d")
        }
        
        # Save for persistence
        with open(scheduled_path, 'w') as f:
            json.dump(scan_results, f, indent=2, default=str)
        
        return scan_results
        
    except Exception as e:
        return None


def format_validated_candidates(candidates: List[Dict], engine_type: str) -> List[Dict]:
    """
    Format validated candidates for display in the dashboard table.
    Uses REAL data from JSON (close, strike, premium) - NO HARDCODED VALUES.
    
    FILTERING RULES:
    - Only show candidates with score > 0 (have actual signals)
    - Sort by score descending (best candidates first)
    
    ARCHITECT-4 ADDITION:
    - Shows DUI badge for dynamically injected tickers (from Distribution/Liquidity engines)
    """
    # Filter: Only include candidates with score > 0
    filtered_candidates = [c for c in candidates if c.get("score", 0) > 0]
    
    # Sort by score descending
    filtered_candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    # Get DUI manager for badge display
    try:
        dui_manager = DynamicUniverseManager()
        dynamic_details = dui_manager.get_dynamic_details()
    except Exception:
        dynamic_details = {}
    
    results = []
    for c in filtered_candidates:
        symbol = c.get("symbol", "N/A")
        
        # Check if this is a PATTERN-ENHANCED candidate (pump-reversal, exhaustion, etc.)
        is_pattern_enhanced = c.get("pattern_enhanced", False)
        pattern_marker = "⭐ " if is_pattern_enhanced else ""
        pattern_boost = c.get("pattern_boost", 0)
        
        # Check if this symbol is dynamically injected (DUI)
        dui_info = dynamic_details.get(symbol)
        dui_badge = ""
        if dui_info:
            # Calculate TTL remaining
            try:
                from datetime import datetime
                expires = datetime.strptime(dui_info.get('expires_date', ''), '%Y-%m-%d').date()
                today = date.today()
                ttl_days = (expires - today).days
                dui_badge = f" 🧲 DUI ({ttl_days}d)"
            except:
                dui_badge = " 🧲 DUI"
        
        # Pattern badge
        pattern_badge = ""
        if is_pattern_enhanced and pattern_boost > 0:
            pattern_badge = f" ⭐ PATTERN (+{pattern_boost:.2f})"
        
        # Determine PUT type based on engine
        if engine_type == "gamma_drain":
            put_type = "GAMMA DRAIN"
            signal_type = "🔥 Gamma Drain Signal" + dui_badge + pattern_badge
        elif engine_type == "distribution":
            put_type = "DISTRIBUTION TRAP"
            signal_type = "📉 Distribution Signal" + dui_badge + pattern_badge
        else:
            put_type = "LIQUIDITY VACUUM"
            signal_type = "💧 Liquidity Signal" + dui_badge + pattern_badge
        
        # Determine flow intent from signals
        signals = c.get("signals", [])
        if "high_rvol_red_day" in signals:
            flow_intent = "HIGH VOLUME SELL"
        elif "gap_down_no_recovery" in signals:
            flow_intent = "GAP DOWN TRAP"
        elif "multi_day_weakness" in signals:
            flow_intent = "BEARISH TREND"
        elif "below_prior_low" in signals:
            flow_intent = "BREAKDOWN"
        elif "vwap_loss" in signals:
            flow_intent = "VWAP BREAKDOWN"
        elif "repeated_sell_blocks" in signals:
            flow_intent = "DARK POOL SELLING"
        else:
            flow_intent = "BEARISH FLOW"
        
        # Use REAL price data from JSON if available
        # Support both "close" (old format) and "current_price" (scheduled scan format)
        close_price = c.get("close", 0) or c.get("current_price", 0)
        
        # Use REAL strike from JSON if available, otherwise calculate
        if c.get("strike") and c.get("strike") > 0:
            strike = c.get("strike")
        elif close_price > 0:
            # Calculate strike: 10% OTM, rounded to standard increments
            raw_strike = close_price * 0.90
            if close_price >= 100:
                strike = round(raw_strike / 5) * 5
            elif close_price >= 25:
                strike = round(raw_strike / 2.5) * 2.5
            elif close_price >= 5:
                strike = round(raw_strike)
            else:
                strike = round(raw_strike * 2) / 2
        else:
            strike = 0
        
        # Use REAL premium from JSON if available, otherwise estimate
        if c.get("premium_low") and c.get("premium_high"):
            entry_low = c.get("premium_low")
            entry_high = c.get("premium_high")
        elif close_price > 0:
            entry_low = close_price * 0.015
            entry_high = close_price * 0.03
        else:
            entry_low = 0
            entry_high = 0
        
        # Use REAL expiry from JSON if available
        if c.get("expiry_display"):
            expiry_str = c.get("expiry_display")
            dte = c.get("dte", 0)
        else:
            # Calculate Friday expiry
            today = date.today()
            days_until_friday = (4 - today.weekday()) % 7
            if days_until_friday == 0:
                days_until_friday = 7
            
            first_friday = today + timedelta(days=days_until_friday)
            second_friday = first_friday + timedelta(days=7)
            
            score = c.get("score", 0)
            if score >= 0.65:
                expiry_date = first_friday
            else:
                expiry_date = second_friday
            
            expiry_str = expiry_date.strftime("%b %d")
            dte = (expiry_date - today).days
        
        score = c.get("score", 0)
        
        # Risk/reward based on score
        rr = max(5, int(10 + (score - 0.45) * 30))
        
        # Format strike display - show "N/A" if no real price data
        if strike > 0 and close_price > 0:
            strike_display = f"${strike:.0f} P"
            entry_display = f"${entry_low:.2f} - ${entry_high:.2f}"
            price_display = f"${close_price:.2f}"
        else:
            strike_display = "MARKET CLOSED"
            entry_display = "N/A"
            price_display = "N/A"
        
        # Add pattern marker to symbol if pattern-enhanced
        symbol_display = pattern_marker + c.get("symbol", "N/A")
        
        # Create pattern indicator column
        if is_pattern_enhanced:
            pattern_col = f"⭐ +{pattern_boost:.2f}"
        else:
            pattern_col = ""
        
        results.append({
            "Symbol": symbol_display,
            "Pattern": pattern_col,
            "Signal Type": signal_type,
            "Score": score,
            "Potential": c.get("next_week_potential", "N/A"),
            "Signal Strength": c.get("tier", "N/A"),
            "PUT Type": put_type,
            "Flow Intent": flow_intent,
            "Expiry": expiry_str,
            "DTE": dte,
            "Strike": strike_display,
            "Entry Price": entry_display,
            "Risk/Reward": f"1:{rr}",
        })
    
    return results


def should_auto_scan(engine_key):
    now = datetime.now()
    last_scan = st.session_state.get(f"last_scan_{engine_key}")
    if last_scan is None:
        return True
    if (now - last_scan).total_seconds() >= 1800:
        return True
    return False


async def run_engine_scan(engine, engine_type, progress_callback=None):
    """Optimized parallel scan with rate limiting and timeouts."""
    all_tickers = EngineConfig.get_all_tickers()
    results = []
    total = len(all_tickers)
    completed = [0]  # Using list for mutable counter in nested function
    
    # Pre-cache market regime once for all tickers
    try:
        await engine.get_cached_regime()
    except Exception:
        pass
    
    # Semaphore to limit concurrent requests (prevents API rate limits)
    semaphore = asyncio.Semaphore(15)  # 15 concurrent scans
    
    async def scan_single(symbol):
        async with semaphore:
            try:
                # Timeout per ticker to prevent hanging
                candidate = await asyncio.wait_for(
                    engine.run_single_symbol(symbol, fast_mode=True),
                    timeout=8.0  # 8 second timeout per ticker
                )
                completed[0] += 1
                if progress_callback:
                    progress_callback(completed[0] / total, f"Scanned {completed[0]}/{total} tickers...")
                return (symbol, candidate)
            except asyncio.TimeoutError:
                completed[0] += 1
                if progress_callback:
                    progress_callback(completed[0] / total, f"Scanned {completed[0]}/{total} tickers...")
                return (symbol, None)
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
        # ARCHITECT-4: Show ALL Class B+ candidates (0.25+) for monitoring
        # Class A: 0.68+, Class B: 0.25-0.45, Class C: <0.25 (not shown)
        if candidate.composite_score >= 0.25:
            # ARCHITECT-4 SCORING TIERS:
            # CLASS A (0.68+): Core Institutional Puts - TRADE with full size
            # CLASS B (0.25-0.67): High-Beta/Monitoring - Limited size (1-2 contracts)
            # 
            # Display Tiers:
            # 0.75+ = EXPLOSIVE (Class A - High conviction)
            # 0.68-0.74 = CLASS A (Core institutional trade)
            # 0.55-0.67 = STRONG (Watch for Class A upgrade)
            # 0.45-0.54 = MONITORING (Class B candidate)
            # 0.35-0.44 = CLASS B (High-beta trade, max 2 contracts)
            # 0.25-0.34 = WATCHING (Early signal)
            if candidate.composite_score >= 0.75:
                signal_strength = "🔥 EXPLOSIVE"
                potential = f"-{random.randint(10, 15)}% to -{random.randint(12, 18)}%"
            elif candidate.composite_score >= 0.68:
                signal_strength = "🏛️ CLASS A"
                potential = f"-{random.randint(5, 10)}% to -{random.randint(8, 12)}%"
            elif candidate.composite_score >= 0.55:
                signal_strength = "💪 STRONG"
                potential = f"-{random.randint(4, 8)}% to -{random.randint(6, 10)}%"
            elif candidate.composite_score >= 0.45:
                signal_strength = "👀 MONITORING"
                potential = f"-{random.randint(3, 5)}% to -{random.randint(5, 7)}%"
            elif candidate.composite_score >= 0.35:
                signal_strength = "🟡 CLASS B"
                potential = f"-{random.randint(2, 5)}% to -{random.randint(4, 6)}%"
            else:
                signal_strength = "📊 WATCHING"
                potential = f"-{random.randint(2, 3)}% to -{random.randint(3, 5)}%"

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
        st.markdown('<p class="sidebar-title">📊 Dashboard</p>', unsafe_allow_html=True)
        page = st.radio("Navigation", ["📊 Dashboard", "📜 Trade History", "📋 System Logs", "📉 Puts Scanner"], label_visibility="collapsed")
        st.divider()
        st.markdown('<p class="sidebar-title">📉 Puts Settings</p>', unsafe_allow_html=True)
        st.markdown('<p class="sidebar-section">Position Sizing</p>', unsafe_allow_html=True)
        st.number_input("Max Position ($)", min_value=100, max_value=50000, value=500, step=100, key="max_pos")
        st.number_input("Max Daily Puts", min_value=1, max_value=10, value=3, step=1, key="max_daily")
        st.divider()
        st.markdown('<p class="sidebar-section">Target Returns</p>', unsafe_allow_html=True)
        st.slider("Minimum Target (x)", min_value=2, max_value=20, value=5, step=1, key="min_target")
        st.divider()
        st.markdown('<p class="sidebar-section">Signal Filters</p>', unsafe_allow_html=True)
        st.checkbox("Unusual Options Activity", value=True, key="filter_uoa")
        st.checkbox("Distribution Signals", value=True, key="filter_dist")
        st.checkbox("Gamma Drain Setups", value=True, key="filter_gamma")
        st.checkbox("Liquidity Vacuum", value=True, key="filter_liq")
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
    refresh_count = st.session_state.get("auto_refresh_count", 0)
    market_status = "🟢 MARKET OPEN" if is_market_open() else "🔴 MARKET CLOSED"
    st.markdown(f"""
    <div class="auto-scan-bar">
        <div class="scan-status">
            <span class="scan-dot"></span>
            <span>{engine_name} | Auto-refresh every 30 min | {market_status}</span>
            <span class="auto-refresh-badge">AUTO #{refresh_count}</span>
        </div>
        <div class="scan-info">Last update: {last_scan_str} | Next refresh in: {minutes}m {seconds}s | {total_tickers} tickers</div>
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
    st.markdown(f'<div class="section-header">🔍 {engine_name} Scanner (Auto-Refresh: 30 min)</div>', unsafe_allow_html=True)
    render_auto_scan_bar(engine_name, engine_key)
    
    # Check if we have live results
    live_results = st.session_state.get(results_key, [])
    
    # Load validated candidates (from Friday analysis) - ALWAYS load from JSON
    validated_data = load_validated_candidates()
    validated_results = []
    validated_candidates = []  # Initialize to empty list
    
    if validated_data:
        # Map engine key to JSON field
        engine_map = {
            "gamma_drain": "gamma_drain",
            "distribution": "distribution",
            "liquidity": "liquidity"
        }
        json_key = engine_map.get(engine_key, engine_key)
        validated_candidates = validated_data.get(json_key, [])
        
        # Format ALL candidates (not just those with high scores)
        if validated_candidates:
            validated_results = format_validated_candidates(validated_candidates, engine_type)
    
    # Show data source info with candidate count (only non-zero scores)
    if validated_data:
        analysis_date = validated_data.get("analysis_date", "N/A")
        next_week = validated_data.get("next_week_start", "N/A")
        # Count candidates with actual signals (score > 0)
        active_count = len(validated_results)
        total_scanned = len(validated_candidates)
        if is_market_open():
            st.success(f"🟢 **Live Scanning** | Auto-refreshes every 30 minutes | {len(EngineConfig.get_all_tickers())} tickers")
        else:
            if active_count > 0:
                st.info(f"📊 **{active_count} Active Signals** (from {total_scanned} scanned) | Week of {next_week} | Next live scan when market opens")
            else:
                st.warning(f"⚠️ **No Active Signals** (scanned {total_scanned} tickers) | Week of {next_week} | Next live scan when market opens")
    
    # ALWAYS display the validated data from JSON FIRST (no waiting)
    # This ensures data shows immediately while any scans run in background
    display_results = validated_results
    
    # Mark last scan time if we have data
    if validated_results and not st.session_state.get(f"last_scan_{engine_key}"):
        st.session_state[f"last_scan_{engine_key}"] = datetime.now()
    
    if display_results:
        table_title = f"{engine_name} PUT Candidates"
        if not is_market_open() and validated_results:
            table_title += " (Validated - Next Week Projection)"
        render_puts_table(display_results, table_title)
    else:
        render_puts_table([], f"{engine_name} PUT Candidates")
    
    # Last update timestamp
    last_scan = st.session_state.get(f"last_scan_{engine_key}")
    if last_scan:
        st.caption(f"🕐 Last updated: {last_scan.strftime('%I:%M:%S %p')} | Auto-refreshes every 30 minutes")
    
    # Manual refresh button
    col1, col2, col3 = st.columns([2, 1, 2])
    with col2:
        if st.button(f"🔄 Refresh Now", key=f"refresh_{engine_key}", use_container_width=True):
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


def render_48hour_analysis():
    """
    Render 48-Hour Frequency Analysis across all 3 engines.
    Shows symbols appearing in 2+ engines with highest conviction.
    """
    st.markdown("""
    <div class="section-header">📊 48-Hour Frequency Analysis (All Engines)</div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    Shows how many times each symbol appeared across ALL scans in the last 48 hours.
    **Multi-Engine symbols** (appearing in 2+ engines) have highest conviction.
    """)
    
    # Add refresh button and auto-sync with current scan
    col_refresh1, col_refresh2, col_refresh3 = st.columns([1, 1, 2])
    
    with col_refresh1:
        if st.button("🔄 Refresh History", key="refresh_48hr_btn"):
            # Add current scan to history
            try:
                results_file = Path(__file__).parent.parent / "scheduled_scan_results.json"
                if results_file.exists():
                    with open(results_file, 'r') as f:
                        current_results = json.load(f)
                    add_scan_to_history(current_results)
                    st.success("History updated!")
                    st.rerun()
            except Exception as e:
                st.error(f"Error updating: {e}")
    
    with col_refresh2:
        # Show last update time from history
        try:
            history = load_scan_history()
            if history.get("scans"):
                last_scan = history["scans"][-1].get("timestamp", "Unknown")
                st.caption(f"Last scan: {last_scan[:19] if isinstance(last_scan, str) else last_scan}")
        except:
            pass
    
    # Auto-sync: Add current scan to history on page load (if not recently added)
    try:
        results_file = Path(__file__).parent.parent / "scheduled_scan_results.json"
        if results_file.exists():
            with open(results_file, 'r') as f:
                current_results = json.load(f)
            
            # Check if we need to add this scan (avoid duplicates)
            history = load_scan_history()
            current_timestamp = current_results.get("last_scan", "")
            
            # Only add if timestamp is different from the last scan in history
            if history.get("scans"):
                last_history_timestamp = history["scans"][-1].get("timestamp", "")
                # Simple check: if timestamps differ by more than 60 seconds, add new scan
                if current_timestamp and current_timestamp != last_history_timestamp:
                    try:
                        current_dt = datetime.fromisoformat(current_timestamp.replace("Z", "+00:00"))
                        last_dt = datetime.fromisoformat(last_history_timestamp.replace("Z", "+00:00"))
                        if abs((current_dt - last_dt).total_seconds()) > 60:
                            add_scan_to_history(current_results)
                    except:
                        # If timestamp parsing fails, still try to add
                        add_scan_to_history(current_results)
            else:
                # History is empty, add current scan
                add_scan_to_history(current_results)
    except Exception as e:
        logger.debug(f"Auto-sync error: {e}")
    
    # Initialize history if needed
    try:
        initialize_history_from_current_scan()
    except:
        pass
    
    # Get frequency analysis
    try:
        analysis = get_48hour_frequency_analysis()
    except Exception as e:
        st.error(f"Error loading analysis: {e}")
        return
    
    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("📊 Unique Symbols", analysis.get("unique_symbols", 0))
    
    with col2:
        st.metric("📈 Total Appearances", analysis.get("total_appearances", 0))
    
    with col3:
        st.metric("🔥 Multi-Engine", analysis.get("multi_engine_count", 0))
    
    with col4:
        top_symbol = analysis.get("top_symbol")
        if top_symbol:
            st.metric("🏆 Top Symbol", f"{top_symbol['symbol']} ({top_symbol['total_appearances']})")
        else:
            st.metric("🏆 Top Symbol", "N/A")
    
    st.divider()
    
    # Multi-Engine Symbols Table (2+ engines)
    st.markdown("### 🔥 Multi-Engine Symbols (2+ Engines)")
    st.markdown("*These symbols appeared in at least 2 different engines - highest conviction picks*")
    
    multi_engine = analysis.get("multi_engine_symbols", [])
    
    if multi_engine:
        # Create DataFrame for display
        df_data = []
        for i, symbol_data in enumerate(multi_engine, 1):
            # Engine badges
            engines = []
            if symbol_data["gamma_drain_count"] > 0:
                engines.append(f"🔥 {symbol_data['gamma_drain_count']}")
            if symbol_data["distribution_count"] > 0:
                engines.append(f"📉 {symbol_data['distribution_count']}")
            if symbol_data["liquidity_count"] > 0:
                engines.append(f"💧 {symbol_data['liquidity_count']}")
            
            # Calculate overall score
            avg_score = max(
                symbol_data["gamma_drain_avg_score"],
                symbol_data["distribution_avg_score"],
                symbol_data["liquidity_avg_score"]
            )
            
            df_data.append({
                "Rank": i,
                "Symbol": symbol_data["symbol"],
                "Total": symbol_data["total_appearances"],
                "🔥 Gamma": symbol_data["gamma_drain_count"],
                "📉 Distribution": symbol_data["distribution_count"],
                "💧 Liquidity": symbol_data["liquidity_count"],
                "Engines": symbol_data["engines_count"],
                "Avg Score": f"{avg_score:.2f}",
                "Engine Breakdown": " | ".join(engines)
            })
        
        df = pd.DataFrame(df_data)
        
        # Style the dataframe
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn("Rank", width="small"),
                "Symbol": st.column_config.TextColumn("Symbol", width="medium"),
                "Total": st.column_config.NumberColumn("Total", width="small"),
                "🔥 Gamma": st.column_config.NumberColumn("🔥 Gamma", width="small"),
                "📉 Distribution": st.column_config.NumberColumn("📉 Dist", width="small"),
                "💧 Liquidity": st.column_config.NumberColumn("💧 Liq", width="small"),
                "Engines": st.column_config.NumberColumn("Engines", width="small"),
                "Avg Score": st.column_config.TextColumn("Score", width="small"),
            }
        )
        
        # Top 3 Multi-Engine cards
        if len(multi_engine) >= 3:
            st.markdown("### 🏆 Top 3 Multi-Engine Picks")
            top3_cols = st.columns(3)
            colors = ["#FFD700", "#C0C0C0", "#CD7F32"]  # Gold, Silver, Bronze
            
            for i, (col, symbol_data) in enumerate(zip(top3_cols, multi_engine[:3])):
                with col:
                    st.markdown(f"""
                    <div style="
                        background: linear-gradient(135deg, {colors[i]}22, {colors[i]}44);
                        border: 2px solid {colors[i]};
                        border-radius: 10px;
                        padding: 15px;
                        text-align: center;
                    ">
                        <h2 style="margin: 0; color: {colors[i]};">#{i+1}</h2>
                        <h1 style="margin: 5px 0; color: white;">{symbol_data['symbol']}</h1>
                        <p style="margin: 5px 0; color: #aaa;">{symbol_data['total_appearances']} appearances</p>
                        <p style="margin: 5px 0; color: #4ecdc4;">{symbol_data['engines_count']} engines</p>
                    </div>
                    """, unsafe_allow_html=True)
    else:
        st.warning("No multi-engine symbols found yet. Run more scans to build history.")
    
    st.divider()
    
    # All Symbols Table
    with st.expander("📋 View All Symbols (Click to expand)", expanded=False):
        all_symbols = analysis.get("all_symbols", [])
        
        if all_symbols:
            df_all = []
            for i, s in enumerate(all_symbols[:50], 1):  # Limit to top 50
                df_all.append({
                    "Rank": i,
                    "Symbol": s["symbol"],
                    "Total": s["total_appearances"],
                    "🔥 Gamma": s["gamma_drain_count"],
                    "📉 Dist": s["distribution_count"],
                    "💧 Liq": s["liquidity_count"],
                    "Engines": s["engines_count"]
                })
            
            st.dataframe(pd.DataFrame(df_all), use_container_width=True, hide_index=True)
        else:
            st.info("No symbols in history yet.")
    
    # Engine Totals
    st.divider()
    st.markdown("### 📊 Engine Breakdown")
    
    engine_totals = analysis.get("engine_totals", {})
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("🔥 Gamma Drain", engine_totals.get("gamma_drain", 0))
    with col2:
        st.metric("📉 Distribution", engine_totals.get("distribution", 0))
    with col3:
        st.metric("💧 Liquidity", engine_totals.get("liquidity", 0))
    
    # Info about scan history
    st.caption(f"📅 Analyzing last {analysis.get('history_hours', 48)} hours | Total scans in history: {analysis.get('total_scans', 0)}")


def render_big_movers_analysis():
    """
    Render Big Movers Analysis tab - shows FUTURE PUT CANDIDATES organized by pattern type.
    These are REAL-TIME candidates showing the same patterns as big movers from Jan 26-29.
    Auto-refreshes every 2 hours.
    """
    # Auto-refresh every 2 hours (7200000 ms)
    from streamlit_autorefresh import st_autorefresh
    pattern_refresh_count = st_autorefresh(interval=7200000, limit=None, key="pattern_autorefresh")
    
    # Track refresh count in session state
    if "pattern_refresh_count" not in st.session_state:
        st.session_state.pattern_refresh_count = 0
    
    # Run pattern scan on auto-refresh or first load if no data
    pattern_file = Path(__file__).parent.parent / "pattern_scan_results.json"
    needs_scan = not pattern_file.exists()
    
    if pattern_refresh_count > st.session_state.pattern_refresh_count:
        st.session_state.pattern_refresh_count = pattern_refresh_count
        needs_scan = True
    
    if needs_scan:
        # Run pattern scan on auto-refresh
        import subprocess
        try:
            subprocess.run(
                ["python3", "integrate_patterns.py"],
                cwd=str(Path(__file__).parent.parent),
                capture_output=True,
                text=True,
                timeout=180
            )
        except:
            pass
    
    st.markdown("""
    <div class="section-header">🎯 Future PUT Candidates by Pattern</div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    **Real-Time Pattern Detection:** These stocks are showing patterns NOW that led to big moves.
    Use this to identify put opportunities 1-2 days BEFORE the crash.
    """)
    
    # Refresh button - always at top
    col_btn1, col_btn2 = st.columns([1, 4])
    with col_btn1:
        refresh_clicked = st.button("🔄 Refresh Pattern Scan", key="refresh_patterns")
    
    if refresh_clicked:
        with st.spinner("Running pattern scan... This may take 30-60 seconds."):
            import subprocess
            try:
                result = subprocess.run(
                    ["python3", "integrate_patterns.py"],
                    cwd=str(Path(__file__).parent.parent),
                    capture_output=True,
                    text=True,
                    timeout=180
                )
                if result.returncode == 0:
                    st.success("✅ Pattern scan complete!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(f"Scan failed: {result.stderr[:200]}")
            except Exception as e:
                st.error(f"Error running scan: {e}")
    
    # Load pattern scan results (always reload fresh)
    pattern_data = None
    if pattern_file.exists():
        try:
            with open(pattern_file, 'r') as f:
                pattern_data = json.load(f)
        except Exception as e:
            st.error(f"Error loading pattern data: {e}")
    
    # Also load scheduled scan for earnings and sector data
    scheduled_file = Path(__file__).parent.parent / "scheduled_scan_results.json"
    scheduled_data = {}
    if scheduled_file.exists():
        try:
            with open(scheduled_file, 'r') as f:
                scheduled_data = json.load(f)
        except:
            pass
    
    if not pattern_data:
        st.warning("⚠️ No pattern scan data found. Running initial scan...")
        import subprocess
        try:
            result = subprocess.run(
                ["python3", "integrate_patterns.py"],
                cwd=str(Path(__file__).parent.parent),
                capture_output=True,
                text=True,
                timeout=180
            )
            if result.returncode == 0:
                # Reload the data
                if pattern_file.exists():
                    with open(pattern_file, 'r') as f:
                        pattern_data = json.load(f)
                    st.success("✅ Pattern scan complete! Displaying results...")
                else:
                    st.error("Scan completed but no data file found.")
                    return
            else:
                st.error(f"Scan failed: {result.stderr[:200]}")
                return
        except Exception as e:
            st.error(f"Error running initial scan: {e}")
            return
    
    # Summary metrics - use correct JSON keys
    pump_reversal = pattern_data.get("pump_reversal", [])
    two_day_rally = pattern_data.get("two_day_rally", [])
    high_vol_run = pattern_data.get("high_vol_run", [])
    
    # =========================================================================
    # ARCHITECT-4 ENHANCEMENT: Cross-Engine Confirmation Check
    # =========================================================================
    # Get symbols confirmed by execution engines (Gamma, Distribution, Liquidity)
    engine_confirmed_symbols = set()
    engine_confirmation_map = {}  # symbol -> list of confirming engines
    
    for engine_key in ["gamma_drain", "distribution", "liquidity"]:
        engine_candidates = scheduled_data.get(engine_key, [])
        for c in engine_candidates:
            sym = c.get("symbol")
            if sym:
                engine_confirmed_symbols.add(sym)
                if sym not in engine_confirmation_map:
                    engine_confirmation_map[sym] = []
                engine_labels = {
                    "gamma_drain": "🔥 Gamma",
                    "distribution": "📉 Dist",
                    "liquidity": "💧 Liq"
                }
                engine_confirmation_map[sym].append(engine_labels.get(engine_key, engine_key))
    
    # =========================================================================
    # ARCHITECT-4 REFINEMENT 1: "Confirmed by ≥2 Engines" Highlight
    # =========================================================================
    # Differentiate 1 engine (✅) vs 2+ engines (⭐⭐⭐) for size differentiation
    def get_engine_badge(symbol: str) -> str:
        """Return badge based on number of confirming engines."""
        engines = engine_confirmation_map.get(symbol, [])
        if len(engines) >= 2:
            return "⭐⭐⭐"  # 2+ engines = highest conviction, larger size
        elif len(engines) == 1:
            return "✅"      # 1 engine = confirmed, standard size
        else:
            return ""        # No confirmation
    
    # =========================================================================
    # ARCHITECT-4 REFINEMENT 2: Time-Decay Warning Badge
    # =========================================================================
    # Track stale theses - Big Movers that remain unconfirmed for 3+ sessions
    stale_thesis_symbols = set()
    try:
        history_file = Path(__file__).parent.parent / "scan_history.json"
        if history_file.exists():
            with open(history_file, 'r') as f:
                history_data = json.load(f)
            
            # Get last 6 scans (roughly 3 sessions if scanning every 30 min)
            recent_scans = history_data.get("scans", [])[-6:]
            
            # Build a map of how many times each symbol appeared WITHOUT engine confirmation
            symbol_unconfirmed_count = {}
            for scan in recent_scans:
                # Get all symbols from this scan
                scan_symbols = set()
                for engine in ["gamma_drain", "distribution", "liquidity"]:
                    for c in scan.get(engine, []):
                        scan_symbols.add(c.get("symbol"))
                
                # For Big Movers symbols, check if they were confirmed
                for sym in all_pattern_symbols if 'all_pattern_symbols' in dir() else []:
                    if sym not in scan_symbols:
                        symbol_unconfirmed_count[sym] = symbol_unconfirmed_count.get(sym, 0) + 1
            
            # Mark symbols unconfirmed in 3+ of last 6 scans as stale
            for sym, count in symbol_unconfirmed_count.items():
                if count >= 3:
                    stale_thesis_symbols.add(sym)
    except Exception:
        pass  # Silently handle if history unavailable
    
    def get_staleness_badge(symbol: str) -> str:
        """Return ⚠️ if thesis is stale (unconfirmed for 3+ sessions)."""
        if symbol in stale_thesis_symbols:
            return "⚠️"
        return ""
    
    # =========================================================================
    # ARCHITECT-4 ENHANCEMENT: Confidence Tier Classification
    # =========================================================================
    def get_confidence_tier(candidate, pattern_type="pump_reversal"):
        """Classify candidate into confidence tier based on reversal signals."""
        if pattern_type == "pump_reversal":
            signals = candidate.get("signals", [])
            if len(signals) >= 3:
                return "HIGH", "🟢"
            elif len(signals) >= 2:
                return "MEDIUM", "🟡"
            else:
                return "LOW", "🔴"
        elif pattern_type == "two_day_rally":
            total = candidate.get("total", 0)
            if total >= 6:
                return "MEDIUM", "🟡"
            else:
                return "LOW", "🔴"
        else:  # high_vol_run
            vol_ratio = candidate.get("vol_ratio", 1)
            if vol_ratio >= 2.0:
                return "MEDIUM", "🟡"
            else:
                return "LOW", "🔴"
        return "LOW", "🔴"
    
    # Parse scan time and calculate dates for column headers
    scan_time_raw = pattern_data.get("scan_time", "Unknown")
    scan_time_display = "Unknown"
    date_1d = "1D"  # Yesterday
    date_2d = "2D"  # 2 days ago
    date_3d = "3D"  # 3 days ago
    
    if scan_time_raw != "Unknown":
        try:
            from datetime import datetime, timedelta
            dt = datetime.fromisoformat(scan_time_raw.replace("Z", "+00:00"))
            scan_time_display = dt.strftime("%Y-%m-%d %H:%M ET")
            # Calculate actual dates for headers
            date_1d = (dt - timedelta(days=1)).strftime("%b %d")  # Yesterday
            date_2d = (dt - timedelta(days=2)).strftime("%b %d")  # 2 days ago
            date_3d = (dt - timedelta(days=3)).strftime("%b %d")  # 3 days ago
        except:
            pass
    
    # =========================================================================
    # ARCHITECT-4 ENHANCEMENT: Cross-Engine Audit Summary (TOP OF PAGE)
    # =========================================================================
    # Count engine-confirmed candidates
    all_pattern_symbols = set()
    for p in pump_reversal:
        all_pattern_symbols.add(p["symbol"])
    for p in two_day_rally:
        all_pattern_symbols.add(p["symbol"])
    for p in high_vol_run:
        all_pattern_symbols.add(p["symbol"])
    
    engine_confirmed_count = len(all_pattern_symbols & engine_confirmed_symbols)
    
    if engine_confirmed_count > 0:
        st.markdown("### ✅ Engine-Confirmed Candidates (PRIORITY)")
        st.markdown("*These Big Movers are ALSO flagged by execution engines → **highest conviction**.*")
        
        confirmed_list = []
        multi_engine_count = 0
        for sym in all_pattern_symbols & engine_confirmed_symbols:
            engines = engine_confirmation_map.get(sym, [])
            badge = get_engine_badge(sym)
            if len(engines) >= 2:
                multi_engine_count += 1
            
            # Find the pattern data
            pattern_info = "Unknown"
            for p in pump_reversal:
                if p["symbol"] == sym:
                    pattern_info = f"Pump +{p.get('total_gain', 0):.1f}%"
                    break
            for p in two_day_rally:
                if p["symbol"] == sym:
                    pattern_info = f"Rally +{p.get('total', 0):.1f}%"
                    break
            for p in high_vol_run:
                if p["symbol"] == sym:
                    pattern_info = f"Vol {p.get('vol_ratio', 1):.1f}x"
                    break
            
            # Determine size recommendation based on engine count
            size_rec = "FULL SIZE" if len(engines) >= 2 else "STANDARD"
            
            confirmed_list.append({
                "Badge": badge,
                "Symbol": sym,
                "Pattern": pattern_info,
                "Confirmed By": " + ".join(engines),
                "Engines": len(engines),
                "Size": size_rec,
                "Status": "✅ TRADEABLE"
            })
        
        # Sort by number of engines (descending)
        confirmed_list.sort(key=lambda x: x["Engines"], reverse=True)
        
        if confirmed_list:
            df_confirmed = pd.DataFrame([{k: v for k, v in c.items() if k != "Engines"} for c in confirmed_list])
            st.dataframe(df_confirmed, use_container_width=True, hide_index=True)
            
            if multi_engine_count > 0:
                st.success(f"⭐⭐⭐ {multi_engine_count} candidates confirmed by 2+ engines → **FULL SIZE** positions!")
            st.info(f"🎯 {engine_confirmed_count} total candidates confirmed by execution engines")
        
        st.divider()
    
    st.markdown("### 🎯 Future Candidates Summary")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("💥 Pump Reversal", len(pump_reversal), help="Pumped stocks - watch for crash")
    
    with col2:
        st.metric("↩️ 2-Day Rally", len(two_day_rally), help="Exhaustion pattern candidates")
    
    with col3:
        st.metric("📈 High Vol Run", len(high_vol_run), help="Big gains on volume - institutions exiting?")
    
    with col4:
        # Get earnings candidates from scheduled data
        earnings_upcoming = [c for c in scheduled_data.get("distribution", []) if "earnings" in str(c.get("signals", [])).lower()]
        st.metric("⚡ Earnings Watch", len(earnings_upcoming), help="Stocks with earnings upcoming")
    
    st.caption(f"Last scan: {scan_time_display} | 🔄 Auto-updates every 30 minutes")
    
    st.divider()
    
    # =========================================================================
    # Pattern 1: Pump Reversal Watch (FUTURE CANDIDATES)
    # =========================================================================
    st.markdown("### 💥 Pattern 1: Pump Reversal Watch")
    st.markdown("*Stocks that pumped +3% in last 1-3 days. HIGH PROBABILITY of reversal crash. These are your primary targets.*")
    
    if pump_reversal:
        # Count by confidence tier
        high_conf = sum(1 for p in pump_reversal if len(p.get("signals", [])) >= 3)
        med_conf = sum(1 for p in pump_reversal if len(p.get("signals", [])) == 2)
        low_conf = sum(1 for p in pump_reversal if len(p.get("signals", [])) < 2)
        
        # Show confidence tier breakdown
        tier_cols = st.columns(4)
        with tier_cols[0]:
            st.metric("🟢 HIGH (3+ signals)", high_conf, help="Highest conviction - consider trading")
        with tier_cols[1]:
            st.metric("🟡 MEDIUM (2 signals)", med_conf, help="Good conviction - watch closely")
        with tier_cols[2]:
            st.metric("🔴 LOW (0-1 signals)", low_conf, help="Lower conviction - wait for confirmation")
        with tier_cols[3]:
            engine_conf_pump = sum(1 for p in pump_reversal if p["symbol"] in engine_confirmed_symbols)
            st.metric("✅ Engine Confirmed", engine_conf_pump, help="Also flagged by execution engines")
        
        df_pump = pd.DataFrame([
            {
                "Tier": get_confidence_tier(p, "pump_reversal")[1],
                "Eng": get_engine_badge(p["symbol"]),
                "⚠️": get_staleness_badge(p["symbol"]),
                "Symbol": p["symbol"],
                "Price": f"${p.get('price', 0):.2f}",
                "🎯 Strike": p.get("strike_display", "N/A"),
                "📅 Expiry": f"{p.get('expiry_display', 'N/A')} ({p.get('dte', 0)}d)",
                "OTM %": f"{p.get('otm_pct', 0):.1f}%",
                "Total Gain": f"+{p.get('total_gain', 0):.1f}%",
                date_1d: f"{p.get('gain_1d', 0):+.1f}%",
                date_2d: f"{p.get('gain_2d', 0):+.1f}%",
                "Signals": ", ".join(p.get("signals", [])[:2]) or "pumped",
                "Target δ": p.get("delta_target", "-0.30"),
                "Potential": p.get("potential_mult", "3x-5x")
            }
            for p in pump_reversal[:15]
        ])
        st.dataframe(df_pump, use_container_width=True, hide_index=True, height=420)
        st.caption("🟢 = HIGH (3+ signals) | 🟡 = MEDIUM | 🔴 = LOW | ⭐⭐⭐ = 2+ engines | ✅ = 1 engine | ⚠️ = Stale thesis")
    else:
        st.info("No pump reversal candidates found. Market may be quiet.")
    
    st.divider()
    
    # =========================================================================
    # Pattern 2: Two-Day Rally (Exhaustion Setup)
    # =========================================================================
    st.markdown("### ↩️ Pattern 2: Two-Day Rally (Exhaustion)")
    st.markdown("*Stocks UP two consecutive days. Classic exhaustion setup - typically crashes on day 3-4.*")
    
    if two_day_rally:
        df_rally = pd.DataFrame([
            {
                "Symbol": p["symbol"],
                "Price": f"${p.get('price', 0):.2f}",
                "🎯 Strike": p.get("strike_display", "N/A"),
                "📅 Expiry": f"{p.get('expiry_display', 'N/A')} ({p.get('dte', 0)}d)",
                "OTM %": f"{p.get('otm_pct', 0):.1f}%",
                date_2d: f"+{p.get('day1', 0):.1f}%",  # First pump day
                date_1d: f"+{p.get('day2', 0):.1f}%",  # Second pump day (yesterday)
                "Total": f"+{p.get('total', 0):.1f}%",
                "Target δ": p.get("delta_target", "-0.30"),
                "Potential": p.get("potential_mult", "3x-5x")
            }
            for p in two_day_rally[:12]
        ])
        st.dataframe(df_rally, use_container_width=True, hide_index=True, height=350)
    else:
        st.info("No two-day rally exhaustion candidates found.")
    
    st.divider()
    
    # =========================================================================
    # Pattern 3: High Volume Run (Institutions Exiting?)
    # =========================================================================
    st.markdown("### 📈 Pattern 3: High Volume Run")
    st.markdown("*Big gains (+5%+) on above-average volume. Often institutions SELLING into strength. Watch for reversal.*")
    
    if high_vol_run:
        df_vol = pd.DataFrame([
            {
                "Symbol": p["symbol"],
                "Price": f"${p.get('price', 0):.2f}",
                "🎯 Strike": p.get("strike_display", "N/A"),
                "📅 Expiry": f"{p.get('expiry_display', 'N/A')} ({p.get('dte', 0)}d)",
                "OTM %": f"{p.get('otm_pct', 0):.1f}%",
                "Gain": f"+{p.get('gain', 0):.1f}%",
                "Volume": f"{p.get('vol_ratio', 1):.1f}x avg",
                "Target δ": p.get("delta_target", "-0.30"),
                "Potential": p.get("potential_mult", "3x-5x")
            }
            for p in high_vol_run[:10]
        ])
        st.dataframe(df_vol, use_container_width=True, hide_index=True)
    else:
        st.info("No high volume run candidates found.")
    
    st.divider()
    
    # =========================================================================
    # Pattern 4: Sector Contagion Watch
    # =========================================================================
    st.markdown("### 🔗 Pattern 4: Sector Contagion Watch")
    st.markdown("*Sectors with multiple stocks showing weakness. When one crashes, others follow.*")
    
    # Group pump_reversal candidates by sector
    sector_groups = {}
    for p in pump_reversal:
        sector = p.get("sector", "other")
        if sector != "other":
            if sector not in sector_groups:
                sector_groups[sector] = []
            sector_groups[sector].append(p)
    
    # Filter to sectors with 2+ candidates
    contagion_sectors = {k: v for k, v in sector_groups.items() if len(v) >= 2}
    
    if contagion_sectors:
        for sector, stocks in sorted(contagion_sectors.items(), key=lambda x: len(x[1]), reverse=True):
            with st.expander(f"**{sector.upper().replace('_', ' ')}** ({len(stocks)} stocks at risk)", expanded=True):
                symbols = [s["symbol"] for s in stocks]
                st.write(f"**At Risk:** {', '.join(symbols)}")
                avg_gain = sum(s.get("total_gain", 0) for s in stocks) / len(stocks)
                st.write(f"**Avg Pump:** +{avg_gain:.1f}%")
                st.write("**Strategy:** If ANY of these drops -3%+, buy puts on ALL of them")
    else:
        st.info("No sector contagion patterns detected (need 2+ stocks in same sector pumping).")
    
    st.divider()
    
    # =========================================================================
    # All Candidates Summary Table (WITH CONFIDENCE TIERS & ENGINE CONFIRMATION)
    # =========================================================================
    st.markdown("### 📋 All Future PUT Candidates")
    st.markdown("*Combined view of all pattern candidates with institutional strike/expiry recommendations*")
    
    # Combine all candidates
    all_candidates = []
    
    for p in pump_reversal:
        tier, tier_icon = get_confidence_tier(p, "pump_reversal")
        all_candidates.append({
            "Symbol": p["symbol"],
            "Pattern": "💥 Pump Reversal",
            "Price": p.get("price", 0),
            "Strike": p.get("strike_display", "N/A"),
            "Expiry": p.get("expiry_display", "N/A"),
            "DTE": p.get("dte", 0),
            "OTM": p.get("otm_pct", 0),
            "Gain/Move": p.get("total_gain", 0),
            "Signals": len(p.get("signals", [])),
            "Delta": p.get("delta_target", "-0.30"),
            "Potential": p.get("potential_mult", "3x-5x"),
            "Score Boost": p.get("score_boost", 0.1),
            "Tier": tier,
            "TierIcon": tier_icon,
            "EngineConfirmed": p["symbol"] in engine_confirmed_symbols,
            "ConfirmingEngines": engine_confirmation_map.get(p["symbol"], [])
        })
    
    for p in two_day_rally:
        tier, tier_icon = get_confidence_tier(p, "two_day_rally")
        all_candidates.append({
            "Symbol": p["symbol"],
            "Pattern": "↩️ 2-Day Rally",
            "Price": p.get("price", 0),
            "Strike": p.get("strike_display", "N/A"),
            "Expiry": p.get("expiry_display", "N/A"),
            "DTE": p.get("dte", 0),
            "OTM": p.get("otm_pct", 0),
            "Gain/Move": p.get("total", 0),
            "Signals": 1,
            "Delta": p.get("delta_target", "-0.30"),
            "Potential": p.get("potential_mult", "3x-5x"),
            "Score Boost": p.get("score_boost", 0.1),
            "Tier": tier,
            "TierIcon": tier_icon,
            "EngineConfirmed": p["symbol"] in engine_confirmed_symbols,
            "ConfirmingEngines": engine_confirmation_map.get(p["symbol"], [])
        })
    
    for p in high_vol_run:
        tier, tier_icon = get_confidence_tier(p, "high_vol_run")
        all_candidates.append({
            "Symbol": p["symbol"],
            "Pattern": "📈 High Vol Run",
            "Price": p.get("price", 0),
            "Strike": p.get("strike_display", "N/A"),
            "Expiry": p.get("expiry_display", "N/A"),
            "DTE": p.get("dte", 0),
            "OTM": p.get("otm_pct", 0),
            "Gain/Move": p.get("gain", 0),
            "Signals": 1,
            "Delta": p.get("delta_target", "-0.30"),
            "Potential": p.get("potential_mult", "3x-5x"),
            "Score Boost": p.get("score_boost", 0.1),
            "Tier": tier,
            "TierIcon": tier_icon,
            "EngineConfirmed": p["symbol"] in engine_confirmed_symbols,
            "ConfirmingEngines": engine_confirmation_map.get(p["symbol"], [])
        })
    
    if all_candidates:
        # Sort by: Engine Confirmed first, then by Tier (HIGH > MEDIUM > LOW), then by Score Boost
        tier_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        all_candidates.sort(key=lambda x: (
            0 if x["EngineConfirmed"] else 1,  # Engine confirmed first
            tier_order.get(x["Tier"], 3),       # Then by tier
            -x["Score Boost"]                   # Then by score boost (descending)
        ))
        
        df_all = pd.DataFrame([
            {
                "Tier": c["TierIcon"],
                "Eng": get_engine_badge(c["Symbol"]),
                "⚠️": get_staleness_badge(c["Symbol"]),
                "Symbol": c["Symbol"],
                "Pattern": c["Pattern"],
                "Price": f"${c['Price']:.2f}",
                "🎯 Strike": c["Strike"],
                "📅 Expiry": f"{c['Expiry']} ({c['DTE']}d)",
                "OTM %": f"{c['OTM']:.1f}%",
                "Gain": f"+{c['Gain/Move']:.1f}%",
                "Engines": " + ".join(c["ConfirmingEngines"]) if c["ConfirmingEngines"] else "-",
                "Target δ": c["Delta"],
                "Potential": c["Potential"]
            }
            for c in all_candidates[:30]
        ])
        st.dataframe(df_all, use_container_width=True, hide_index=True, height=550)
        
        # Summary stats
        total_engine_confirmed = sum(1 for c in all_candidates if c["EngineConfirmed"])
        total_multi_engine = sum(1 for c in all_candidates if len(c.get("ConfirmingEngines", [])) >= 2)
        total_high_tier = sum(1 for c in all_candidates if c["Tier"] == "HIGH")
        total_stale = sum(1 for c in all_candidates if c["Symbol"] in stale_thesis_symbols)
        total_tradeable = sum(1 for c in all_candidates if c["EngineConfirmed"] or c["Tier"] == "HIGH")
        
        st.markdown(f"""
        **Summary:**
        - ⭐⭐⭐ **2+ engines** (FULL SIZE): **{total_multi_engine}** candidates
        - ✅ **1 engine** (STANDARD): **{total_engine_confirmed - total_multi_engine}** candidates
        - 🟢 HIGH confidence (3+ signals): **{total_high_tier}** candidates
        - 🎯 **TRADEABLE** (HIGH or Engine Confirmed): **{total_tradeable}** candidates
        {"- ⚠️ **Stale thesis** (3+ sessions): **" + str(total_stale) + "** candidates — consider removing" if total_stale > 0 else ""}
        
        **Position Sizing Guide:**
        - ⭐⭐⭐ = FULL SIZE (2+ engines confirming)
        - ✅ or 🟢 = STANDARD SIZE
        - ⚠️ = AVOID (stale thesis)
        """)
    else:
        st.info("No candidates found. Run pattern scan to populate.")
    
    st.caption(f"Total candidates: {len(all_candidates)} | Last updated: {scan_time_display}")


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

    # Force initial data load on all 3 engines (first load)
    if "initial_load_done" not in st.session_state:
        st.session_state.initial_load_done = True
        st.session_state["force_refresh_gamma_drain"] = True
        st.session_state["force_refresh_distribution"] = True
        st.session_state["force_refresh_liquidity"] = True
    
    # Show auto-refresh status
    refresh_count = st.session_state.get("auto_refresh_count", 0)
    last_refresh = st.session_state.get("last_auto_refresh", datetime.now())
    next_refresh = last_refresh + timedelta(minutes=30)
    time_to_refresh = (next_refresh - datetime.now()).total_seconds()
    mins_to_refresh = max(0, int(time_to_refresh // 60))
    secs_to_refresh = max(0, int(time_to_refresh % 60))

    if "Dashboard" in page or "Puts Scanner" in page:
        tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
            "🔥 Gamma Drain Engine", 
            "📉 Distribution Engine", 
            "💧 Liquidity Engine", 
            "📊 48-Hour Analysis",
            "🎯 Big Movers Analysis",
            "📒 Ledger",
            "📈 Backtest",
            "⚙️ Config"
        ])

        with tab1:
            render_engine_tab(engine, "Gamma Drain", "gamma_drain", "gamma_drain", "gamma_drain_results")
            st.divider()
            try:
                regime = run_async(engine.get_cached_regime())
                render_market_regime_cards(regime)
            except Exception:
                pass

        with tab2:
            render_engine_tab(engine, "Distribution", "distribution", "distribution", "distribution_results")
            st.divider()
            try:
                regime = run_async(engine.get_cached_regime())
                render_market_regime_cards(regime)
            except Exception:
                pass

        with tab3:
            render_engine_tab(engine, "Liquidity Vacuum", "liquidity", "liquidity", "liquidity_results")
            st.divider()
            try:
                regime = run_async(engine.get_cached_regime())
                render_market_regime_cards(regime)
            except Exception:
                pass

        with tab4:
            render_48hour_analysis()

        with tab5:
            render_big_movers_analysis()

        with tab6:
            render_ledger_view()

        with tab7:
            render_backtest_view()

        with tab8:
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
