"""
Market Regime Layer - Layer 1 in the PUT detection pipeline.

This layer acts as a binary kill-switch for the entire engine.
If market regime conditions are not met, NO trades are taken.

Required conditions (ALL must be true):
- SPY/QQQ below VWAP or failed reclaim
- Index Net GEX <= neutral
- VIX rising or VVIX rising

Absolute blockers (ANY one blocks):
- Index pinned (strong +GEX)
- Heavy passive inflows (end-month, rebalance)
- Buyback window active (mega-caps)
"""

from datetime import datetime, date, timedelta
from typing import Optional, List, Tuple
from loguru import logger

from putsengine.config import EngineConfig, Settings
from putsengine.models import (
    MarketRegimeData, MarketRegime, BlockReason, PriceBar, GEXData
)
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient


class MarketRegimeLayer:
    """
    Market Regime Analysis Layer.

    This is the FIRST and most important gate. If market regime
    is not favorable for puts, the engine stops here.

    Rule: Never short single names against a pinned index.
    """

    def __init__(
        self,
        alpaca: AlpacaClient,
        polygon: PolygonClient,
        unusual_whales: UnusualWhalesClient,
        settings: Settings
    ):
        self.alpaca = alpaca
        self.polygon = polygon
        self.unusual_whales = unusual_whales
        self.settings = settings
        self.config = EngineConfig

    async def analyze(self) -> MarketRegimeData:
        """
        Perform complete market regime analysis.

        Returns:
            MarketRegimeData with regime classification and tradability flag.
        """
        logger.info("Analyzing market regime...")

        # Gather data for all index symbols
        spy_data = await self._analyze_index("SPY")
        qqq_data = await self._analyze_index("QQQ")

        # Get VIX data
        vix_level, vix_change = await self._get_vix_data()

        # Get market-wide GEX
        index_gex = await self._get_index_gex()

        # Check for blockers
        block_reasons = []
        
        # Track passive inflow for reporting
        is_passive_window, passive_reason = self._is_passive_inflow_window()

        # Blocker: Positive GEX (index pinned)
        if index_gex > self.config.GEX_NEUTRAL_THRESHOLD * 1.5:
            block_reasons.append(BlockReason.POSITIVE_GEX)
            logger.warning(f"BLOCKED: Positive GEX regime ({index_gex:,.0f})")

        # Blocker: Index pinned (SPY and QQQ both above VWAP with low vol)
        if spy_data[0] and qqq_data[0]:  # Both above VWAP
            block_reasons.append(BlockReason.INDEX_PINNED)
            logger.warning("BLOCKED: Index appears pinned (SPY & QQQ above VWAP)")

        # Blocker: Passive inflow window (HARD BLOCK per Architect)
        # "Never short against systematic inflows. You are fighting a machine."
        if is_passive_window:
            block_reasons.append(BlockReason.PASSIVE_INFLOW_WINDOW)
            logger.warning(f"BLOCKED: Passive inflow window ({passive_reason})")

        # Determine regime
        regime = self._classify_regime(
            spy_below_vwap=not spy_data[0],
            qqq_below_vwap=not qqq_data[0],
            index_gex=index_gex,
            vix_change=vix_change
        )

        # Tradeable only if:
        # 1. No block reasons
        # 2. At least one index below VWAP
        # 3. VIX stable or rising
        is_tradeable = (
            len(block_reasons) == 0 and
            (not spy_data[0] or not qqq_data[0]) and  # At least one below VWAP
            vix_change >= -0.05  # VIX not collapsing
        )

        if not is_tradeable and not block_reasons:
            block_reasons.append(BlockReason.INDEX_PINNED)

        result = MarketRegimeData(
            timestamp=datetime.now(),
            regime=regime,
            spy_below_vwap=not spy_data[0],
            qqq_below_vwap=not qqq_data[0],
            index_gex=index_gex,
            vix_level=vix_level,
            vix_change=vix_change,
            is_tradeable=is_tradeable,
            block_reasons=block_reasons,
            # New fields per Architect
            is_passive_inflow_window=is_passive_window,
            passive_inflow_reason=passive_reason,
            below_zero_gamma=index_gex < 0
        )

        logger.info(
            f"Market regime: {regime.value}, "
            f"Tradeable: {is_tradeable}, "
            f"SPY<VWAP: {result.spy_below_vwap}, "
            f"QQQ<VWAP: {result.qqq_below_vwap}, "
            f"GEX: {index_gex:,.0f}, "
            f"VIX: {vix_level:.2f} ({vix_change:+.2%})"
        )

        return result

    async def _analyze_index(self, symbol: str) -> Tuple[bool, float, float]:
        """
        Analyze a single index symbol.

        Returns:
            Tuple of (is_above_vwap, current_price, vwap)
        """
        try:
            # Get intraday bars for VWAP calculation
            bars = await self.polygon.get_minute_bars(
                symbol=symbol,
                from_date=date.today(),
                limit=500
            )

            if not bars:
                # Fallback to daily bar
                daily_bars = await self.polygon.get_daily_bars(
                    symbol=symbol,
                    from_date=date.today() - timedelta(days=5)
                )
                if daily_bars:
                    last_bar = daily_bars[-1]
                    return (True, last_bar.close, last_bar.vwap or last_bar.close)
                return (True, 0.0, 0.0)  # Default to above VWAP if no data

            # Calculate VWAP if not provided
            current_price = bars[-1].close
            vwap = self._calculate_vwap(bars)

            is_above_vwap = current_price > vwap

            logger.debug(
                f"{symbol}: Price={current_price:.2f}, VWAP={vwap:.2f}, "
                f"{'Above' if is_above_vwap else 'Below'} VWAP"
            )

            return (is_above_vwap, current_price, vwap)

        except Exception as e:
            logger.error(f"Error analyzing index {symbol}: {e}")
            return (True, 0.0, 0.0)  # Default to above VWAP on error

    def _calculate_vwap(self, bars: List[PriceBar]) -> float:
        """Calculate VWAP from price bars."""
        if not bars:
            return 0.0

        # Use provided VWAP if available
        if bars[-1].vwap and bars[-1].vwap > 0:
            return bars[-1].vwap

        # Calculate manually
        total_volume = 0
        total_vwap = 0.0

        for bar in bars:
            typical_price = (bar.high + bar.low + bar.close) / 3
            total_vwap += typical_price * bar.volume
            total_volume += bar.volume

        if total_volume > 0:
            return total_vwap / total_volume
        return bars[-1].close

    async def _get_vix_data(self) -> Tuple[float, float]:
        """
        Get VIX level and change.

        Returns:
            Tuple of (current_level, percent_change)
        """
        try:
            # Get VIX bars
            bars = await self.polygon.get_daily_bars(
                symbol="VIX",
                from_date=date.today() - timedelta(days=10)
            )

            if not bars or len(bars) < 2:
                # Try VIXY as proxy
                bars = await self.polygon.get_daily_bars(
                    symbol="VIXY",
                    from_date=date.today() - timedelta(days=10)
                )

            if bars and len(bars) >= 2:
                current = bars[-1].close
                previous = bars[-2].close
                change = (current - previous) / previous if previous > 0 else 0
                return (current, change)

            return (20.0, 0.0)  # Default values

        except Exception as e:
            logger.error(f"Error getting VIX data: {e}")
            return (20.0, 0.0)

    async def _get_index_gex(self) -> float:
        """
        Get aggregate Gamma Exposure for major indices.

        Positive GEX = dealers long gamma = will buy dips, sell rips
        Negative GEX = dealers short gamma = will amplify moves
        """
        total_gex = 0.0

        for symbol in ["SPY", "QQQ"]:
            try:
                gex_data = await self.unusual_whales.get_gex_data(symbol)
                if gex_data:
                    total_gex += gex_data.net_gex
            except Exception as e:
                logger.warning(f"Error getting GEX for {symbol}: {e}")

        return total_gex

    def _is_passive_inflow_window(self) -> tuple:
        """
        Check if we're in a passive inflow window.
        
        Per Final Architect Report:
        "Never short against systematic inflows. You are fighting a machine."

        These are periods when passive funds rebalance and
        tend to buy equities regardless of conditions:
        - Day 1-3 of month (month start inflows)
        - Day 28-31 of month (month end rebalance)
        - Quarter end (March, June, September, December)
        
        Returns:
            Tuple of (is_passive_window, reason_string)
        """
        today = date.today()
        
        # Day 1-3: Month start inflows
        if today.day <= 3:
            reason = f"month_start (Day {today.day})"
            logger.warning(f"PASSIVE INFLOW: {reason} - systematic buying expected")
            return (True, reason)

        # Day 28-31: Month end rebalance
        if today.day >= 28:
            reason = f"month_end (Day {today.day})"
            logger.warning(f"PASSIVE INFLOW: {reason} - rebalance flows expected")
            return (True, reason)

        # Quarter end: Larger rebalances (March, June, September, December)
        if today.month in [3, 6, 9, 12] and today.day >= 25:
            reason = f"quarter_end (Month {today.month}, Day {today.day})"
            logger.warning(f"PASSIVE INFLOW: {reason} - large institutional rebalance")
            return (True, reason)

        return (False, "")

    def _classify_regime(
        self,
        spy_below_vwap: bool,
        qqq_below_vwap: bool,
        index_gex: float,
        vix_change: float
    ) -> MarketRegime:
        """
        Classify the current market regime.

        Returns:
            MarketRegime enum value
        """
        # Check for pinned market
        if not spy_below_vwap and not qqq_below_vwap and index_gex > 0:
            return MarketRegime.PINNED

        # Bearish expansion: Both indices weak, negative GEX, VIX rising
        if (spy_below_vwap and qqq_below_vwap and
            index_gex < 0 and vix_change > 0.05):
            return MarketRegime.BEARISH_EXPANSION

        # Bearish neutral: Some weakness but not full expansion
        if (spy_below_vwap or qqq_below_vwap) and index_gex <= 0:
            return MarketRegime.BEARISH_NEUTRAL

        # Bullish expansion: Both indices strong, positive GEX
        if (not spy_below_vwap and not qqq_below_vwap and
            index_gex > 0 and vix_change < -0.05):
            return MarketRegime.BULLISH_EXPANSION

        # Bullish neutral
        if not spy_below_vwap and not qqq_below_vwap:
            return MarketRegime.BULLISH_NEUTRAL

        return MarketRegime.NEUTRAL

    async def check_buyback_window(self, symbol: str) -> bool:
        """
        Check if a specific stock is in a buyback blackout window.

        Companies typically cannot buy back shares:
        - 2 weeks before earnings
        - Until 48 hours after earnings

        This is a simplified check - production would use
        actual earnings calendar data.
        """
        # This would require earnings calendar API
        # For now, we'll use a heuristic based on typical patterns
        return False

    async def is_tradeable_for_puts(self) -> Tuple[bool, List[BlockReason]]:
        """
        Quick check if market regime allows put trading.

        Returns:
            Tuple of (is_tradeable, list_of_block_reasons)
        """
        regime_data = await self.analyze()
        return (regime_data.is_tradeable, regime_data.block_reasons)
