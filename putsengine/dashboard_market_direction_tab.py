"""
MarketPulse Tab - Pre-Market Regime Awareness
=============================================
COMPLETELY ISOLATED NEW TAB

Consolidated from Architect-2, 3, 4, 5 feedback.

THE HARD TRUTH:
- You CANNOT know market direction with certainty at 8-9 AM
- You CAN extract a probabilistic regime bias (risk-off / neutral / risk-on)
- 52-58% edge is valuable when used to gate risk and structure

THE GOAL IS NOT PREDICTION.
THE GOAL IS REGIME AWARENESS + STRUCTURE ALIGNMENT.

Combines:
1. MarketPulse Regime Analysis (Futures, VIX, Gamma, Breadth, Sentiment)
2. Picks from all 3 engines (Gamma Drain, Distribution, Liquidity)
3. Conditional candidates based on regime
4. Finviz sector data

This tab is completely isolated from existing functionality.
"""

import streamlit as st
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import asyncio


# ============================================================================
# FILE PATHS - Using same paths as main dashboard
# ============================================================================

# Get the putsengine directory
_PUTSENGINE_DIR = Path(__file__).parent
_PROJECT_ROOT = _PUTSENGINE_DIR.parent

MARKET_DIRECTION_FILE = _PROJECT_ROOT / "logs" / "market_direction.json"
SCAN_RESULTS_FILE = _PROJECT_ROOT / "scan_results.json"
PATTERN_SCAN_FILE = _PROJECT_ROOT / "pattern_scan_results.json"
EARLY_WARNING_FILE = _PROJECT_ROOT / "early_warning_alerts.json"  # Same as main dashboard
FOOTPRINT_HISTORY_FILE = _PROJECT_ROOT / "footprint_history.json"


# ============================================================================
# DATA LOADING FUNCTIONS
# ============================================================================

