#!/usr/bin/env python3
"""
MarketPulse Pre-Market Microstructure Engine
=============================================
Consolidated from Architect-2, 3, 4, 5 feedback.

THE HARD TRUTH:
- You CANNOT know market direction with certainty at 8-9 AM
- You CAN extract a probabilistic regime bias (risk-off / neutral / risk-on)
- Opening direction can be inferred with higher confidence than full-day
- 65-70% full-day accuracy claims are NOT institutionally credible
- 52-58% edge, used to gate risk and structure, IS very valuable

THE GOAL IS NOT PREDICTION.
THE GOAL IS REGIME AWARENESS + STRUCTURE ALIGNMENT.

This module is:
- READ-ONLY
- NO EXECUTION
- NO THRESHOLD CHANGES
- NO GUI DISRUPTION

This is CONTEXT, not a signal.

Feb 5, 2026
"""

import asyncio
import json
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
from pathlib import Path

from loguru import logger
from putsengine.config import get_settings, EngineConfig
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient


# =============================================================================
# ENUMS & DATA CLASSES
# =============================================================================

class MarketRegime(Enum):
    """Market regime classification - NOT prediction."""
    RISK_OFF = "RISK_OFF"       # Score 0.00-0.40: Bearish bias, puts favorable
    NEUTRAL = "NEUTRAL"         # Score 0.40-0.60: Chop, be selective
    RISK_ON = "RISK_ON"         # Score 0.60-1.00: Bullish bias, avoid puts


class Tradeability(Enum):
    """How the market is likely to move."""
    TREND = "TREND"             # Negative gamma - directional moves amplified
    CHOP = "CHOP"               # Positive gamma - mean reversion, pins
    UNKNOWN = "UNKNOWN"


class Confidence(Enum):
    """Confidence in the regime classification."""
    LOW = "LOW"                 # < 55% confidence
    MEDIUM = "MEDIUM"           # 55-65% confidence  
    HIGH = "HIGH"               # > 65% confidence


@dataclass
class MarketPulseResult:
    """
    MarketPulse output - regime awareness, not prediction.
    """
    timestamp: datetime
    
    # Core regime classification
    regime: MarketRegime
    regime_score: float         # 0.0 (risk-off) to 1.0 (risk-on)
    confidence: Confidence
    confidence_pct: float       # e.g., 62%
    
    # Tradeability
    tradeability: Tradeability
    
    # Component scores (for transparency/audit)
    futures_score: float        # 0-1, weight 0.30
    vix_score: float            # 0-1, weight 0.25
    gamma_score: float          # 0-1, weight 0.20
    breadth_score: float        # 0-1, weight 0.15
    sentiment_score: float      # 0-1, weight 0.10 (contrarian)
    
    # =========================================================================
    # ARCHITECT-4 ADDITIONS (Feb 5, 2026) - READ-ONLY CONTEXT ENHANCEMENTS
    # These enhance context WITHOUT changing behavior
    # =========================================================================
    
    # 1. Distance to Gamma Flip (%) - fragility indicator
    gamma_flip_distance: float = 0.0      # % distance to flip level
    gamma_flip_zone: str = "UNKNOWN"      # SAFE / FRAGILE / KNIFE_EDGE
    
    # 2. Certainty Gap (8 AM vs 9 AM delta) - information velocity
    prior_score: Optional[float] = None   # Previous run score
    score_delta: float = 0.0              # Change from prior
    certainty_gap: str = "N/A"            # STABLE / SHIFTING / VOLATILE
    
    # 3. Flow Quality Flag - opening vs closing
    flow_opening_pct: float = 0.0         # % opening transactions
    flow_quality: str = "UNKNOWN"         # GOOD / CAUTION / WARNING
    
    # 4. Pre-Market Spread Expansion - violence indicator
    spread_expansion: float = 0.0         # % above normal spread
    spread_flag: str = "NORMAL"           # NORMAL / WIDE / DANGEROUS
    
    # 5. Expected Move vs Open - dealer re-hedge risk
    expected_move_pct: float = 0.0        # ATM straddle expected move %
    open_vs_expected: str = "UNKNOWN"     # INSIDE / STRETCHING / OUTSIDE
    
    # 6. Sample Size / Historical Match - confidence calibration
    historical_matches: int = 0           # Days matching current profile
    sample_confidence: str = "UNKNOWN"    # HIGH / MEDIUM / LOW
    
    # 7. Liquidity Depth Ratio - ARCHITECT-4 FINAL (Feb 5)
    liquidity_depth_ratio: float = 1.0    # bid_size / rolling_avg_bid_size
    liquidity_flag: str = "NORMAL"        # NORMAL / THINNING / VACUUM
    
    # 8. Execution Light - ARCHITECT-4 FINAL (Feb 5)
    # RED = Wait, YELLOW = Small size, GREEN = Permission
    execution_light: str = "YELLOW"       # RED / YELLOW / GREEN
    execution_rationale: str = ""         # Why this light
    
    # Key observations
    notes: List[str] = field(default_factory=list)
    
    # Conditional picks (ONLY if risk-off + trend)
    conditional_picks: List[Dict] = field(default_factory=list)
    
    # Raw data for debugging
    raw_data: Dict = field(default_factory=dict)


# =============================================================================
# SCORING WEIGHTS (Simple, Auditable, Honest)
# =============================================================================

WEIGHTS = {
    "futures": 0.30,    # NQ/ES drift - WHO is in control
    "vix": 0.25,        # Volatility regime - HOW it will move
    "gamma": 0.20,      # Dealer positioning - mechanical flows
    "breadth": 0.15,    # Sector stress - WHY it accelerates
    "sentiment": 0.10,  # Contrarian only - fade retail extremes
}


