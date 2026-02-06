"""
🌪️ MARKET WEATHER ENGINE v5.1 - Architect Operational + Calibration Fixes
==========================================================================
Two daily "Weather Reports":
  • 9:00 AM ET — "Open Risk Forecast" (same-day decisions)
  • 3:00 PM ET — "Overnight Storm Build" (next-day prep)

v5.1 OPERATIONAL FIXES:
━━━━━━━━━━━━━━━━━━━━━━
F) Confidence PENALTY when gamma/flow/VIX data is MISSING (don't promote on incomplete info)
G) Permission Light (🟢/🟡/🔴) per pick — tradable/watch/stand-down
H) Data Freshness stamps per provider (EWS, Polygon, UW, Regime)
I) Attribution Logger — save T+1/T+2 outcomes for calibration loop
J) Independence Check — structural/technical overlap detection
K) generated_at_utc in every report

PRIOR v5 FIXES:
━━━━━━━━━━━━━━━
A) Gamma Flip Distance — fragility meter (how close to forced dealer hedging?)
B) Opening vs Closing Flow — bearish if opening puts, neutral if closing
C) Liquidity Violence Score — spread/quote degradation (cascade vs absorb?)
D) STOP calling it "probability" — it's a Storm Score until calibrated
E) Add similar_days_n + confidence band

4 INDEPENDENT WEATHER LAYERS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Layer 1: STRUCTURAL PRESSURE ("Jet Stream") — 3-7 day lead
  Source: Polygon technical indicators (UNLIMITED)
Layer 2: INSTITUTIONAL FLOW ("Pressure System") — 1-3 day lead
  Source: EWS IPI (existing scans, NO new API calls)
Layer 3: TECHNICAL DETERIORATION ("Radar") — 0-2 day lead
  Source: Polygon real-time data (UNLIMITED)
Layer 4: CATALYST PROXIMITY ("Known Fronts") — Scheduled
  Source: Polygon news (UNLIMITED)

CONVERGENCE SCORING:
━━━━━━━━━━━━━━━━━━━
4/4 layers active = 🌪️ STORM WARNING  (highest storm score)
3/4 layers active = ⛈️ STORM WATCH    (high storm score)
2/4 layers active = 🌧️ ADVISORY       (moderate storm score)
1/4 layers active = ☁️ MONITORING     (low storm score)
"""

import json
import asyncio
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum
import numpy as np
from loguru import logger


# ============================================================================
# DATA STRUCTURES
# ============================================================================

class ForecastLevel(Enum):
    """Weather forecast severity levels"""
    STORM_WARNING = "STORM WARNING"   # 4/4 layers — highest confidence
    STORM_WATCH = "STORM WATCH"       # 3/4 layers — high confidence
    ADVISORY = "ADVISORY"             # 2/4 layers — moderate confidence
    MONITORING = "MONITORING"         # 1/4 layers — early watch
    CLEAR = "CLEAR"                   # 0/4 layers — no signals


class TrajectoryType(Enum):
    """How signals are evolving over time — like storm tracking"""
    ACCELERATING = "ACCELERATING"   # Getting worse (storm intensifying)
    SUSTAINED = "SUSTAINED"         # Stable at high level (persistent system)
    EMERGING = "EMERGING"           # New signals appearing (system forming)
    DISSIPATING = "DISSIPATING"     # Getting better (system weakening)
    NEW = "NEW"                     # First detection (no prior history)


class ConfidenceLevel(Enum):
    """Confidence based on sample size / data quality"""
    HIGH = "HIGH"       # >= 50 historical days match
    MEDIUM = "MEDIUM"   # 30-49 historical days match
    LOW = "LOW"         # < 30 historical days match


class ReportMode(Enum):
    """AM or PM weather report"""
    AM = "am"    # 9:00 AM ET — same-day decisions
    PM = "pm"    # 3:00 PM ET — next-day prep


@dataclass
class LayerScore:
    """Score for a single weather layer"""
    name: str
    score: float          # 0.0 to 1.0
    active: bool          # Is this layer confirming bearish?
    signals: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def label(self) -> str:
        if self.score >= 0.7:
            return "STRONG"
        elif self.score >= 0.4:
            return "MODERATE"
        elif self.score > 0:
            return "WEAK"
        return "INACTIVE"

    def to_dict(self) -> Dict:
        return {
            "score": round(self.score, 3),
            "active": self.active,
            "label": self.label,
            "signals": self.signals[:5],
            "details": self.details
        }


@dataclass
class WeatherForecast:
    """Complete weather forecast for a ticker — like a 5-day weather outlook"""
    symbol: str
    forecast: ForecastLevel
    storm_score: float        # 0-1 (NOT probability — uncalibrated)
    timing: str               # e.g., "1-2 days"
    
    # Layer scores
    structural: LayerScore
    institutional: LayerScore
    technical: LayerScore
    catalyst: LayerScore
    
    # Convergence
    layers_active: int        # How many layers confirm bearish (0-4)
    convergence_score: float  # Overall convergence (0-1)
    
    # Trajectory
    trajectory: TrajectoryType
    days_building: int
    
    # v5 Architect additions
    gamma_flip_distance: Optional[float] = None    # % distance to gamma flip level
    gamma_flip_fragile: bool = False                # True if abs(distance) <= 0.5%
    opening_flow_bias: str = "UNKNOWN"              # OPENING_BEARISH, CLOSING_BULLISH, MIXED
    liquidity_violence_score: float = 0.0           # 0-1, spread/quote degradation
    liquidity_violence_flag: str = "NORMAL"         # NORMAL, GAPPY, VIOLENT
    confidence: ConfidenceLevel = ConfidenceLevel.LOW
    similar_days_n: int = 0                         # How many historical days match
    
    # v5.1 Architect operational additions
    permission_light: str = "🟡"                    # 🟢 tradable / 🟡 watch / 🔴 stand down
    missing_inputs: List[str] = field(default_factory=list)  # Which critical inputs are missing
    
    # Trading info
    expected_drop: str = ""
    current_price: float = 0.0
    sector: str = "unknown"
    
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "forecast": self.forecast.value,
            "forecast_emoji": {
                "STORM WARNING": "🌪️",
                "STORM WATCH": "⛈️",
                "ADVISORY": "🌧️",
                "MONITORING": "☁️",
                "CLEAR": "☀️",
            }.get(self.forecast.value, "❓"),
            "storm_score": round(self.storm_score, 3),
            "timing": self.timing,
            "layers_active": self.layers_active,
            "convergence_score": round(self.convergence_score, 3),
            "trajectory": self.trajectory.value,
            "trajectory_emoji": {
                "ACCELERATING": "🔺",
                "SUSTAINED": "➡️",
                "EMERGING": "🆕",
                "DISSIPATING": "🔻",
                "NEW": "⭐",
            }.get(self.trajectory.value, ""),
            "days_building": self.days_building,
            # v5 Architect fields
            "gamma_flip_distance": round(self.gamma_flip_distance, 3) if self.gamma_flip_distance is not None else None,
            "gamma_flip_fragile": self.gamma_flip_fragile,
            "opening_flow_bias": self.opening_flow_bias,
            "liquidity_violence_score": round(self.liquidity_violence_score, 3),
            "liquidity_violence_flag": self.liquidity_violence_flag,
            "confidence": self.confidence.value,
            "similar_days_n": self.similar_days_n,
            # v5.1 fields
            "permission_light": self.permission_light,
            "missing_inputs": self.missing_inputs,
            # Trading info
            "expected_drop": self.expected_drop,
            "current_price": round(self.current_price, 2),
            "sector": self.sector,
            "layers": {
                "structural": self.structural.to_dict(),
                "institutional": self.institutional.to_dict(),
                "technical": self.technical.to_dict(),
                "catalyst": self.catalyst.to_dict(),
            }
        }