def load_market_direction() -> Optional[Dict]:
    """Load market direction analysis results."""
    if not MARKET_DIRECTION_FILE.exists():
        return None
    try:
        with open(MARKET_DIRECTION_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Error loading market direction: {e}")
        return None


def load_engine_picks() -> Dict[str, List[Dict]]:
    """Load picks from all 3 engines - scan results and pattern files."""
    picks = {
        "gamma_drain": [],
        "distribution": [],
        "liquidity": []
    }
    
    # Load from scan_results.json (main scan output)
    if SCAN_RESULTS_FILE.exists():
        try:
            with open(SCAN_RESULTS_FILE, 'r') as f:
                data = json.load(f)
            
            candidates = data.get("candidates", [])
            
            for candidate in candidates:
                # Categorize by engine
                engines = candidate.get("engines", [])
                symbol = candidate.get("symbol", "")
                score = candidate.get("score", 0)
                
                pick_data = {
                    "symbol": symbol,
                    "score": score,
                    "engines": engines,
                    "signals": candidate.get("signals", []),
                    "action": candidate.get("action", ""),
                    "price": candidate.get("price", 0),
                    "target": candidate.get("target", 0)
                }
                
                # Add to appropriate engine lists
                if "GammaDrain" in str(engines) or "gamma" in str(engines).lower():
                    picks["gamma_drain"].append(pick_data)
                if "Distribution" in str(engines) or "distribution" in str(engines).lower():
                    picks["distribution"].append(pick_data)
                if "Liquidity" in str(engines) or "liquidity" in str(engines).lower():
                    picks["liquidity"].append(pick_data)
                    
        except Exception as e:
            pass  # Silent fail - file might not exist
    
    # Also load from pattern scan results
    if PATTERN_SCAN_FILE.exists():
        try:
            with open(PATTERN_SCAN_FILE, 'r') as f:
                pattern_data = json.load(f)
            
            # Support both formats: direct patterns and nested
            patterns = pattern_data.get("patterns", pattern_data)
            
            for pattern_type, pattern_picks in patterns.items():
                if isinstance(pattern_picks, list):
                    for pick in pattern_picks:
                        if isinstance(pick, dict):
                            symbol = pick.get("symbol", pick.get("ticker", ""))
                            if not symbol:
                                continue
                                
                            pick_data = {
                                "symbol": symbol,
                                "score": pick.get("confidence", pick.get("score", 0.5)),
                                "engines": [pattern_type],
                                "signals": [pick.get("pattern_type", pick.get("signal", pattern_type))],
                                "action": "BUY PUTS",
                                "price": pick.get("current_price", pick.get("price", 0)),
                                "target": pick.get("target", 0)
                            }
                            
                            # Categorize by pattern type
                            if "pump" in pattern_type.lower() or "reversal" in pattern_type.lower():
                                picks["gamma_drain"].append(pick_data)
                            elif "distribution" in pattern_type.lower() or "weakness" in pattern_type.lower():
                                picks["distribution"].append(pick_data)
                            else:
                                picks["liquidity"].append(pick_data)
                                
        except Exception as e:
            pass  # Silent fail
    
    # Try loading from scheduled_scans folder for most recent results
    scheduled_path = _PROJECT_ROOT / "scheduled_scans"
    if scheduled_path.exists():
        try:
            # Find most recent gamma/distribution/liquidity files
            for engine_type in ["gamma_drain", "distribution", "liquidity"]:
                engine_files = list(scheduled_path.glob(f"*{engine_type}*.json"))
                if engine_files:
                    most_recent = max(engine_files, key=lambda f: f.stat().st_mtime)
                    with open(most_recent, 'r') as f:
                        engine_data = json.load(f)
                    
                    for item in engine_data.get("candidates", engine_data.get("picks", [])):
                        if isinstance(item, dict):
                            picks[engine_type].append({
                                "symbol": item.get("symbol", item.get("ticker", "")),
                                "score": item.get("score", item.get("confidence", 0.5)),
                                "engines": [engine_type],
                                "signals": item.get("signals", []),
                                "action": "BUY PUTS",
                                "price": item.get("price", 0),
                                "target": item.get("target", 0)
                            })
        except:
            pass
    
    # Sort each list by score and deduplicate
    for engine in picks:
        # Dedupe by symbol
        seen = set()
        unique_picks = []
        for pick in sorted(picks[engine], key=lambda x: x.get("score", 0), reverse=True):
            if pick.get("symbol") not in seen:
                seen.add(pick.get("symbol"))
                unique_picks.append(pick)
        picks[engine] = unique_picks[:10]
    
    return picks


def load_early_warning_picks() -> List[Dict]:
    """Load picks from Early Warning System - same source as main dashboard."""
    if not EARLY_WARNING_FILE.exists():
        # Try footprint history as fallback
        if FOOTPRINT_HISTORY_FILE.exists():
            try:
                with open(FOOTPRINT_HISTORY_FILE, 'r') as f:
                    history = json.load(f)
                picks = []
                for symbol, footprints in history.items():
                    if isinstance(footprints, list) and len(footprints) > 0:
                        picks.append({
                            "symbol": symbol,
                            "score": len(footprints) * 0.15,  # Approximate IPI
                            "level": "WATCH" if len(footprints) < 3 else "PREPARE" if len(footprints) < 5 else "ACT",
                            "footprints": len(footprints),
                            "signals": [fp.get("type", "") for fp in footprints[:3]] if isinstance(footprints[0], dict) else []
                        })
                return sorted(picks, key=lambda x: x.get("score", 0), reverse=True)[:15]
            except:
                pass
        return []
    
    try:
        with open(EARLY_WARNING_FILE, 'r') as f:
            data = json.load(f)
        
        alerts = data.get("alerts", {})
        picks = []
        
        for symbol, alert_data in alerts.items():
            if isinstance(alert_data, dict):
                # Convert level to uppercase for consistency
                level = alert_data.get("level", "watch").upper()
                
                picks.append({
                    "symbol": symbol,
                    "score": alert_data.get("ipi", 0),
                    "level": level,
                    "footprints": alert_data.get("unique_footprints", 0),
                    "signals": alert_data.get("footprint_types", []),
                    "days_building": alert_data.get("days_building", 0),
                    "recommendation": alert_data.get("recommendation", "")
                })
        
        # Sort by IPI score
        return sorted(picks, key=lambda x: x.get("score", 0), reverse=True)[:15]
        
    except Exception as e:
        st.warning(f"Error loading early warning data: {e}")
        return []


async def run_live_market_pulse():
    """Run live MarketPulse regime analysis."""
    try:
        from putsengine.market_pulse_engine import MarketPulseEngine
        engine = MarketPulseEngine()
        result = await engine.analyze()
        await engine.close()
        
        # Save to file
        MARKET_DIRECTION_FILE.parent.mkdir(exist_ok=True)
        with open(MARKET_DIRECTION_FILE, "w") as f:
            json.dump({
                "timestamp": result.timestamp.isoformat(),
                "regime": result.regime.value,
                "regime_score": result.regime_score,
                "confidence": result.confidence.value,
                "confidence_pct": result.confidence_pct,
                "tradeability": result.tradeability.value,
                "futures_score": result.futures_score,
                "vix_score": result.vix_score,
                "gamma_score": result.gamma_score,
                "breadth_score": result.breadth_score,
                "sentiment_score": result.sentiment_score,
                "notes": result.notes,
                "conditional_picks": result.conditional_picks,
                "raw_data": result.raw_data,
                # Legacy compatibility
                "direction": result.regime.value,
                "spy_signal": result.raw_data.get("futures", {}).get("spy_change", 0),
                "qqq_signal": result.raw_data.get("futures", {}).get("qqq_change", 0),
                "vix_signal": result.raw_data.get("vix", {}).get("vix_level", 20),
                "gex_regime": result.raw_data.get("gamma", {}).get("gamma_regime", "NEUTRAL"),
                "gex_value": result.raw_data.get("gamma", {}).get("gex_value", 0),
                "best_plays": result.conditional_picks,
                "avoid_plays": []
            }, f, indent=2, default=str)
        
        return result
    except Exception as e:
        st.error(f"Error running MarketPulse: {e}")
        return None


async def get_finviz_data() -> Dict[str, Any]:
    """Get sector performance, news, and insider activity from Finviz."""
    result = {
        "sectors": [],
        "news": [],
        "insiders": {}
    }
    
    try:
        from putsengine.config import get_settings
        from putsengine.clients.finviz_client import FinVizClient
        
        settings = get_settings()
        client = FinVizClient(settings)
        
        # Get sector performance
        sector_perf = await client.get_sector_performance()
        for sector, change in sector_perf.items():
            sentiment = "bearish" if change < -1 else "bullish" if change > 1 else "neutral"
            result["sectors"].append({
                "sector": sector,
                "change": change,
                "sentiment": sentiment
            })
        result["sectors"] = sorted(result["sectors"], key=lambda x: x.get("change", 0))
        
        # Get market news
        news = await client.get_market_news(limit=15)
        result["news"] = news
        
        # Get insider activity
        insiders = await client.get_insider_activity_summary()
        result["insiders"] = insiders
        
        await client.close()
        
    except Exception as e:
        pass  # Silent fail
    
    return result


async def get_finviz_news(symbols: List[str] = None) -> List[Dict]:
    """Get sector data from Finviz (legacy function for compatibility)."""
    data = await get_finviz_data()
    return data.get("sectors", [])


# ============================================================================
# DISPLAY FUNCTIONS
# ============================================================================

def display_market_pulse(data: Dict):
    """Display MarketPulse regime analysis - NOT prediction."""
    
    if not data:
        st.warning("No MarketPulse data available. Click 'Run Analysis' to generate.")
        return
    
    # Regime with emoji
    regime = data.get("regime", data.get("direction", "NEUTRAL"))
    confidence_pct = data.get("confidence_pct", data.get("confidence", 50))
    regime_score = data.get("regime_score", 0.5)
    tradeability = data.get("tradeability", "UNKNOWN")
    
    regime_emoji = {
        "RISK_OFF": "🔴",
        "NEUTRAL": "⚪",
        "RISK_ON": "🟢",
        # Legacy compatibility
        "STRONG_BEARISH": "🔴",
        "BEARISH": "🔴",
        "STRONG_BULLISH": "🟢",
        "BULLISH": "🟢",
    }
    
    # HONEST DISCLAIMER
    st.info("""
    **⚠️ THE HARD TRUTH:** This is regime awareness, NOT prediction.
    Edge: 52-58% opening direction. Full-day prediction is NOT reliable.
    Use this to gate risk and structure, not to force trades.
    """)
    
    # Main metrics row
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "🌊 Regime",
            f"{regime_emoji.get(regime, '⚪')} {regime.replace('_', ' ')}",
            delta=None
        )
    
    with col2:
        st.metric(
            "📊 Score", 
            f"{regime_score:.2f}",
            help="0.0 = Risk-Off, 0.5 = Neutral, 1.0 = Risk-On"
        )
    
    with col3:
        conf_emoji = "🟢" if confidence_pct >= 60 else "🟡" if confidence_pct >= 55 else "⚪"
        st.metric(
            "📈 Confidence", 
            f"{conf_emoji} {confidence_pct:.0f}%",
            help="Capped at 70% - we're honest about uncertainty"
        )
    
    with col4:
        trade_emoji = "📈" if tradeability == "TREND" else "📊" if tradeability == "CHOP" else "❓"
        st.metric(
            "🎯 Tradeability", 
            f"{trade_emoji} {tradeability}",
            help="TREND = directional moves amplified, CHOP = mean reversion"
        )
    
    # Component scores (transparency)
    st.markdown("---")
    st.markdown("### 📊 Component Scores (Weighted)")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        futures = data.get("futures_score", 0.5)
        st.metric("Futures (30%)", f"{futures:.2f}")
    
    with col2:
        vix = data.get("vix_score", 0.5)
        st.metric("VIX (25%)", f"{vix:.2f}")
    
    with col3:
        gamma = data.get("gamma_score", 0.5)
        st.metric("Gamma (20%)", f"{gamma:.2f}")
    
    with col4:
        breadth = data.get("breadth_score", 0.5)
        st.metric("Breadth (15%)", f"{breadth:.2f}")
    
    with col5:
        sentiment = data.get("sentiment_score", 0.5)
        st.metric("Sentiment (10%)", f"{sentiment:.2f}")
    
    # =========================================================================
    # ARCHITECT-4 ADDITIONS: Context Enhancements (Read-Only)
    # =========================================================================
    
    st.markdown("---")
    st.markdown("### 🔬 Microstructure Context (Architect-4)")
    st.caption("Read-only indicators - enhance context, don't change behavior")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # Gamma Flip Distance
        flip_dist = data.get("gamma_flip_distance", 0)
        flip_zone = data.get("gamma_flip_zone", "UNKNOWN")
        zone_emoji = "🔪" if flip_zone == "KNIFE_EDGE" else "⚠️" if flip_zone == "FRAGILE" else "✅"
        st.metric(
            "🎯 Gamma Flip Distance",
            f"{zone_emoji} {flip_dist:.1f}%",
            help="Distance to gamma flip level. KNIFE_EDGE (<0.3%) = extreme fragility"
        )
        st.caption(f"Zone: {flip_zone}")
        
        # Sample Confidence
        sample_conf = data.get("sample_confidence", "UNKNOWN")
        hist_matches = data.get("historical_matches", 0)
        conf_emoji = "🟢" if sample_conf == "HIGH" else "🟡" if sample_conf == "MEDIUM" else "🔴"
        st.metric(
            "📊 Historical Match",
            f"{conf_emoji} ~{hist_matches} days",
            help="How many historical days match current profile. Low = rare regime."
        )
        st.caption(f"Sample Confidence: {sample_conf}")
    
    with col2:
        # Flow Quality
        flow_pct = data.get("flow_opening_pct", 50)
        flow_quality = data.get("flow_quality", "UNKNOWN")
        flow_emoji = "✅" if flow_quality == "GOOD" else "⚠️" if flow_quality == "CAUTION" else "🚨"
        st.metric(
            "📋 Flow Quality",
            f"{flow_emoji} {flow_pct:.0f}% opening",
            help="% of options flow that is opening (new positions) vs closing"
        )
        st.caption(f"Quality: {flow_quality}")
        
        # Certainty Gap
        prior_score = data.get("prior_score")
        score_delta = data.get("score_delta", 0)
        certainty_gap = data.get("certainty_gap", "N/A")
        if prior_score is not None:
            gap_emoji = "🟢" if certainty_gap == "STABLE" else "🟡" if certainty_gap == "SHIFTING" else "🔴"
            st.metric(
                "📈 Certainty Gap",
                f"{gap_emoji} {score_delta:+.2f}",
                help="Score change from prior run. Large delta = information velocity"
            )
            st.caption(f"Gap: {certainty_gap} (prior: {prior_score:.2f})")
        else:
            st.metric("📈 Certainty Gap", "N/A", help="No prior run to compare")
    
    with col3:
        # Spread Expansion
        spread_exp = data.get("spread_expansion", 0)
        spread_flag = data.get("spread_flag", "NORMAL")
        spread_emoji = "✅" if spread_flag == "NORMAL" else "⚠️" if spread_flag == "WIDE" else "🚨"
        st.metric(
            "💧 Spread Expansion",
            f"{spread_emoji} {spread_exp:.1f}x",
            help="Pre-market spread vs normal. DANGEROUS = discontinuous moves likely"
        )
        st.caption(f"Flag: {spread_flag}")
        
        # Expected Move Position
        em_pct = data.get("expected_move_pct", 0)
        open_vs_em = data.get("open_vs_expected", "UNKNOWN")
        em_emoji = "✅" if open_vs_em == "INSIDE" else "⚠️" if open_vs_em == "STRETCHING" else "🚨"
        st.metric(
            "📏 vs Expected Move",
            f"{em_emoji} {open_vs_em}",
            help="Opening position vs ATM straddle expected move. OUTSIDE = dealer re-hedge risk"
        )
    
    # Key observations
    notes = data.get("notes", [])
    if notes:
        st.markdown("---")
        st.markdown("### 📝 Key Observations")
        for note in notes:
            st.markdown(f"- {note}")
    
    # Regime-based guidance
    st.markdown("---")
    
    if regime in ["RISK_OFF", "STRONG_BEARISH", "BEARISH"]:
        if tradeability == "TREND":
            st.success("### 🎯 RISK-OFF + TREND: Puts Favorable")
            st.markdown("""
            **Regime allows aggressive put deployment:**
            - Conditional candidates generated below
            - Use existing EWS/Engine signals for selection
            - Structure via Vega Gate (no override)
            """)
        else:
            st.warning("### ⏸️ RISK-OFF + CHOP: Be Patient")
            st.markdown("""
            **Regime is bearish but expect mean reversion:**
            - Wait for trend confirmation
            - Only highest conviction plays
            - Smaller position sizes
            """)
    elif regime in ["RISK_ON", "STRONG_BULLISH", "BULLISH"]:
        st.error("### ⚠️ RISK-ON: Avoid New Puts")
        st.markdown("""
        **Wrong regime for puts:**
        - Wait for regime change
        - Only trade specific catalysts
        - Existing positions: manage, don't add
        """)
    else:
        st.info("### ⚪ NEUTRAL: Selective Only")
        st.markdown("""
        **Mixed signals - be very selective:**
        - Only ACT-level EWS signals
        - Multiple engine confirmation required
        - Reduced position sizes
        """)