class MarketPulseEngine:
    """
    Pre-Market Microstructure Engine.
    
    Turns 8-9 AM chaos into a probabilistic regime nowcast.
    
    INSTITUTIONAL HIERARCHY:
    
    Tier 1 - Directional Bias (WHO is in control)
        - ES/NQ futures drift
        - QQQ vs SPY relative weakness
        - Premarket gap vs prior close
    
    Tier 2 - Tradeability (HOW it will move)
        - VIX level + change + term structure
        - Dealer gamma / net GEX
    
    Tier 3 - Cause & Amplifiers (WHY it accelerates)
        - Earnings clusters, macro releases
        - Sector leadership
        - Institutional options flow
    """
    
    # VIX thresholds
    VIX_LOW = 15
    VIX_NORMAL = 20
    VIX_ELEVATED = 25
    VIX_HIGH = 30
    
    # GEX thresholds (billions)
    GEX_POSITIVE = 2.0
    GEX_NEGATIVE = -2.0
    
    def __init__(self):
        self.settings = get_settings()
        self.polygon: Optional[PolygonClient] = None
        self.uw: Optional[UnusualWhalesClient] = None
        
    async def _init_clients(self):
        """Initialize API clients."""
        if self.polygon is None:
            self.polygon = PolygonClient(self.settings)
        if self.uw is None:
            self.uw = UnusualWhalesClient(self.settings)
    
    async def close(self):
        """Close client connections."""
        if self.polygon:
            await self.polygon.close()
        if self.uw:
            await self.uw.close()
    
    # =========================================================================
    # TIER 1: DIRECTIONAL BIAS (WHO is in control)
    # =========================================================================
    
    async def get_futures_score(self) -> Tuple[float, Dict]:
        """
        Score based on ES/NQ futures and relative weakness.
        
        TRUTH: Futures explain opening direction reasonably well (60-70%),
        but NOT close-to-close direction.
        
        Returns score 0-1 where:
        - 0.0 = Strong risk-off (futures down, QQQ weaker than SPY)
        - 0.5 = Neutral
        - 1.0 = Strong risk-on (futures up, QQQ leading)
        """
        await self._init_clients()
        
        data = {}
        score = 0.5  # Default neutral
        
        try:
            # Get SPY and QQQ snapshots
            spy_snap = await self.polygon.get_snapshot("SPY")
            qqq_snap = await self.polygon.get_snapshot("QQQ")
            
            spy_change = 0
            qqq_change = 0
            
            if spy_snap and "ticker" in spy_snap:
                spy_change = spy_snap["ticker"].get("todaysChangePerc", 0)
                data["spy_change"] = spy_change
                
            if qqq_snap and "ticker" in qqq_snap:
                qqq_change = qqq_snap["ticker"].get("todaysChangePerc", 0)
                data["qqq_change"] = qqq_change
            
            # Calculate relative weakness (QQQ - SPY)
            # Negative = QQQ underperforming = risk-off signal
            relative_weakness = qqq_change - spy_change
            data["relative_weakness"] = relative_weakness
            
            # Average change (weighted toward QQQ as tech leads)
            avg_change = (spy_change * 0.4) + (qqq_change * 0.6)
            data["avg_change"] = avg_change
            
            # Convert to score (0-1)
            # -2% or worse = 0.0, +2% or better = 1.0
            score = (avg_change + 2) / 4  # Maps [-2, +2] to [0, 1]
            score = max(0, min(1, score))
            
            # Adjust for relative weakness
            if relative_weakness < -0.5:
                score -= 0.1  # QQQ significantly underperforming = more bearish
            elif relative_weakness > 0.5:
                score += 0.1  # QQQ leading = more bullish
            
            score = max(0, min(1, score))
            
            data["interpretation"] = (
                f"SPY {spy_change:+.2f}% | QQQ {qqq_change:+.2f}% | "
                f"Relative: {relative_weakness:+.2f}%"
            )
            
        except Exception as e:
            logger.debug(f"Futures score error: {e}")
            
        return score, data
    
    # =========================================================================
    # TIER 2: TRADEABILITY (HOW it will move)
    # =========================================================================
    
    async def get_vix_score(self) -> Tuple[float, Tradeability, Dict]:
        """
        Score based on VIX level, change, and regime.
        
        VIX tells us:
        - Current fear level
        - Expected volatility
        - Risk appetite
        
        Returns score 0-1 where:
        - 0.0 = High VIX, spiking = risk-off
        - 0.5 = Normal VIX
        - 1.0 = Low VIX, falling = risk-on (but complacency risk)
        """
        await self._init_clients()
        
        data = {}
        score = 0.5
        tradeability = Tradeability.UNKNOWN
        
        try:
            vix_snap = await self.polygon.get_snapshot("VIX")
            
            if vix_snap and "ticker" in vix_snap:
                ticker = vix_snap["ticker"]
                vix_level = ticker.get("lastTrade", {}).get("p", 20)
                vix_change = ticker.get("todaysChangePerc", 0)
                
                data["vix_level"] = vix_level
                data["vix_change"] = vix_change
                
                # Base score from level (inverse relationship)
                # VIX 30+ = 0.0, VIX 15 or less = 1.0
                level_score = (30 - vix_level) / 15
                level_score = max(0, min(1, level_score))
                
                # Adjust for change
                change_adj = 0
                if vix_change > 10:
                    change_adj = -0.2  # Spiking = risk-off
                    data["vix_spike"] = True
                elif vix_change < -10:
                    change_adj = 0.1   # Falling = risk-on
                    data["vix_falling"] = True
                
                score = level_score + change_adj
                score = max(0, min(1, score))
                
                # Determine tradeability
                # High VIX = trending possible
                # Low VIX = chop likely
                if vix_level > self.VIX_ELEVATED:
                    tradeability = Tradeability.TREND
                elif vix_level < self.VIX_LOW:
                    tradeability = Tradeability.CHOP
                
                data["interpretation"] = (
                    f"VIX {vix_level:.1f} ({vix_change:+.1f}%) - "
                    f"{'High fear' if vix_level > 25 else 'Normal' if vix_level > 18 else 'Low/Complacent'}"
                )
                
        except Exception as e:
            logger.debug(f"VIX score error: {e}")
            
        return score, tradeability, data
    
    async def get_gamma_score(self) -> Tuple[float, Tradeability, Dict]:
        """
        Score based on dealer gamma positioning.
        
        THE KEY INSTITUTIONAL SIGNAL:
        - Positive gamma = dealers SHORT gamma = they provide liquidity
          → Market pins, mean-reverts, CHOP
        - Negative gamma = dealers LONG gamma = they remove liquidity
          → Market trends, volatility amplified, TREND
        
        Returns score 0-1 where:
        - 0.0 = Strong negative gamma (amplifies selling)
        - 0.5 = Neutral gamma
        - 1.0 = Strong positive gamma (stabilizes)
        """
        await self._init_clients()
        
        data = {}
        score = 0.5
        tradeability = Tradeability.UNKNOWN
        
        try:
            gex_data = await self.uw.get_gex_data("SPY")
            
            if gex_data:
                gex_value = getattr(gex_data, 'gex', 0) or 0
                data["gex_value"] = gex_value
                
                # Convert GEX to score
                # -5B or worse = 0.0 (extreme negative), +5B or better = 1.0
                score = (gex_value + 5) / 10
                score = max(0, min(1, score))
                
                # Determine tradeability from gamma
                if gex_value < self.GEX_NEGATIVE:
                    tradeability = Tradeability.TREND
                    data["gamma_regime"] = "NEGATIVE (trend amplification)"
                elif gex_value > self.GEX_POSITIVE:
                    tradeability = Tradeability.CHOP
                    data["gamma_regime"] = "POSITIVE (mean reversion)"
                else:
                    tradeability = Tradeability.UNKNOWN
                    data["gamma_regime"] = "NEUTRAL"
                
                data["interpretation"] = f"GEX {gex_value:.2f}B - {data['gamma_regime']}"
                
        except Exception as e:
            logger.debug(f"Gamma score error: {e}")
            
        return score, tradeability, data
    
    # =========================================================================
    # ARCHITECT-4 ADDITIONS: READ-ONLY CONTEXT ENHANCEMENTS
    # These enhance context WITHOUT changing behavior
    # =========================================================================
    
    async def get_gamma_flip_distance(self) -> Tuple[float, str, Dict]:
        """
        Calculate distance to gamma flip level.
        
        ARCHITECT-4 INSIGHT:
        The market is most fragile when:
        - Gamma is close to zero (flip level)
        - Price is within ~0.5% of the flip
        
        This is where mechanical dealer hedging takes over.
        
        Returns:
        - distance_pct: % distance from flip level
        - zone: SAFE / FRAGILE / KNIFE_EDGE
        """
        await self._init_clients()
        
        data = {}
        distance_pct = 999.0  # Default far away
        zone = "UNKNOWN"
        
        try:
            # Get GEX data which includes flip level
            gex_data = await self.uw.get_gex_data("SPY")
            
            if gex_data:
                # Get current price
                spy_snap = await self.polygon.get_snapshot("SPY")
                
                if spy_snap and "ticker" in spy_snap:
                    current_price = spy_snap["ticker"].get("lastTrade", {}).get("p", 0)
                    
                    # GEX flip level is where gamma crosses zero
                    # Approximate from GEX value direction
                    gex_value = getattr(gex_data, 'gex', 0) or 0
                    
                    # Estimate flip level (simplified - real would use strike-level data)
                    # When GEX is small, we're close to flip
                    if current_price > 0:
                        # Distance proxy based on GEX magnitude
                        # Small GEX magnitude = close to flip
                        gex_magnitude = abs(gex_value)
                        
                        if gex_magnitude < 0.5:
                            distance_pct = 0.2  # Very close
                        elif gex_magnitude < 1.0:
                            distance_pct = 0.4
                        elif gex_magnitude < 2.0:
                            distance_pct = 0.8
                        else:
                            distance_pct = 1.5  # Far from flip
                        
                        data["gex_value"] = gex_value
                        data["current_price"] = current_price
                        data["distance_pct"] = distance_pct
                        
                        # Classify zone
                        if distance_pct < 0.3:
                            zone = "KNIFE_EDGE"
                        elif distance_pct < 0.5:
                            zone = "FRAGILE"
                        else:
                            zone = "SAFE"
                        
                        data["zone"] = zone
                        data["interpretation"] = f"Gamma flip distance: {distance_pct:.1f}% - {zone}"
                        
        except Exception as e:
            logger.debug(f"Gamma flip distance error: {e}")
            
        return distance_pct, zone, data
    
    async def get_flow_quality(self) -> Tuple[float, str, Dict]:
        """
        Assess flow quality: opening vs closing transactions.
        
        ARCHITECT-4 INSIGHT:
        Pre-market options flow can be misleading if majority is closing.
        Opening flow = new conviction
        Closing flow = profit taking / hedging exits
        """
        await self._init_clients()
        
        data = {}
        opening_pct = 50.0  # Default balanced
        quality = "UNKNOWN"
        
        try:
            # Get flow alerts for SPY as market proxy
            flow = await self.uw.get_flow_alerts("SPY", limit=50)
            
            if flow:
                opening_count = 0
                closing_count = 0
                
                for trade in flow:
                    # Check if opening or closing
                    if hasattr(trade, 'is_opening'):
                        if trade.is_opening:
                            opening_count += 1
                        else:
                            closing_count += 1
                    elif hasattr(trade, 'open_interest_change'):
                        # Positive OI change = likely opening
                        if trade.open_interest_change > 0:
                            opening_count += 1
                        else:
                            closing_count += 1
                
                total = opening_count + closing_count
                if total > 0:
                    opening_pct = (opening_count / total) * 100
                
                data["opening_count"] = opening_count
                data["closing_count"] = closing_count
                data["opening_pct"] = opening_pct
                
                # Classify quality
                if opening_pct >= 60:
                    quality = "GOOD"
                elif opening_pct >= 40:
                    quality = "CAUTION"
                else:
                    quality = "WARNING"
                
                data["quality"] = quality
                data["interpretation"] = f"Flow quality: {opening_pct:.0f}% opening - {quality}"
                
        except Exception as e:
            logger.debug(f"Flow quality error: {e}")
            
        return opening_pct, quality, data
    
    async def get_spread_expansion(self) -> Tuple[float, str, Dict]:
        """
        Detect pre-market spread widening.
        
        ARCHITECT-4 INSIGHT:
        If MarketPulse says Risk-Off AND spreads widen →
        downside is likely DISCONTINUOUS (gap risk)
        
        This is a "violence indicator", not a trade command.
        """
        await self._init_clients()
        
        data = {}
        expansion = 0.0
        flag = "NORMAL"
        
        try:
            # Get quotes for SPY and QQQ
            for symbol in ["SPY", "QQQ"]:
                try:
                    quote = await self.polygon.get_latest_quote(symbol)
                    
                    if quote:
                        bid = quote.get("bid", 0)
                        ask = quote.get("ask", 0)
                        
                        if bid > 0 and ask > 0:
                            spread_pct = ((ask - bid) / bid) * 100
                            data[f"{symbol}_spread_pct"] = spread_pct
                            
                            # Normal SPY spread is ~0.01%, QQQ ~0.02%
                            normal_spread = 0.01 if symbol == "SPY" else 0.02
                            
                            # Calculate expansion ratio
                            if spread_pct > normal_spread * 5:
                                expansion = max(expansion, spread_pct / normal_spread)
                                
                except Exception:
                    pass
            
            # Classify flag
            if expansion > 10:
                flag = "DANGEROUS"
            elif expansion > 3:
                flag = "WIDE"
            else:
                flag = "NORMAL"
            
            data["expansion"] = expansion
            data["flag"] = flag
            data["interpretation"] = f"Spread expansion: {expansion:.1f}x normal - {flag}"
            
        except Exception as e:
            logger.debug(f"Spread expansion error: {e}")
            
        return expansion, flag, data
    
    async def get_expected_move_position(self) -> Tuple[float, str, Dict]:
        """
        Compare opening price vs ATM straddle expected move.
        
        ARCHITECT-4 INSIGHT:
        Large divergence = dealer re-hedging risk at open.
        
        Returns:
        - expected_move_pct: The ATM straddle expected move
        - position: INSIDE / STRETCHING / OUTSIDE
        """
        await self._init_clients()
        
        data = {}
        expected_move = 0.0
        position = "UNKNOWN"
        
        try:
            # Get SPY IV for expected move estimate
            spy_snap = await self.polygon.get_snapshot("SPY")
            
            if spy_snap and "ticker" in spy_snap:
                current_price = spy_snap["ticker"].get("lastTrade", {}).get("p", 0)
                prev_close = spy_snap["ticker"].get("prevDay", {}).get("c", current_price)
                
                # Get IV from UW
                try:
                    iv_data = await self.uw.get_iv_data("SPY")
                    if iv_data:
                        iv = getattr(iv_data, 'iv', 0.20) or 0.20
                    else:
                        iv = 0.20  # Default 20% IV
                except:
                    iv = 0.20
                
                # Calculate 1-day expected move
                # EM = price * IV * sqrt(1/252)
                import math
                expected_move = current_price * iv * math.sqrt(1/252)
                expected_move_pct = (expected_move / current_price) * 100
                
                data["current_price"] = current_price
                data["prev_close"] = prev_close
                data["iv"] = iv
                data["expected_move"] = expected_move
                data["expected_move_pct"] = expected_move_pct
                
                # Calculate where we are vs expected move
                if prev_close > 0:
                    actual_move = abs(current_price - prev_close)
                    actual_move_pct = (actual_move / prev_close) * 100
                    
                    move_ratio = actual_move_pct / expected_move_pct if expected_move_pct > 0 else 0
                    
                    data["actual_move_pct"] = actual_move_pct
                    data["move_ratio"] = move_ratio
                    
                    # Classify position
                    if move_ratio < 0.5:
                        position = "INSIDE"
                    elif move_ratio < 1.0:
                        position = "STRETCHING"
                    else:
                        position = "OUTSIDE"
                    
                    data["position"] = position
                    data["interpretation"] = f"Open at {move_ratio:.1f}x expected move - {position}"
                    
        except Exception as e:
            logger.debug(f"Expected move position error: {e}")
            
        return expected_move, position, data
    
    def get_sample_confidence(self, regime_score: float, tradeability: Tradeability) -> Tuple[int, str]:
        """
        Estimate historical sample size for current profile.
        
        ARCHITECT-4 INSIGHT:
        If the current feature profile only matches few historical days,
        label LOW CONFIDENCE to prevent false conviction.
        
        This is a rough heuristic - real implementation would use backtest data.
        """
        # Rough estimates based on regime extremity
        # More extreme regimes are rarer
        
        score_distance = abs(regime_score - 0.5)
        
        if score_distance > 0.3:
            # Extreme regime - rare
            matches = 30
            confidence = "LOW"
        elif score_distance > 0.15:
            # Moderate regime - more common
            matches = 100
            confidence = "MEDIUM"
        else:
            # Neutral - very common
            matches = 200
            confidence = "HIGH"
        
        # Adjust for tradeability clarity
        if tradeability == Tradeability.UNKNOWN:
            matches = int(matches * 0.7)
            if confidence == "HIGH":
                confidence = "MEDIUM"
        
        return matches, confidence
    
    def get_certainty_gap(self, current_score: float, prior_score: Optional[float]) -> Tuple[float, str]:
        """
        Calculate certainty gap between runs.
        
        ARCHITECT-4 INSIGHT:
        Large delta between 8 AM and 9 AM = information velocity,
        not prediction accuracy.
        """
        if prior_score is None:
            return 0.0, "N/A"
        
        delta = current_score - prior_score
        abs_delta = abs(delta)
        
        if abs_delta > 0.15:
            gap = "VOLATILE"
        elif abs_delta > 0.08:
            gap = "SHIFTING"
        else:
            gap = "STABLE"
        
        return delta, gap
    
    # =========================================================================
    # ARCHITECT-4 FINAL: LIQUIDITY & EXECUTION LIGHT (Feb 5, 2026)
    # =========================================================================
    
    async def get_liquidity_depth_ratio(self) -> Tuple[float, str, Dict]:
        """
        Calculate liquidity depth ratio for fragility detection.
        
        ARCHITECT-4 FINAL INSIGHT:
        High IPI on thin liquidity can be noise.
        Institutional crashes require BOTH pressure AND disappearing bids.
        
        Formula: quote_depth_ratio = bid_size / rolling_avg_bid_size
        
        Interpretation (READ-ONLY - does NOT change IPI):
        - > 0.7: NORMAL - Liquidity adequate
        - 0.5 - 0.7: THINNING - Liquidity reducing
        - < 0.5: VACUUM - Liquidity vacuum risk
        """
        await self._init_clients()
        
        data = {}
        ratio = 1.0
        flag = "NORMAL"
        
        try:
            # Get current quote for SPY
            spy_snap = await self.polygon.get_snapshot("SPY")
            
            if spy_snap and "ticker" in spy_snap:
                # Get current bid size
                current_bid_size = spy_snap["ticker"].get("lastQuote", {}).get("S", 0)
                
                # For rolling average, we approximate using typical market conditions
                # Normal SPY bid size is ~500-1000 shares in pre-market
                # During market hours, 2000-5000 is normal
                typical_bid_size = 1000  # Pre-market typical
                
                data["current_bid_size"] = current_bid_size
                data["typical_bid_size"] = typical_bid_size
                
                if typical_bid_size > 0 and current_bid_size > 0:
                    ratio = current_bid_size / typical_bid_size
                    data["ratio"] = ratio
                    
                    # Classify flag
                    if ratio >= 0.7:
                        flag = "NORMAL"
                    elif ratio >= 0.5:
                        flag = "THINNING"
                    else:
                        flag = "VACUUM"
                    
                    data["flag"] = flag
                    data["interpretation"] = f"Bid depth at {ratio:.1f}x normal - {flag}"
                    
        except Exception as e:
            logger.debug(f"Liquidity depth ratio error: {e}")
        
        return ratio, flag, data
    
    def determine_execution_light(
        self,
        regime: MarketRegime,
        tradeability: Tradeability,
        gamma_flip_zone: str,
        flow_quality: str,
        liquidity_flag: str,
        ipi_level: str = "UNKNOWN"  # From EWS: ACT/PREPARE/WATCH/NONE
    ) -> Tuple[str, str]:
        """
        Determine execution light: RED / YELLOW / GREEN.
        
        ARCHITECT-4 FINAL INSIGHT:
        This is DESCRIPTIVE, not PRESCRIPTIVE.
        It reflects STATE, not COMMAND.
        
        Approved Logic:
        - 🔴 RED: High IPI but positive gamma → Wait
        - 🟡 YELLOW: High IPI + fragility but liquidity thin → Small size
        - 🟢 GREEN: High IPI + negative gamma + opening flow → Permission
        
        NO AUTOMATION. NO FORCED TRADE.
        This helps discipline, not replaces it.
        """
        # Start with YELLOW (neutral/selective)
        light = "YELLOW"
        rationale = "Mixed signals - be selective"
        
        # GREEN conditions (permission to deploy puts)
        green_conditions = [
            regime == MarketRegime.RISK_OFF,           # Bearish regime
            tradeability == Tradeability.TREND,        # Negative gamma (trend)
            flow_quality in ["GOOD", "UNKNOWN"],       # Opening flow or unknown
            gamma_flip_zone not in ["KNIFE_EDGE"],     # Not at flip level
            liquidity_flag != "VACUUM"                 # Liquidity present
        ]
        
        # RED conditions (wait, don't deploy)
        red_conditions = [
            regime == MarketRegime.RISK_ON,            # Bullish regime
            gamma_flip_zone == "KNIFE_EDGE" and tradeability == Tradeability.CHOP,  # Fragile + chop
            flow_quality == "WARNING",                 # Closing flow dominant
            liquidity_flag == "VACUUM"                 # No bids
        ]
        
        # Count conditions met
        green_count = sum(1 for c in green_conditions if c)
        red_count = sum(1 for c in red_conditions if c)
        
        # Determine light
        if red_count >= 2:
            light = "RED"
            if regime == MarketRegime.RISK_ON:
                rationale = "RISK-ON regime - puts unfavorable"
            elif liquidity_flag == "VACUUM":
                rationale = "Liquidity vacuum - gappy moves, no exit"
            elif flow_quality == "WARNING":
                rationale = "Closing flow dominant - signals misleading"
            else:
                rationale = "Multiple adverse conditions - wait"
                
        elif green_count >= 4:
            light = "GREEN"
            rationale = "RISK-OFF + TREND + GOOD FLOW - puts permitted"
            
        else:
            light = "YELLOW"
            if tradeability == Tradeability.CHOP:
                rationale = "Choppy conditions - reduce size, be selective"
            elif liquidity_flag == "THINNING":
                rationale = "Liquidity thinning - small size only"
            elif gamma_flip_zone == "FRAGILE":
                rationale = "Fragility zone - heightened risk, be cautious"
            else:
                rationale = "Mixed signals - be selective"
        
        return light, rationale
    
    # =========================================================================
    # TIER 3: CAUSE & AMPLIFIERS
    # =========================================================================
    
    async def get_breadth_score(self) -> Tuple[float, Dict]:
        """
        Score based on sector stress and market breadth.
        
        Checks:
        - Key sector ETFs (XLK, SMH, XLF, IWM)
        - Relative strength/weakness
        
        Returns score 0-1 where:
        - 0.0 = Broad weakness across sectors
        - 0.5 = Mixed
        - 1.0 = Broad strength
        """
        await self._init_clients()
        
        data = {}
        score = 0.5
        
        SECTOR_ETFS = ["XLK", "SMH", "XLF", "IWM", "XLE", "XLV"]
        
        try:
            changes = []
            sector_data = {}
            
            for etf in SECTOR_ETFS:
                try:
                    snap = await self.polygon.get_snapshot(etf)
                    if snap and "ticker" in snap:
                        change = snap["ticker"].get("todaysChangePerc", 0)
                        changes.append(change)
                        sector_data[etf] = change
                except:
                    pass
            
            data["sectors"] = sector_data
            
            if changes:
                avg_change = sum(changes) / len(changes)
                data["avg_sector_change"] = avg_change
                
                # Count positive/negative
                positive = sum(1 for c in changes if c > 0)
                negative = sum(1 for c in changes if c < 0)
                
                data["sectors_positive"] = positive
                data["sectors_negative"] = negative
                
                # Score based on breadth and magnitude
                # Average change maps to score
                score = (avg_change + 2) / 4
                score = max(0, min(1, score))
                
                # Adjust for breadth (unanimous = stronger signal)
                if negative == len(changes):
                    score -= 0.1  # All down = more bearish
                elif positive == len(changes):
                    score += 0.1  # All up = more bullish
                
                score = max(0, min(1, score))
                
                data["interpretation"] = (
                    f"Sectors: {positive}↑ {negative}↓ | Avg: {avg_change:+.2f}%"
                )
                
        except Exception as e:
            logger.debug(f"Breadth score error: {e}")
            
        return score, data
    
    async def get_sentiment_score(self) -> Tuple[float, Dict]:
        """
        Contrarian sentiment score.
        
        WEIGHT ≤ 10% - Used ONLY to fade retail extremes.
        
        When retail is extremely bullish → slightly bearish bias
        When retail is extremely bearish → slightly bullish bias
        
        Returns score 0-1 where:
        - 0.0 = Extreme retail bullishness (contrarian bearish)
        - 0.5 = Neutral
        - 1.0 = Extreme retail bearishness (contrarian bullish)
        """
        await self._init_clients()
        
        data = {}
        score = 0.5  # Default neutral
        
        try:
            # Use options flow put/call ratio as sentiment proxy
            # High P/C = retail fear = contrarian bullish
            # Low P/C = retail greed = contrarian bearish
            
            tide = await self.uw.get_market_tide()
            
            if tide:
                calls = tide.get("calls", {})
                puts = tide.get("puts", {})
                
                call_premium = calls.get("total_premium", 0)
                put_premium = puts.get("total_premium", 0)
                
                if call_premium > 0:
                    pc_ratio = put_premium / call_premium
                    data["put_call_ratio"] = pc_ratio
                    
                    # Contrarian logic:
                    # High P/C (>1.5) = fear = contrarian bullish = high score
                    # Low P/C (<0.7) = greed = contrarian bearish = low score
                    if pc_ratio > 1.5:
                        score = 0.7  # Retail scared → contrarian bullish
                    elif pc_ratio < 0.7:
                        score = 0.3  # Retail greedy → contrarian bearish
                    else:
                        score = 0.5  # Neutral
                    
                    data["interpretation"] = (
                        f"P/C Ratio: {pc_ratio:.2f} - "
                        f"{'Retail fear (fade)' if pc_ratio > 1.3 else 'Retail greed (fade)' if pc_ratio < 0.8 else 'Neutral'}"
                    )
                    
        except Exception as e:
            logger.debug(f"Sentiment score error: {e}")
            
        return score, data
    
    # =========================================================================
    # MAIN ANALYSIS
    # =========================================================================
    
    async def analyze(self) -> MarketPulseResult:
        """
        Run MarketPulse analysis.
        
        Returns regime classification with honest confidence bounds.
        """
        await self._init_clients()
        
        logger.info("=" * 60)
        logger.info("MARKETPULSE PRE-MARKET MICROSTRUCTURE ENGINE")
        logger.info("Regime Awareness, Not Prediction")
        logger.info("=" * 60)
        
        notes = []
        raw_data = {}
        
        # Collect all scores
        futures_score, futures_data = await self.get_futures_score()
        raw_data["futures"] = futures_data
        
        vix_score, vix_tradeability, vix_data = await self.get_vix_score()
        raw_data["vix"] = vix_data
        
        gamma_score, gamma_tradeability, gamma_data = await self.get_gamma_score()
        raw_data["gamma"] = gamma_data
        
        breadth_score, breadth_data = await self.get_breadth_score()
        raw_data["breadth"] = breadth_data
        
        sentiment_score, sentiment_data = await self.get_sentiment_score()
        raw_data["sentiment"] = sentiment_data
        
        # =====================================================================
        # ARCHITECT-4 ADDITIONS (Feb 5, 2026) - Read-only context enhancements
        # These enhance context WITHOUT changing scoring behavior
        # =====================================================================
        
        # A1. Distance to Gamma Flip
        logger.info("Calculating gamma flip distance...")
        gamma_flip_distance, gamma_flip_zone, flip_data = await self.get_gamma_flip_distance()
        raw_data["gamma_flip"] = flip_data
        
        # A2. Flow Quality
        logger.info("Assessing flow quality...")
        flow_opening_pct, flow_quality, flow_qual_data = await self.get_flow_quality()
        raw_data["flow_quality"] = flow_qual_data
        
        # A3. Spread Expansion
        logger.info("Checking spread expansion...")
        spread_expansion, spread_flag, spread_data = await self.get_spread_expansion()
        raw_data["spread"] = spread_data
        
        # A4. Expected Move Position
        logger.info("Calculating expected move position...")
        expected_move_pct, open_vs_expected, em_data = await self.get_expected_move_position()
        raw_data["expected_move"] = em_data
        
        # A5. Liquidity Depth Ratio (ARCHITECT-4 FINAL)
        logger.info("Calculating liquidity depth ratio...")
        liquidity_depth_ratio, liquidity_flag, liquidity_data = await self.get_liquidity_depth_ratio()
        raw_data["liquidity"] = liquidity_data
        
        # =====================================================================
        # END ARCHITECT-4 ADDITIONS
        # =====================================================================
        
        # Calculate weighted regime score
        regime_score = (
            futures_score * WEIGHTS["futures"] +
            vix_score * WEIGHTS["vix"] +
            gamma_score * WEIGHTS["gamma"] +
            breadth_score * WEIGHTS["breadth"] +
            sentiment_score * WEIGHTS["sentiment"]
        )
        
        # Classify regime
        if regime_score < 0.40:
            regime = MarketRegime.RISK_OFF
            notes.append("🔴 RISK-OFF regime detected")
        elif regime_score > 0.60:
            regime = MarketRegime.RISK_ON
            notes.append("🟢 RISK-ON regime detected")
        else:
            regime = MarketRegime.NEUTRAL
            notes.append("⚪ NEUTRAL regime - be selective")
        
        # Determine tradeability (gamma takes precedence)
        if gamma_tradeability != Tradeability.UNKNOWN:
            tradeability = gamma_tradeability
        elif vix_tradeability != Tradeability.UNKNOWN:
            tradeability = vix_tradeability
        else:
            tradeability = Tradeability.UNKNOWN
        
        if tradeability == Tradeability.TREND:
            notes.append("📈 TREND environment - directional moves amplified")
        elif tradeability == Tradeability.CHOP:
            notes.append("📊 CHOP environment - expect mean reversion")
        
        # Calculate confidence (HONEST bounds)
        # Base confidence from score extremity
        score_distance = abs(regime_score - 0.5)
        base_confidence = 50 + (score_distance * 30)  # 50-65% range
        
        # Adjust for signal agreement
        signals_bearish = sum([
            futures_score < 0.4,
            vix_score < 0.4,
            gamma_score < 0.4,
            breadth_score < 0.4
        ])
        signals_bullish = sum([
            futures_score > 0.6,
            vix_score > 0.6,
            gamma_score > 0.6,
            breadth_score > 0.6
        ])
        
        if signals_bearish >= 3 or signals_bullish >= 3:
            base_confidence += 5  # Agreement bonus
            notes.append("✅ Strong signal agreement")
        
        confidence_pct = min(base_confidence, 70)  # Cap at 70% - HONEST
        
        if confidence_pct >= 60:
            confidence = Confidence.HIGH
        elif confidence_pct >= 55:
            confidence = Confidence.MEDIUM
        else:
            confidence = Confidence.LOW
        
        # Add key observations
        if futures_data.get("relative_weakness", 0) < -0.5:
            notes.append("⚠️ QQQ underperforming SPY - tech leading weakness")
        
        if vix_data.get("vix_spike"):
            notes.append("⚠️ VIX spiking - fear increasing")
        
        if gamma_data.get("gamma_regime") == "NEGATIVE (trend amplification)":
            notes.append("⚠️ Negative gamma - moves will be amplified")
        
        # ARCHITECT-4: Add context notes (read-only)
        if gamma_flip_zone == "KNIFE_EDGE":
            notes.append("🔪 KNIFE-EDGE: Price near gamma flip - extreme fragility")
        elif gamma_flip_zone == "FRAGILE":
            notes.append("⚠️ FRAGILE: Price in gamma flip zone - heightened risk")
        
        if flow_quality == "WARNING":
            notes.append("⚠️ FLOW WARNING: Majority closing transactions - signals may be misleading")
        
        if spread_flag == "DANGEROUS":
            notes.append("🚨 SPREAD DANGER: Extreme widening - discontinuous moves likely")
        elif spread_flag == "WIDE":
            notes.append("⚠️ Spreads wide: Reduced liquidity - gap risk elevated")
        
        if open_vs_expected == "OUTSIDE":
            notes.append("🚨 OUTSIDE EXPECTED MOVE: Dealer re-hedge risk at open")
        
        # Calculate sample confidence and certainty gap
        historical_matches, sample_confidence = self.get_sample_confidence(regime_score, tradeability)
        
        # Try to load prior score for certainty gap
        prior_score = None
        try:
            prior_file = Path("logs/market_direction.json")
            if prior_file.exists():
                with open(prior_file, 'r') as f:
                    prior_data = json.load(f)
                    prior_score = prior_data.get("regime_score")
        except:
            pass
        
        score_delta, certainty_gap = self.get_certainty_gap(regime_score, prior_score)
        
        if certainty_gap == "VOLATILE":
            notes.append("📊 VOLATILE CERTAINTY: Large score change from prior run")
        
        # Add liquidity depth note
        if liquidity_flag == "VACUUM":
            notes.append("🚨 LIQUIDITY VACUUM: Bids disappearing - gappy moves, no exit")
        elif liquidity_flag == "THINNING":
            notes.append("⚠️ LIQUIDITY THINNING: Bid depth reducing - reduce size")
        
        # ARCHITECT-4 FINAL: Determine Execution Light
        execution_light, execution_rationale = self.determine_execution_light(
            regime=regime,
            tradeability=tradeability,
            gamma_flip_zone=gamma_flip_zone,
            flow_quality=flow_quality,
            liquidity_flag=liquidity_flag
        )
        
        if execution_light == "RED":
            notes.append(f"🔴 EXECUTION: RED - {execution_rationale}")
        elif execution_light == "GREEN":
            notes.append(f"🟢 EXECUTION: GREEN - {execution_rationale}")
        else:
            notes.append(f"🟡 EXECUTION: YELLOW - {execution_rationale}")
        
        # Generate conditional picks (ONLY if risk-off + trend)
        conditional_picks = []
        if regime == MarketRegime.RISK_OFF and tradeability == Tradeability.TREND:
            conditional_picks = await self._generate_conditional_picks(raw_data)
            notes.append(f"🎯 {len(conditional_picks)} conditional put candidates identified")
        elif regime == MarketRegime.RISK_OFF:
            notes.append("⏸️ Risk-off but CHOP expected - be patient")
        elif regime == MarketRegime.RISK_ON:
            notes.append("⚠️ Risk-on regime - avoid new put positions")
        
        result = MarketPulseResult(
            timestamp=datetime.now(),
            regime=regime,
            regime_score=regime_score,
            confidence=confidence,
            confidence_pct=confidence_pct,
            tradeability=tradeability,
            futures_score=futures_score,
            vix_score=vix_score,
            gamma_score=gamma_score,
            breadth_score=breadth_score,
            sentiment_score=sentiment_score,
            # ARCHITECT-4 ADDITIONS
            gamma_flip_distance=gamma_flip_distance,
            gamma_flip_zone=gamma_flip_zone,
            prior_score=prior_score,
            score_delta=score_delta,
            certainty_gap=certainty_gap,
            flow_opening_pct=flow_opening_pct,
            flow_quality=flow_quality,
            spread_expansion=spread_expansion,
            spread_flag=spread_flag,
            expected_move_pct=expected_move_pct,
            open_vs_expected=open_vs_expected,
            historical_matches=historical_matches,
            sample_confidence=sample_confidence,
            # ARCHITECT-4 FINAL ADDITIONS
            liquidity_depth_ratio=liquidity_depth_ratio,
            liquidity_flag=liquidity_flag,
            execution_light=execution_light,
            execution_rationale=execution_rationale,
            # Original fields
            notes=notes,
            conditional_picks=conditional_picks,
            raw_data=raw_data
        )
        
        # Log results
        logger.info(f"REGIME: {regime.value}")
        logger.info(f"SCORE: {regime_score:.2f}")
        logger.info(f"CONFIDENCE: {confidence_pct:.0f}% ({confidence.value})")
        logger.info(f"TRADEABILITY: {tradeability.value}")
        logger.info("=" * 60)
        
        return result
    
    async def _generate_conditional_picks(self, raw_data: Dict) -> List[Dict]:
        """
        Generate conditional put candidates.
        
        ONLY called when:
        - Risk-Off >= 0.60
        - Tradeability = TREND
        
        Picks are SYMBOLS ONLY, not strikes.
        Structure delegated to existing Vega Gate.
        """
        picks = []
        
        # Get weak sectors
        sectors = raw_data.get("breadth", {}).get("sectors", {})
        
        # Find weakest sector ETF
        if sectors:
            weakest = min(sectors.items(), key=lambda x: x[1])
            if weakest[1] < -0.5:
                picks.append({
                    "symbol": weakest[0],
                    "reason": f"Weakest sector ETF ({weakest[1]:+.2f}%)",
                    "type": "sector_weakness"
                })
        
        # Add high-beta names from weak sectors
        WEAK_SECTOR_STOCKS = {
            "XLK": ["NVDA", "AMD", "MSFT"],
            "SMH": ["NVDA", "AMD", "AVGO", "MU"],
            "XLF": ["JPM", "GS", "BAC"],
            "IWM": ["COIN", "MARA", "RIOT"],
        }
        
        for etf, change in sectors.items():
            if change < -0.5 and etf in WEAK_SECTOR_STOCKS:
                for stock in WEAK_SECTOR_STOCKS[etf][:2]:
                    picks.append({
                        "symbol": stock,
                        "reason": f"High-beta in weak sector {etf} ({change:+.2f}%)",
                        "type": "sector_beta"
                    })
        
        # Always include SPY/QQQ if risk-off
        spy_change = raw_data.get("futures", {}).get("spy_change", 0)
        qqq_change = raw_data.get("futures", {}).get("qqq_change", 0)
        
        if qqq_change < spy_change - 0.3:
            picks.append({
                "symbol": "QQQ",
                "reason": f"Tech underperforming ({qqq_change:+.2f}% vs SPY {spy_change:+.2f}%)",
                "type": "index_weakness"
            })
        
        if spy_change < -0.3:
            picks.append({
                "symbol": "SPY",
                "reason": f"Broad market weakness ({spy_change:+.2f}%)",
                "type": "index_weakness"
            })
        
        # Deduplicate and limit to 8
        seen = set()
        unique_picks = []
        for pick in picks:
            if pick["symbol"] not in seen:
                seen.add(pick["symbol"])
                unique_picks.append(pick)
        
        return unique_picks[:8]


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def run_market_pulse() -> MarketPulseResult:
    """Run MarketPulse analysis."""
    engine = MarketPulseEngine()
    try:
        return await engine.analyze()
    finally:
        await engine.close()