# ============================================================================
# MARKET WEATHER ENGINE v5
# ============================================================================

class MarketWeatherEngine:
    """
    Multi-Layer Convergence Engine for Stock Market Prediction v5
    
    v5 Architect Fixes:
    A) Gamma Flip Distance — fragility meter
    B) Opening vs Closing Flow classification
    C) Liquidity Violence Score
    D) storm_score instead of probability
    E) similar_days_n + confidence band
    
    Two report modes:
    - AM (9:00 AM ET): same-day trading decisions
    - PM (3:00 PM ET): next-day preparation
    """
    
    # Layer activation thresholds — a layer must score above this to be "active"
    STRUCTURAL_THRESHOLD = 0.35
    INSTITUTIONAL_THRESHOLD = 0.50
    TECHNICAL_THRESHOLD = 0.35
    CATALYST_THRESHOLD = 0.25
    
    # Minimum IPI to consider a ticker (below this = noise)
    MIN_IPI_THRESHOLD = 0.40
    
    # Output directories
    WEATHER_DIR = Path("logs/market_weather")
    LEGACY_OUTPUT = Path("logs/predictive_analysis.json")
    
    def __init__(self, polygon_client=None, uw_client=None, settings=None):
        self.polygon = polygon_client
        self.uw = uw_client
        self.settings = settings
        
        # Data caches
        self.ews_data = {}
        self.ews_timestamp = None
        self.footprint_history = {}
    
    def _load_ews_data(self):
        """Load EWS institutional pressure data (already cached from scheduled scans)"""
        path = Path("early_warning_alerts.json")
        if path.exists():
            with open(path) as f:
                data = json.load(f)
                self.ews_data = data.get("alerts", {})
                self.ews_timestamp = data.get("timestamp", "Unknown")
    
    def _load_footprint_history(self):
        """Load historical footprint data for trajectory analysis"""
        path = Path("footprint_history.json")
        if path.exists():
            with open(path) as f:
                self.footprint_history = json.load(f)
    
    # =========================================================================
    # MAIN ENTRY POINT
    # =========================================================================
    
    async def analyze_universe(self, mode: ReportMode = ReportMode.AM) -> List[WeatherForecast]:
        """
        Analyze all tickers with institutional pressure.
        Returns ranked list of weather forecasts (top 10).
        
        Mode:
        - AM: Focus on same-day signals (more weight on technical + catalyst)
        - PM: Focus on next-day signals (more weight on structural + institutional)
        """
        # Load cached data from existing scans (NO new API calls for UW)
        self._load_ews_data()
        self._load_footprint_history()
        
        if not self.ews_data:
            logger.warning("No EWS data available for weather analysis")
            return []
        
        # Get candidates with meaningful IPI (institutional pressure)
        candidates = {
            symbol: data for symbol, data in self.ews_data.items()
            if data.get('ipi', 0) >= self.MIN_IPI_THRESHOLD
        }
        
        logger.info(f"Weather Engine v5 [{mode.value.upper()}]: Analyzing {len(candidates)} candidates with IPI >= {self.MIN_IPI_THRESHOLD}")
        
        # Analyze each candidate across all 4 layers
        forecasts = []
        for symbol, ews in candidates.items():
            try:
                forecast = await self._analyze_ticker(symbol, ews, mode)
                if forecast and forecast.layers_active >= 1:
                    forecasts.append(forecast)
            except Exception as e:
                logger.debug(f"Weather analysis failed for {symbol}: {e}")
                continue
            
            # Brief pause between tickers
            await asyncio.sleep(0.02)
        
        # Sort by: layers_active DESC, then storm_score DESC
        forecasts.sort(
            key=lambda f: (f.layers_active, f.storm_score),
            reverse=True
        )
        
        # Return top 10
        return forecasts[:10]
    
    async def _analyze_ticker(self, symbol: str, ews_data: Dict, mode: ReportMode) -> Optional[WeatherForecast]:
        """Analyze a single ticker across all 4 weather layers + v5 additions."""
        # Layer 2: INSTITUTIONAL (from existing EWS data — no API calls)
        institutional = self._score_institutional(symbol, ews_data)
        
        # Layers 1, 3, 4: From Polygon (UNLIMITED API calls)
        # v5: Also get gamma flip, flow quality, liquidity
        if self.polygon:
            try:
                tasks = [
                    self._score_structural(symbol),
                    self._score_technical(symbol),
                    self._score_catalyst(symbol),
                    self._get_gamma_flip_distance(symbol),
                    self._get_liquidity_violence(symbol),
                ]
                # v5: Opening flow bias if UW client available
                if self.uw:
                    tasks.append(self._get_opening_flow_bias(symbol))
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                structural = results[0] if not isinstance(results[0], Exception) else LayerScore("Structural", 0, False)
                technical = results[1] if not isinstance(results[1], Exception) else LayerScore("Technical", 0, False)
                catalyst = results[2] if not isinstance(results[2], Exception) else LayerScore("Catalyst", 0, False)
                gamma_result = results[3] if not isinstance(results[3], Exception) else (None, False)
                liquidity_result = results[4] if not isinstance(results[4], Exception) else (0.0, "NORMAL")
                flow_result = results[5] if len(results) > 5 and not isinstance(results[5], Exception) else "UNKNOWN"
                
            except Exception:
                structural = LayerScore("Structural", 0, False)
                technical = LayerScore("Technical", 0, False)
                catalyst = LayerScore("Catalyst", 0, False)
                gamma_result = (None, False)
                liquidity_result = (0.0, "NORMAL")
                flow_result = "UNKNOWN"
        else:
            structural = LayerScore("Structural", 0, False)
            technical = LayerScore("Technical", 0, False)
            catalyst = LayerScore("Catalyst", 0, False)
            gamma_result = (None, False)
            liquidity_result = (0.0, "NORMAL")
            flow_result = "UNKNOWN"
        
        # Unpack v5 results
        gamma_flip_distance, gamma_flip_fragile = gamma_result
        liquidity_violence_score, liquidity_violence_flag = liquidity_result
        opening_flow_bias = flow_result
        
        # Trajectory analysis (from footprint history — no API calls)
        trajectory, days_building = self._analyze_trajectory(symbol)
        
        # Count active layers
        layers_active = sum([
            structural.active,
            institutional.active,
            technical.active,
            catalyst.active
        ])
        
        # Compute convergence score (mode-dependent weights)
        if mode == ReportMode.AM:
            # AM: More weight on near-term (technical + catalyst for same-day)
            convergence_score = (
                institutional.score * 0.35 +
                technical.score * 0.30 +
                structural.score * 0.20 +
                catalyst.score * 0.15
            )
        else:
            # PM: More weight on building pressure (structural + institutional for next-day)
            convergence_score = (
                institutional.score * 0.40 +
                structural.score * 0.30 +
                technical.score * 0.20 +
                catalyst.score * 0.10
            )
        
        # ── v5.1: Independence Check ──
        # Structural (SMA position) and Technical (RSI/MACD momentum) both use price data.
        # If BOTH are active with high scores but Institutional (dark pool/OI) is NOT,
        # that's potentially a single-source echo. Apply a mild damper.
        if (structural.active and technical.active and not institutional.active 
                and structural.score > 0.5 and technical.score > 0.5):
            # Possible price-echo: both layers activated by same price move
            convergence_score = convergence_score * 0.90  # 10% damper
            logger.debug(f"{symbol}: Independence damper applied (structural+technical without institutional)")
        
        # Trajectory bonus: accelerating storm = higher score
        if trajectory == TrajectoryType.ACCELERATING:
            convergence_score = min(1.0, convergence_score * 1.15)
        elif trajectory == TrajectoryType.SUSTAINED:
            convergence_score = min(1.0, convergence_score * 1.08)
        elif trajectory == TrajectoryType.DISSIPATING:
            convergence_score = convergence_score * 0.85
        
        # v5: Gamma fragility bonus — if near flip level AND risk-off
        if gamma_flip_fragile and institutional.active:
            convergence_score = min(1.0, convergence_score * 1.10)
        
        # v5: Liquidity violence amplifier — gappy/violent conditions = worse
        if liquidity_violence_flag == "VIOLENT" and layers_active >= 2:
            convergence_score = min(1.0, convergence_score * 1.08)
        
        # Determine forecast level from layers_active
        if layers_active >= 4:
            forecast = ForecastLevel.STORM_WARNING
        elif layers_active >= 3:
            forecast = ForecastLevel.STORM_WATCH
        elif layers_active >= 2:
            forecast = ForecastLevel.ADVISORY
        elif layers_active >= 1:
            forecast = ForecastLevel.MONITORING
        else:
            forecast = ForecastLevel.CLEAR
        
        # Calculate storm score (NOT probability — uncalibrated)
        storm_score = self._calculate_storm_score(layers_active, convergence_score, trajectory)
        
        # Estimate timing based on which layers are active
        timing = self._estimate_timing(structural, institutional, technical, catalyst)
        
        # Estimate expected drop
        expected_drop = self._estimate_drop(layers_active, convergence_score)
        
        # ── v5.1: Track missing inputs (for confidence penalty + UI transparency) ──
        missing_inputs = []
        if gamma_flip_distance is None:
            missing_inputs.append("gamma_flip")
        if opening_flow_bias == "UNKNOWN":
            missing_inputs.append("flow_quality")
        if liquidity_violence_score == 0.0 and liquidity_violence_flag == "NORMAL":
            missing_inputs.append("liquidity_depth")
        
        # v5: Confidence from similar historical days
        similar_days_n = self._estimate_similar_days(layers_active, convergence_score)
        if similar_days_n >= 50:
            confidence = ConfidenceLevel.HIGH
        elif similar_days_n >= 30:
            confidence = ConfidenceLevel.MEDIUM
        else:
            confidence = ConfidenceLevel.LOW
        
        # ── v5.1: Confidence PENALTY for missing critical inputs ──
        # Rule: Missing data reduces confidence, never shifts the storm_score
        if len(missing_inputs) >= 2:
            # Two+ missing → cap at LOW
            confidence = ConfidenceLevel.LOW
        elif len(missing_inputs) == 1 and confidence == ConfidenceLevel.HIGH:
            # One missing → demote HIGH to MEDIUM
            confidence = ConfidenceLevel.MEDIUM
        
        # ── v5.1: Permission Light (decision-grade gating) ──
        # 🟢 tradable: confidence >= MEDIUM AND layers >= 3 AND no critical missing
        # 🟡 watch: score high but missing inputs OR confidence LOW OR layers < 3
        # 🔴 stand down: conflicting regime OR confidence LOW + many missing
        if confidence in (ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM) and layers_active >= 3 and len(missing_inputs) == 0:
            permission_light = "🟢"
        elif confidence == ConfidenceLevel.LOW and len(missing_inputs) >= 2:
            permission_light = "🔴"
        else:
            permission_light = "🟡"
        
        # Get current price from Polygon
        current_price = 0.0
        if self.polygon:
            try:
                current_price = await self.polygon.get_current_price(symbol) or 0.0
            except Exception:
                pass
        
        return WeatherForecast(
            symbol=symbol,
            forecast=forecast,
            storm_score=storm_score,
            timing=timing,
            structural=structural,
            institutional=institutional,
            technical=technical,
            catalyst=catalyst,
            layers_active=layers_active,
            convergence_score=convergence_score,
            trajectory=trajectory,
            days_building=days_building,
            # v5 fields
            gamma_flip_distance=gamma_flip_distance,
            gamma_flip_fragile=gamma_flip_fragile,
            opening_flow_bias=opening_flow_bias,
            liquidity_violence_score=liquidity_violence_score,
            liquidity_violence_flag=liquidity_violence_flag,
            confidence=confidence,
            similar_days_n=similar_days_n,
            # v5.1 fields
            permission_light=permission_light,
            missing_inputs=missing_inputs,
            expected_drop=expected_drop,
            current_price=current_price,
            sector=ews_data.get('sector', 'unknown')
        )
    
    # =========================================================================
    # LAYER 1: STRUCTURAL PRESSURE ("Jet Stream") — 3-7 day lead
    # =========================================================================
    
    async def _score_structural(self, symbol: str) -> LayerScore:
        """
        Structural pressure = long-term bearish setup.
        Like the jet stream — sets the large-scale weather pattern.
        """
        signals = []
        total_score = 0.0
        details = {}
        
        try:
            # Fetch SMA data and current price in parallel (Polygon UNLIMITED)
            sma20_task = self.polygon.get_sma(symbol, window=20, limit=3)
            sma50_task = self.polygon.get_sma(symbol, window=50, limit=3)
            sma200_task = self.polygon.get_sma(symbol, window=200, limit=3)
            price_task = self.polygon.get_current_price(symbol)
            
            sma20_data, sma50_data, sma200_data, price = await asyncio.gather(
                sma20_task, sma50_task, sma200_task, price_task,
                return_exceptions=True
            )
            
            if isinstance(price, Exception) or not price:
                return LayerScore("Structural", 0, False)
            
            # Extract SMA values
            sma20 = sma20_data[0].get('value', 0) if isinstance(sma20_data, list) and sma20_data else 0
            sma50 = sma50_data[0].get('value', 0) if isinstance(sma50_data, list) and sma50_data else 0
            sma200 = sma200_data[0].get('value', 0) if isinstance(sma200_data, list) and sma200_data else 0
            
            details['price'] = round(price, 2)
            details['sma20'] = round(sma20, 2) if sma20 else 0
            details['sma50'] = round(sma50, 2) if sma50 else 0
            details['sma200'] = round(sma200, 2) if sma200 else 0
            
            # Score: Price below key SMAs
            if sma200 and price < sma200:
                pct_below = (price / sma200 - 1) * 100
                signals.append(f"Below 200 SMA ({pct_below:.1f}%)")
                total_score += 0.35
            
            if sma50 and price < sma50:
                pct_below = (price / sma50 - 1) * 100
                signals.append(f"Below 50 SMA ({pct_below:.1f}%)")
                total_score += 0.25
            
            if sma20 and price < sma20:
                pct_below = (price / sma20 - 1) * 100
                signals.append(f"Below 20 SMA ({pct_below:.1f}%)")
                total_score += 0.20
            
            # Death Cross: SMA50 crosses below SMA200
            if sma50 and sma200 and sma50 < sma200:
                signals.append("☠️ Death Cross (50 SMA < 200 SMA)")
                total_score += 0.20
                
        except Exception as e:
            logger.debug(f"Structural analysis failed for {symbol}: {e}")
        
        total_score = min(1.0, total_score)
        active = total_score >= self.STRUCTURAL_THRESHOLD
        
        return LayerScore(
            name="Structural",
            score=total_score,
            active=active,
            signals=signals,
            details=details
        )
    
    # =========================================================================
    # LAYER 2: INSTITUTIONAL FLOW ("Pressure System") — 1-3 day lead
    # =========================================================================
    
    def _score_institutional(self, symbol: str, ews_data: Dict) -> LayerScore:
        """
        Institutional pressure = smart money selling.
        Like a pressure system — it MUST eventually resolve.
        """
        ipi = ews_data.get('ipi', 0)
        level = ews_data.get('level', 'none')
        unique_fp = ews_data.get('unique_footprints', 0)
        days = ews_data.get('days_building', 0)
        footprints = ews_data.get('footprints', [])
        
        signals = []
        details = {
            'ipi': round(ipi, 3),
            'level': level,
            'unique_footprints': unique_fp,
            'days_building': days
        }
        
        # Map footprint types to human-readable signals
        fp_type_map = {
            'dark_pool_sequence': "🏦 Dark pool staircase selling",
            'put_oi_accumulation': "📈 Stealth put OI building",
            'iv_term_inversion': "📉 IV curve inverted (hedging)",
            'quote_degradation': "🔻 Market makers pulling bids",
            'flow_divergence': "🔄 Options flow bearish divergence",
            'multi_day_distribution': "📊 Wyckoff distribution pattern",
            'cross_asset_divergence': "🔗 Diverging from sector peers",
        }
        
        fp_types = set()
        for fp in footprints:
            fp_type = fp.get('type', fp.get('footprint_type', ''))
            fp_types.add(fp_type)
        
        for fp_type, description in fp_type_map.items():
            if fp_type in fp_types:
                signals.append(description)
        
        # IPI level signals
        if ipi >= 0.85:
            signals.insert(0, f"🚨 IPI EXTREME: {ipi:.0%} — IMMINENT")
        elif ipi >= 0.7:
            signals.insert(0, f"⚠️ IPI CRITICAL: {ipi:.0%} — ACT NOW")
        elif ipi >= 0.5:
            signals.insert(0, f"📊 IPI ELEVATED: {ipi:.0%} — PREPARE")
        
        if days >= 3:
            signals.append(f"⏰ Pressure building {days} days")
        
        if unique_fp >= 4:
            signals.append(f"🔀 {unique_fp} different footprint types converging")
        
        active = ipi >= self.INSTITUTIONAL_THRESHOLD
        
        return LayerScore(
            name="Institutional",
            score=ipi,
            active=active,
            signals=signals,
            details=details
        )
    
    # =========================================================================
    # LAYER 3: TECHNICAL DETERIORATION ("Radar") — 0-2 day lead
    # =========================================================================
    
    async def _score_technical(self, symbol: str) -> LayerScore:
        """
        Technical deterioration = price action confirming breakdown.
        Like radar — shows the storm happening in real-time.
        """
        signals = []
        total_score = 0.0
        details = {}
        
        try:
            # Fetch all technical data in parallel (Polygon UNLIMITED)
            rsi_task = self.polygon.get_rsi(symbol, window=14, limit=5)
            macd_task = self.polygon.get_macd(symbol, limit=3)
            bars_task = self.polygon.get_daily_bars(
                symbol, from_date=date.today() - timedelta(days=12)
            )
            
            rsi_data, macd_data, bars = await asyncio.gather(
                rsi_task, macd_task, bars_task,
                return_exceptions=True
            )
            
            # ── RSI Analysis ──
            if isinstance(rsi_data, list) and rsi_data:
                rsi = rsi_data[0].get('value', 50)
                details['rsi'] = round(rsi, 1)
                
                if rsi < 30:
                    signals.append(f"RSI Oversold ({rsi:.0f}) — extreme weakness")
                    total_score += 0.15
                elif rsi < 40:
                    signals.append(f"RSI Weak ({rsi:.0f}) — bearish momentum")
                    total_score += 0.25
                elif rsi < 50:
                    signals.append(f"RSI Below 50 ({rsi:.0f}) — negative momentum")
                    total_score += 0.10
                
                # RSI TRAJECTORY (declining = bearish)
                if len(rsi_data) >= 3:
                    rsi_values = [r.get('value', 50) for r in rsi_data[:3]]
                    if all(rsi_values[i] <= rsi_values[i+1] for i in range(len(rsi_values)-1)):
                        signals.append("📉 RSI declining trajectory")
                        total_score += 0.10
            
            # ── MACD Analysis ──
            if isinstance(macd_data, list) and macd_data:
                macd_item = macd_data[0]
                macd_val = macd_item.get('value', 0)
                macd_signal = macd_item.get('signal', 0)
                macd_hist = macd_item.get('histogram', 0)
                
                if macd_val is not None:
                    details['macd'] = round(macd_val, 3)
                if macd_signal is not None:
                    details['macd_signal'] = round(macd_signal, 3)
                
                # MACD below signal = bearish crossover
                if macd_val and macd_signal and macd_val < macd_signal:
                    signals.append("MACD bearish crossover")
                    total_score += 0.20
                
                # Histogram negative and growing
                if macd_hist and macd_hist < 0:
                    signals.append(f"MACD histogram negative ({macd_hist:.3f})")
                    total_score += 0.10
            
            # ── Volume & Price Pattern Analysis ──
            if isinstance(bars, list) and len(bars) >= 5:
                recent = bars[-5:]
                
                up_days = [b for b in recent if b.close > b.open]
                down_days = [b for b in recent if b.close <= b.open]
                
                avg_up_vol = np.mean([b.volume for b in up_days]) if up_days else 0
                avg_down_vol = np.mean([b.volume for b in down_days]) if down_days else 0
                
                details['down_days_5d'] = len(down_days)
                details['up_days_5d'] = len(up_days)
                
                # Volume distribution: heavy selling volume
                if avg_down_vol > avg_up_vol * 1.3 and avg_up_vol > 0:
                    signals.append("📊 Heavy selling volume (distribution)")
                    total_score += 0.15
                
                # Lower highs pattern
                highs = [b.high for b in recent[-3:]]
                if len(highs) == 3 and highs[0] >= highs[1] >= highs[2]:
                    signals.append("Lower highs pattern (supply)")
                    total_score += 0.10
                
                # More down days than up
                if len(down_days) >= 4:
                    signals.append(f"{len(down_days)}/5 down days")
                    total_score += 0.10
                
        except Exception as e:
            logger.debug(f"Technical analysis failed for {symbol}: {e}")
        
        total_score = min(1.0, total_score)
        active = total_score >= self.TECHNICAL_THRESHOLD
        
        return LayerScore(
            name="Technical",
            score=total_score,
            active=active,
            signals=signals,
            details=details
        )
    
    # =========================================================================
    # LAYER 4: CATALYST PROXIMITY ("Known Fronts") — Scheduled events
    # =========================================================================
    
    async def _score_catalyst(self, symbol: str) -> LayerScore:
        """
        Catalyst proximity = known events that could trigger the move.
        Like known weather fronts — you know they're coming.
        """
        signals = []
        total_score = 0.0
        details = {}
        
        try:
            # Fetch earnings proximity and news in parallel (Polygon UNLIMITED)
            earnings_task = self.polygon.check_earnings_proximity(symbol)
            news_task = self.polygon.get_ticker_news(symbol, limit=10)
            
            earnings_data, news = await asyncio.gather(
                earnings_task, news_task,
                return_exceptions=True
            )
            
            # ── Earnings Analysis ──
            if isinstance(earnings_data, dict):
                if earnings_data.get('is_post_earnings'):
                    if earnings_data.get('guidance_sentiment') == 'negative':
                        signals.append("📉 Post-earnings NEGATIVE guidance")
                        total_score += 0.50
                        details['negative_guidance'] = True
                    elif earnings_data.get('guidance_sentiment') == 'positive':
                        total_score -= 0.25
                        details['positive_guidance'] = True
                
                if earnings_data.get('is_pre_earnings'):
                    signals.append("⚠️ Earnings approaching (binary risk)")
                    total_score += 0.10
                    details['pre_earnings'] = True
            
            # ── News Sentiment Analysis ──
            if isinstance(news, list) and news:
                bearish_keywords = [
                    'crash', 'plunge', 'tumble', 'selloff', 'downgrade',
                    'miss', 'weak', 'cut', 'layoff', 'recall', 'investigation',
                    'fraud', 'warns', 'disappoints', 'decline', 'loss',
                    'slump', 'drops', 'falls', 'deficit', 'bankruptcy'
                ]
                
                bearish_count = 0
                bearish_headlines = []
                
                for article in news[:10]:
                    title = article.get('title', '').lower()
                    if any(kw in title for kw in bearish_keywords):
                        bearish_count += 1
                        bearish_headlines.append(article.get('title', '')[:60])
                
                details['bearish_news_count'] = bearish_count
                details['total_articles'] = len(news)
                
                if bearish_count >= 3:
                    signals.append(f"📰 Multiple bearish headlines ({bearish_count})")
                    total_score += 0.35
                elif bearish_count >= 2:
                    signals.append(f"📰 Bearish news ({bearish_count} articles)")
                    total_score += 0.25
                elif bearish_count >= 1:
                    signals.append("📰 Bearish headline detected")
                    total_score += 0.15
                
                if bearish_headlines:
                    details['bearish_headlines'] = bearish_headlines[:3]
                
        except Exception as e:
            logger.debug(f"Catalyst analysis failed for {symbol}: {e}")
        
        total_score = max(0, min(1.0, total_score))
        active = total_score >= self.CATALYST_THRESHOLD
        
        return LayerScore(
            name="Catalyst",
            score=total_score,
            active=active,
            signals=signals,
            details=details
        )
    
    # =========================================================================
    # v5: GAMMA FLIP DISTANCE (Architect-4's #1 point)
    # =========================================================================
    
    async def _get_gamma_flip_distance(self, symbol: str) -> Tuple[Optional[float], bool]:
        """
        Calculate distance to gamma flip level.
        
        If abs(distance) <= 0.5% → HIGH FRAGILITY (knife-edge)
        When gamma flips from positive to negative, dealer hedging 
        reverses from mean-reverting to trend-following = cascading moves.
        
        Returns: (distance_pct, is_fragile)
        """
        try:
            if not self.uw:
                return (None, False)
            
            # Get GEX data which includes gamma flip level
            gex_data = await self.uw.get_gex_data(symbol)
            if not gex_data:
                return (None, False)
            
            flip_level = gex_data.gex_flip_level
            if not flip_level or flip_level <= 0:
                return (None, False)
            
            # Get current price
            price = await self.polygon.get_current_price(symbol) if self.polygon else None
            if not price or price <= 0:
                return (None, False)
            
            # Distance as percentage
            distance_pct = (price - flip_level) / flip_level
            is_fragile = abs(distance_pct) <= 0.005  # 0.5%
            
            return (distance_pct, is_fragile)
            
        except Exception as e:
            logger.debug(f"Gamma flip distance failed for {symbol}: {e}")
            return (None, False)
    
    # =========================================================================
    # v5: OPENING vs CLOSING FLOW (Architect fix B)
    # =========================================================================
    
    async def _get_opening_flow_bias(self, symbol: str) -> str:
        """
        Classify recent options flow as opening or closing.
        
        Opening put pressure = bearish (new positions being created)
        Closing put activity = possible short covering / bullish divergence
        
        Uses volume/OI ratio as proxy for opening-intent.
        
        Returns: OPENING_BEARISH, CLOSING_NEUTRAL, MIXED, UNKNOWN
        """
        try:
            if not self.uw:
                return "UNKNOWN"
            
            # Get recent flow for this symbol
            flows = await self.uw.get_flow_recent(symbol, limit=20)
            if not flows:
                return "UNKNOWN"
            
            # Classify put flows
            opening_put_count = 0
            closing_put_count = 0
            
            for flow in flows:
                if flow.option_type.lower() != "put":
                    continue
                
                # High volume relative to size suggests opening trades
                # Bought at ask = new bullish (for puts: bearish for stock)
                if flow.side.lower() in ["ask", "buy"]:
                    # Put bought at ask = bearish opening intent
                    opening_put_count += 1
                elif flow.side.lower() in ["bid", "sell"]:
                    # Put sold at bid = closing position or bullish
                    closing_put_count += 1
            
            total = opening_put_count + closing_put_count
            if total == 0:
                return "UNKNOWN"
            
            opening_ratio = opening_put_count / total
            
            if opening_ratio >= 0.65:
                return "OPENING_BEARISH"
            elif opening_ratio <= 0.35:
                return "CLOSING_NEUTRAL"
            else:
                return "MIXED"
                
        except Exception as e:
            logger.debug(f"Opening flow bias failed for {symbol}: {e}")
            return "UNKNOWN"
    
    # =========================================================================
    # v5: LIQUIDITY VIOLENCE SCORE (Architect fix C)
    # =========================================================================
    
    async def _get_liquidity_violence(self, symbol: str) -> Tuple[float, str]:
        """
        Check if selling will cascade or get absorbed.
        
        Uses bid-ask spread width as proxy for market microstructure health.
        Wide spreads + thinning depth = "gappy/violent" conditions.
        
        Returns: (score 0-1, flag: NORMAL/GAPPY/VIOLENT)
        """
        try:
            if not self.polygon:
                return (0.0, "NORMAL")
            
            quote = await self.polygon.get_latest_quote(symbol)
            if not quote:
                return (0.0, "NORMAL")
            
            bid = quote.get('bid', 0)
            ask = quote.get('ask', 0)
            price = quote.get('price', 0)
            bid_size = quote.get('bid_size', 0)
            ask_size = quote.get('ask_size', 0)
            
            if not price or price <= 0 or not bid or not ask:
                return (0.0, "NORMAL")
            
            # Spread as percentage of mid price
            mid = (bid + ask) / 2
            spread_pct = (ask - bid) / mid if mid > 0 else 0
            
            # Size imbalance (more ask than bid = sellers dominating)
            total_size = bid_size + ask_size
            size_imbalance = (ask_size - bid_size) / total_size if total_size > 0 else 0
            
            # Score: spread width + size imbalance
            score = 0.0
            
            # Wide spread = low liquidity
            if spread_pct > 0.005:  # > 0.5%
                score += 0.3
            if spread_pct > 0.01:   # > 1%
                score += 0.3
            if spread_pct > 0.02:   # > 2%
                score += 0.2
            
            # Bid thinning (more asks than bids = sellers overwhelming)
            if size_imbalance > 0.3:
                score += 0.2
            
            score = min(1.0, score)
            
            # Flag
            if score >= 0.6:
                flag = "VIOLENT"
            elif score >= 0.3:
                flag = "GAPPY"
            else:
                flag = "NORMAL"
            
            return (score, flag)
            
        except Exception as e:
            logger.debug(f"Liquidity violence check failed for {symbol}: {e}")
            return (0.0, "NORMAL")
    
    # =========================================================================
    # TRAJECTORY ANALYSIS — "Storm Tracking"
    # =========================================================================
    
    def _analyze_trajectory(self, symbol: str) -> Tuple[TrajectoryType, int]:
        """
        Analyze how signals are evolving over time.
        Like tracking a hurricane — is it building or dissipating?
        """
        history = self.footprint_history.get(symbol, [])
        
        if not history:
            return TrajectoryType.NEW, 0
        
        # Sort by timestamp
        sorted_history = sorted(history, key=lambda x: x.get('timestamp', ''))
        
        # Calculate days building
        try:
            first_ts = datetime.fromisoformat(sorted_history[0].get('timestamp', ''))
            days_building = max(1, (datetime.now() - first_ts).days + 1)
        except Exception:
            days_building = 1
        
        if len(sorted_history) < 4:
            return TrajectoryType.EMERGING, days_building
        
        # Split history into two halves: older vs newer
        mid = len(sorted_history) // 2
        older_half = sorted_history[:mid]
        newer_half = sorted_history[mid:]
        
        # Compare average strength
        avg_older = np.mean([f.get('strength', 0) for f in older_half])
        avg_newer = np.mean([f.get('strength', 0) for f in newer_half])
        
        # Compare unique footprint types
        older_types = set(f.get('footprint_type', '') for f in older_half)
        newer_types = set(f.get('footprint_type', '') for f in newer_half)
        
        if avg_newer > avg_older * 1.15 or len(newer_types) > len(older_types):
            return TrajectoryType.ACCELERATING, days_building
        elif avg_newer >= avg_older * 0.85:
            return TrajectoryType.SUSTAINED, days_building
        elif len(newer_half) < len(older_half) * 0.5:
            return TrajectoryType.DISSIPATING, days_building
        else:
            return TrajectoryType.EMERGING, days_building
    
    # =========================================================================
    # CONVERGENCE & STORM SCORE CALCULATIONS
    # =========================================================================
    
    def _calculate_storm_score(
        self, 
        layers_active: int, 
        convergence_score: float, 
        trajectory: TrajectoryType
    ) -> float:
        """
        Calculate storm score (0-1 scale, NOT probability).
        
        v5: Renamed from probability. This is an uncalibrated ranking score.
        Call it "storm_score" until backtested against actual outcomes.
        """
        # Base score from number of active layers
        base_scores = {4: 0.85, 3: 0.65, 2: 0.45, 1: 0.25, 0: 0.05}
        base = base_scores.get(layers_active, 0.05)
        
        # Adjust by convergence score
        score_adjustment = convergence_score * 0.10
        
        # Trajectory adjustment
        trajectory_adj = {
            TrajectoryType.ACCELERATING: 0.05,
            TrajectoryType.SUSTAINED: 0.02,
            TrajectoryType.EMERGING: 0,
            TrajectoryType.NEW: -0.02,
            TrajectoryType.DISSIPATING: -0.10,
        }
        
        storm_score = base + score_adjustment + trajectory_adj.get(trajectory, 0)
        return min(0.98, max(0.05, storm_score))
    
    def _estimate_timing(
        self,
        structural: LayerScore,
        institutional: LayerScore,
        technical: LayerScore,
        catalyst: LayerScore
    ) -> str:
        """Estimate WHEN the move will happen based on which layers are active."""
        if technical.active and institutional.active:
            return "1-2 days"
        elif institutional.active and catalyst.active:
            return "1-2 days"
        elif institutional.active:
            return "1-3 days"
        elif structural.active and technical.active:
            return "2-4 days"
        elif structural.active:
            return "3-7 days"
        else:
            return "2-5 days"
    
    def _estimate_drop(self, layers_active: int, convergence_score: float) -> str:
        """Estimate expected price drop magnitude."""
        if layers_active >= 4 and convergence_score > 0.7:
            return "15-40%"
        elif layers_active >= 3 and convergence_score > 0.5:
            return "10-25%"
        elif layers_active >= 3:
            return "8-20%"
        elif layers_active >= 2:
            return "5-15%"
        else:
            return "3-10%"
    
    def _estimate_similar_days(self, layers_active: int, convergence_score: float) -> int:
        """
        v5: Estimate number of similar historical days.
        This is a proxy until real backtesting data exists.
        
        Higher layers + higher convergence = more data points supporting
        (because the conditions are more common / well-documented).
        """
        # Simple heuristic until real calibration
        base = {4: 35, 3: 50, 2: 70, 1: 90, 0: 200}
        count = base.get(layers_active, 100)
        
        # Extreme convergence = rarer, fewer historical matches
        if convergence_score > 0.8:
            count = int(count * 0.5)
        elif convergence_score > 0.6:
            count = int(count * 0.75)
        
        return max(5, count)
    
    # =========================================================================
    # PUBLIC API — AM/PM REPORTS
    # =========================================================================
    
    async def run(self, mode: ReportMode = ReportMode.AM) -> Dict:
        """
        Run the weather engine and return complete forecast.
        
        v5.1: Adds generated_at_utc, data_freshness, regime_context,
              permission_light per pick, and attribution logger.
        
        Writes to:
        - logs/market_weather/report_YYYYMMDD_0900.json (or 1500)
        - logs/market_weather/latest_am.json (or latest_pm.json)
        - logs/market_weather/attribution/YYYYMMDD_mode.json (for T+1/T+2 tracking)
        - logs/predictive_analysis.json (legacy, always latest)
        """
        forecasts = await self.analyze_universe(mode)
        
        # Count by forecast level
        storm_warnings = len([f for f in forecasts if f.forecast == ForecastLevel.STORM_WARNING])
        storm_watches = len([f for f in forecasts if f.forecast == ForecastLevel.STORM_WATCH])
        advisories = len([f for f in forecasts if f.forecast == ForecastLevel.ADVISORY])
        monitoring = len([f for f in forecasts if f.forecast == ForecastLevel.MONITORING])
        
        # v5.1: Permission light distribution
        green_count = len([f for f in forecasts if f.permission_light == "🟢"])
        yellow_count = len([f for f in forecasts if f.permission_light == "🟡"])
        red_count = len([f for f in forecasts if f.permission_light == "🔴"])
        
        now = datetime.now()
        from datetime import timezone as tz
        now_utc = datetime.now(tz.utc)
        
        # ── v5.1: Load regime context for the Regime Panel ──
        regime_context = self._load_regime_context()
        
        # ── v5.1: Data freshness stamps per provider ──
        data_freshness = {
            "ews": self.ews_timestamp if self.ews_timestamp else "MISSING",
            "polygon": now.isoformat(),  # always fresh (unlimited)
            "uw": "available" if self.uw else "MISSING",
            "regime": regime_context.get("cache_time", "MISSING"),
        }
        
        result = {
            "timestamp": now.isoformat(),
            "generated_at_utc": now_utc.isoformat(),
            "ews_timestamp": self.ews_timestamp,
            "engine_version": "v5.1_weather",
            "report_mode": mode.value,
            "report_label": "Open Risk Forecast" if mode == ReportMode.AM else "Overnight Storm Build",
            "methodology": "Multi-Layer Convergence v5.1 (Architect Operational Fixes)",
            "note": (
                "4 independent layers + Gamma Flip Distance + Flow Quality + Liquidity Violence. "
                "Storm Score is NOT probability — it's uncalibrated until backtested. "
                "Missing inputs REDUCE confidence (never shift score). "
                "Permission Light: 🟢 tradable, 🟡 watch, 🔴 stand down."
            ),
            "regime_context": regime_context,
            "data_freshness": data_freshness,
            "forecasts": [f.to_dict() for f in forecasts],
            "summary": {
                "total_candidates": len(forecasts),
                "storm_warnings": storm_warnings,
                "storm_watches": storm_watches,
                "advisories": advisories,
                "monitoring": monitoring,
                "permission_lights": {
                    "green": green_count,
                    "yellow": yellow_count,
                    "red": red_count
                },
                "data_sources": {
                    "ews_alerts_count": len(self.ews_data),
                    "polygon_calls": "Unlimited (technical + news + price)",
                    "uw_calls": "GEX/flow only for gamma flip + flow quality",
                    "footprint_history_tickers": len(self.footprint_history)
                }
            },
            "status": "ok"
        }
        
        # Save to structured directory
        self.WEATHER_DIR.mkdir(parents=True, exist_ok=True)
        
        # 1. Timestamped report
        time_label = now.strftime("%Y%m%d_%H%M")
        report_path = self.WEATHER_DIR / f"report_{time_label}.json"
        with open(report_path, 'w') as f:
            json.dump(result, f, indent=2)
        
        # 2. Latest pointer (am or pm)
        latest_path = self.WEATHER_DIR / f"latest_{mode.value}.json"
        with open(latest_path, 'w') as f:
            json.dump(result, f, indent=2)
        
        # 3. Legacy output (for backward compatibility with dashboard)
        self.LEGACY_OUTPUT.parent.mkdir(exist_ok=True)
        with open(self.LEGACY_OUTPUT, 'w') as f:
            json.dump(result, f, indent=2)
        
        # 4. v5.1: Attribution Logger — save snapshot for T+1/T+2 outcome tracking
        self._save_attribution_snapshot(result, mode, now)
        
        logger.info(f"Weather v5.1 [{mode.value.upper()}] saved to {report_path} + {latest_path}")
        
        return result
    
    def _load_regime_context(self) -> Dict:
        """
        v5.1: Load current market regime context for the Regime Panel.
        Reads from market_regime_cache.json (existing, no new API calls).
        """
        regime_file = Path("market_regime_cache.json")
        try:
            if regime_file.exists():
                with open(regime_file) as f:
                    cache = json.load(f)
                rd = cache.get("regime_data", {})
                return {
                    "cache_time": cache.get("cache_time", "MISSING"),
                    "regime": rd.get("regime", "unknown"),
                    "vix_level": rd.get("vix_level", 0.0),
                    "vix_change": rd.get("vix_change", 0.0),
                    "spy_below_vwap": rd.get("spy_below_vwap", False),
                    "qqq_below_vwap": rd.get("qqq_below_vwap", False),
                    "below_zero_gamma": rd.get("below_zero_gamma", False),
                    "index_gex": rd.get("index_gex", 0.0),
                    # Derived regime classification
                    "risk_regime": self._classify_risk_regime(rd),
                    "tape_type": self._classify_tape_type(rd),
                    "fragility": "HIGH" if rd.get("below_zero_gamma", False) else "LOW",
                }
        except Exception as e:
            logger.debug(f"Could not load regime context: {e}")
        return {"regime": "unknown", "risk_regime": "UNKNOWN", "tape_type": "UNKNOWN", "fragility": "UNKNOWN", "cache_time": "MISSING"}
    
    def _classify_risk_regime(self, rd: Dict) -> str:
        """Classify risk regime from market regime data."""
        vix = rd.get("vix_level", 0.0)
        spy_below = rd.get("spy_below_vwap", False)
        qqq_below = rd.get("qqq_below_vwap", False)
        regime = rd.get("regime", "")
        
        if vix > 25 and spy_below and qqq_below:
            return "RISK_OFF"
        elif vix > 20 or spy_below or qqq_below:
            if "bearish" in regime.lower():
                return "RISK_OFF"
            return "NEUTRAL"
        else:
            if "bullish" in regime.lower():
                return "RISK_ON"
            return "NEUTRAL"
    
    def _classify_tape_type(self, rd: Dict) -> str:
        """Classify tape type from GEX regime."""
        gex = rd.get("index_gex", 0.0)
        below_zero_gamma = rd.get("below_zero_gamma", False)
        
        if below_zero_gamma or gex < 0:
            return "TREND"  # Negative gamma = trend amplification
        elif gex > 0:
            return "CHOP"   # Positive gamma = mean reversion / choppy
        return "UNKNOWN"
    
    def _save_attribution_snapshot(self, result: Dict, mode: ReportMode, now: datetime):
        """
        v5.1: Attribution Logger.
        
        Save a snapshot of today's picks + storm_scores + regime fields.
        A separate process (or the next AM report) can compute T+1/T+2 outcomes.
        
        This is how you turn "unknown into known" over time:
        - "It said 70% storm; did it actually rain?"
        - Target: 55-60% bearish follow-through for Storm Warning bucket = elite
        """
        try:
            attr_dir = self.WEATHER_DIR / "attribution"
            attr_dir.mkdir(parents=True, exist_ok=True)
            
            date_str = now.strftime("%Y%m%d")
            attr_file = attr_dir / f"{date_str}_{mode.value}.json"
            
            # Compact snapshot for calibration
            snapshot = {
                "report_date": date_str,
                "report_mode": mode.value,
                "generated_at_utc": datetime.utcnow().isoformat(),
                "regime_context": result.get("regime_context", {}),
                "picks": []
            }
            
            for fc in result.get("forecasts", []):
                snapshot["picks"].append({
                    "symbol": fc["symbol"],
                    "storm_score": fc.get("storm_score", 0),
                    "forecast": fc.get("forecast", ""),
                    "layers_active": fc.get("layers_active", 0),
                    "convergence_score": fc.get("convergence_score", 0),
                    "confidence": fc.get("confidence", "LOW"),
                    "permission_light": fc.get("permission_light", "🟡"),
                    "missing_inputs": fc.get("missing_inputs", []),
                    "current_price": fc.get("current_price", 0),
                    # Outcomes — filled in by attribution checker later
                    "t1_close": None,     # next day close
                    "t1_return": None,    # next day return %
                    "t2_close": None,     # T+2 close
                    "t2_return": None,    # T+2 return %
                    "max_adverse": None,  # max adverse excursion in window
                    "did_drop_5pct": None,
                    "did_drop_10pct": None,
                })
            
            with open(attr_file, 'w') as f:
                json.dump(snapshot, f, indent=2)
            
            logger.info(f"Attribution snapshot saved: {attr_file}")
            
        except Exception as e:
            logger.debug(f"Attribution save failed (non-critical): {e}")
    
    def format_result(self, result: Dict) -> str:
        """Format result for console display."""
        mode = result.get('report_mode', 'am').upper()
        label = result.get('report_label', 'Weather Report')
        regime = result.get('regime_context', {})
        freshness = result.get('data_freshness', {})
        
        lines = [
            "=" * 78,
            f"🌪️  MARKET WEATHER ENGINE v5.1 — {label} [{mode}]",
            "=" * 78,
            f"Methodology: Multi-Layer Convergence v5.1 (Architect Operational Fixes)",
            f"EWS Data: {result.get('ews_timestamp', 'Unknown')}",
            f"Generated (UTC): {result.get('generated_at_utc', 'Unknown')}",
            f"Status: {result.get('status', 'unknown')}",
            "",
            "── REGIME PANEL ──────────────────────────────────────────────────",
            f"  Risk: {regime.get('risk_regime', 'UNKNOWN')} | "
            f"Tape: {regime.get('tape_type', 'UNKNOWN')} | "
            f"Fragility: {regime.get('fragility', 'UNKNOWN')} | "
            f"VIX: {regime.get('vix_level', 0):.1f} ({regime.get('vix_change', 0):+.1%})",
            "",
            "── DATA FRESHNESS ────────────────────────────────────────────────",
            f"  EWS: {freshness.get('ews', 'N/A')} | Polygon: OK | "
            f"UW: {freshness.get('uw', 'N/A')} | Regime: {freshness.get('regime', 'N/A')}",
            "",
        ]
        
        emojis = {
            "STORM WARNING": "🌪️",
            "STORM WATCH": "⛈️",
            "ADVISORY": "🌧️",
            "MONITORING": "☁️",
            "CLEAR": "☀️"
        }
        
        for i, fc in enumerate(result.get('forecasts', []), 1):
            emoji = emojis.get(fc['forecast'], "❓")
            layers = fc.get('layers', {})
            active_names = [
                name.upper()[:4] for name, data in layers.items() 
                if data.get('active')
            ]
            
            storm_score = fc.get('storm_score', 0)
            confidence = fc.get('confidence', 'LOW')
            perm = fc.get('permission_light', '🟡')
            gamma_frag = "⚡FRAG" if fc.get('gamma_flip_fragile') else ""
            flow_bias = fc.get('opening_flow_bias', 'UNKNOWN')[:4]
            liq_flag = fc.get('liquidity_violence_flag', 'NORMAL')[:4]
            missing = fc.get('missing_inputs', [])
            miss_str = f" [MISSING: {','.join(missing)}]" if missing else ""
            
            lines.append(
                f"{i:2}. {perm} {emoji} {fc['forecast']:15} | {fc['symbol']:5} | "
                f"Storm: {storm_score:.2f} | {fc['timing']:8} | "
                f"Layers: {fc['layers_active']}/4 [{', '.join(active_names)}]"
            )
            
            traj_emoji = fc.get('trajectory_emoji', '')
            lines.append(
                f"      └─ {traj_emoji} {fc.get('trajectory', 'NEW')} | "
                f"Conf: {confidence} (n={fc.get('similar_days_n', 0)}) | "
                f"Flow: {flow_bias} | Liq: {liq_flag} {gamma_frag}{miss_str}"
            )
        
        lines.append("=" * 78)
        summary = result.get('summary', {})
        perm_lights = summary.get('permission_lights', {})
        lines.append(
            f"Summary: {summary.get('storm_warnings', 0)} 🌪️ WARNINGS, "
            f"{summary.get('storm_watches', 0)} ⛈️ WATCHES, "
            f"{summary.get('advisories', 0)} 🌧️ ADVISORIES, "
            f"{summary.get('monitoring', 0)} ☁️ MONITORING"
        )
        lines.append(
            f"Lights: 🟢 {perm_lights.get('green', 0)} tradable | "
            f"🟡 {perm_lights.get('yellow', 0)} watch | "
            f"🔴 {perm_lights.get('red', 0)} stand down"
        )
        
        return "\n".join(lines)


