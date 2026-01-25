"""
Put Scoring Model - Final scoring for PUT candidates.

LOCKED WEIGHTS per Final Architect Report (DO NOT MODIFY):

| Component                        | Weight     |
| -------------------------------- | ---------- |
| Distribution Quality             | 30%        |
| Dealer Positioning (GEX / Delta) | 20%        |
| Liquidity Vacuum                 | 15%        |
| Options Flow Quality             | 15%        |
| Catalyst Proximity               | 10%        |
| Sentiment / Technical            | 10%        |
| Risk Gates                       | HARD BLOCK |

Minimum actionable score: 0.68
If score is 0.67 -> NO TRADE

"Only score AFTER all gates pass. Gates are binary, score is continuous."
"""

from datetime import datetime, date
from typing import Optional, List, Dict
from loguru import logger

from putsengine.config import EngineConfig, Settings
from putsengine.models import (
    PutCandidate, DistributionSignal, LiquidityVacuum,
    AccelerationWindow, GEXData, BlockReason
)


class PutScorer:
    """
    PUT Candidate Scoring Engine.

    This module combines all layer outputs into a final
    composite score that determines trade actionability.

    Key principle: The score is only calculated AFTER
    all gates have passed. Gates are binary, score is continuous.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.config = EngineConfig
        self.weights = self.config.SCORE_WEIGHTS
        self.min_threshold = settings.min_score_threshold

    def score_candidate(self, candidate: PutCandidate) -> float:
        """
        Calculate composite score for a PUT candidate.

        Args:
            candidate: PutCandidate with all layer analysis populated

        Returns:
            Composite score from 0.0 to 1.0
        """
        logger.debug(f"Scoring candidate: {candidate.symbol}")

        # If any hard blocks exist, return 0
        if candidate.block_reasons:
            logger.info(
                f"{candidate.symbol}: Score=0.00 (blocked: {candidate.block_reasons})"
            )
            return 0.0

        # Calculate individual component scores
        scores = {
            "distribution_quality": self._score_distribution(candidate.distribution),
            "dealer_positioning": candidate.dealer_score,
            "liquidity_vacuum": self._score_liquidity(candidate.liquidity),
            "options_flow": self._score_options_flow(candidate),
            "catalyst_proximity": self._score_catalyst(candidate),
            "sentiment_divergence": self._score_sentiment(candidate),
            "technical_alignment": self._score_technical(candidate)
        }

        # Update candidate with individual scores
        candidate.distribution_score = scores["distribution_quality"]
        candidate.dealer_score = scores["dealer_positioning"]
        candidate.liquidity_score = scores["liquidity_vacuum"]
        candidate.flow_score = scores["options_flow"]
        candidate.catalyst_score = scores["catalyst_proximity"]
        candidate.sentiment_score = scores["sentiment_divergence"]
        candidate.technical_score = scores["technical_alignment"]

        # Calculate weighted composite
        composite = sum(
            scores[key] * self.weights.get(key, 0)
            for key in scores
        )

        # Ensure bounds
        composite = max(0.0, min(1.0, composite))

        logger.info(
            f"{candidate.symbol}: Score={composite:.2f} "
            f"(dist={scores['distribution_quality']:.2f}, "
            f"dealer={scores['dealer_positioning']:.2f}, "
            f"liq={scores['liquidity_vacuum']:.2f}, "
            f"flow={scores['options_flow']:.2f})"
        )

        return composite

    def _score_distribution(
        self,
        distribution: Optional[DistributionSignal]
    ) -> float:
        """
        Score distribution quality (30% weight).
        
        INSTITUTIONAL-GRADE SCORING for -3% to -15% moves:

        Price-Volume Signals (Core - 45% max):
        - HIGH RVOL red day: 0.20 (strongest signal)
        - Gap down no recovery: 0.15
        - Multi-day weakness: 0.12
        - Standard signals: 0.08 each
        
        Returns the distribution score from signals.
        """
        if not distribution:
            return 0.0

        # If score was already calculated, use it
        if distribution.score > 0:
            return distribution.score
        
        # Otherwise, calculate from signals dict
        if not distribution.signals:
            return 0.0
        
        score = 0.0
        signals = distribution.signals
        
        # === PRICE-VOLUME SIGNALS (45% max) ===
        
        # HIGH RVOL red day is the STRONGEST bearish signal
        if signals.get("high_rvol_red_day", False):
            score += 0.20
        
        # Gap down without recovery = trapped longs
        if signals.get("gap_down_no_recovery", False):
            score += 0.15
        
        # Multi-day weakness = sustained pressure
        if signals.get("multi_day_weakness", False):
            score += 0.12
        
        # Standard signals (0.08 each)
        if distribution.flat_price_rising_volume or signals.get("flat_price_rising_volume", False):
            score += 0.08
        if distribution.failed_breakout or signals.get("failed_breakout", False):
            score += 0.08
        if distribution.lower_highs_flat_rsi or signals.get("lower_highs_flat_rsi", False):
            score += 0.08
        if distribution.vwap_loss or signals.get("vwap_loss", False):
            score += 0.08
        
        # === DARK POOL (10%) ===
        if distribution.repeated_sell_blocks or signals.get("repeated_sell_blocks", False):
            score += 0.10
        
        # === INSIDER/CONGRESS BOOSTS ===
        if signals.get("c_level_selling", False):
            score += 0.10
        if signals.get("insider_cluster", False):
            score += 0.06
        if signals.get("congress_selling", False):
            score += 0.04
        
        # === POST-EARNINGS NEGATIVE ===
        if signals.get("is_post_earnings_negative", False):
            score += 0.10
        
        return min(score, 1.0)

    def _score_liquidity(
        self,
        liquidity: Optional[LiquidityVacuum]
    ) -> float:
        """Score liquidity vacuum (15% weight)."""
        if not liquidity:
            return 0.0

        return liquidity.score

    def _score_options_flow(self, candidate: PutCandidate) -> float:
        """
        Score options flow quality (15% weight).

        Based on:
        - Put buying at ask (aggressive)
        - Call selling at bid (bearish)
        - Sweep activity
        - Block trades
        """
        if not candidate.distribution:
            return 0.0

        score = 0.0

        # Put buying at ask
        if candidate.distribution.put_buying_at_ask:
            score += 0.30

        # Call selling at bid
        if candidate.distribution.call_selling_at_bid:
            score += 0.30

        # Rising put OI
        if candidate.distribution.rising_put_oi:
            score += 0.20

        # Skew steepening
        if candidate.distribution.skew_steepening:
            score += 0.20

        return min(score, 1.0)

    def _score_catalyst(self, candidate: PutCandidate) -> float:
        """
        Score catalyst proximity (10% weight).

        Catalysts that can accelerate downside:
        - Post-earnings with negative guidance (+0.3)
        - Insider/Congress selling clusters (+0.2)
        - Recent price weakness (+0.2)
        - High RVOL on down move (+0.3)
        """
        score = 0.0

        # Check distribution signals for catalyst info
        if candidate.distribution and candidate.distribution.signals:
            signals = candidate.distribution.signals
            
            # Post-earnings negative = strong catalyst
            if signals.get("is_post_earnings_negative", False):
                score += 0.35
            
            # C-level selling cluster = medium catalyst
            if signals.get("c_level_selling", False):
                score += 0.25
            elif signals.get("insider_cluster", False):
                score += 0.15
            
            # Congress selling = weak catalyst
            if signals.get("congress_selling", False):
                score += 0.10

        # Check acceleration for timing catalysts
        if candidate.acceleration:
            # Failed reclaim = momentum catalyst
            if candidate.acceleration.failed_reclaim:
                score += 0.15
            
            # Below all key levels = trend catalyst
            if (candidate.acceleration.price_below_vwap and 
                candidate.acceleration.price_below_ema20 and
                candidate.acceleration.price_below_prior_low):
                score += 0.20

        return min(score, 1.0)

    def _score_sentiment(self, candidate: PutCandidate) -> float:
        """
        Score sentiment divergence (5% weight).

        Bearish sentiment signals:
        - Rising put OI while price flat = smart money bearish
        - Skew steepening = puts getting expensive (fear)
        - Call selling = bullishness fading
        - Gamma flipping short = dealers turning bearish
        """
        score = 0.0

        # Options sentiment from distribution
        if candidate.distribution:
            # Rising put OI = institutional bearishness
            if candidate.distribution.rising_put_oi:
                score += 0.30
            
            # Skew steepening = fear increasing
            if candidate.distribution.skew_steepening:
                score += 0.25
            
            # Call selling at bid = bulls exiting
            if candidate.distribution.call_selling_at_bid:
                score += 0.25

        # Dealer sentiment from acceleration
        if candidate.acceleration:
            # Gamma flipping short = dealers turning bearish
            if candidate.acceleration.gamma_flipping_short:
                score += 0.20
            
            # Net delta negative = overall bearish positioning
            if candidate.acceleration.net_delta_negative:
                score += 0.15

        return min(score, 1.0)

    def _score_technical(self, candidate: PutCandidate) -> float:
        """
        Score technical alignment (5% weight).

        Based on acceleration window signals.
        """
        if not candidate.acceleration:
            return 0.0

        score = 0.0

        if candidate.acceleration.price_below_vwap:
            score += 0.25
        if candidate.acceleration.price_below_ema20:
            score += 0.25
        if candidate.acceleration.price_below_prior_low:
            score += 0.25
        if candidate.acceleration.failed_reclaim:
            score += 0.25

        return min(score, 1.0)

    def is_actionable(self, candidate: PutCandidate) -> bool:
        """
        Determine if candidate meets minimum threshold for action.

        Args:
            candidate: Scored PutCandidate

        Returns:
            True if score >= minimum threshold (0.68)
        """
        return candidate.composite_score >= self.min_threshold

    def rank_candidates(
        self,
        candidates: List[PutCandidate]
    ) -> List[PutCandidate]:
        """
        Rank candidates by composite score.

        Args:
            candidates: List of scored candidates

        Returns:
            Candidates sorted by score descending, filtered by threshold
        """
        # Score all candidates
        for candidate in candidates:
            if candidate.composite_score == 0:
                candidate.composite_score = self.score_candidate(candidate)

        # Filter by threshold and sort
        actionable = [c for c in candidates if self.is_actionable(c)]
        actionable.sort(key=lambda x: x.composite_score, reverse=True)

        logger.info(
            f"Ranked {len(actionable)} actionable candidates "
            f"from {len(candidates)} total"
        )

        return actionable

    def get_score_breakdown(
        self,
        candidate: PutCandidate
    ) -> Dict[str, Dict[str, float]]:
        """
        Get detailed score breakdown for a candidate.

        Returns:
            Dict with component scores and weights
        """
        return {
            "components": {
                "distribution_quality": candidate.distribution_score,
                "dealer_positioning": candidate.dealer_score,
                "liquidity_vacuum": candidate.liquidity_score,
                "options_flow": candidate.flow_score,
                "catalyst_proximity": candidate.catalyst_score,
                "sentiment_divergence": candidate.sentiment_score,
                "technical_alignment": candidate.technical_score
            },
            "weights": dict(self.weights),
            "composite": candidate.composite_score,
            "threshold": self.min_threshold,
            "is_actionable": self.is_actionable(candidate)
        }
