"""
🎯 CONVERGENCE ENGINE v2.0 — Automated 4-Step Decision Hierarchy
================================================================
Merges the FOUR independent detection systems into a single
"Top 9 Candidates" board that auto-updates every 30 minutes.

DECISION HIERARCHY (fully automated, zero manual intervention):
  Step 1: 🚨 Early Warning (WHO is about to fall?)        — 35% weight
  Step 2: 📈 Market Direction (Is the MARKET allowing?)   — 15% weight  
  Step 3: 🔥 Gamma Drain (Confirms with real-time score)  — 25% weight
  Step 4: 🌪️ Predictive System (Cross-validates storm)    — 25% weight

v2.0 ENHANCEMENTS (PhD quant + institutional microstructure):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• TRIFECTA BONUS: Stocks in 2+ Gamma Drain sub-engines (distribution +
  liquidity + gamma_drain) get a 1.15x multiplier. True trifecta = 1.25x.
  Rationale: Multiple independent dealer-positioning signals converging is
  like two weather radars showing the same storm. False positive rate drops
  exponentially with each independent confirmation.

• TRAJECTORY TRACKING: Saves convergence history and computes score delta
  vs last run. ↑ RISING = storm building, ↓ FALLING = dissipating,
  → STABLE = holding pattern. Tracks "days on list" for persistence.
  Rationale: A stock that was 0.5 yesterday and 0.8 today is ACCELERATING
  into breakdown. Time-series of conviction is more informative than a
  single snapshot. Institutional sellers don't finish in one day.

• SECTOR DIVERSITY: If 4+ of Top 9 are from the same sector, rotates in
  next-best from underrepresented sectors. Market crashes aren't uniform.
  Rationale: Sector concentration = correlated risk. If all picks are
  crypto, one sector bounce wipes all positions. Diversification is the
  only free lunch (Markowitz 1952, still holds).

• SELF-HEALING v2: Source staleness is market-hours-aware. Weekend data
  from Friday close is "FRESH" until Monday pre-market. If an engine
  crashes, the convergence gracefully degrades rather than going blank.
  "Stale" is surfaced prominently, not silently swallowed.

• PIPELINE STATUS: Records which engines ran recently and when, surfacing
  a "pipeline heartbeat" in the dashboard. If EWS hasn't run in 2 hours
  during market hours, that's a red flag.

CONVERGENCE SCORING (institutional microstructure rationale):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• EWS IPI (35%): Dark pool sequences can't be hidden. When a stock shows
  10+ dark pool prints in a price-declining sequence, that's institutional
  selling pressure. Put OI accumulation = pre-news positioning (buying
  insurance before the fire). IV term inversion = someone knows something
  — they're paying MORE for near-term protection than long-term.
  This LEADS price by 1-3 days because institutions can't liquidate
  large positions instantaneously (Almgren-Chriss optimal execution).

• Gamma Drain (25%): When a stock appears in BOTH EWS and Gamma Drain,
  institutional selling (EWS) + dealer positioning (GD) are aligning.
  The Gamma Drain engine specifically looks at distribution patterns
  (smart money selling into retail buying), liquidity vacuums (bid
  depth thinning), and dealer gamma exposure (market maker hedging
  creating directional pressure). This is CONFIRMATION of EWS signals
  from a completely independent measurement of the order book.

• Weather/Storm (25%): Multi-layer convergence using structural (SMA
  breakdown), institutional (dark pool + OI), technical (RSI/MACD
  acceleration), and catalyst (earnings/news proximity) layers.
  Adds TIMING (when) and MAGNITUDE (expected drop %) estimation.

• Market Direction (15%): Regime gating. RISK_OFF → put amplifier,
  RISK_ON → dampener. Market structure must ALLOW the trade.
  In RISK_ON, even the strongest individual signal needs a higher
  threshold because mean-reversion dominates. In RISK_OFF, momentum
  cascades make puts significantly more profitable (VIX expansion +
  correlation spike = all boats sink together).

PERMISSION LIGHT (tradability gate):
  🟢 TRADE:      convergence ≥ 0.55 AND regime allows AND ≥2 sources agree
  🟡 WATCH:      convergence ≥ 0.30 OR 1 strong source (EWS ACT or GD ≥ 0.68)
  🔴 STAND DOWN: convergence < 0.30 OR regime blocks puts

SELF-HEALING:
  • Missing source → use available data, mark missing, reduce confidence
  • Stale data (>2h market hours) → "⚠️ STALE" indicator
  • Engine crash → write status="degraded" with error context
  • Auto-recovers next run cycle (30 min)
  • History preserved for trajectory analysis

OUTPUT: logs/convergence/latest_top9.json
        logs/convergence/history_YYYYMMDD_HHMM.json
"""

import json
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field, asdict
from loguru import logger
from collections import Counter
import pytz

ET = pytz.timezone('US/Eastern')

# ============================================================================
# DATA PATHS
# ============================================================================
EWS_FILE = Path("early_warning_alerts.json")
DIRECTION_FILE = Path("logs/market_direction.json")
SCAN_RESULTS_FILE = Path("scheduled_scan_results.json")
WEATHER_AM_FILE = Path("logs/market_weather/latest_am.json")
WEATHER_PM_FILE = Path("logs/market_weather/latest_pm.json")
INTRADAY_FILE = Path("intraday_alerts.json")         # Gap 12: Intraday momentum
FINVIZ_BEARISH_FILE = Path("logs/finviz_bearish.json")  # Gap 5/6: FinViz sentiment
SHORT_INTEREST_FILE = Path("logs/finviz_short_interest.json")  # Gap 7: Short interest
BACKTEST_FILE = Path("logs/convergence/backtest_ledger.json")  # Gap 9: Backtest
OUTPUT_DIR = Path("logs/convergence")
OUTPUT_FILE = OUTPUT_DIR / "latest_top9.json"
HISTORY_DIR = OUTPUT_DIR / "history"

# ============================================================================
# WEIGHTS — Institutional Microstructure Rationale (see docstring)
# ============================================================================
WEIGHT_EWS = 0.35
WEIGHT_GAMMA = 0.25
WEIGHT_WEATHER = 0.25
WEIGHT_DIRECTION = 0.15

# Staleness thresholds (seconds)
STALE_WARN_SECONDS = 7200       # 2 hours → "⚠️ STALE" during market hours
STALE_CRITICAL_SECONDS = 14400  # 4 hours → "🔴 CRITICAL STALE"
STALE_WEEKEND_SECONDS = 172800  # 48 hours → acceptable for weekend

# Sector diversity: max picks from same sector in Top 9
MAX_SAME_SECTOR = 3


@dataclass
class SourceStatus:
    """Health status of a single data source"""
    name: str
    available: bool = False
    timestamp: str = ""
    age_seconds: float = 0.0
    freshness: str = "MISSING"       # FRESH / STALE / CRITICAL / MISSING
    record_count: int = 0
    error: str = ""


@dataclass
class ConvergenceCandidate:
    """A single stock scored across all 4 systems"""
    symbol: str
    convergence_score: float = 0.0
    permission_light: str = "🔴"     # 🟢 / 🟡 / 🔴
    
    # Source scores (0-1 normalized)
    ews_score: float = 0.0           # From EWS IPI
    ews_level: str = ""              # ACT / PREPARE / WATCH
    ews_footprints: int = 0
    ews_days_building: int = 0
    ews_recommendation: str = ""
    
    gamma_score: float = 0.0         # From Gamma Drain composite
    gamma_signals: List[str] = field(default_factory=list)
    gamma_engine: str = ""           # gamma_drain / distribution / liquidity
    gamma_engines_count: int = 0     # v2: How many sub-engines flagged this
    gamma_is_trifecta: bool = False  # v2: In all 3 sub-engines
    
    weather_score: float = 0.0       # From Weather storm_score
    weather_forecast: str = ""       # STORM WARNING / WATCH / ADVISORY / etc
    weather_layers: int = 0
    weather_confidence: str = ""
    
    direction_alignment: float = 0.0 # 0-1 how aligned with bearish regime
    direction_regime: str = ""       # RISK_OFF / NEUTRAL / RISK_ON
    
    # Derived
    sources_agreeing: int = 0        # How many of 4 systems flagged this stock
    source_list: List[str] = field(default_factory=list)
    sector: str = ""
    current_price: float = 0.0
    expected_drop: str = ""
    timing: str = ""
    
    # Staleness
    data_age: str = ""               # Oldest data source age
    
    # v2.0: Trajectory
    trajectory: str = "NEW"          # RISING / FALLING / STABLE / NEW
    trajectory_emoji: str = "🆕"     # 🔺 / 🔻 / ➡️ / 🆕
    prev_score: float = 0.0          # Previous convergence score
    score_delta: float = 0.0         # Change from previous
    days_on_list: int = 0            # How many consecutive runs on Top 9
    
    # v3.0: Gap fix fields
    intraday_confirmed: bool = False  # Gap 12: Intraday momentum confirmed
    intraday_drop: float = 0.0        # Gap 12: Intraday % drop
    finviz_bearish: bool = False      # Gap 5/6: FinViz bearish signal
    short_float: float = 0.0          # Gap 7: Short interest %
    sector_contagion: bool = False    # Gap 11: Sector contagion detected