def format_result(result: MarketPulseResult) -> str:
    """Format result for display."""
    lines = []
    lines.append("=" * 60)
    lines.append("🌊 MARKETPULSE - PRE-MARKET REGIME AWARENESS")
    lines.append(f"   Time: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S ET')}")
    lines.append("=" * 60)
    
    # Regime
    regime_emoji = {
        MarketRegime.RISK_OFF: "🔴",
        MarketRegime.NEUTRAL: "⚪",
        MarketRegime.RISK_ON: "🟢",
    }
    
    lines.append(f"\n{regime_emoji.get(result.regime, '⚪')} REGIME: {result.regime.value}")
    lines.append(f"📊 SCORE: {result.regime_score:.2f} (0=risk-off, 1=risk-on)")
    lines.append(f"📈 CONFIDENCE: {result.confidence_pct:.0f}% ({result.confidence.value})")
    lines.append(f"🎯 TRADEABILITY: {result.tradeability.value}")
    
    lines.append("\n" + "-" * 60)
    lines.append("COMPONENT SCORES (weighted)")
    lines.append("-" * 60)
    lines.append(f"  Futures (30%):   {result.futures_score:.2f}")
    lines.append(f"  VIX (25%):       {result.vix_score:.2f}")
    lines.append(f"  Gamma (20%):     {result.gamma_score:.2f}")
    lines.append(f"  Breadth (15%):   {result.breadth_score:.2f}")
    lines.append(f"  Sentiment (10%): {result.sentiment_score:.2f}")
    
    lines.append("\n" + "-" * 60)
    lines.append("KEY OBSERVATIONS")
    lines.append("-" * 60)
    for note in result.notes:
        lines.append(f"  {note}")
    
    if result.conditional_picks:
        lines.append("\n" + "-" * 60)
        lines.append("CONDITIONAL PUT CANDIDATES (symbols only)")
        lines.append("-" * 60)
        for i, pick in enumerate(result.conditional_picks, 1):
            lines.append(f"  {i}. {pick['symbol']:6} - {pick['reason']}")
        lines.append("\n  ⚠️ Structure selection delegated to Vega Gate")
        lines.append("  ⚠️ These are NOT trade recommendations")
    
    lines.append("\n" + "=" * 60)
    lines.append("DISCLAIMER: This is regime awareness, not prediction.")
    lines.append("Edge: 52-58% opening direction, NOT full-day direction.")
    lines.append("=" * 60)
    
    return "\n".join(lines)