def display_filtered_picks(market_direction: Dict, engine_picks: Dict, ews_picks: List):
    """Display picks filtered by market direction."""
    
    direction = market_direction.get("direction", "NEUTRAL") if market_direction else "NEUTRAL"
    
    st.markdown("---")
    st.markdown("## 🎯 TOP PICKS BY ENGINE")
    
    # Show/hide based on direction
    show_all = direction in ["STRONG_BEARISH", "BEARISH", "NEUTRAL"]
    
    if not show_all:
        st.warning("⚠️ Market is bullish - puts are risky! Showing limited picks.")
    
    # Early Warning System Picks (Most Important)
    st.markdown("### 🚨 Early Warning System (Highest Priority)")
    
    if ews_picks:
        # Filter by market direction
        if direction in ["STRONG_BEARISH", "BEARISH"]:
            filtered_ews = ews_picks  # Show all
        elif direction == "NEUTRAL":
            filtered_ews = [p for p in ews_picks if p.get("level") in ["ACT", "PREPARE"]]
        else:
            filtered_ews = [p for p in ews_picks if p.get("level") == "ACT"]
        
        if filtered_ews:
            ews_data = []
            for pick in filtered_ews[:8]:
                level = pick.get("level", "WATCH")
                level_emoji = "🔴" if level == "ACT" else "🟡" if level == "PREPARE" else "👀"
                
                ews_data.append({
                    "Symbol": pick.get("symbol", ""),
                    "Level": f"{level_emoji} {level}",
                    "IPI Score": f"{pick.get('score', 0):.2f}",
                    "Footprints": pick.get("footprints", 0),
                    "Action": "BUY PUTS" if level in ["ACT", "PREPARE"] else "WATCH"
                })
            
            st.dataframe(ews_data, use_container_width=True)
        else:
            st.info("No EWS picks meet criteria for current market direction")
    else:
        st.info("No Early Warning data available")
    
    # Engine picks in columns
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("### ⚡ Gamma Drain")
        gamma_picks = engine_picks.get("gamma_drain", [])
        
        if gamma_picks and show_all:
            for pick in gamma_picks[:5]:
                score = pick.get("score", 0)
                st.markdown(f"""
                **{pick.get('symbol', 'N/A')}** - Score: {score:.2f}
                - Signals: {', '.join(pick.get('signals', [])[:2]) or 'N/A'}
                """)
        else:
            st.info("No Gamma Drain picks" if not gamma_picks else "Hidden (bullish market)")
    
    with col2:
        st.markdown("### 📉 Distribution")
        dist_picks = engine_picks.get("distribution", [])
        
        if dist_picks and show_all:
            for pick in dist_picks[:5]:
                score = pick.get("score", 0)
                st.markdown(f"""
                **{pick.get('symbol', 'N/A')}** - Score: {score:.2f}
                - Signals: {', '.join(pick.get('signals', [])[:2]) or 'N/A'}
                """)
        else:
            st.info("No Distribution picks" if not dist_picks else "Hidden (bullish market)")
    
    with col3:
        st.markdown("### 💧 Liquidity Vacuum")
        liq_picks = engine_picks.get("liquidity", [])
        
        if liq_picks and show_all:
            for pick in liq_picks[:5]:
                score = pick.get("score", 0)
                st.markdown(f"""
                **{pick.get('symbol', 'N/A')}** - Score: {score:.2f}
                - Signals: {', '.join(pick.get('signals', [])[:2]) or 'N/A'}
                """)
        else:
            st.info("No Liquidity picks" if not liq_picks else "Hidden (bullish market)")


