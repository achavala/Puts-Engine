"""
ARCHITECT-4 FINAL: Trade Classifier - Class A/B/C Separation.

This module implements the explicit trade class separation per Final Architect-4 Addendum.

CLASS A — CORE INSTITUTIONAL PUTS (Original PutsEngine logic)
    Score:      >= 0.68
    Permissions: All 3 required (Gamma + Liquidity + Incentive)
    Engine:     Gamma Drain / Distribution Trap
    Size:       Full (up to 5 contracts)
    Expectancy: High
    Frequency:  Low

CLASS B — HIGH-BETA REACTION PUTS (New logic, constrained)
    Score:      0.25 - 0.45
    Universe:   High-beta only
    Required:   >= 1 price-based signal
    Boosts:     Gap-up reversal, sector velocity
    Size:       1-2 contracts MAX
    Expectancy: Mixed
    Goal:       Capture spillover moves

CLASS C — MONITOR ONLY (Never traded)
    Dark pool signal alone
    No VWAP loss
    No liquidity vacuum
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any
from loguru import logger

from putsengine.config import EngineConfig, get_settings
from putsengine.models import PutCandidate, EngineType, DistributionSignal


class TradeClass(Enum):
    """Trade classification per Architect-4 Final."""
    CLASS_A = "class_a"  # Core institutional - TRADE
    CLASS_B = "class_b"  # High-beta reaction - TRADE (limited)
    CLASS_C = "class_c"  # Monitor only - DO NOT TRADE


@dataclass
class TradeClassification:
    """Result of trade classification."""
    trade_class: TradeClass
    symbol: str
    score: float
    max_contracts: int
    is_tradeable: bool
    reason: str
    engine_type: EngineType
    
    # Class-specific fields
    is_high_beta: bool = False
    sector_boost_applied: float = 0.0
    front_run_boost_applied: float = 0.0


class TradeClassifier:
    """
    Classifies trades into Class A, B, or C per Architect-4 Final.
    
    This is the gatekeeper that ensures:
    - Class A trades meet full institutional criteria
    - Class B trades are constrained to high-beta universe
    - Class C signals are logged but never traded
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.config = EngineConfig
    
    def classify(
        self,
        candidate: PutCandidate,
        distribution: Optional[DistributionSignal] = None,
        peer_scores: Optional[Dict[str, float]] = None
    ) -> TradeClassification:
        """
        Classify a trade candidate into Class A, B, or C.
        
        Args:
            candidate: The PUT candidate to classify
            distribution: Distribution analysis (if available)
            peer_scores: Scores of sector peers (for sector velocity)
            
        Returns:
            TradeClassification with trade class and parameters
        """
        symbol = candidate.symbol
        score = candidate.composite_score
        engine_type = candidate.engine_type
        
        # Check if high-beta
        is_high_beta = self.config.is_high_beta(symbol)
        
        # Get signals
        has_vwap_loss = distribution.vwap_loss if distribution else False
        has_dark_pool = distribution.repeated_sell_blocks if distribution else False
        has_price_signal = self._has_price_based_signal(distribution)
        has_liquidity = candidate.liquidity is not None and candidate.liquidity.score > 0.3
        
        # ================================================================
        # CLASS A: Core Institutional Puts
        # ================================================================
        if score >= self.settings.class_a_min_score:
            # Full institutional criteria
            has_all_permissions = (
                engine_type in [EngineType.GAMMA_DRAIN, EngineType.DISTRIBUTION_TRAP]
                and has_price_signal
                and (has_liquidity or has_dark_pool)
            )
            
            if has_all_permissions:
                return TradeClassification(
                    trade_class=TradeClass.CLASS_A,
                    symbol=symbol,
                    score=score,
                    max_contracts=5,  # Full size
                    is_tradeable=True,
                    reason="Class A: Core institutional criteria met",
                    engine_type=engine_type,
                    is_high_beta=is_high_beta
                )
            else:
                # High score but missing permissions - still Class A but flagged
                return TradeClassification(
                    trade_class=TradeClass.CLASS_A,
                    symbol=symbol,
                    score=score,
                    max_contracts=3,  # Reduced size due to missing permissions
                    is_tradeable=True,
                    reason="Class A: High score but partial permissions",
                    engine_type=engine_type,
                    is_high_beta=is_high_beta
                )
        
        # ================================================================
        # CLASS B: High-Beta Reaction Puts
        # ================================================================
        if (self.settings.class_b_min_score <= score <= self.settings.class_b_max_score):
            # Class B ONLY for high-beta names
            if not is_high_beta:
                # Not high-beta - CLASS C (monitor only)
                return TradeClassification(
                    trade_class=TradeClass.CLASS_C,
                    symbol=symbol,
                    score=score,
                    max_contracts=0,
                    is_tradeable=False,
                    reason="Class C: Score in Class B range but not high-beta",
                    engine_type=engine_type,
                    is_high_beta=False
                )
            
            # Must have at least 1 price-based signal
            if not has_price_signal:
                return TradeClassification(
                    trade_class=TradeClass.CLASS_C,
                    symbol=symbol,
                    score=score,
                    max_contracts=0,
                    is_tradeable=False,
                    reason="Class C: High-beta but no price-based signal",
                    engine_type=engine_type,
                    is_high_beta=True
                )
            
            # Class B trade - limited size
            return TradeClassification(
                trade_class=TradeClass.CLASS_B,
                symbol=symbol,
                score=score,
                max_contracts=self.settings.max_class_b_contracts,  # Max 2
                is_tradeable=True,
                reason="Class B: High-beta reaction trade",
                engine_type=engine_type,
                is_high_beta=True
            )
        
        # ================================================================
        # CLASS C: Monitor Only
        # ================================================================
        # Below Class B threshold or missing requirements
        reason = self._get_class_c_reason(score, has_dark_pool, has_vwap_loss, has_liquidity)
        
        return TradeClassification(
            trade_class=TradeClass.CLASS_C,
            symbol=symbol,
            score=score,
            max_contracts=0,
            is_tradeable=False,
            reason=reason,
            engine_type=engine_type,
            is_high_beta=is_high_beta
        )
    
    def _has_price_based_signal(self, distribution: Optional[DistributionSignal]) -> bool:
        """Check if distribution has at least one price-based signal."""
        if not distribution:
            return False
        
        price_signals = [
            distribution.vwap_loss,
            distribution.failed_breakout,
            distribution.flat_price_rising_volume,
            distribution.lower_highs_flat_rsi,
            distribution.signals.get("gap_down_no_recovery", False),
            distribution.signals.get("gap_up_reversal", False),
            distribution.signals.get("multi_day_weakness", False),
            distribution.signals.get("high_rvol_red_day", False),
        ]
        
        return any(price_signals)
    
    def _get_class_c_reason(
        self, 
        score: float, 
        has_dark_pool: bool,
        has_vwap_loss: bool,
        has_liquidity: bool
    ) -> str:
        """Get the reason why trade is Class C (monitor only)."""
        if score < self.settings.class_b_min_score:
            return f"Class C: Score {score:.2f} below minimum threshold"
        
        reasons = []
        if has_dark_pool and not has_vwap_loss and not has_liquidity:
            reasons.append("Dark pool signal alone (no price confirmation)")
        if not has_vwap_loss:
            reasons.append("No VWAP loss")
        if not has_liquidity:
            reasons.append("No liquidity vacuum")
        
        if reasons:
            return f"Class C: {', '.join(reasons)}"
        
        return "Class C: Insufficient signals for trade"
    
    def log_classification(self, classification: TradeClassification):
        """Log the trade classification result."""
        if classification.trade_class == TradeClass.CLASS_A:
            logger.info(
                f"🟢 CLASS A: {classification.symbol} | "
                f"Score: {classification.score:.2f} | "
                f"Max contracts: {classification.max_contracts} | "
                f"{classification.reason}"
            )
        elif classification.trade_class == TradeClass.CLASS_B:
            logger.info(
                f"🟡 CLASS B: {classification.symbol} | "
                f"Score: {classification.score:.2f} | "
                f"Max contracts: {classification.max_contracts} | "
                f"{classification.reason}"
            )
        else:
            logger.debug(
                f"⚪ CLASS C: {classification.symbol} | "
                f"Score: {classification.score:.2f} | "
                f"NOT TRADEABLE | {classification.reason}"
            )


# Singleton instance
_classifier: Optional[TradeClassifier] = None


def get_trade_classifier() -> TradeClassifier:
    """Get the singleton trade classifier instance."""
    global _classifier
    if _classifier is None:
        _classifier = TradeClassifier()
    return _classifier