async def analyze_market_direction(polygon=None, uw=None):
    """
    Compatibility wrapper for scheduler integration.
    Uses new MarketPulse engine internally.
    """
    engine = MarketPulseEngine()
    if polygon:
        engine.polygon = polygon
    if uw:
        engine.uw = uw
    
    try:
        result = await engine.analyze()
        
        # Save to file
        output_file = Path("logs/market_direction.json")
        output_file.parent.mkdir(exist_ok=True)
        
        with open(output_file, "w") as f:
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
                # ARCHITECT-4 ADDITIONS
                "gamma_flip_distance": result.gamma_flip_distance,
                "gamma_flip_zone": result.gamma_flip_zone,
                "prior_score": result.prior_score,
                "score_delta": result.score_delta,
                "certainty_gap": result.certainty_gap,
                "flow_opening_pct": result.flow_opening_pct,
                "flow_quality": result.flow_quality,
                "spread_expansion": result.spread_expansion,
                "spread_flag": result.spread_flag,
                "expected_move_pct": result.expected_move_pct,
                "open_vs_expected": result.open_vs_expected,
                "historical_matches": result.historical_matches,
                "sample_confidence": result.sample_confidence,
                # ARCHITECT-4 FINAL ADDITIONS
                "liquidity_depth_ratio": result.liquidity_depth_ratio,
                "liquidity_flag": result.liquidity_flag,
                "execution_light": result.execution_light,
                "execution_rationale": result.execution_rationale,
                # Original fields
                "notes": result.notes,
                "conditional_picks": result.conditional_picks,
                "raw_data": result.raw_data,
                # Legacy fields for compatibility
                "direction": result.regime.value,
                "spy_signal": result.raw_data.get("futures", {}).get("spy_change", 0),
                "qqq_signal": result.raw_data.get("futures", {}).get("qqq_change", 0),
                "vix_signal": result.raw_data.get("vix", {}).get("vix_level", 20),
                "gex_regime": result.raw_data.get("gamma", {}).get("gamma_regime", "NEUTRAL"),
                "gex_value": result.raw_data.get("gamma", {}).get("gex_value", 0),
                "dark_pool_signal": 0,
                "put_call_ratio": result.raw_data.get("sentiment", {}).get("put_call_ratio", 1),
                "best_plays": result.conditional_picks,
                "avoid_plays": [] if result.regime == MarketRegime.RISK_OFF else [{"symbol": "PUTS", "reason": "Wrong regime"}]
            }, f, indent=2, default=str)
        
        logger.info(f"MarketPulse results saved to {output_file}")
        
        # Print formatted output
        print(format_result(result))
        
        return result
        
    finally:
        if not polygon and not uw:
            await engine.close()


if __name__ == "__main__":
    asyncio.run(analyze_market_direction())