def display_finviz_sentiment():
    """Display Finviz sector sentiment, news, and options skew."""
    
    st.markdown("---")
    st.markdown("### 📰 Sector Performance & Smart Money Signals (Finviz)")
    
    # Get Finviz data
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        finviz_data = loop.run_until_complete(get_finviz_data())
        loop.close()
    except Exception as e:
        finviz_data = {"sectors": [], "news": [], "insiders": {}}
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("#### 📊 Weak Sectors (Put Targets)")
        sectors = finviz_data.get("sectors", [])
        
        if sectors:
            bearish = [n for n in sectors if n.get("change", 0) < -1]
            
            for item in bearish[:5]:
                st.markdown(f"🔴 **{item.get('sector', 'N/A')}**: {item.get('change', 0):+.1f}%")
            
            if not bearish:
                st.success("No weak sectors - Market healthy")
        else:
            st.info("Sector data not available")
    
    with col2:
        st.markdown("#### 📰 Market News Sentiment")
        news = finviz_data.get("news", [])
        
        if news:
            bearish_news = [n for n in news if n.get("sentiment") == "bearish"]
            bullish_news = [n for n in news if n.get("sentiment") == "bullish"]
            
            # Summary metrics
            st.metric(
                "News Sentiment", 
                f"🔴 {len(bearish_news)} | 🟢 {len(bullish_news)}",
                help="Bearish vs Bullish headlines"
            )
            
            # Show top bearish headlines
            if bearish_news:
                st.markdown("**Recent Bearish:**")
                for item in bearish_news[:3]:
                    st.caption(f"🔴 {item.get('title', '')[:60]}...")
        else:
            st.info("News not available")
    
    with col3:
        st.markdown("#### 📈 Options Skew (Smart Money)")
        
        # Show skew from market direction data
        md_data = load_market_direction()
        if md_data:
            raw_data = md_data.get("raw_data", {})
            skew_data = raw_data.get("skew", {})
            
            if skew_data:
                skew_value = skew_data.get("skew", 1.0)
                skew_emoji = "🔴" if skew_value > 1.2 else "🟢" if skew_value < 0.8 else "⚪"
                st.metric(
                    "Put/Call Skew",
                    f"{skew_emoji} {skew_value:.2f}",
                    help="High (>1.2) = Bearish hedging"
                )
                st.caption(skew_data.get("interpretation", ""))
            else:
                st.info("Run Market Direction Analysis")
        else:
            st.info("Run Market Direction Analysis")
        
        # Show insider selling from Finviz
        insiders = finviz_data.get("insiders", {})
        if insiders:
            seller_count = insiders.get("insider_sellers", 0)
            if seller_count > 0:
                st.metric("Insider Selling", f"🔴 {seller_count} stocks")
    
    # Options skew explanation
    with st.expander("ℹ️ Why Options Skew > Reddit Sentiment"):
        st.markdown("""
        **Options skew reflects where INSTITUTIONS are hedging:**
        - High put skew (>1.2) = Smart money buying protection = BEARISH
        - Low put skew (<0.8) = Complacency = BULLISH (or trap)
        - Options are LEVERAGED bets - they show conviction
        - Reddit/Stocktwits sentiment is noise - retail doesn't move markets
        
        **THE HARD TRUTH:** Trust the skew, not the chatter.
        """)


