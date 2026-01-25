"""
Tests for PutsEngine data models.
"""

import pytest
from datetime import datetime, date

from putsengine.models import (
    PriceBar, OptionsContract, OptionsFlow, PutCandidate,
    DistributionSignal, LiquidityVacuum, AccelerationWindow,
    MarketRegime, BlockReason, TradeSignal
)


class TestPriceBar:
    """Tests for PriceBar model."""

    def test_creation(self):
        bar = PriceBar(
            timestamp=datetime.now(),
            open=100.0,
            high=105.0,
            low=99.0,
            close=103.0,
            volume=1000000
        )
        assert bar.close == 103.0
        assert bar.volume == 1000000

    def test_with_vwap(self):
        bar = PriceBar(
            timestamp=datetime.now(),
            open=100.0,
            high=105.0,
            low=99.0,
            close=103.0,
            volume=1000000,
            vwap=101.5
        )
        assert bar.vwap == 101.5


class TestOptionsContract:
    """Tests for OptionsContract model."""

    def test_creation(self):
        contract = OptionsContract(
            symbol="AAPL240119P00180000",
            underlying="AAPL",
            expiration=date(2024, 1, 19),
            strike=180.0,
            option_type="put",
            bid=2.50,
            ask=2.60,
            last=2.55,
            volume=1000,
            open_interest=5000,
            implied_volatility=0.25,
            delta=-0.30,
            gamma=0.02,
            theta=-0.05,
            vega=0.10,
            dte=14
        )
        assert contract.underlying == "AAPL"
        assert contract.option_type == "put"
        assert contract.delta == -0.30

    def test_mid_price(self):
        contract = OptionsContract(
            symbol="TEST",
            underlying="TEST",
            expiration=date.today(),
            strike=100.0,
            option_type="put",
            bid=2.50,
            ask=2.60,
            last=2.55,
            volume=100,
            open_interest=500,
            implied_volatility=0.25,
            delta=-0.30,
            gamma=0.02,
            theta=-0.05,
            vega=0.10,
            dte=14
        )
        assert contract.mid_price == 2.55

    def test_spread(self):
        contract = OptionsContract(
            symbol="TEST",
            underlying="TEST",
            expiration=date.today(),
            strike=100.0,
            option_type="put",
            bid=2.50,
            ask=2.60,
            last=2.55,
            volume=100,
            open_interest=500,
            implied_volatility=0.25,
            delta=-0.30,
            gamma=0.02,
            theta=-0.05,
            vega=0.10,
            dte=14
        )
        assert contract.spread == 0.10
        assert abs(contract.spread_pct - 0.039215) < 0.001


class TestPutCandidate:
    """Tests for PutCandidate model."""

    def test_creation(self):
        candidate = PutCandidate(
            symbol="AAPL",
            timestamp=datetime.now()
        )
        assert candidate.symbol == "AAPL"
        assert candidate.composite_score == 0.0
        assert candidate.passed_all_gates == False
        assert candidate.block_reasons == []

    def test_score_calculation(self):
        candidate = PutCandidate(
            symbol="AAPL",
            timestamp=datetime.now(),
            distribution_score=0.8,
            dealer_score=0.7,
            liquidity_score=0.6,
            flow_score=0.5,
            catalyst_score=0.5,
            sentiment_score=0.5,
            technical_score=0.4
        )

        weights = {
            "distribution_quality": 0.30,
            "dealer_positioning": 0.20,
            "liquidity_vacuum": 0.15,
            "options_flow": 0.15,
            "catalyst_proximity": 0.10,
            "sentiment_divergence": 0.05,
            "technical_alignment": 0.05
        }

        score = candidate.calculate_composite_score(weights)

        # Manual calculation:
        # 0.8*0.30 + 0.7*0.20 + 0.6*0.15 + 0.5*0.15 + 0.5*0.10 + 0.5*0.05 + 0.4*0.05
        # = 0.24 + 0.14 + 0.09 + 0.075 + 0.05 + 0.025 + 0.02
        # = 0.64
        assert abs(score - 0.64) < 0.01


class TestDistributionSignal:
    """Tests for DistributionSignal model."""

    def test_creation(self):
        signal = DistributionSignal(
            symbol="AAPL",
            timestamp=datetime.now(),
            score=0.75
        )
        assert signal.symbol == "AAPL"
        assert signal.score == 0.75

    def test_signals(self):
        signal = DistributionSignal(
            symbol="AAPL",
            timestamp=datetime.now(),
            score=0.75,
            flat_price_rising_volume=True,
            failed_breakout=True,
            call_selling_at_bid=True
        )
        assert signal.flat_price_rising_volume == True
        assert signal.failed_breakout == True
        assert signal.call_selling_at_bid == True
        assert signal.put_buying_at_ask == False


class TestEnums:
    """Tests for enum types."""

    def test_market_regime(self):
        assert MarketRegime.BEARISH_EXPANSION.value == "bearish_expansion"
        assert MarketRegime.PINNED.value == "pinned"

    def test_block_reason(self):
        assert BlockReason.POSITIVE_GEX.value == "positive_gex_regime"
        assert BlockReason.PUT_WALL_SUPPORT.value == "put_wall_support"

    def test_trade_signal(self):
        assert TradeSignal.STRONG_BEARISH.value == "strong_bearish"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
