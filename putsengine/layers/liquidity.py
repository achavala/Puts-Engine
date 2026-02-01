"""
Liquidity Vacuum Layer - Layer 3 in the PUT detection pipeline.

This is where most PUT engines fail by omission.
It's not enough to have sellers - buyers must STEP AWAY.

Detection signals (at least 1 required):
- Bid size collapsing
- Spread widening
- Volume up but price progress down
- VWAP retest fails twice

Interpretation: Downside accelerates only when liquidity disappears.
"""

from datetime import datetime, date, timedelta
from typing import Optional, List, Dict
from loguru import logger
import numpy as np

from putsengine.config import EngineConfig, Settings
from putsengine.models import LiquidityVacuum, PriceBar
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient


class LiquidityVacuumLayer:
    """
    Liquidity Vacuum Detection Layer.

    This layer identifies when buyers have stepped away from a stock,
    creating conditions for accelerated downside.

    Key insight: Selling alone doesn't crash stocks. The absence of
    buyers is what allows prices to fall rapidly.
    """

    def __init__(
        self,
        alpaca: AlpacaClient,
        polygon: PolygonClient,
        settings: Settings
    ):
        self.alpaca = alpaca
        self.polygon = polygon
        self.settings = settings
        self.config = EngineConfig

    async def analyze(self, symbol: str) -> LiquidityVacuum:
        """
        Perform liquidity vacuum analysis for a symbol.

        Args:
            symbol: Stock ticker to analyze

        Returns:
            LiquidityVacuum with detection results and score
        """
        logger.info(f"Analyzing liquidity vacuum for {symbol}...")

        vacuum = LiquidityVacuum(
            symbol=symbol,
            timestamp=datetime.now(),
            score=0.0
        )

        try:
            # Get intraday bars
            minute_bars = await self.polygon.get_minute_bars(
                symbol=symbol,
                from_date=date.today() - timedelta(days=2),
                limit=2000
            )

            # Get quotes for bid/ask analysis
            quote_data = await self.alpaca.get_latest_quote(symbol)

            # Get snapshot for current market data
            snapshot = await self.polygon.get_snapshot(symbol)

            # 1. Bid size collapsing (ARCHITECT-4: ADV-normalized)
            vacuum.bid_collapsing = await self._detect_bid_collapse(
                symbol, quote_data, snapshot, minute_bars
            )

            # 2. Spread widening (ARCHITECT-4: 15-min persistence)
            vacuum.spread_widening = await self._detect_spread_widening(
                symbol, quote_data, snapshot, minute_bars
            )

            # 3. Volume with no price progress
            if minute_bars:
                vacuum.volume_no_progress = self._detect_volume_no_progress(minute_bars)

            # 4. VWAP retest failures
            if minute_bars:
                vacuum.vwap_retest_failed = self._detect_vwap_retest_failure(minute_bars)

            # Calculate score
            vacuum.score = self._calculate_liquidity_score(vacuum)

            active_signals = sum([
                vacuum.bid_collapsing,
                vacuum.spread_widening,
                vacuum.volume_no_progress,
                vacuum.vwap_retest_failed
            ])

            logger.info(
                f"{symbol} liquidity vacuum: "
                f"Score={vacuum.score:.2f}, "
                f"Active signals={active_signals}/4"
            )

        except Exception as e:
            logger.error(f"Error in liquidity analysis for {symbol}: {e}")

        return vacuum

    async def _detect_bid_collapse(
        self,
        symbol: str,
        quote_data: Dict,
        snapshot: Dict,
        minute_bars: Optional[List] = None
    ) -> bool:
        """
        Detect if bid size is collapsing.

        When market makers reduce bid sizes, it signals
        they expect lower prices and don't want to accumulate.
        
        ARCHITECT-4 REFINEMENT: ADV-Normalized Bid Collapse
        ====================================================
        Added dual-condition for precision:
        1. bid_size < 30% of avg_print_size_1000 (rolling baseline)
        2. bid_size < 0.5% of ADV_shares (stock-relative normalization)
        
        This reduces false positives for stocks with irregular print sizes.
        """
        try:
            # Get current bid size
            current_bid_size = 0
            if quote_data and "quote" in quote_data:
                current_bid_size = quote_data["quote"].get("bs", 0)
            elif snapshot and "ticker" in snapshot:
                current_bid_size = snapshot["ticker"].get("lastQuote", {}).get("bidsize", 0)

            if current_bid_size == 0:
                return False

            # Get historical quote data for comparison
            # We'll use trades as a proxy for typical liquidity
            trades = await self.polygon.get_trades(
                symbol=symbol,
                from_date=date.today() - timedelta(days=1),
                limit=1000
            )

            if not trades:
                return False

            # Calculate avg_print_size_1000 (rolling baseline from recent trades)
            avg_print_size_1000 = np.mean([t.get("size", 0) for t in trades])

            # CONDITION 1: Bid collapse relative to print size
            # bid_size < 30% of avg_print_size_1000
            threshold_print = avg_print_size_1000 * self.config.BID_COLLAPSE_THRESHOLD
            collapse_vs_print = current_bid_size < threshold_print
            
            # ARCHITECT-4 REFINEMENT: ADV-normalized condition
            # CONDITION 2: bid_size < 0.5% of ADV_shares
            # ADV proxy: avg minute volume × 390 (minutes in trading day)
            collapse_vs_adv = False
            if minute_bars and len(minute_bars) > 0:
                avg_minute_volume = np.mean([b.volume for b in minute_bars])
                adv_shares = avg_minute_volume * 390  # Approx ADV
                threshold_adv = adv_shares * 0.005  # 0.5% of ADV
                collapse_vs_adv = current_bid_size < threshold_adv
                
                if collapse_vs_print and collapse_vs_adv:
                    logger.info(
                        f"{symbol}: BID COLLAPSE CONFIRMED (dual-condition) - "
                        f"bid={current_bid_size:,}, print_threshold={threshold_print:,.0f}, "
                        f"adv_threshold={threshold_adv:,.0f}"
                    )
            
            # Require BOTH conditions for confirmed collapse (high precision)
            # Fall back to single condition if ADV data unavailable
            if minute_bars and len(minute_bars) > 0:
                return collapse_vs_print and collapse_vs_adv
            else:
                return collapse_vs_print

        except Exception as e:
            logger.warning(f"Error detecting bid collapse for {symbol}: {e}")
            return False

    async def _detect_spread_widening(
        self,
        symbol: str,
        quote_data: Dict,
        snapshot: Dict,
        minute_bars: Optional[List] = None
    ) -> bool:
        """
        Detect if bid-ask spread is widening.

        Widening spreads indicate market makers are less
        confident in fair value - expecting volatility.
        
        ARCHITECT-4 REFINEMENT: Persistence Window
        ==========================================
        Spread widening signal requires persistence:
        - Signal must persist ≥ 60% of last 15 minutes
        - This converts tick noise into a real regime
        - Uses minute bar high-low range as spread proxy
        
        NOTE: Baseline spread estimated from low-volume bar ranges (proxy method).
        """
        try:
            # Get current spread
            bid = 0.0
            ask = 0.0

            if quote_data and "quote" in quote_data:
                bid = float(quote_data["quote"].get("bp", 0))
                ask = float(quote_data["quote"].get("ap", 0))
            elif snapshot and "ticker" in snapshot:
                quote = snapshot["ticker"].get("lastQuote", {})
                bid = float(quote.get("P", 0))  # Polygon uses P for bid
                ask = float(quote.get("p", 0))  # and p for ask

            if bid == 0 or ask == 0:
                return False

            current_spread = ask - bid
            mid_price = (bid + ask) / 2
            spread_pct = current_spread / mid_price if mid_price > 0 else 0

            # Get historical bars to estimate normal spread
            bars = await self.polygon.get_minute_bars(
                symbol=symbol,
                from_date=date.today() - timedelta(days=5),
                limit=1000
            )

            if not bars:
                return False

            # Estimate typical spread from high-low range during low volume periods
            # NOTE: This is a PROXY method, not true quote spread history
            avg_volume = np.mean([b.volume for b in bars])
            typical_ranges = []
            for bar in bars:
                if bar.volume < avg_volume * 0.5:
                    # Low volume bar - range approximates spread
                    range_pct = (bar.high - bar.low) / bar.close if bar.close > 0 else 0
                    typical_ranges.append(range_pct)

            if not typical_ranges:
                # Default: spread > 0.5% is wide for liquid stocks
                normal_spread = 0.0025  # 0.25% baseline
            else:
                normal_spread = np.mean(typical_ranges)
            
            threshold = normal_spread * self.config.SPREAD_WIDENING_THRESHOLD
            current_wide = spread_pct > threshold
            
            # ============================================================
            # ARCHITECT-4 REFINEMENT: 15-Minute Persistence Window
            # ============================================================
            # Require spread widening to persist for ≥60% of last 15 minutes
            # This converts tick noise into a real regime
            # ============================================================
            
            if minute_bars and len(minute_bars) >= 15:
                # Get last 15 minutes of bars
                today = date.today()
                today_bars = [b for b in minute_bars if b.timestamp.date() == today]
                
                if len(today_bars) >= 15:
                    recent_15 = today_bars[-15:]
                    
                    # Count bars where range (spread proxy) exceeded threshold
                    wide_count = 0
                    for bar in recent_15:
                        bar_range_pct = (bar.high - bar.low) / bar.close if bar.close > 0 else 0
                        if bar_range_pct > threshold:
                            wide_count += 1
                    
                    persistence_pct = wide_count / 15
                    
                    # Require 60%+ persistence for confirmed spread widening
                    if current_wide and persistence_pct >= 0.60:
                        logger.info(
                            f"{symbol}: SPREAD WIDENING CONFIRMED (persistence={persistence_pct:.0%}) - "
                            f"current_spread={spread_pct:.4f}, threshold={threshold:.4f}"
                        )
                        return True
                    elif current_wide:
                        logger.debug(
                            f"{symbol}: Spread wide but not persistent ({persistence_pct:.0%} < 60%)"
                        )
                        return False
            
            # Fallback: just use current spread if persistence check unavailable
            return current_wide

        except Exception as e:
            logger.warning(f"Error detecting spread widening for {symbol}: {e}")
            return False

    def _detect_volume_no_progress(self, bars: List[PriceBar]) -> bool:
        """
        Detect high volume with no price progress.

        When volume spikes but price doesn't move, it means
        selling is being absorbed. But if this continues,
        buyers eventually exhaust - creating vacuum.
        """
        if len(bars) < 60:
            return False

        # Get today's bars
        today = date.today()
        today_bars = [b for b in bars if b.timestamp.date() == today]

        if len(today_bars) < 30:
            return False

        # Analyze last 30 minutes
        recent = today_bars[-30:]

        # Calculate volume vs price change
        total_volume = sum(b.volume for b in recent)
        avg_volume = np.mean([b.volume for b in today_bars[:-30]]) if len(today_bars) > 30 else total_volume / 30

        # Price change over period
        price_start = recent[0].open
        price_end = recent[-1].close
        price_change = abs(price_end - price_start) / price_start if price_start > 0 else 0

        # Volume is elevated (>1.5x normal)
        volume_elevated = total_volume > avg_volume * 30 * 1.5

        # Price change is minimal (< 0.5%)
        price_minimal = price_change < 0.005

        return volume_elevated and price_minimal

    def _detect_vwap_retest_failure(self, bars: List[PriceBar]) -> bool:
        """
        Detect multiple failed VWAP reclaim attempts.

        When price fails to reclaim VWAP twice, it confirms
        institutional selling pressure and buyer exhaustion.
        """
        if len(bars) < 100:
            return False

        # Get today's bars
        today = date.today()
        today_bars = [b for b in bars if b.timestamp.date() == today]

        if len(today_bars) < 50:
            return False

        # Calculate VWAP
        vwap = self._calculate_vwap(today_bars)
        current_price = today_bars[-1].close

        # Only relevant if currently below VWAP
        if current_price >= vwap:
            return False

        # Count failed reclaim attempts
        failed_reclaims = 0
        in_retest = False

        for bar in today_bars:
            if not in_retest and bar.low < vwap:
                # Price dipped below VWAP
                in_retest = True
            elif in_retest and bar.high >= vwap:
                # Price attempted to reclaim
                if bar.close < vwap:
                    # But closed below = failed reclaim
                    failed_reclaims += 1
                    in_retest = False

        return failed_reclaims >= 2

    def _calculate_vwap(self, bars: List[PriceBar]) -> float:
        """Calculate VWAP from price bars."""
        if not bars:
            return 0.0

        total_volume = 0
        total_vwap = 0.0

        for bar in bars:
            typical_price = (bar.high + bar.low + bar.close) / 3
            total_vwap += typical_price * bar.volume
            total_volume += bar.volume

        return total_vwap / total_volume if total_volume > 0 else bars[-1].close

    def _calculate_liquidity_score(self, vacuum: LiquidityVacuum) -> float:
        """
        Calculate liquidity vacuum score.

        Each signal contributes 25% to the score.
        At least one signal is required for a non-zero score.
        """
        signals = [
            vacuum.bid_collapsing,
            vacuum.spread_widening,
            vacuum.volume_no_progress,
            vacuum.vwap_retest_failed
        ]

        signal_count = sum(1 for s in signals if s)

        if signal_count == 0:
            return 0.0

        return min(signal_count * 0.25, 1.0)

    async def has_liquidity_vacuum(
        self,
        symbol: str,
        min_score: float = 0.25
    ) -> bool:
        """
        Quick check if symbol shows liquidity vacuum.

        Args:
            symbol: Stock ticker
            min_score: Minimum score threshold (default 0.25 = 1 signal)

        Returns:
            True if liquidity vacuum detected
        """
        vacuum = await self.analyze(symbol)
        return vacuum.score >= min_score

    async def screen_for_vacuum(
        self,
        symbols: List[str],
        min_score: float = 0.25
    ) -> List[LiquidityVacuum]:
        """
        Screen multiple symbols for liquidity vacuum.

        Args:
            symbols: List of symbols to screen
            min_score: Minimum score threshold

        Returns:
            List of symbols showing liquidity vacuum
        """
        results = []

        for symbol in symbols:
            try:
                vacuum = await self.analyze(symbol)
                if vacuum.score >= min_score:
                    results.append(vacuum)
            except Exception as e:
                logger.error(f"Error screening {symbol}: {e}")
                continue

        # Sort by score descending
        results.sort(key=lambda x: x.score, reverse=True)

        return results