def display_best_8_picks(market_direction: Dict, best_plays: List[Dict], ews_picks: List[Dict], engine_picks: Dict):
    """Display the 8 best picks based on market direction, EWS, and engines."""
    
    st.markdown("---")
    st.markdown("## 🏆 TODAY'S 8 BEST PLAYS")
    
    # If market direction has best_plays, use them
    if best_plays:
        play_data = []
        for i, play in enumerate(best_plays[:8], 1):
            action = play.get("action", "WATCH")
            action_emoji = "🎯" if "PUT" in action else "⏸️" if "WAIT" in action else "👀"
            
            play_data.append({
                "#": i,
                "Symbol": play.get("symbol", ""),
                "Action": f"{action_emoji} {action}",
                "Reason": play.get("reason", ""),
                "Note": play.get("note", "")
            })
        
        st.dataframe(play_data, use_container_width=True, hide_index=True)
        
    else:
        # Generate picks from EWS and Engine data
        combined_picks = []
        
        # Add EWS picks (highest priority)
        for pick in ews_picks[:4]:
            level = pick.get("level", "WATCH")
            action = "BUY PUTS" if level == "ACT" else "PREPARE PUTS" if level == "PREPARE" else "WATCH"
            combined_picks.append({
                "symbol": pick.get("symbol", ""),
                "action": action,
                "reason": f"EWS {level} - IPI: {pick.get('score', 0):.2f}",
                "note": f"{pick.get('footprints', 0)} footprints",
                "priority": 3 if level == "ACT" else 2 if level == "PREPARE" else 1
            })
        
        # Add engine picks
        for engine_name, engine_list in engine_picks.items():
            for pick in engine_list[:2]:
                combined_picks.append({
                    "symbol": pick.get("symbol", ""),
                    "action": "BUY PUTS" if pick.get("score", 0) > 0.6 else "WATCH",
                    "reason": f"{engine_name.replace('_', ' ').title()} - Score: {pick.get('score', 0):.2f}",
                    "note": ", ".join(pick.get("signals", [])[:2]),
                    "priority": pick.get("score", 0)
                })
        
        # Dedupe by symbol and sort by priority
        seen = set()
        unique_picks = []
        for pick in sorted(combined_picks, key=lambda x: x.get("priority", 0), reverse=True):
            if pick.get("symbol") and pick.get("symbol") not in seen:
                seen.add(pick.get("symbol"))
                unique_picks.append(pick)
        
        if unique_picks:
            play_data = []
            for i, play in enumerate(unique_picks[:8], 1):
                action = play.get("action", "WATCH")
                action_emoji = "🎯" if "PUT" in action else "⏸️" if "WAIT" in action else "👀"
                
                play_data.append({
                    "#": i,
                    "Symbol": play.get("symbol", ""),
                    "Action": f"{action_emoji} {action}",
                    "Reason": play.get("reason", ""),
                    "Note": play.get("note", "")
                })
            
            st.dataframe(play_data, use_container_width=True, hide_index=True)
        else:
            st.info("No picks available. Run Market Direction Analysis or wait for scan results.")
    
    # Avoid section
    avoid_plays = market_direction.get("avoid_plays", []) if market_direction else []
    
    if avoid_plays:
        st.markdown("### ⚠️ AVOID TODAY")
        for avoid in avoid_plays:
            st.markdown(f"- ❌ **{avoid.get('symbol', 'N/A')}**: {avoid.get('reason', '')}")