# ============================================================================
# STANDALONE RUNNERS
# ============================================================================

async def run_weather_analysis(mode: str = "am"):
    """Run the weather engine standalone."""
    from putsengine.config import get_settings
    from putsengine.clients.polygon_client import PolygonClient
    from putsengine.clients.unusual_whales_client import UnusualWhalesClient
    
    settings = get_settings()
    polygon = PolygonClient(settings)
    uw = UnusualWhalesClient(settings)
    
    report_mode = ReportMode.PM if mode.lower() == "pm" else ReportMode.AM
    
    try:
        engine = MarketWeatherEngine(
            polygon_client=polygon, uw_client=uw, settings=settings
        )
        result = await engine.run(report_mode)
        print(engine.format_result(result))
        return result
    finally:
        await polygon.close()
        try:
            await uw.close()
        except Exception:
            pass


async def run_weather_am():
    """Run AM weather report (9:00 AM ET)."""
    return await run_weather_analysis("am")


async def run_weather_pm():
    """Run PM weather report (3:00 PM ET)."""
    return await run_weather_analysis("pm")


# Keep backward compatibility with v3/v4 API
class PredictiveEngine:
    """Backward-compatible wrapper for MarketWeatherEngine"""
    
    def __init__(self, settings=None):
        self.settings = settings
        self._engine = None
    
    async def run(self, mode: str = "am") -> Dict:
        from putsengine.config import get_settings
        from putsengine.clients.polygon_client import PolygonClient
        from putsengine.clients.unusual_whales_client import UnusualWhalesClient
        
        settings = self.settings or get_settings()
        polygon = PolygonClient(settings)
        uw = UnusualWhalesClient(settings)
        
        report_mode = ReportMode.PM if mode.lower() == "pm" else ReportMode.AM
        
        try:
            self._engine = MarketWeatherEngine(
                polygon_client=polygon, uw_client=uw, settings=settings
            )
            return await self._engine.run(report_mode)
        finally:
            await polygon.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Market Weather Engine v5")
    parser.add_argument("--mode", choices=["am", "pm"], default="am",
                        help="Report mode: 'am' for Open Risk Forecast, 'pm' for Overnight Storm Build")
    args = parser.parse_args()
    asyncio.run(run_weather_analysis(args.mode))