class ConvergenceEngine:
    """
    Merges 4+ detection systems into unified Top 9 candidates.
    
    v2.0: Trifecta bonus, trajectory tracking, sector diversity, 
    enhanced self-healing, pipeline status.
    
    v3.0 (Gap Fixes Feb 9, 2026):
    - Gap 3: Properly reads pattern-populated scan data
    - Gap 5/6: Integrates FinViz bearish sentiment + macro signals
    - Gap 7: Integrates short interest data for squeeze/cascade detection
    - Gap 9: Backtesting ledger for historical calibration
    - Gap 11: Enhanced cross-asset divergence via sector correlation
    - Gap 12: Intraday momentum feed for same-day signal boosting
    
    Self-healing:
    - Gracefully handles missing/corrupt files
    - Marks stale data with indicators
    - Writes degraded status on failure
    - Auto-recovers on next scheduled run (30 min)
    """
    
    def __init__(self):
        self.now = datetime.now(ET)
        self.source_statuses: Dict[str, SourceStatus] = {}
        self._ews_data: Dict = {}
        self._direction_data: Dict = {}
        self._scan_data: Dict = {}
        self._weather_data: Dict = {}
        self._intraday_data: List = []        # Gap 12: Intraday momentum
        self._finviz_bearish: List = []        # Gap 5/6: FinViz sentiment
        self._short_interest: Dict = {}        # Gap 7: Short interest
        self._previous_top9: Dict[str, Dict] = {}  # v2: previous run data
    
    def run(self) -> Dict:
        """
        Main entry point. Reads all 4 sources, merges, ranks, outputs Top 9.
        
        Returns the convergence report dict (also saved to JSON).
        """
        self.now = datetime.now(ET)
        logger.info("=" * 70)
        logger.info("🎯 CONVERGENCE ENGINE v2.0 — Automated Decision Hierarchy")
        logger.info(f"Time: {self.now.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info("Step 1: EWS (35%) → Step 2: Direction (15%) → Step 3: Gamma (25%) → Step 4: Weather (25%)")
        logger.info("=" * 70)
        
        try:
            # Step 0: Load previous run for trajectory comparison
            self._load_previous_top9()
            
            # Step 1: Load all data sources (self-healing — tolerates missing data)
            self._load_ews()
            self._load_direction()
            self._load_scan_results()
            self._load_weather()
            
            # Step 1b: Load supplementary data sources (Gaps 5/6/7/12)
            # These are optional — engine works without them, but they boost quality
            self._load_intraday_alerts()     # Gap 12: Intraday momentum
            self._load_finviz_bearish()       # Gap 5/6: Sentiment + macro
            self._load_short_interest()       # Gap 7: Short interest
            
            # Log source status
            available_count = sum(1 for s in self.source_statuses.values() if s.available)
            logger.info(f"Data sources available: {available_count}/4")
            for name, status in self.source_statuses.items():
                icon = "✅" if status.available else "❌"
                fresh_icon = {"FRESH": "🟢", "STALE": "🟡", "CRITICAL": "🔴", "MISSING": "❌"}.get(status.freshness, "❓")
                logger.info(f"  {icon} {name}: {fresh_icon} {status.freshness} | {status.record_count} records | age: {status.age_seconds:.0f}s")
            
            if available_count == 0:
                logger.error("NO data sources available. Writing degraded report.")
                return self._write_degraded("All 4 data sources unavailable")
            
            # Step 2: Build candidate universe (union of all tickers across all sources)
            all_candidates = self._merge_candidates()
            logger.info(f"Unique candidate tickers: {len(all_candidates)}")
            
            # Step 3: Score each candidate
            scored = self._score_candidates(all_candidates)
            
            # Step 4: Rank and select Top 9 with sector diversity
            top9 = self._select_top9_diverse(scored)
            
            # Step 5: Assign permission lights
            for c in top9:
                c.permission_light = self._assign_permission(c)
            
            # Step 6: Compute trajectory vs previous run
            self._compute_trajectories(top9)
            
            # Step 7: Build and save report
            report = self._build_report(top9)
            self._save_report(report)
            self._save_history(report)
            
            # Log results
            logger.info(f"Top 9 convergence candidates:")
            for i, c in enumerate(top9, 1):
                trifecta_tag = " [TRIFECTA]" if c.gamma_is_trifecta else f" [{c.gamma_engines_count}eng]" if c.gamma_engines_count >= 2 else ""
                logger.info(
                    f"  #{i} {c.permission_light} {c.symbol:8s} "
                    f"conv={c.convergence_score:.3f} {c.trajectory_emoji} "
                    f"src={c.sources_agreeing}/4 "
                    f"[EWS={c.ews_score:.2f} GD={c.gamma_score:.2f} "
                    f"WX={c.weather_score:.2f} DIR={c.direction_alignment:.2f}] "
                    f"{','.join(c.source_list)}{trifecta_tag}"
                )
            
            # Step 8: Inject EWS ACT/PREPARE tickers into DUI
            # This ensures that stocks with institutional footprints get
            # scanned by the Gamma Drain/Distribution/Liquidity engines
            # in subsequent scheduled scans. BRIDGES the coverage gap.
            self._inject_ews_to_dui()
            
            # Step 9 (Gap 9): Record backtest ledger entry for calibration
            # Logs each Top 9 pick with timestamp for future T+1/T+2 price comparison
            self._record_backtest_entry(top9)
            
            logger.info("✅ Convergence Engine v3.0 complete (all gaps fixed)")
            return report
            
        except Exception as e:
            logger.error(f"Convergence Engine FAILED: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return self._write_degraded(str(e))
    
    # ======================================================================
    # DATA LOADERS (self-healing — each handles its own errors)
    # ======================================================================
    
    def _load_previous_top9(self):
        """Load previous convergence run for trajectory comparison."""
        try:
            if OUTPUT_FILE.exists():
                with open(OUTPUT_FILE) as f:
                    prev = json.load(f)
                for c in prev.get("top9", []):
                    sym = c.get("symbol", "")
                    if sym:
                        self._previous_top9[sym] = c
                logger.debug(f"Previous run loaded: {len(self._previous_top9)} candidates")
        except Exception as e:
            logger.debug(f"No previous run (first time or corrupt): {e}")
    
    def _load_ews(self):
        """Load Early Warning System alerts"""
        status = SourceStatus(name="Early Warning (EWS)")
        try:
            if not EWS_FILE.exists():
                status.error = "File not found"
                self.source_statuses["ews"] = status
                return
            
            with open(EWS_FILE) as f:
                data = json.load(f)
            
            alerts = data.get("alerts", {})
            ts = data.get("timestamp", "")
            
            status.available = len(alerts) > 0
            status.timestamp = ts
            status.age_seconds = self._calc_age(ts)
            status.freshness = self._classify_freshness(status.age_seconds)
            status.record_count = len(alerts)
            
            self._ews_data = data
            
        except Exception as e:
            status.error = str(e)
            logger.warning(f"EWS load error: {e}")
        
        self.source_statuses["ews"] = status
    
    def _load_direction(self):
        """Load Market Direction analysis"""
        status = SourceStatus(name="Market Direction")
        try:
            if not DIRECTION_FILE.exists():
                status.error = "File not found"
                self.source_statuses["direction"] = status
                return
            
            with open(DIRECTION_FILE) as f:
                data = json.load(f)
            
            ts = data.get("timestamp", "")
            
            status.available = bool(data.get("regime"))
            status.timestamp = ts
            status.age_seconds = self._calc_age(ts)
            status.freshness = self._classify_freshness(status.age_seconds)
            status.record_count = len(data.get("conditional_picks", []))
            
            self._direction_data = data
            
        except Exception as e:
            status.error = str(e)
            logger.warning(f"Direction load error: {e}")
        
        self.source_statuses["direction"] = status
    
    def _load_scan_results(self):
        """Load Gamma Drain / Distribution / Liquidity scan results"""
        status = SourceStatus(name="Gamma Drain Engine")
        try:
            if not SCAN_RESULTS_FILE.exists():
                status.error = "File not found"
                self.source_statuses["gamma"] = status
                return
            
            with open(SCAN_RESULTS_FILE) as f:
                data = json.load(f)
            
            ts = data.get("last_scan", "")
            total = (
                len(data.get("gamma_drain", [])) +
                len(data.get("distribution", [])) +
                len(data.get("liquidity", []))
            )
            
            status.available = total > 0
            status.timestamp = ts
            status.age_seconds = self._calc_age(ts)
            status.freshness = self._classify_freshness(status.age_seconds)
            status.record_count = total
            
            self._scan_data = data
            
        except Exception as e:
            status.error = str(e)
            logger.warning(f"Scan results load error: {e}")
        
        self.source_statuses["gamma"] = status
    
    def _load_weather(self):
        """Load Market Weather forecast (latest of AM/PM)"""
        status = SourceStatus(name="Weather Forecast")
        try:
            # Try PM first (most recent), then AM
            data = None
            for path in [WEATHER_PM_FILE, WEATHER_AM_FILE]:
                if path.exists():
                    with open(path) as f:
                        candidate = json.load(f)
                    if candidate.get("status") != "degraded":
                        if data is None:
                            data = candidate
                        else:
                            # Pick the newer one
                            if candidate.get("timestamp", "") > data.get("timestamp", ""):
                                data = candidate
            
            if not data:
                status.error = "No valid weather data found"
                self.source_statuses["weather"] = status
                return
            
            ts = data.get("timestamp", "")
            forecasts = data.get("forecasts", [])
            
            status.available = len(forecasts) > 0
            status.timestamp = ts
            status.age_seconds = self._calc_age(ts)
            status.freshness = self._classify_freshness(status.age_seconds)
            status.record_count = len(forecasts)
            
            self._weather_data = data
            
        except Exception as e:
            status.error = str(e)
            logger.warning(f"Weather load error: {e}")
        
        self.source_statuses["weather"] = status
    
    # ======================================================================
    # GAP 12: Load Intraday Momentum Alerts
    # ======================================================================
    
    def _load_intraday_alerts(self):
        """
        Gap 12 Fix: Load intraday big mover alerts so same-day drops
        boost convergence scores. A stock dropping 3%+ intraday with
        EWS footprints is very high conviction.
        """
        try:
            if not INTRADAY_FILE.exists():
                return
            with open(INTRADAY_FILE) as f:
                data = json.load(f)
            alerts = data.get("alerts", data if isinstance(data, list) else [])
            ts = data.get("timestamp", "") if isinstance(data, dict) else ""
            age = self._calc_age(ts) if ts else 99999
            # Only use intraday data if fresh (< 2 hours old)
            if age < 7200:
                self._intraday_data = alerts
                logger.debug(f"Intraday alerts loaded: {len(alerts)} movers")
            else:
                logger.debug(f"Intraday alerts stale ({age:.0f}s), skipping")
        except Exception as e:
            logger.debug(f"Intraday load (non-fatal): {e}")
    
    # ======================================================================
    # GAP 5/6: Load FinViz Bearish Candidates + Macro Sentiment
    # ======================================================================
    
    def _load_finviz_bearish(self):
        """
        Gap 5/6 Fix: Load FinViz bearish candidate data if available.
        This includes insider selling, analyst downgrades, technical
        weakness, and sector performance — all from FinViz Elite.
        
        Macro events are captured via FinViz news sentiment scoring.
        """
        try:
            if not FINVIZ_BEARISH_FILE.exists():
                return
            with open(FINVIZ_BEARISH_FILE) as f:
                data = json.load(f)
            candidates = data.get("candidates", [])
            ts = data.get("timestamp", "")
            age = self._calc_age(ts) if ts else 99999
            # FinViz data is daily — accept up to 24 hours
            if age < 86400:
                self._finviz_bearish = candidates
                logger.debug(f"FinViz bearish loaded: {len(candidates)} candidates")
        except Exception as e:
            logger.debug(f"FinViz bearish load (non-fatal): {e}")
    
    # ======================================================================
    # GAP 7: Load Short Interest Data
    # ======================================================================
    
    def _load_short_interest(self):
        """
        Gap 7 Fix: Load short interest data from FinViz.
        High short interest (>15%) changes the dynamics:
        - With bearish signals → cascade risk (shorts pile on)
        - Without bearish signals → squeeze risk (avoid)
        """
        try:
            if not SHORT_INTEREST_FILE.exists():
                return
            with open(SHORT_INTEREST_FILE) as f:
                data = json.load(f)
            self._short_interest = data.get("data", data if isinstance(data, dict) else {})
            logger.debug(f"Short interest loaded: {len(self._short_interest)} stocks")
        except Exception as e:
            logger.debug(f"Short interest load (non-fatal): {e}")
    
    # ======================================================================
    # CANDIDATE MERGER — Union of all tickers from all 4 systems
    # ======================================================================
    
    def _merge_candidates(self) -> Dict[str, Dict]:
        """
        Build a universe of all tickers mentioned across all 4 systems.
        
        v2.0: Also tracks which Gamma Drain sub-engines flagged each ticker
        for trifecta detection.
        """
        universe: Dict[str, Dict] = {}
        
        # --- EWS: Extract tickers with IPI scores ---
        ews_alerts = self._ews_data.get("alerts", {})
        for symbol, alert in ews_alerts.items():
            if symbol not in universe:
                universe[symbol] = {"symbol": symbol}
            
            ipi = alert.get("ipi_score", alert.get("ipi", 0.0))
            level = alert.get("level", "")
            footprints = alert.get("footprints_count", alert.get("unique_footprints", 0))
            days = alert.get("days_building", 0)
            
            universe[symbol]["ews_ipi"] = ipi
            universe[symbol]["ews_level"] = level
            universe[symbol]["ews_footprints"] = footprints
            universe[symbol]["ews_days_building"] = days
            universe[symbol]["ews_recommendation"] = alert.get("recommendation", "")
        
        # --- Gamma Drain / Distribution / Liquidity ---
        # v2.0: Track which sub-engines flagged each ticker
        engine_membership: Dict[str, Set[str]] = {}  # symbol -> {engine_keys}
        
        for engine_key in ["gamma_drain", "distribution", "liquidity"]:
            candidates = self._scan_data.get(engine_key, [])
            for c in candidates:
                sym = c.get("symbol", "")
                if not sym:
                    continue
                if sym not in universe:
                    universe[sym] = {"symbol": sym}
                
                # Track engine membership for trifecta
                if sym not in engine_membership:
                    engine_membership[sym] = set()
                engine_membership[sym].add(engine_key)
                
                score = c.get("score", 0.0)
                # Keep highest score if in multiple engines
                existing = universe[sym].get("gamma_score", 0.0)
                if score > existing:
                    universe[sym]["gamma_score"] = score
                    universe[sym]["gamma_engine"] = engine_key
                    universe[sym]["gamma_signals"] = c.get("signals", [])
                
                # Capture price/sector from scan data
                if c.get("current_price"):
                    universe[sym]["current_price"] = c["current_price"]
                if c.get("close"):
                    universe[sym]["current_price"] = c["close"]
                if c.get("sector"):
                    universe[sym]["sector"] = c["sector"]
        
        # Store engine membership count for each symbol
        for sym, engines in engine_membership.items():
            if sym in universe:
                universe[sym]["gamma_engines_count"] = len(engines)
                universe[sym]["gamma_engines_list"] = list(engines)
                universe[sym]["gamma_is_trifecta"] = len(engines) >= 3
        
        # ─── v2.1: SYNTHETIC GAMMA SCORE for EWS-only stocks ───
        # Problem: EWS finds stocks with institutional footprints (dark pool,
        # IV inversion, distribution) but if the stock isn't in scan_results,
        # it gets gamma_score=0 → low convergence score → never surfaces.
        #
        # Solution: Map EWS footprint types to the Gamma Drain sub-engine
        # that would detect the same signal. This bridges the coverage gap.
        #
        # Rationale: EWS footprints ARE institutional signals:
        #   - dark_pool_sequence → Distribution engine would detect this
        #   - iv_term_inversion → Dealer/Acceleration engine would detect this
        #   - multi_day_distribution → Distribution engine directly
        #   - quote_degradation → Liquidity engine would detect this
        #   - put_oi_accumulation → Distribution engine
        #   - net_premium_flow → Distribution engine
        # So if EWS has 3+ diverse footprints on a stock but Gamma Drain
        # hasn't scanned it, we can infer a synthetic score.
        
        FOOTPRINT_TO_ENGINE = {
            "dark_pool_sequence": "distribution",
            "iv_term_inversion": "gamma_drain",
            "multi_day_distribution": "distribution",
            "quote_degradation": "liquidity",
            "put_oi_accumulation": "distribution",
            "net_premium_flow": "distribution",
            "flow_divergence": "gamma_drain",
            "cross_asset_divergence": "gamma_drain",
        }
        
        for sym, data in universe.items():
            ews_ipi = data.get("ews_ipi", 0.0)
            ews_level = data.get("ews_level", "")
            has_gamma = data.get("gamma_score", 0.0) > 0
            
            # Only synthesize for EWS stocks NOT already in scan results
            if ews_ipi > 0.3 and not has_gamma:
                # Get footprint types from EWS alerts
                alert = ews_alerts.get(sym, {})
                footprints = alert.get("footprints", [])
                
                # Map footprint types to sub-engines
                synthetic_engines = set()
                total_strength = 0.0
                fp_count = 0
                unique_types = set()
                
                for fp in footprints:
                    if isinstance(fp, dict):
                        fp_type = fp.get("type", "")
                        fp_strength = float(fp.get("strength", 0))
                        if fp_type and fp_type not in unique_types:
                            unique_types.add(fp_type)
                            total_strength += fp_strength
                            fp_count += 1
                            engine = FOOTPRINT_TO_ENGINE.get(fp_type)
                            if engine:
                                synthetic_engines.add(engine)
                
                if fp_count >= 2:  # Need at least 2 unique footprint types
                    # Compute synthetic gamma score:
                    # Base = IPI score (0-1) × 0.7 (discount for indirect measurement)
                    # + footprint diversity bonus (more types = more convincing)
                    avg_strength = total_strength / fp_count if fp_count > 0 else 0
                    diversity_bonus = min(0.15, len(unique_types) * 0.03)
                    
                    synthetic_score = min(1.0, ews_ipi * 0.7 + diversity_bonus + avg_strength * 0.1)
                    
                    # Only apply if meaningfully better than zero
                    if synthetic_score >= 0.3:
                        data["gamma_score"] = synthetic_score
                        data["gamma_engine"] = "ews_synthetic"
                        data["gamma_signals"] = list(unique_types)
                        data["gamma_engines_count"] = len(synthetic_engines)
                        data["gamma_engines_list"] = list(synthetic_engines)
                        data["gamma_is_trifecta"] = len(synthetic_engines) >= 3
                        data["synthetic_gamma"] = True  # Flag for display
                        
                        logger.info(
                            f"  {sym}: SYNTHETIC gamma={synthetic_score:.3f} "
                            f"(from EWS IPI={ews_ipi:.3f}, {fp_count} footprints, "
                            f"engines={synthetic_engines})"
                        )
        
        # --- Weather: Extract storm scores ---
        forecasts = self._weather_data.get("forecasts", [])
        for fc in forecasts:
            sym = fc.get("symbol", "")
            if not sym:
                continue
            if sym not in universe:
                universe[sym] = {"symbol": sym}
            
            universe[sym]["weather_storm"] = fc.get("storm_score", 0.0)
            universe[sym]["weather_forecast"] = fc.get("forecast", "")
            universe[sym]["weather_layers"] = fc.get("layers_active", 0)
            universe[sym]["weather_confidence"] = fc.get("confidence", "LOW")
            universe[sym]["weather_timing"] = fc.get("timing", "")
            universe[sym]["weather_drop"] = fc.get("expected_drop", "")
            # Gap 4: Store non-institutional weather score for de-duplication
            universe[sym]["weather_non_inst"] = fc.get("non_institutional_score", 0.0)
            
            if fc.get("current_price"):
                universe[sym]["current_price"] = fc["current_price"]
            if fc.get("sector"):
                universe[sym]["sector"] = fc["sector"]
        
        # ─── Gap 12: INTRADAY MOMENTUM FEED ───
        # If a stock is already in the universe AND dropping 3%+ intraday today,
        # that's same-day confirmation. Boost its score and flag it.
        intraday_symbols = set()
        for alert in self._intraday_data:
            sym = alert.get("symbol", "")
            change_pct = alert.get("change_pct", 0)
            severity = alert.get("severity", "")
            if not sym or change_pct >= 0:  # Only bearish moves
                continue
            intraday_symbols.add(sym)
            if sym in universe:
                # Existing candidate confirmed by intraday momentum
                universe[sym]["intraday_drop"] = change_pct
                universe[sym]["intraday_severity"] = severity
                universe[sym]["intraday_confirmed"] = True
                logger.debug(f"  {sym}: Intraday drop {change_pct:+.2f}% confirms bearish thesis")
            # We don't ADD new tickers just from intraday — only confirm existing
        
        # ─── Gap 5/6: FINVIZ SENTIMENT + MACRO ───
        # If FinViz flagged a ticker as bearish (insider selling, downgrade, etc.)
        # AND it's already in the universe, that's cross-source confirmation.
        finviz_symbols = set()
        for candidate in self._finviz_bearish:
            sym = candidate.get("symbol", "")
            if not sym:
                continue
            finviz_symbols.add(sym)
            if sym not in universe:
                universe[sym] = {"symbol": sym}
            universe[sym]["finviz_bearish"] = True
            universe[sym]["finviz_signals"] = candidate.get("signals", [])
            universe[sym]["finviz_score_boost"] = candidate.get("score_boost", 0.0)
        
        # ─── Gap 7: SHORT INTEREST DATA ───
        # High short interest + bearish signals = cascade risk (strong put)
        # High short interest alone = squeeze risk (cautious)
        for sym, si_data in self._short_interest.items():
            if sym in universe:
                sf = si_data.get("short_float")
                sr = si_data.get("short_ratio")
                if sf is not None:
                    universe[sym]["short_float"] = sf
                    universe[sym]["short_ratio"] = sr
                    if sf >= 20.0:
                        universe[sym]["high_short_interest"] = True
                        logger.debug(f"  {sym}: High short float {sf:.1f}%")
        
        # ─── Gap 11: CROSS-ASSET DIVERGENCE (sector correlation) ───
        # Build sector → tickers mapping, then check for sector weakness
        sector_tickers: Dict[str, List[str]] = {}
        for sym, data in universe.items():
            sector = data.get("sector", "unknown")
            if sector and sector != "unknown":
                sector_tickers.setdefault(sector, []).append(sym)
        
        # If 3+ tickers in the same sector are flagged, boost all of them
        # (sector contagion — one falling stock suggests the sector is weak)
        for sector, tickers in sector_tickers.items():
            ews_in_sector = sum(1 for t in tickers if universe[t].get("ews_ipi", 0) > 0.3)
            if ews_in_sector >= 3:
                for t in tickers:
                    universe[t]["sector_contagion"] = True
                    universe[t]["sector_ews_count"] = ews_in_sector
                    logger.debug(f"  {t}: Sector contagion ({sector}: {ews_in_sector} EWS tickers)")
        
        # --- Market Direction: conditional picks ---
        direction_picks = self._direction_data.get("conditional_picks", [])
        direction_symbols = set()
        for pick in direction_picks:
            sym = pick.get("symbol", "")
            if sym:
                direction_symbols.add(sym)
                if sym not in universe:
                    universe[sym] = {"symbol": sym}
                universe[sym]["direction_pick"] = True
                universe[sym]["direction_reason"] = pick.get("reason", "")
        
        # Store direction regime for all candidates
        regime = self._direction_data.get("regime", "UNKNOWN")
        regime_score = self._direction_data.get("regime_score", 0.5)
        tradeability = self._direction_data.get("tradeability", "UNKNOWN")
        
        for sym in universe:
            universe[sym]["direction_regime"] = regime
            universe[sym]["direction_regime_score"] = regime_score
            universe[sym]["direction_tradeability"] = tradeability
            if sym in direction_symbols:
                universe[sym]["in_direction_picks"] = True
        
        return universe
    
    # ======================================================================
    # SCORING — PhD Quant Convergence Model v2.0
    # ======================================================================
    
    def _score_candidates(self, universe: Dict[str, Dict]) -> List[ConvergenceCandidate]:
        """
        Score each candidate across all 4 systems using weighted convergence.
        
        v2.0 enhancements:
        - Trifecta/2-engine bonus for Gamma Drain sub-engine overlap
        - Better multi-day accumulation bonus for EWS
        - Source staleness penalty (stale data = reduced score)
        """
        candidates = []
        
        # Pre-compute source staleness penalty
        source_penalty = self._compute_source_penalty()
        
        for sym, data in universe.items():
            c = ConvergenceCandidate(symbol=sym)
            
            # --- EWS Score (0-1) ---
            ews_ipi = data.get("ews_ipi", 0.0)
            ews_level = data.get("ews_level", "")
            c.ews_score = min(1.0, ews_ipi)  # Already 0-1
            c.ews_level = ews_level
            c.ews_footprints = data.get("ews_footprints", 0)
            c.ews_days_building = data.get("ews_days_building", 0)
            c.ews_recommendation = data.get("ews_recommendation", "")
            
            # Multi-day accumulation bonus (institutional sellers need multiple days)
            # 3+ days building = strong (they can't hide for that long)
            # 5+ days = extreme (very patient institutional campaign)
            if c.ews_days_building >= 5 and c.ews_score > 0:
                c.ews_score = min(1.0, c.ews_score * 1.15)
            elif c.ews_days_building >= 3 and c.ews_score > 0:
                c.ews_score = min(1.0, c.ews_score * 1.10)
            
            # Footprint count bonus (more diverse footprint types = higher conviction)
            if c.ews_footprints >= 4:
                c.ews_score = min(1.0, c.ews_score * 1.08)
            elif c.ews_footprints >= 3:
                c.ews_score = min(1.0, c.ews_score * 1.04)
            
            # --- Gamma Drain Score (0-1) with trifecta bonus ---
            c.gamma_score = min(1.0, data.get("gamma_score", 0.0))
            c.gamma_signals = data.get("gamma_signals", [])[:5]
            c.gamma_engine = data.get("gamma_engine", "")
            c.gamma_engines_count = data.get("gamma_engines_count", 0)
            c.gamma_is_trifecta = data.get("gamma_is_trifecta", False)
            
            # v2.0: Trifecta / multi-engine bonus
            # True trifecta (all 3 sub-engines) is like 3 independent radars
            # confirming the same storm — extremely strong signal.
            if c.gamma_is_trifecta and c.gamma_score > 0:
                c.gamma_score = min(1.0, c.gamma_score * 1.25)
                logger.debug(f"  {sym}: TRIFECTA boost → GD={c.gamma_score:.3f}")
            elif c.gamma_engines_count >= 2 and c.gamma_score > 0:
                c.gamma_score = min(1.0, c.gamma_score * 1.15)
                logger.debug(f"  {sym}: 2-engine boost → GD={c.gamma_score:.3f}")
            
            # --- Weather Score (0-1) ---
            # Gap 4: Use non-institutional weather score to avoid double-counting
            # EWS IPI. If non_inst is available, use it. Otherwise fallback to storm.
            non_inst = data.get("weather_non_inst", 0.0)
            storm = data.get("weather_storm", 0.0)
            c.weather_score = min(1.0, non_inst if non_inst > 0.01 else storm)
            c.weather_forecast = data.get("weather_forecast", "")
            c.weather_layers = data.get("weather_layers", 0)
            c.weather_confidence = data.get("weather_confidence", "")
            
            # --- Direction Alignment (0-1) ---
            regime = data.get("direction_regime", "UNKNOWN")
            regime_score = data.get("direction_regime_score", 0.5)
            
            # For PUTS: RISK_OFF is good (amplifier), RISK_ON is bad (dampener)
            if regime == "RISK_OFF":
                c.direction_alignment = 0.8 + (1.0 - regime_score) * 0.2
            elif regime == "NEUTRAL":
                c.direction_alignment = 0.4
            elif regime == "RISK_ON":
                # In RISK_ON, allow directional picks through but dampen general signals
                c.direction_alignment = max(0.05, 0.3 - regime_score * 0.2)
            else:
                c.direction_alignment = 0.3  # Unknown = slight dampener
            
            # Bonus if this ticker is in direction conditional picks
            if data.get("in_direction_picks"):
                c.direction_alignment = min(1.0, c.direction_alignment + 0.15)
            
            c.direction_regime = regime
            
            # --- Count agreeing sources ---
            c.source_list = []
            if c.ews_score > 0.1:
                c.source_list.append("EWS")
            if c.gamma_score > 0.1:
                c.source_list.append("GammaDrain")
            if c.weather_score > 0.1:
                c.source_list.append("Weather")
            if data.get("in_direction_picks"):
                c.source_list.append("Direction")
            # Gap 5/6: FinViz as additional source
            if data.get("finviz_bearish"):
                c.source_list.append("FinViz")
            # Gap 12: Intraday as additional source
            if data.get("intraday_confirmed"):
                c.source_list.append("Intraday")
            c.sources_agreeing = len(c.source_list)
            
            # --- Weighted Convergence Score ---
            raw_score = (
                WEIGHT_EWS * c.ews_score * source_penalty.get("ews", 1.0) +
                WEIGHT_GAMMA * c.gamma_score * source_penalty.get("gamma", 1.0) +
                WEIGHT_WEATHER * c.weather_score * source_penalty.get("weather", 1.0) +
                WEIGHT_DIRECTION * c.direction_alignment * source_penalty.get("direction", 1.0)
            )
            
            # ─── Gap 5/6: FinViz sentiment boost ───
            # Insider selling, analyst downgrade, technical weakness from FinViz
            finviz_boost = data.get("finviz_score_boost", 0.0)
            finviz_signals = data.get("finviz_signals", [])
            if "insider_selling" in finviz_signals:
                raw_score += 0.04  # Insider selling is one of strongest bearish signals
            if "analyst_downgrade" in finviz_signals:
                raw_score += 0.02
            if "technical_weakness" in finviz_signals:
                raw_score += 0.01
            
            # ─── Gap 7: Short interest modifier ───
            short_float = data.get("short_float", 0)
            if short_float and short_float >= 20.0 and c.ews_score > 0.3:
                # High short + bearish EWS = cascade risk (shorts will pile on)
                raw_score = raw_score * 1.08
                logger.debug(f"  {sym}: Short cascade boost (SF={short_float:.1f}%)")
            elif short_float and short_float >= 30.0 and c.ews_score <= 0.1:
                # Very high short but NO bearish EWS = squeeze risk (careful)
                raw_score = raw_score * 0.90
            
            # ─── Gap 11: Sector contagion boost ───
            if data.get("sector_contagion"):
                raw_score = raw_score * 1.05
            
            # ─── Gap 12: Intraday momentum boost ───
            intraday_drop = data.get("intraday_drop", 0)
            if intraday_drop < -3.0:  # Dropping 3%+ today
                raw_score = raw_score * 1.10
                logger.debug(f"  {sym}: Intraday momentum boost ({intraday_drop:+.1f}%)")
            elif intraday_drop < -1.5:
                raw_score = raw_score * 1.03
            
            # CONVERGENCE BONUS: Multiple systems agreeing = non-linear boost
            # This is the key insight: independent confirmation compounds conviction.
            # 5+/6 systems → 1.35x (massive consensus across independent systems)
            # 4/6 systems → 1.30x (all 4 core detectors agree)
            # 3/6 systems → 1.15x (strong consensus)
            # 2/6 systems → 1.05x (mild confirmation)
            # 1/6 systems → 1.00x (no cross-validation)
            convergence_multiplier = {6: 1.35, 5: 1.35, 4: 1.30, 3: 1.15, 2: 1.05, 1: 1.00, 0: 1.00}
            multiplier = convergence_multiplier.get(min(c.sources_agreeing, 6), 1.0)
            
            c.convergence_score = min(1.0, raw_score * multiplier)
            
            # --- Metadata ---
            c.sector = data.get("sector", "unknown")
            c.current_price = data.get("current_price", 0.0)
            c.expected_drop = data.get("weather_drop", "")
            c.timing = data.get("weather_timing", "")
            
            # v3.0 Gap fix fields
            c.intraday_confirmed = data.get("intraday_confirmed", False)
            c.intraday_drop = data.get("intraday_drop", 0.0)
            c.finviz_bearish = data.get("finviz_bearish", False)
            c.short_float = data.get("short_float", 0.0)
            c.sector_contagion = data.get("sector_contagion", False)
            
            # Data age = oldest source
            ages = []
            for src_key in ["ews", "direction", "gamma", "weather"]:
                src = self.source_statuses.get(src_key)
                if src and src.available:
                    ages.append(src.age_seconds)
            c.data_age = self._format_age(max(ages) if ages else 0)
            
            candidates.append(c)
        
        return candidates
    
    def _compute_source_penalty(self) -> Dict[str, float]:
        """
        Compute penalty multiplier for each source based on staleness.
        
        FRESH = 1.0 (no penalty)
        STALE = 0.85 (15% reduction — data might be outdated)
        CRITICAL = 0.60 (40% reduction — data likely outdated)
        MISSING = 0.0 (source contributes nothing)
        """
        penalties = {}
        penalty_map = {
            "FRESH": 1.0,
            "STALE": 0.85,
            "CRITICAL": 0.60,
            "MISSING": 0.0,
        }
        for key in ["ews", "direction", "gamma", "weather"]:
            status = self.source_statuses.get(key)
            if status:
                penalties[key] = penalty_map.get(status.freshness, 0.0)
            else:
                penalties[key] = 0.0
        return penalties
    
    # ======================================================================
    # SECTOR DIVERSITY — Don't put all eggs in one basket
    # ======================================================================
    
    def _select_top9_diverse(self, scored: List[ConvergenceCandidate]) -> List[ConvergenceCandidate]:
        """
        Select Top 9 with sector diversity constraint.
        
        Ensures no more than MAX_SAME_SECTOR (3) picks from the same sector.
        If violated, rotates in next-best from underrepresented sectors.
        
        Why: If 5/9 picks are crypto and Bitcoin bounces, ALL positions get
        stopped out simultaneously. Sector diversification reduces correlated
        risk. This is portfolio construction 101 (Markowitz 1952).
        """
        # Sort by convergence score descending
        ranked = sorted(scored, key=lambda c: c.convergence_score, reverse=True)
        
        if len(ranked) <= 9:
            return ranked
        
        selected = []
        sector_count: Counter = Counter()
        remaining = list(ranked)
        
        for candidate in ranked:
            sector = candidate.sector or "unknown"
            
            if sector_count[sector] < MAX_SAME_SECTOR:
                selected.append(candidate)
                sector_count[sector] += 1
                remaining.remove(candidate)
                
                if len(selected) >= 9:
                    break
        
        # If we still need more (unlikely), fill from remaining
        if len(selected) < 9:
            for candidate in remaining:
                if candidate not in selected:
                    selected.append(candidate)
                    if len(selected) >= 9:
                        break
        
        return selected
    
    # ======================================================================
    # TRAJECTORY TRACKING — Is the storm building or dissipating?
    # ======================================================================
    
    def _compute_trajectories(self, top9: List[ConvergenceCandidate]):
        """
        Compare each candidate's current score with the previous run.
        
        Trajectory tells you the DIRECTION of conviction:
        - 🔺 RISING: Score increased → storm building → more urgent
        - 🔻 FALLING: Score decreased → dissipating → less urgent
        - ➡️ STABLE: Score unchanged → holding pattern → watch
        - 🆕 NEW: First time on list → just emerged
        """
        for c in top9:
            prev = self._previous_top9.get(c.symbol)
            
            if prev is None:
                c.trajectory = "NEW"
                c.trajectory_emoji = "🆕"
                c.prev_score = 0.0
                c.score_delta = 0.0
                c.days_on_list = 1
                continue
            
            prev_score = prev.get("convergence_score", 0.0)
            delta = c.convergence_score - prev_score
            prev_days = prev.get("days_on_list", 0)
            
            c.prev_score = prev_score
            c.score_delta = round(delta, 4)
            c.days_on_list = prev_days + 1
            
            if delta > 0.03:
                c.trajectory = "RISING"
                c.trajectory_emoji = "🔺"
            elif delta < -0.03:
                c.trajectory = "FALLING"
                c.trajectory_emoji = "🔻"
            else:
                c.trajectory = "STABLE"
                c.trajectory_emoji = "➡️"
    
    # ======================================================================
    # PERMISSION LIGHT — Tradability Gate
    # ======================================================================
    
    def _assign_permission(self, c: ConvergenceCandidate) -> str:
        """
        Assign permission light based on convergence + regime + data quality.
        
        🟢 TRADE:       conv ≥ 0.55 AND regime not RISK_ON AND ≥2 sources
        🟡 WATCH:       conv ≥ 0.30 OR 1 strong source (EWS ACT or GD ≥ 0.68)
        🔴 STAND DOWN:  conv < 0.30 OR regime blocks OR all data stale
        
        v2.0: Lowered green threshold from 0.60 to 0.55 (with trifecta bonus,
        legitimate candidates were getting stuck at yellow). Also lowered
        watch from 0.35 to 0.30 for better sensitivity. Added trifecta
        override for RISK_ON regime — if a trifecta + EWS ACT stock shows up
        in a RISK_ON market, it still gets 🟡 (not 🔴) because the individual
        stock signal is stronger than the market-wide regime.
        """
        # Check for stale data
        all_stale = all(
            s.freshness in ("CRITICAL", "MISSING")
            for s in self.source_statuses.values()
        )
        if all_stale:
            return "🔴"
        
        # Regime block — but with trifecta override
        if c.direction_regime == "RISK_ON" and c.convergence_score < 0.65:
            # v2.0: Trifecta + EWS ACT can override RISK_ON block to 🟡
            if c.gamma_is_trifecta or (c.ews_level == "act" and c.ews_score >= 0.70):
                return "🟡"  # Strong individual signal in wrong market = watch, not block
            return "🔴"
        
        # 🟢 TRADE: High convergence + multiple sources + regime allows
        if (c.convergence_score >= 0.55 
            and c.sources_agreeing >= 2 
            and c.direction_regime != "RISK_ON"):
            return "🟢"
        
        # 🟡 WATCH: Moderate convergence OR one strong signal
        if c.convergence_score >= 0.30:
            return "🟡"
        if c.ews_level == "act" and c.ews_score >= 0.70:
            return "🟡"
        if c.gamma_score >= 0.68:
            return "🟡"
        
        return "🔴"
    
    # ======================================================================
    # REPORT BUILDER
    # ======================================================================
    
    def _build_report(self, top9: List[ConvergenceCandidate]) -> Dict:
        """Build the output report JSON — v2.0 with trajectory + trifecta"""
        now_utc = datetime.utcnow().isoformat()
        
        candidates_list = []
        for c in top9:
            candidates_list.append({
                "symbol": c.symbol,
                "convergence_score": round(c.convergence_score, 4),
                "permission_light": c.permission_light,
                "sources_agreeing": c.sources_agreeing,
                "source_list": c.source_list,
                
                "ews_score": round(c.ews_score, 3),
                "ews_level": c.ews_level,
                "ews_footprints": c.ews_footprints,
                "ews_days_building": c.ews_days_building,
                "ews_recommendation": c.ews_recommendation,
                
                "gamma_score": round(c.gamma_score, 3),
                "gamma_signals": c.gamma_signals,
                "gamma_engine": c.gamma_engine,
                "gamma_engines_count": c.gamma_engines_count,
                "gamma_is_trifecta": c.gamma_is_trifecta,
                
                "weather_score": round(c.weather_score, 3),
                "weather_forecast": c.weather_forecast,
                "weather_layers": c.weather_layers,
                "weather_confidence": c.weather_confidence,
                
                "direction_alignment": round(c.direction_alignment, 3),
                "direction_regime": c.direction_regime,
                
                "sector": c.sector,
                "current_price": round(c.current_price, 2) if c.current_price else 0,
                "expected_drop": c.expected_drop,
                "timing": c.timing,
                "data_age": c.data_age,
                
                # v2.0: Trajectory
                "trajectory": c.trajectory,
                "trajectory_emoji": c.trajectory_emoji,
                "prev_score": round(c.prev_score, 4),
                "score_delta": round(c.score_delta, 4),
                "days_on_list": c.days_on_list,
                
                # v3.0: Gap fixes — additional data sources
                "intraday_confirmed": getattr(c, "intraday_confirmed", False),
                "intraday_drop": getattr(c, "intraday_drop", 0.0),
                "finviz_bearish": getattr(c, "finviz_bearish", False),
                "short_float": getattr(c, "short_float", 0.0),
                "sector_contagion": getattr(c, "sector_contagion", False),
            })
        
        # Permission light summary
        greens = sum(1 for c in top9 if c.permission_light == "🟢")
        yellows = sum(1 for c in top9 if c.permission_light == "🟡")
        reds = sum(1 for c in top9 if c.permission_light == "🔴")
        
        # Source health
        source_health = {}
        for key, status in self.source_statuses.items():
            source_health[key] = {
                "name": status.name,
                "available": status.available,
                "freshness": status.freshness,
                "age_seconds": round(status.age_seconds),
                "record_count": status.record_count,
                "timestamp": status.timestamp,
                "error": status.error,
            }
        
        # Pipeline status
        pipeline_status = self._get_pipeline_status()
        
        # Sector breakdown
        sector_dist = Counter(c.sector for c in top9)
        
        report = {
            "status": "ok",
            "generated_at_utc": now_utc,
            "generated_at_et": self.now.strftime("%Y-%m-%d %H:%M:%S ET"),
            "engine": "ConvergenceEngine v3.0",
            "description": "Automated 6+ source decision hierarchy: EWS → Direction → Gamma → Weather → FinViz → Intraday",
            
            "top9": candidates_list,
            
            "summary": {
                "total_candidates": len(candidates_list),
                "permission_lights": {
                    "green": greens,
                    "yellow": yellows,
                    "red": reds,
                },
                "sources_available": sum(1 for s in self.source_statuses.values() if s.available),
                "sources_total": 4,
                "direction_regime": self._direction_data.get("regime", "UNKNOWN"),
                "direction_tradeability": self._direction_data.get("tradeability", "UNKNOWN"),
                "trifecta_count": sum(1 for c in top9 if c.gamma_is_trifecta),
                "multi_engine_count": sum(1 for c in top9 if c.gamma_engines_count >= 2),
                "sector_distribution": dict(sector_dist),
                "any_stale": any(
                    s.freshness in ("STALE", "CRITICAL") 
                    for s in self.source_statuses.values()
                ),
            },
            
            "source_health": source_health,
            "pipeline_status": pipeline_status,
            
            "weights": {
                "ews": WEIGHT_EWS,
                "gamma": WEIGHT_GAMMA,
                "weather": WEIGHT_WEATHER,
                "direction": WEIGHT_DIRECTION,
            },
            
            # v2.1: Include scan engine top picks for comparison/overlap display
            "scan_engine_top10": self._get_scan_engine_top10(),
            
            # v2.1: Coverage gap analysis
            "coverage_analysis": self._get_coverage_analysis(top9),
        }
        
        return report
    
    def _get_pipeline_status(self) -> Dict:
        """
        Build pipeline status showing which steps have run and when.
        This is the "pipeline heartbeat" for the dashboard.
        """
        steps = []
        step_configs = [
            ("Step 1: EWS", "ews", "🚨"),
            ("Step 2: Direction", "direction", "📈"),
            ("Step 3: Gamma", "gamma", "🔥"),
            ("Step 4: Weather", "weather", "🌪️"),
        ]
        
        for label, key, icon in step_configs:
            status = self.source_statuses.get(key)
            if not status:
                steps.append({
                    "label": label,
                    "icon": icon,
                    "status": "MISSING",
                    "status_emoji": "❌",
                    "last_run": "Never",
                    "records": 0,
                })
                continue
            
            status_emoji = {
                "FRESH": "✅",
                "STALE": "⚠️",
                "CRITICAL": "🔴",
                "MISSING": "❌",
            }.get(status.freshness, "❓")
            
            last_run = status.timestamp[:19] if len(status.timestamp) >= 19 else status.timestamp
            
            steps.append({
                "label": label,
                "icon": icon,
                "status": status.freshness,
                "status_emoji": status_emoji,
                "last_run": last_run or "Never",
                "records": status.record_count,
                "error": status.error if status.error else None,
            })
        
        return {
            "steps": steps,
            "all_healthy": all(s["status"] == "FRESH" for s in steps),
            "any_stale": any(s["status"] in ("STALE", "CRITICAL") for s in steps),
            "any_missing": any(s["status"] == "MISSING" for s in steps),
        }
    
    def _get_scan_engine_top10(self) -> List[Dict]:
        """
        v2.1: Get the Top 10 from scan results (Gamma Drain + Distribution + Liquidity)
        for display alongside convergence Top 9, enabling overlap analysis.
        
        This lets the user see BOTH lists side-by-side and understand where
        they agree (overlap = higher conviction) and where they diverge.
        """
        all_scan_picks = {}
        
        for engine_key in ["gamma_drain", "distribution", "liquidity"]:
            candidates = self._scan_data.get(engine_key, [])
            for c in candidates:
                sym = c.get("symbol", "")
                if not sym:
                    continue
                score = c.get("score", 0.0)
                existing = all_scan_picks.get(sym, {}).get("score", 0.0)
                if score > existing:
                    all_scan_picks[sym] = {
                        "symbol": sym,
                        "score": score,
                        "engine": engine_key,
                        "signals": c.get("signals", 0),
                        "sector": c.get("sector", ""),
                        "current_price": c.get("current_price", c.get("close", 0)),
                    }
                # Track how many engines flagged this ticker
                eng_list = all_scan_picks.get(sym, {}).get("engines", [])
                if engine_key not in eng_list:
                    eng_list.append(engine_key)
                all_scan_picks.setdefault(sym, {})["engines"] = eng_list
        
        # Sort by score descending, take top 10
        sorted_picks = sorted(all_scan_picks.values(), key=lambda x: x.get("score", 0), reverse=True)
        return sorted_picks[:10]
    
    def _get_coverage_analysis(self, top9: List[ConvergenceCandidate]) -> Dict:
        """
        v2.1: Analyze the coverage gap between EWS and scan results.
        This shows:
        - How many EWS stocks are NOT in scan results (gap)
        - How many scan result stocks are NOT in EWS (uninstrumented)
        - Overlap (both systems agree — highest conviction)
        """
        ews_symbols = set(self._ews_data.get("alerts", {}).keys())
        
        scan_symbols = set()
        for engine_key in ["gamma_drain", "distribution", "liquidity"]:
            for c in self._scan_data.get(engine_key, []):
                sym = c.get("symbol", "")
                if sym:
                    scan_symbols.add(sym)
        
        weather_symbols = set()
        for fc in self._weather_data.get("forecasts", []):
            sym = fc.get("symbol", "")
            if sym:
                weather_symbols.add(sym)
        
        top9_symbols = set(c.symbol for c in top9)
        
        overlap_ews_scan = ews_symbols & scan_symbols
        ews_only = ews_symbols - scan_symbols
        scan_only = scan_symbols - ews_symbols
        
        # How many convergence candidates have synthetic gamma scores
        synthetic_count = sum(
            1 for c in top9 
            if c.gamma_engine == "ews_synthetic"
        )
        
        return {
            "ews_count": len(ews_symbols),
            "scan_count": len(scan_symbols),
            "weather_count": len(weather_symbols),
            "overlap_ews_scan": len(overlap_ews_scan),
            "overlap_symbols": sorted(list(overlap_ews_scan)),
            "ews_only_count": len(ews_only),
            "ews_only_top": sorted(list(ews_only))[:10],
            "scan_only_count": len(scan_only),
            "scan_only_top": sorted(list(scan_only))[:10],
            "synthetic_gamma_count": synthetic_count,
            "note": (
                "EWS-only stocks now get SYNTHETIC gamma scores from footprint mapping. "
                "EWS ACT/PREPARE tickers are auto-injected into DUI for next scan cycle."
            ),
        }
    
    def _write_degraded(self, error: str) -> Dict:
        """Write a degraded status report when engine fails"""
        report = {
            "status": "degraded",
            "error": error,
            "generated_at_utc": datetime.utcnow().isoformat(),
            "generated_at_et": self.now.strftime("%Y-%m-%d %H:%M:%S ET"),
            "engine": "ConvergenceEngine v2.0",
            "top9": [],
            "summary": {
                "total_candidates": 0,
                "permission_lights": {"green": 0, "yellow": 0, "red": 0},
                "sources_available": 0,
                "sources_total": 4,
            },
            "source_health": {
                key: {
                    "name": s.name,
                    "available": s.available,
                    "freshness": s.freshness,
                    "error": s.error,
                }
                for key, s in self.source_statuses.items()
            },
            "pipeline_status": self._get_pipeline_status(),
        }
        self._save_report(report)
        return report
    
    def _save_report(self, report: Dict):
        """Save report to JSON file"""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, "w") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info(f"Convergence report saved to {OUTPUT_FILE}")
    
    def _save_history(self, report: Dict):
        """
        Save historical snapshot for trajectory tracking.
        Keep last 48 hours of history (about 24 runs during market hours).
        """
        try:
            HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            ts = self.now.strftime("%Y%m%d_%H%M")
            history_file = HISTORY_DIR / f"conv_{ts}.json"
            
            # Slim history: only symbols + scores + trajectory
            slim = {
                "timestamp": report.get("generated_at_utc"),
                "candidates": {
                    c["symbol"]: {
                        "convergence_score": c["convergence_score"],
                        "sources_agreeing": c["sources_agreeing"],
                        "permission_light": c["permission_light"],
                        "days_on_list": c.get("days_on_list", 0),
                    }
                    for c in report.get("top9", [])
                }
            }
            
            with open(history_file, "w") as f:
                json.dump(slim, f, indent=2)
            
            # Cleanup: remove files older than 48 hours
            cutoff = datetime.now() - timedelta(hours=48)
            for old_file in HISTORY_DIR.glob("conv_*.json"):
                try:
                    file_ts = datetime.strptime(old_file.stem[5:], "%Y%m%d_%H%M")
                    if file_ts < cutoff:
                        old_file.unlink()
                except (ValueError, OSError):
                    pass
                    
        except Exception as e:
            logger.debug(f"History save failed (non-fatal): {e}")
    
    # ======================================================================
    # UTILITY
    # ======================================================================
    
    def _calc_age(self, timestamp_str: str) -> float:
        """Calculate age of a timestamp in seconds"""
        if not timestamp_str:
            return 999999
        try:
            ts = datetime.fromisoformat(str(timestamp_str))
            if ts.tzinfo is None:
                ts = ET.localize(ts)
            return (self.now - ts).total_seconds()
        except Exception:
            return 999999
    
    def _classify_freshness(self, age_seconds: float) -> str:
        """
        Classify data freshness with market-hours awareness.
        
        During market hours: 2h = STALE, 4h = CRITICAL
        After hours / weekend: 48h tolerance before STALE
        """
        now_et = self.now
        
        # Weekend: very lenient (Friday close to Monday pre-market)
        if now_et.weekday() >= 5:  # Saturday/Sunday
            if age_seconds < STALE_WEEKEND_SECONDS:
                return "FRESH"
            elif age_seconds < STALE_WEEKEND_SECONDS * 2:
                return "STALE"
            return "CRITICAL"
        
        # After-hours (before 7 AM or after 5 PM ET): lenient
        hour = now_et.hour
        if hour < 7 or hour >= 17:
            if age_seconds < STALE_CRITICAL_SECONDS:  # 4h
                return "FRESH"
            elif age_seconds < STALE_CRITICAL_SECONDS * 2:
                return "STALE"
            return "CRITICAL"
        
        # Market hours: strict
        if age_seconds < STALE_WARN_SECONDS:  # 2h
            return "FRESH"
        elif age_seconds < STALE_CRITICAL_SECONDS:  # 4h
            return "STALE"
        elif age_seconds < 999990:
            return "CRITICAL"
        return "MISSING"
    
    def _format_age(self, seconds: float) -> str:
        """Format seconds to human-readable age"""
        if seconds >= 999990:
            return "N/A"
        if seconds < 60:
            return f"{int(seconds)}s"
        if seconds < 3600:
            return f"{int(seconds // 60)}m"
        if seconds < 86400:
            return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"
        return f"{int(seconds // 86400)}d"
    
    # ======================================================================
    # GAP 9: BACKTESTING LEDGER — Record picks for historical calibration
    # ======================================================================
    
    def _record_backtest_entry(self, top9: List[ConvergenceCandidate]):
        """
        Gap 9 Fix: Record each Top 9 pick with timestamp, score, and current price
        so that the 5:30 PM weather_attribution_backfill job can compare T+1/T+2
        actual prices and compute accuracy metrics.
        
        After 15-20 trading days, this data enables:
        - "When convergence > 0.55, how often did stock drop 3%+ in 2 days?"
        - "What IPI threshold gives best precision?"
        - "Are trifecta picks actually better than single-engine?"
        
        Output: logs/convergence/backtest_ledger.json (append-only)
        """
        try:
            BACKTEST_FILE.parent.mkdir(parents=True, exist_ok=True)
            
            # Load existing ledger
            ledger = []
            if BACKTEST_FILE.exists():
                try:
                    with open(BACKTEST_FILE) as f:
                        ledger = json.load(f)
                except (json.JSONDecodeError, KeyError):
                    ledger = []
            
            # Add new entry
            entry = {
                "timestamp": self.now.isoformat(),
                "date": self.now.strftime("%Y-%m-%d"),
                "picks": []
            }
            
            for c in top9:
                entry["picks"].append({
                    "symbol": c.symbol,
                    "convergence_score": round(c.convergence_score, 4),
                    "ews_score": round(c.ews_score, 3),
                    "gamma_score": round(c.gamma_score, 3),
                    "weather_score": round(c.weather_score, 3),
                    "sources_agreeing": c.sources_agreeing,
                    "permission_light": c.permission_light,
                    "ews_level": c.ews_level,
                    "gamma_is_trifecta": c.gamma_is_trifecta,
                    "current_price": round(c.current_price, 2) if c.current_price else 0,
                    "sector": c.sector,
                    # These will be filled by backfill job:
                    "price_t1": None,   # T+1 close
                    "price_t2": None,   # T+2 close
                    "drop_t1": None,    # % change at T+1
                    "drop_t2": None,    # % change at T+2
                    "hit_3pct": None,   # Did it drop 3%+ by T+2?
                    "hit_5pct": None,   # Did it drop 5%+ by T+2?
                    "max_drop": None,   # Max intraday drop within T+2
                })
            
            ledger.append(entry)
            
            # Keep last 30 days of entries (trim older)
            if len(ledger) > 500:
                ledger = ledger[-500:]
            
            with open(BACKTEST_FILE, "w") as f:
                json.dump(ledger, f, indent=2, default=str)
            
            logger.debug(f"Backtest ledger: recorded {len(top9)} picks (total entries: {len(ledger)})")
            
        except Exception as e:
            logger.debug(f"Backtest ledger write failed (non-fatal): {e}")
    
    # ======================================================================
    # EWS → DUI BRIDGE — Inject detected stocks into scan universe
    # ======================================================================
    
    def _inject_ews_to_dui(self):
        """
        v2.1: Inject EWS ACT and PREPARE level tickers into the Dynamic
        Universe Injection (DUI) so they get scanned by the Gamma Drain,
        Distribution, and Liquidity engines in subsequent scheduled scans.
        
        This bridges the critical coverage gap where EWS detects institutional
        selling but the stock never gets analyzed by the full engine pipeline
        because it's not in the scan universe.
        
        Only injects tickers that are NOT already in scan results.
        """
        try:
            from putsengine.config import DynamicUniverseManager
            
            dui = DynamicUniverseManager()
            ews_alerts = self._ews_data.get("alerts", {})
            
            # Get tickers already in scan results
            scan_tickers = set()
            for engine_key in ["gamma_drain", "distribution", "liquidity"]:
                for c in self._scan_data.get(engine_key, []):
                    sym = c.get("symbol", "")
                    if sym:
                        scan_tickers.add(sym)
            
            injected = 0
            for symbol, alert in ews_alerts.items():
                ipi = alert.get("ipi_score", alert.get("ipi", 0.0))
                level = alert.get("level", "")
                
                # Only inject ACT and PREPARE level alerts
                if level not in ("act", "prepare"):
                    continue
                
                # Skip if already in scan results
                if symbol in scan_tickers:
                    continue
                
                # Inject with appropriate TTL
                ttl = 3 if level == "act" else 2  # ACT = 3 days, PREPARE = 2 days
                footprints = alert.get("footprints", [])
                fp_types = [fp.get("type", "") for fp in footprints if isinstance(fp, dict)]
                
                dui.inject_symbol(
                    symbol=symbol,
                    source="convergence_ews_bridge",
                    reason=f"EWS {level.upper()} IPI={ipi:.2f} ({len(fp_types)} footprints)",
                    score=ipi,
                    signals=fp_types,
                    ttl_days=ttl
                )
                injected += 1
            
            if injected > 0:
                logger.info(f"🔗 EWS→DUI Bridge: Injected {injected} tickers for scan coverage")
        
        except Exception as e:
            logger.debug(f"EWS→DUI injection skipped: {e}")


def run_convergence() -> Dict:
    """
    Convenience function to run the convergence engine.
    Called by scheduler every 30 minutes and after each EWS scan.
    Zero API calls — reads only from cached JSON files.
    """
    engine = ConvergenceEngine()
    return engine.run()


if __name__ == "__main__":
    """Run convergence engine directly for testing"""
    import sys
    result = run_convergence()
    
    if result.get("status") == "ok":
        top9 = result.get("top9", [])
        print(f"\n🎯 TOP 9 CONVERGENCE CANDIDATES (v2.0):")
        print(f"{'#':>2} {'':3} {'Symbol':8} {'Conv':>6} {'Traj':>4} {'Src':>4} {'EWS':>5} {'GD':>5} {'WX':>5} {'DIR':>5} {'Eng':>3} Sources")
        print("-" * 85)
        for i, c in enumerate(top9, 1):
            trifecta = "T" if c.get("gamma_is_trifecta") else str(c.get("gamma_engines_count", 0))
            print(
                f"{i:2} {c['permission_light']:3} {c['symbol']:8} "
                f"{c['convergence_score']:6.3f} "
                f"{c.get('trajectory_emoji', '?'):4} "
                f"{c['sources_agreeing']:3}/4 "
                f"{c['ews_score']:5.2f} "
                f"{c['gamma_score']:5.2f} "
                f"{c['weather_score']:5.2f} "
                f"{c['direction_alignment']:5.2f} "
                f"{trifecta:>3} "
                f"{','.join(c['source_list'])}"
            )
        
        summary = result.get("summary", {})
        lights = summary.get("permission_lights", {})
        print(f"\n🟢 {lights.get('green', 0)} TRADE | 🟡 {lights.get('yellow', 0)} WATCH | 🔴 {lights.get('red', 0)} STAND DOWN")
        print(f"Sources: {summary.get('sources_available', 0)}/4 available")
        print(f"Regime: {summary.get('direction_regime', 'UNKNOWN')} ({summary.get('direction_tradeability', 'UNKNOWN')})")
        print(f"Trifectas: {summary.get('trifecta_count', 0)} | Multi-engine: {summary.get('multi_engine_count', 0)}")
        
        # Pipeline status
        pipeline = result.get("pipeline_status", {})
        if pipeline.get("steps"):
            print(f"\n📡 Pipeline Status:")
            for step in pipeline["steps"]:
                print(f"  {step['icon']} {step['status_emoji']} {step['label']}: {step['status']} (last: {step['last_run']} | {step['records']} records)")
    else:
        print(f"❌ DEGRADED: {result.get('error', 'Unknown error')}")
        sys.exit(1)