# ============================================================================
# MAIN RENDER FUNCTION
# ============================================================================

def render_market_direction_tab():
    """
    Render the MarketPulse Pre-Market Regime tab.
    
    This is completely isolated from other tabs.
    Implements consolidated Architect-2,3,4,5 feedback.
    """
    
    st.markdown("# 🌊 MarketPulse - Pre-Market Regime")
    st.markdown("*Regime Awareness, Not Prediction | 52-58% Edge for Risk Gating*")
    
    # Refresh button
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        if st.button("🔄 Run Live Analysis", key="run_md_analysis"):
            with st.spinner("Running MarketPulse Analysis..."):
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(run_live_market_pulse())
                    loop.close()
                    st.success("Analysis complete!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
    
    with col2:
        if st.button("🔃 Refresh Data", key="refresh_md_data"):
            st.rerun()
    
    with col3:
        # Show last update time
        md_data = load_market_direction()
        if md_data:
            timestamp = md_data.get("timestamp", "")
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp)
                    st.caption(f"Last updated: {dt.strftime('%Y-%m-%d %H:%M:%S ET')}")
                except:
                    pass
    
    st.markdown("---")
    
    # Load all data
    market_direction = load_market_direction()
    engine_picks = load_engine_picks()
    ews_picks = load_early_warning_picks()
    
    # Display MarketPulse regime analysis
    display_market_pulse(market_direction)
    
    # Display best 8 picks - combining market direction, EWS, and engines
    best_plays = market_direction.get("best_plays", []) if market_direction else []
    display_best_8_picks(market_direction, best_plays, ews_picks, engine_picks)
    
    # Display filtered picks from engines
    display_filtered_picks(market_direction, engine_picks, ews_picks)
    
    # Display Finviz sentiment
    display_finviz_sentiment()
    
    # Conditional picks from MarketPulse
    conditional_picks = market_direction.get("conditional_picks", []) if market_direction else []
    if conditional_picks:
        st.markdown("---")
        st.markdown("### 🎯 CONDITIONAL PUT CANDIDATES")
        st.warning("⚠️ These are symbols only. Structure delegated to Vega Gate. NOT trade recommendations.")
        
        pick_data = []
        for i, pick in enumerate(conditional_picks, 1):
            pick_data.append({
                "#": i,
                "Symbol": pick.get("symbol", ""),
                "Reason": pick.get("reason", ""),
                "Type": pick.get("type", "")
            })
        
        if pick_data:
            st.dataframe(pick_data, use_container_width=True, hide_index=True)
    
    # Footer
    st.markdown("---")
    st.caption("""
    **Philosophy:** PRESSURE → PERMISSION → STRUCTURE (unchanged)
    
    **Data Sources:** Polygon (Massive), Unusual Whales, Finviz
    
    **Weights:** Futures 30% | VIX 25% | Gamma 20% | Breadth 15% | Sentiment 10%
    
    **Schedule:** MarketPulse runs at 8:00 AM & 9:00 AM ET
    
    **Honest Expectation:** 52-58% opening direction edge. NOT full-day prediction.
    """)


# For testing
if __name__ == "__main__":
    st.set_page_config(page_title="Market Direction", layout="wide")
    render_market_direction_tab()
