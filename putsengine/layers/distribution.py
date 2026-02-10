"""
Distribution Detection Layer - Layer 2 in the PUT detection pipeline.

This is the PRIMARY ALPHA layer. Distribution detection identifies
stocks where smart money is selling into strength.

Price-Volume Contradictions (>=2 required):
- Flat price + rising volume
- Failed breakout on high volume
- Lower highs with flat RSI
- VWAP loss with reclaim failure

Options-Led Distribution (CRITICAL):
- Call selling at bid
- Put buying at ask
- Rising put OI while price flat
- Put IV faster than call IV (skew steepening)

This typically appears 1-3 days before breakdown.
"""

from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Tuple, Any
from loguru import logger
import numpy as np

from putsengine.config import EngineConfig, Settings
from putsengine.models import (
    DistributionSignal, PriceBar, OptionsFlow, DarkPoolPrint
)
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient


class DistributionLayer:
    """
    Distribution Detection Layer.

    This layer identifies stocks under distribution - where
    institutional sellers are offloading shares into retail buying.

    Key insight: Distribution happens BEFORE price breaks down.
    By the time price breaks, the opportunity has passed.
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

    async def analyze(self, symbol: str) -> DistributionSignal:
        """
        Perform complete distribution analysis for a symbol.

        Args:
            symbol: Stock ticker to analyze

        Returns:
            DistributionSignal with detection results and score
        """
        logger.info(f"Analyzing distribution for {symbol}...")

        # Initialize signal
        signal = DistributionSignal(
            symbol=symbol,
            timestamp=datetime.now(),
            score=0.0,
            signals={}
        )

        # A. Price-Volume Analysis
        pv_signals = await self._analyze_price_volume(symbol)
        signal.flat_price_rising_volume = pv_signals.get("flat_price_rising_volume", False)
        signal.failed_breakout = pv_signals.get("failed_breakout", False)
        signal.lower_highs_flat_rsi = pv_signals.get("lower_highs_flat_rsi", False)
        signal.vwap_loss = pv_signals.get("vwap_loss", False)
        
        # Store enhanced price-volume signals EARLY so they can be used in score calculation
        high_rvol_red_day = pv_signals.get("high_rvol_red_day", False)
        gap_down_no_recovery = pv_signals.get("gap_down_no_recovery", False)
        multi_day_weakness = pv_signals.get("multi_day_weakness", False)
        
        # Extract context data for dark pool analysis (ARCHITECT-4 REFINEMENT)
        current_vwap = pv_signals.get("current_vwap")
        current_price = pv_signals.get("current_price")
        session_high = pv_signals.get("session_high")

        # B. Options Flow Analysis
        options_signals = await self._analyze_options_flow(symbol)
        signal.call_selling_at_bid = options_signals.get("call_selling_at_bid", False)
        signal.put_buying_at_ask = options_signals.get("put_buying_at_ask", False)
        signal.rising_put_oi = options_signals.get("rising_put_oi", False)
        signal.skew_steepening = options_signals.get("skew_steepening", False)

        # C. Dark Pool Analysis (with ARCHITECT-4 Context Guard)
        dp_signals = await self._analyze_dark_pool(
            symbol,
            current_vwap=current_vwap,
            current_price=current_price,
            session_high=session_high
        )
        signal.repeated_sell_blocks = dp_signals.get("repeated_sell_blocks", False)
        
        # FEB 8, 2026: Dark pool violence (thin NBBO books + large prints)
        dark_pool_violence = dp_signals.get("dark_pool_violence", False)

        # D. Insider Trading Analysis (per Architect Blueprint)
        insider_result = await self._analyze_insider_activity(symbol)
        insider_boost = insider_result.get("boost", 0.0)
        
        # E. Congress Trading Analysis (per Architect Blueprint)
        congress_result = await self._analyze_congress_activity(symbol)
        congress_boost = congress_result.get("boost", 0.0)
        
        # F. Earnings Proximity Check (per Final Architect Report)
        # "Never buy puts BEFORE earnings"
        # "Buy 1 day AFTER earnings only if gap down + VWAP reclaim fails"
        earnings_data = await self.polygon.check_earnings_proximity(symbol)
        is_pre_earnings = earnings_data.get("is_pre_earnings", False)
        is_post_earnings = earnings_data.get("is_post_earnings", False)
        guidance_sentiment = earnings_data.get("guidance_sentiment", "neutral")
        
        # Post-earnings with negative guidance = valid put opportunity
        earnings_boost = 0.0
        if is_post_earnings and guidance_sentiment == "negative":
            earnings_boost = 0.10
            logger.info(f"{symbol}: Post-earnings with negative guidance - boost +0.10")

        # *** CRITICAL FIX: Store signals BEFORE score calculation ***
        # Store all signals in dict for easy access (needed for score calculation)
        gap_up_reversal = pv_signals.get("gap_up_reversal", False)
        
        signal.signals = {
            # Price-Volume Signals
            "flat_price_rising_volume": signal.flat_price_rising_volume,
            "failed_breakout": signal.failed_breakout,
            "lower_highs_flat_rsi": signal.lower_highs_flat_rsi,
            "vwap_loss": signal.vwap_loss,
            # Enhanced price-volume signals (stored early above)
            "high_rvol_red_day": high_rvol_red_day,
            "gap_down_no_recovery": gap_down_no_recovery,
            "gap_up_reversal": gap_up_reversal,  # NEW: Distribution trap
            "multi_day_weakness": multi_day_weakness,
            # Options Flow Signals
            "call_selling_at_bid": signal.call_selling_at_bid,
            "put_buying_at_ask": signal.put_buying_at_ask,
            "rising_put_oi": signal.rising_put_oi,
            "skew_steepening": signal.skew_steepening,
            "skew_reversal": options_signals.get("skew_reversal", False),  # FEB 8: Sign flip
            "repeated_sell_blocks": signal.repeated_sell_blocks,
            "dark_pool_violence": dark_pool_violence,  # FEB 8: Thin books + large prints
            "high_greek_weighted_flow": options_signals.get("high_greek_weighted_flow", False),  # FEB 8: Greek conviction
            # Signals from Architect Blueprint
            "c_level_selling": insider_result.get("c_level_selling", False),
            "insider_cluster": insider_result.get("insider_cluster", False),
            "congress_selling": congress_result.get("congress_selling", False),
            # Earnings signals
            "is_pre_earnings": is_pre_earnings,  # BLOCK signal
            "is_post_earnings_negative": is_post_earnings and guidance_sentiment == "negative",
        }
        
        # NOW calculate score (signals dict is populated)
        base_score = self._calculate_distribution_score(signal)
        
        # Apply boosts ONLY if base_score > 0 (confirmation, not trigger)
        # Per Architect: "Use as confirmation, not trigger"
        if base_score > 0:
            total_boost = min(insider_boost + congress_boost + earnings_boost, 0.25)  # Cap total boost at 0.25
            signal.score = min(base_score + total_boost, 1.0)
        else:
            signal.score = base_score

        # =============================================================
        # ARCHITECT-4 REFINEMENT: Distribution → Gamma Drain Handoff
        # =============================================================
        # When Distribution detects early signals AND conditions align,
        # flag for Gamma Drain entry timing.
        # 
        # This mirrors real desk workflow:
        # - Distribution = watchlist (early warning)
        # - Gamma Drain = entry timing (acceleration)
        #
        # Handoff criteria:
        # 1. Distribution score >= 0.55
        # 2. pump_reversal OR gap_up_reversal pattern present
        # 3. Index GEX <= neutral (dealer permission)
        # =============================================================
        
        handoff_candidate = False
        has_reversal_pattern = (
            signal.signals.get("gap_up_reversal", False) or 
            "pump_reversal" in str(signal.signals)
        )
        
        if signal.score >= 0.55 and has_reversal_pattern:
            # Check index GEX condition (attempt to fetch, but don't fail if unavailable)
            try:
                spy_gex = await self.unusual_whales.get_greek_exposure("SPY")
                if spy_gex:
                    net_gex = spy_gex.get("net_gex", 0)
                    if net_gex is None or net_gex <= 0:  # Neutral or negative = dealer permission
                        handoff_candidate = True
                        logger.info(
                            f"{symbol}: HANDOFF CANDIDATE - Distribution score={signal.score:.2f}, "
                            f"reversal pattern present, SPY GEX={net_gex} (neutral/negative)"
                        )
                else:
                    # Can't verify GEX, but other conditions met - still flag with warning
                    handoff_candidate = True
                    logger.info(
                        f"{symbol}: HANDOFF CANDIDATE (GEX unverified) - "
                        f"Distribution score={signal.score:.2f}, reversal pattern present"
                    )
            except Exception as e:
                logger.debug(f"Could not check GEX for handoff: {e}")
                # Still mark as potential handoff if score and pattern criteria met
                if signal.score >= 0.60:  # Slightly higher threshold when GEX unavailable
                    handoff_candidate = True
        
        # Add handoff flag to signals
        signal.signals["handoff_candidate"] = handoff_candidate

        # =============================================================
        # ARCHITECT-4 OPTIONAL: Distribution Failure Labeling
        # =============================================================
        # This is LEARNING INFRASTRUCTURE that helps answer:
        # "When does distribution NOT work?"
        #
        # Failure modes to detect:
        # - "absorption": VWAP holds, volume fades, dark pool selling stops
        # - "squeeze": Short covering forces price higher despite distribution
        # - "support_bounce": Price holds key support despite selling
        #
        # This enables post-mortem analysis and pattern refinement.
        # =============================================================
        
        failure_mode = None
        
        # Check for potential failure conditions
        vwap_holding = not signal.vwap_loss  # VWAP NOT lost = absorption
        no_dark_pool_selling = not signal.repeated_sell_blocks
        low_rvol = not signal.signals.get("high_rvol_red_day", False)
        
        # If we have some distribution signals but key confirmations missing...
        active_dist_signals = sum([
            signal.flat_price_rising_volume,
            signal.failed_breakout,
            signal.lower_highs_flat_rsi,
            signal.call_selling_at_bid,
            signal.put_buying_at_ask,
        ])
        
        if active_dist_signals >= 2:  # Had distribution signals
            if vwap_holding and low_rvol:
                failure_mode = "absorption"  # Selling absorbed, price held
            elif vwap_holding and no_dark_pool_selling:
                failure_mode = "support_bounce"  # Key support held
        
        signal.signals["failure_mode"] = failure_mode
        if failure_mode:
            logger.debug(f"{symbol}: Distribution failure mode detected: {failure_mode}")

        active_signals = sum(1 for k, v in signal.signals.items() 
                           if v and k not in ["handoff_candidate", "failure_mode"])
        boost_applied = insider_boost + congress_boost + earnings_boost
        
        handoff_str = " 🎯 HANDOFF" if handoff_candidate else ""
        failure_str = f" ⚠️ FAILURE_MODE={failure_mode}" if failure_mode else ""
        logger.info(
            f"{symbol} distribution analysis: "
            f"Score={signal.score:.2f} (base={base_score:.2f}, boost=+{boost_applied:.2f}), "
            f"Active signals={active_signals}/{len(signal.signals) - 2}{handoff_str}{failure_str}"
        )

        return signal

    async def _analyze_price_volume(self, symbol: str) -> Dict[str, bool]:
        """
        Analyze price-volume contradictions.

        These patterns indicate stealth distribution:
        - Price flat but volume rising = someone selling into bids
        - Failed breakout = rejection at resistance
        - Lower highs + flat RSI = distribution pattern
        - VWAP loss = institutional selling
        - HIGH RVOL on red day = institutional selling
        - Gap down without recovery = trapped longs
        - Gap UP reversal = distribution trap (NEW!)
        """
        signals = {
            "flat_price_rising_volume": False,
            "failed_breakout": False,
            "lower_highs_flat_rsi": False,
            "vwap_loss": False,
            "high_rvol_red_day": False,
            "gap_down_no_recovery": False,
            "gap_up_reversal": False,  # NEW: Distribution trap pattern
            "multi_day_weakness": False,
            # ARCHITECT-4 REFINEMENT: Context data for dark pool analysis
            "current_vwap": None,
            "current_price": None,
            "session_high": None
        }

        try:
            # Get daily bars for pattern analysis
            daily_bars = await self.polygon.get_daily_bars(
                symbol=symbol,
                from_date=date.today() - timedelta(days=30)
            )

            if len(daily_bars) < 10:
                return signals

            # Get minute bars for intraday analysis
            minute_bars = await self.polygon.get_minute_bars(
                symbol=symbol,
                from_date=date.today() - timedelta(days=2),
                limit=2000
            )
            
            # ARCHITECT-4 REFINEMENT: Extract context data for dark pool analysis
            if daily_bars:
                signals["current_price"] = daily_bars[-1].close
            if minute_bars:
                # Calculate VWAP from minute bars
                today_bars = [b for b in minute_bars if b.timestamp.date() == date.today()]
                if today_bars:
                    signals["session_high"] = max(b.high for b in today_bars)
                    # VWAP = Σ(typical_price × volume) / Σ(volume)
                    total_vp = sum((b.high + b.low + b.close) / 3 * b.volume for b in today_bars)
                    total_vol = sum(b.volume for b in today_bars)
                    if total_vol > 0:
                        signals["current_vwap"] = total_vp / total_vol

            # 1. Flat price + rising volume
            signals["flat_price_rising_volume"] = self._detect_flat_price_rising_volume(
                daily_bars
            )

            # 2. Failed breakout
            signals["failed_breakout"] = self._detect_failed_breakout(daily_bars)

            # 3. Lower highs with flat RSI
            signals["lower_highs_flat_rsi"] = self._detect_lower_highs_flat_rsi(
                daily_bars
            )

            # 4. VWAP loss with reclaim failure
            if minute_bars:
                signals["vwap_loss"] = self._detect_vwap_loss(minute_bars)

            # 5. HIGH RVOL on red day (CRITICAL - institutional selling)
            # Per Architect: "RVOL > 2.0 on red day" is valid distribution trap
            signals["high_rvol_red_day"] = self._detect_high_rvol_red_day(daily_bars)

            # 6. Gap down without recovery (trapped longs)
            signals["gap_down_no_recovery"] = self._detect_gap_down_no_recovery(daily_bars)

            # 7. Gap UP reversal (CRITICAL - distribution trap!)
            # This catches UUUU-type moves: gaps up, then reverses hard
            signals["gap_up_reversal"] = self._detect_gap_up_reversal(daily_bars)

            # 8. Multi-day price weakness (3+ consecutive red days or lower closes)
            signals["multi_day_weakness"] = self._detect_multi_day_weakness(daily_bars)

        except Exception as e:
            logger.error(f"Error in price-volume analysis for {symbol}: {e}")

        return signals

    def _detect_high_rvol_red_day(self, bars: List[PriceBar]) -> bool:
        """
        Detect high relative volume on a down day.
        
        Per Final Architect Report:
        "RVOL > 2.0 on red day" = valid distribution pattern.
        
        UPDATED: Also catch RVOL > 1.3 with significant moves
        This indicates institutional selling - they're moving large
        blocks with urgency, creating volume spike on down move.
        """
        if len(bars) < 20:
            return False

        # Calculate average volume (exclude last bar to get true average)
        avg_volume = np.mean([b.volume for b in bars[-21:-1]])  # Use 20 bars before current
        
        if avg_volume == 0:
            return False

        # Get today/most recent bar
        recent_bar = bars[-1]
        rvol = recent_bar.volume / avg_volume

        # Check if red day (close < open OR close < previous close)
        is_red = recent_bar.close < recent_bar.open
        if len(bars) >= 2:
            is_down_day = recent_bar.close < bars[-2].close
        else:
            is_down_day = is_red

        # Price change calculation
        price_change = (recent_bar.close - recent_bar.open) / recent_bar.open if recent_bar.open > 0 else 0

        # EXTREME: RVOL >= 2.0 on red day = strong distribution signal
        if rvol >= self.config.RVOL_EXTREME_THRESHOLD and (is_red or is_down_day):
            logger.info(f"EXTREME RVOL RED DAY: RVOL={rvol:.1f}x, Change={price_change*100:.1f}%")
            return True

        # HIGH: RVOL >= 1.5 with significant drop (>1.5%)
        if rvol >= self.config.RVOL_HIGH_THRESHOLD and price_change < -0.015:
            logger.info(f"HIGH RVOL with drop: RVOL={rvol:.1f}x, Drop={price_change*100:.1f}%")
            return True

        # ELEVATED: RVOL >= 1.3 with big drop (>3%) - catch institutional selling
        if rvol >= self.config.VOLUME_SPIKE_THRESHOLD and price_change < -0.03:
            logger.info(f"ELEVATED RVOL significant drop: RVOL={rvol:.1f}x, Drop={price_change*100:.1f}%")
            return True

        return False

    def _detect_gap_down_no_recovery(self, bars: List[PriceBar]) -> bool:
        """
        Detect gap down that fails to recover.
        
        Per Architect: "Gap up → first 30-min candle closes red" is bearish.
        Inverse also applies: Gap down that doesn't recover = trapped longs.
        
        This pattern often precedes -5% to -15% moves as trapped
        longs are forced to sell.
        """
        if len(bars) < 2:
            return False

        # Compare today's open vs yesterday's close
        yesterday = bars[-2]
        today = bars[-1]

        gap_pct = (today.open - yesterday.close) / yesterday.close

        # Gap down of at least 1%
        if gap_pct < -0.01:
            # Check if price recovered: today's close should be above today's open
            # If close < open, gap wasn't recovered
            if today.close <= today.open:
                # Extra confirmation: close below yesterday's close
                if today.close < yesterday.close:
                    logger.info(f"GAP DOWN NO RECOVERY: Gap={gap_pct*100:.1f}%, Close < Open")
                    return True

        return False

    def _detect_gap_up_reversal(self, bars: List[PriceBar]) -> bool:
        """
        ARCHITECT-4 FINAL: Gap-Up → Reversal with Opening RVOL Confirmation.
        
        This is REAL institutional distribution:
        - Stock gaps UP (looks bullish) 
        - But closes significantly below open (distribution)
        - CRITICAL: Must have elevated opening RVOL (>= 1.3)
        
        Per Architect-4 Final Rule:
        gap_up_reversal = (
            gap_up >= +1%
            AND close <= open - 2%
            AND open_RVOL >= 1.3
            AND VWAP lost within first 30-60 min
        )
        
        Why RVOL matters:
        - Low-volume reversals = noise
        - High-RVOL reversals = supply hitting bids
        
        This caught UUUU which gapped +5% then fell -15%!
        """
        if len(bars) < 21:  # Need 20 days for RVOL
            return False

        yesterday = bars[-2]
        today = bars[-1]

        # 1. Gap up of at least 1%
        gap_pct = (today.open - yesterday.close) / yesterday.close
        if gap_pct < 0.01:
            return False

        # 2. Significant reversal: close at least 2% below open
        intraday_drop = (today.close - today.open) / today.open
        if intraday_drop >= -0.02:
            # Not enough reversal
            return False
        
        # 3. RVOL confirmation (ARCHITECT-4 ADDITION)
        # Use 20-day SMA as baseline per Architect-4
        avg_volume_20d = np.mean([b.volume for b in bars[-21:-1]])
        if avg_volume_20d == 0:
            return False
        
        rvol = today.volume / avg_volume_20d
        
        # Opening RVOL must be >= 1.3 (supply hitting bids)
        if rvol < 1.3:
            logger.debug(f"Gap-up reversal rejected: RVOL {rvol:.2f} < 1.3 threshold")
            return False
        
        # 4. VWAP check (if available from today's bar)
        # The VWAP loss should occur in first 30-60 min - approximated by close < vwap
        if hasattr(today, 'vwap') and today.vwap > 0:
            if today.close >= today.vwap:
                logger.debug(f"Gap-up reversal rejected: price above VWAP")
                return False
        
        logger.info(
            f"GAP UP REVERSAL CONFIRMED: Gap={gap_pct*100:.1f}%, "
            f"Intraday drop={intraday_drop*100:.1f}%, RVOL={rvol:.2f}x"
        )
        return True

    def _detect_multi_day_weakness(self, bars: List[PriceBar]) -> bool:
        """
        Detect multi-day price weakness pattern.
        
        3+ consecutive lower closes or red days indicates
        sustained selling pressure - often precedes larger move.
        """
        if len(bars) < 5:
            return False

        recent = bars[-5:]
        
        # Count consecutive lower closes
        lower_closes = 0
        for i in range(1, len(recent)):
            if recent[i].close < recent[i-1].close:
                lower_closes += 1
            else:
                break  # Reset count if we get an up close
        
        # Count red days (close < open)
        red_days = sum(1 for b in recent[-3:] if b.close < b.open)
        
        # 3+ consecutive lower closes OR 3 red days in last 3 = weakness
        return lower_closes >= 3 or red_days >= 3

    def _detect_flat_price_rising_volume(self, bars: List[PriceBar]) -> bool:
        """
        Detect flat price with rising volume pattern.

        This indicates sellers are meeting buyers, but price
        isn't rising = supply overwhelming demand.
        """
        if len(bars) < 5:
            return False

        recent = bars[-5:]

        # Check price range (should be tight)
        prices = [b.close for b in recent]
        price_range = (max(prices) - min(prices)) / np.mean(prices)

        # Check volume trend (should be rising)
        volumes = [b.volume for b in recent]
        vol_trend = (volumes[-1] - volumes[0]) / volumes[0] if volumes[0] > 0 else 0

        # Flat price (< 2% range) + rising volume (> 20% increase)
        return price_range < 0.02 and vol_trend > 0.20

    def _detect_failed_breakout(self, bars: List[PriceBar]) -> bool:
        """
        Detect failed breakout pattern.

        A breakout that fails on high volume is very bearish -
        it shows buyers exhausted at resistance.
        """
        if len(bars) < 20:
            return False

        # Find recent high
        recent_20 = bars[-20:]
        highs = [b.high for b in recent_20]
        resistance = max(highs)

        # Check if recent bar broke above then closed below
        for i in range(-3, 0):
            bar = bars[i]
            if bar.high >= resistance * 0.995:  # Touched resistance
                if bar.close < resistance * 0.98:  # Closed below
                    # Check if volume was elevated
                    avg_vol = np.mean([b.volume for b in bars[-20:-1]])
                    if bar.volume > avg_vol * self.config.VOLUME_SPIKE_THRESHOLD:
                        return True

        return False

    def _detect_lower_highs_flat_rsi(self, bars: List[PriceBar]) -> bool:
        """
        Detect lower highs with flat/rising RSI.

        Normally, lower highs should come with lower RSI.
        If RSI is flat while price makes lower highs,
        it shows hidden strength being sold into.
        """
        if len(bars) < 20:
            return False

        # Calculate RSI
        rsi_values = self._calculate_rsi([b.close for b in bars], period=14)
        if len(rsi_values) < 10:
            return False

        recent = bars[-10:]
        recent_rsi = rsi_values[-10:]

        # Check for lower highs in price
        highs = [b.high for b in recent]
        price_making_lower_highs = all(
            highs[i] >= highs[i + 1] for i in range(len(highs) - 3, len(highs) - 1)
        )

        # Check RSI is flat or rising
        rsi_flat_or_rising = recent_rsi[-1] >= recent_rsi[-3] - 5

        return price_making_lower_highs and rsi_flat_or_rising

    def _detect_vwap_loss(self, bars: List[PriceBar]) -> bool:
        """
        Detect VWAP loss with failed reclaim.

        Losing VWAP and failing to reclaim it is a sign
        of institutional selling.
        """
        if len(bars) < 100:
            return False

        # Get today's bars only
        today = date.today()
        today_bars = [b for b in bars if b.timestamp.date() == today]

        if len(today_bars) < 30:
            return False

        # Calculate VWAP
        vwap = self._calculate_vwap(today_bars)
        current_price = today_bars[-1].close

        # Check if below VWAP
        if current_price >= vwap:
            return False

        # Check for failed reclaim attempts
        reclaim_attempts = 0
        for i in range(len(today_bars) - 20, len(today_bars)):
            bar = today_bars[i]
            if bar.high >= vwap and bar.close < vwap:
                reclaim_attempts += 1

        return reclaim_attempts >= 2

    def _calculate_vwap(self, bars: List[PriceBar]) -> float:
        """Calculate VWAP from bars."""
        if not bars:
            return 0.0

        total_volume = 0
        total_vwap = 0.0

        for bar in bars:
            typical_price = (bar.high + bar.low + bar.close) / 3
            total_vwap += typical_price * bar.volume
            total_volume += bar.volume

        return total_vwap / total_volume if total_volume > 0 else bars[-1].close

    def _calculate_rsi(self, prices: List[float], period: int = 14) -> List[float]:
        """Calculate RSI indicator."""
        if len(prices) < period + 1:
            return []

        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        rsi_values = []

        # Initial average
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))

            rsi_values.append(rsi)

        return rsi_values

    async def _analyze_options_flow(self, symbol: str) -> Dict[str, bool]:
        """
        Analyze options flow for distribution signals.

        Key signals:
        - Call selling at bid = bearish (someone dumping calls)
        - Put buying at ask = bearish (aggressive put buying)
        - Rising put OI = accumulation of puts
        - Skew steepening = put IV rising faster than call IV
        """
        signals = {
            "call_selling_at_bid": False,
            "put_buying_at_ask": False,
            "rising_put_oi": False,
            "skew_steepening": False
        }

        try:
            # Get options flow from Unusual Whales
            put_flow = await self.unusual_whales.get_put_flow(
                symbol=symbol,
                min_premium=10000,
                limit=30
            )

            call_selling = await self.unusual_whales.get_call_selling_flow(
                symbol=symbol,
                limit=30
            )

            # 1. Call selling at bid
            if call_selling and isinstance(call_selling, list):
                bid_sells = [f for f in call_selling if hasattr(f, 'side') and f.side.lower() in ["bid", "sell"]]
                total_premium = sum(f.premium for f in bid_sells if hasattr(f, 'premium'))
                if total_premium > 50000:  # $50K+ in call selling
                    signals["call_selling_at_bid"] = True

            # 2. Put buying at ask
            if put_flow and isinstance(put_flow, list):
                ask_buys = [f for f in put_flow if hasattr(f, 'side') and f.side.lower() in ["ask", "buy"]]
                total_premium = sum(f.premium for f in ask_buys if hasattr(f, 'premium'))
                if total_premium > 50000:  # $50K+ in put buying
                    signals["put_buying_at_ask"] = True
            
            # FEB 8, 2026: Greek-weighted flow analysis
            # Weight bearish flow by delta/gamma/vega × size to capture conviction
            # High delta puts = deep ITM = max directional exposure = smart money
            # High gamma puts = near ATM = max acceleration exposure = timing bets
            # High vega puts = vol-sensitive = hedging ahead of event
            all_flow = (put_flow or []) + (call_selling or [])
            if all_flow:
                bearish_delta_exposure = 0.0
                bearish_gamma_exposure = 0.0
                bearish_vega_exposure = 0.0
                total_bearish_trades = 0
                for f in all_flow:
                    if hasattr(f, 'sentiment') and f.sentiment == "bearish":
                        total_bearish_trades += 1
                        # Delta-weighted: larger delta = more directional conviction
                        bearish_delta_exposure += abs(getattr(f, 'delta', 0)) * f.size * 100
                        # Gamma-weighted: larger gamma = more acceleration sensitivity
                        # Near-ATM puts with high gamma = max P&L acceleration on move
                        bearish_gamma_exposure += abs(getattr(f, 'gamma', 0)) * f.size * 100
                        # Vega-weighted: larger vega = more volatility-sensitive
                        bearish_vega_exposure += abs(getattr(f, 'vega', 0)) * f.size * 100
                
                # Store for downstream scoring
                signals["bearish_delta_exposure"] = bearish_delta_exposure
                signals["bearish_gamma_exposure"] = bearish_gamma_exposure
                signals["bearish_vega_exposure"] = bearish_vega_exposure
                
                # ── Boolean signal: High Greek-weighted bearish flow ──
                # Triggers when institutional conviction is clear across Greeks
                # This feeds into signal_priority.py scoring as PRE-breakdown
                greek_conviction_count = sum([
                    bearish_delta_exposure > 500000,  # $500K+ delta exposure
                    bearish_gamma_exposure > 100000,  # $100K+ gamma exposure
                    bearish_vega_exposure > 200000,   # $200K+ vega exposure
                ])
                signals["high_greek_weighted_flow"] = greek_conviction_count >= 2
                
                # High delta exposure = institutional directional bets
                if bearish_delta_exposure > 500000:
                    logger.info(
                        f"{symbol}: High bearish delta exposure "
                        f"${bearish_delta_exposure:,.0f} — institutional conviction"
                    )
                # High gamma exposure = acceleration-sensitive positioning
                if bearish_gamma_exposure > 100000:
                    logger.info(
                        f"{symbol}: High bearish gamma exposure "
                        f"${bearish_gamma_exposure:,.0f} — acceleration positioning"
                    )
                # High vega exposure = hedging ahead of expected vol event
                if bearish_vega_exposure > 200000:
                    logger.info(
                        f"{symbol}: High bearish vega exposure "
                        f"${bearish_vega_exposure:,.0f} — event hedging"
                    )

        except Exception as e:
            logger.debug(f"Error in flow analysis for {symbol}: {e}")

        try:
            # 3. Check for rising put OI
            oi_data = await self.unusual_whales.get_oi_change(symbol)
            if oi_data:
                # Handle list response
                if isinstance(oi_data, list):
                    if len(oi_data) > 0:
                        oi_data = {"data": oi_data}
                    else:
                        oi_data = {}

                if isinstance(oi_data, dict):
                    data = oi_data.get("data", oi_data)
                    if isinstance(data, list) and len(data) > 0:
                        data = data[0]
                    if isinstance(data, dict):
                        put_oi_change = float(data.get("put_oi_change_pct", data.get("put_change_pct", 0)))
                        if put_oi_change > 10:  # 10%+ increase in put OI
                            signals["rising_put_oi"] = True
        except Exception as e:
            logger.debug(f"Error in OI analysis for {symbol}: {e}")

        try:
            # 4. Check skew steepening + skew reversal
            # FEB 8, 2026 FIX: get_skew() now returns enriched data with
            # top-level 'skew_change' computed from risk_reversal time series.
            # Negative risk_reversal = puts expensive vs calls = bearish.
            # Increasingly negative (skew_change < 0) = skew steepening = bearish.
            # NEW: skew_reversal = True when risk_reversal flips sign day-over-day.
            skew_data = await self.unusual_whales.get_skew(symbol)
            if skew_data:
                # Handle list response
                if isinstance(skew_data, list):
                    if len(skew_data) > 0:
                        skew_data = {"data": skew_data}
                    else:
                        skew_data = {}

                if isinstance(skew_data, dict):
                    # First check top-level enriched fields (from fixed get_skew)
                    skew_change = float(skew_data.get("skew_change", 0))
                    
                    # Fallback: look inside nested data
                    if skew_change == 0:
                        data = skew_data.get("data", skew_data)
                        if isinstance(data, list) and len(data) > 0:
                            data = data[-1]  # Use latest record
                        if isinstance(data, dict):
                            skew_change = float(data.get("skew_change", data.get("change", data.get("risk_reversal", 0))))
                    
                    # For risk_reversal-based skew: steepening when change is MORE negative
                    # A negative skew_change means risk_reversal became more negative = bearish
                    # Use absolute value comparison with threshold
                    if abs(skew_change) > self.config.SKEW_STEEPENING_THRESHOLD:
                        # For risk_reversal: negative change = puts getting more expensive = bearish
                        if skew_change < 0:
                            signals["skew_steepening"] = True
                            logger.info(f"{symbol}: Skew steepening detected (change={skew_change:.4f})")
                        elif skew_change > self.config.SKEW_STEEPENING_THRESHOLD:
                            # Legacy path: positive skew_change (old data format)
                            signals["skew_steepening"] = True
                    
                    # FEB 8, 2026: Check for skew reversal (sign flip day-over-day)
                    # This is a regime-change signal — options skew flipped direction
                    skew_reversal = skew_data.get("skew_reversal", False)
                    if skew_reversal:
                        signals["skew_reversal"] = True
                        # If reversal is to negative (bearish), it's extra significant
                        latest_rr = float(skew_data.get("risk_reversal", 0))
                        if latest_rr < 0:
                            logger.info(
                                f"{symbol}: SKEW REVERSAL TO BEARISH - "
                                f"risk_reversal flipped to {latest_rr:.4f}"
                            )
        except Exception as e:
            logger.debug(f"Error in skew analysis for {symbol}: {e}")

        return signals

    async def _analyze_dark_pool(
        self, 
        symbol: str,
        current_vwap: Optional[float] = None,
        current_price: Optional[float] = None,
        session_high: Optional[float] = None
    ) -> Dict[str, bool]:
        """
        Analyze dark pool for distribution signals.

        Key signal: Repeated sell blocks near same price
        with no positive price response.
        
        ARCHITECT-4 REFINEMENT: Dark Pool Context Guard
        ================================================
        To filter false positives from ETF rebalancing, VWAP facilitation,
        and neutral internalization, we require:
        
        Repeated sell blocks AND (price below VWAP OR failed new intraday high)
        
        FEB 8, 2026: Dark Pool Violence Detection
        ==========================================
        Large prints hitting thin NBBO books = violent absorption conditions.
        Uses nbbo_bid_quantity and nbbo_ask_quantity from UW dark pool data.
        When print_size >> nbbo_depth, market makers are overwhelmed.
        
        This ensures we're detecting genuine distribution, not neutral facilitation.
        """
        signals = {
            "repeated_sell_blocks": False,
            "dark_pool_violence": False,  # FEB 8, 2026: Thin-book violence
        }

        try:
            # Get dark pool prints
            dp_prints = await self.unusual_whales.get_dark_pool_flow(
                symbol=symbol,
                limit=30
            )

            if len(dp_prints) < 5:
                return signals

            # FEB 8, 2026 FIX: Now that is_buy is inferred from price vs NBBO,
            # prioritize SELL-side prints for distribution detection.
            # Filter to sell-side or ambiguous prints (exclude confirmed buys)
            sell_or_ambiguous = [p for p in dp_prints if p.is_buy is not True]
            
            # If we have enough sell-side prints, use them; otherwise use all
            target_prints = sell_or_ambiguous if len(sell_or_ambiguous) >= 3 else dp_prints
            
            # Group prints by price level (within 0.5%)
            price_clusters: Dict[float, List[DarkPoolPrint]] = {}
            for print_data in target_prints:
                # Round to nearest 0.5%
                if print_data.price <= 0:
                    continue
                rounded_price = round(print_data.price / (print_data.price * 0.005)) * (print_data.price * 0.005)
                if rounded_price not in price_clusters:
                    price_clusters[rounded_price] = []
                price_clusters[rounded_price].append(print_data)

            # Check for repeated blocks at same level
            for price_level, prints in price_clusters.items():
                if len(prints) >= 3:  # 3+ blocks at same level
                    total_size = sum(p.size for p in prints)
                    if total_size > 50000:  # 50K+ shares
                        # Check if price moved up after (it shouldn't for distribution)
                        last_print_price = prints[-1].price
                        if last_print_price <= price_level * 1.01:  # Price didn't rise
                            
                            # ARCHITECT-4 CONTEXT GUARD:
                            # Require price below VWAP OR failed to make new intraday high
                            # This filters ETF rebalancing, VWAP facilitation, neutral internalization
                            context_confirmed = True
                            
                            if current_vwap and current_price and session_high:
                                # Check context conditions
                                below_vwap = current_price < current_vwap
                                failed_new_high = current_price < session_high * 0.995  # Below 0.5% of high
                                
                                # Must have at least one bearish context
                                context_confirmed = below_vwap or failed_new_high
                                
                                if not context_confirmed:
                                    logger.debug(
                                        f"{symbol}: Dark pool blocks detected but context guard failed "
                                        f"(price ${current_price:.2f} above VWAP ${current_vwap:.2f} "
                                        f"and near session high ${session_high:.2f})"
                                    )
                            
                            if context_confirmed:
                                signals["repeated_sell_blocks"] = True
                                logger.info(
                                    f"{symbol}: DARK POOL DISTRIBUTION - {len(prints)} blocks, "
                                    f"{total_size:,} shares at ${price_level:.2f}"
                                )
                                break

            # ── FEB 8, 2026: Dark Pool Violence Scoring ──
            # Thin NBBO books + large prints = violent conditions
            # When print_size is >> nbbo_depth, market makers are overwhelmed
            # This indicates absorption capacity is depleted
            violence_prints = 0
            total_violence_ratio = 0.0
            for p in dp_prints:
                nbbo_depth = max(
                    getattr(p, 'nbbo_bid_quantity', 0),
                    getattr(p, 'nbbo_ask_quantity', 0)
                )
                if nbbo_depth > 0 and p.size > 0:
                    # Violence ratio: print_size / nbbo_depth
                    # > 5x means the print is 5x bigger than what's on the book
                    violence_ratio = p.size / nbbo_depth
                    if violence_ratio > 5.0:
                        violence_prints += 1
                        total_violence_ratio += violence_ratio
            
            if violence_prints >= 3:
                avg_violence = total_violence_ratio / violence_prints
                signals["dark_pool_violence"] = True
                logger.info(
                    f"{symbol}: DARK POOL VIOLENCE - {violence_prints} prints "
                    f"on thin books (avg ratio={avg_violence:.1f}x NBBO depth)"
                )

        except Exception as e:
            logger.error(f"Error in dark pool analysis for {symbol}: {e}")

        return signals

    async def _analyze_insider_activity(self, symbol: str) -> Dict[str, Any]:
        """
        Analyze insider trading patterns per Final Architect Blueprint.
        
        C-level selling clusters are highly predictive of downside.
        Use as CONFIRMATION, not trigger.
        
        Returns:
            Dict with signals and boost value (+0.10 to +0.15)
        """
        result = {
            "c_level_selling": False,
            "insider_cluster": False,
            "large_sale": False,
            "boost": 0.0
        }

        try:
            # v2.0 (Gap 10): UW now iterates person slugs for real trade details
            insider_trades = await self.unusual_whales.get_insider_trades(
                symbol, limit=50, max_person_lookups=5
            )

            if not insider_trades:
                return result

            # C-level titles to watch
            c_level_titles = ['CEO', 'CFO', 'COO', 'CTO', 'PRESIDENT', 'CHAIRMAN', 
                             'CHIEF', 'DIRECTOR', 'VP', 'VICE PRESIDENT']
            
            c_level_sales = 0
            total_sales = 0
            large_sales = 0
            recent_sales = 0  # Within 14 days
            real_trade_count = 0  # Gap 10: count actual trade records
            
            from datetime import datetime, timedelta
            cutoff_date = datetime.now() - timedelta(days=14)

            for trade in insider_trades:
                title = str(trade.get('title', '') or '').upper()
                trans_type = str(trade.get('transaction_type', '') or '').lower()
                value = float(trade.get('value', 0) or 0)
                source = trade.get('source', '')
                
                # Skip person-level stubs with no trade data (they have unknown type)
                if trans_type == 'unknown':
                    continue
                
                # Count real trades from person iteration (Gap 10)
                if source == 'uw_insider_person_trades':
                    real_trade_count += 1
                
                # Parse trade date
                trade_date_str = trade.get('transaction_date', trade.get('filing_date', ''))
                try:
                    if trade_date_str:
                        trade_date = datetime.strptime(str(trade_date_str)[:10], "%Y-%m-%d")
                        is_recent = trade_date >= cutoff_date
                    else:
                        is_recent = False
                except Exception:
                    is_recent = False

                if 'sale' in trans_type or 'sell' in trans_type or 's - sale' in trans_type:
                    total_sales += 1
                    if is_recent:
                        recent_sales += 1

                    # Check if C-level
                    if any(t in title for t in c_level_titles):
                        c_level_sales += 1

                    # Check for large sale (>$500K)
                    if value > 500_000:
                        large_sales += 1

            # Gap 10: Also check FinViz insider data (cross-validation)
            finviz_insider_boost = False
            if hasattr(self, 'finviz') and self.finviz:
                try:
                    fv_quote = await self.finviz.get_quote(symbol)
                    if fv_quote:
                        # FinViz _parse_quote_data may populate insider activity info
                        cached = self.finviz._quote_cache.get(symbol, {})
                        insider_own = cached.get('Insider Own', '')
                        insider_trans = cached.get('Insider Trans', '')
                        # If insider ownership is declining (negative trans %)
                        if insider_trans:
                            try:
                                trans_pct = float(insider_trans.replace('%', ''))
                                if trans_pct < -5.0:  # Insiders reduced by >5%
                                    finviz_insider_boost = True
                                    logger.debug(
                                        f"{symbol}: FinViz insider transaction "
                                        f"{trans_pct:.1f}% (bearish cross-validation)"
                                    )
                            except (ValueError, TypeError):
                                pass
                except Exception:
                    pass  # FinViz is supplementary, not critical

            # C-level selling: 2+ C-level execs sold within 14 days
            result["c_level_selling"] = c_level_sales >= 2
            
            # Insider cluster: 3+ insiders selling in period
            result["insider_cluster"] = recent_sales >= 3

            # Large sale: any sale >$500K
            result["large_sale"] = large_sales > 0
            
            # Gap 10: Track data quality
            result["real_trades"] = real_trade_count
            result["total_sales"] = total_sales
            result["finviz_confirmed"] = finviz_insider_boost

            # Calculate boost per Architect Blueprint (+0.10 to +0.15)
            # NOT a trigger, only confirmation boost
            if result["c_level_selling"] and result["insider_cluster"]:
                result["boost"] = 0.15  # Max boost: strong signal
                logger.info(f"{symbol}: C-level cluster selling detected! Boost +0.15")
            elif result["c_level_selling"] or (result["insider_cluster"] and result["large_sale"]):
                result["boost"] = 0.12
                logger.info(f"{symbol}: Insider selling signal. Boost +0.12")
            elif result["insider_cluster"]:
                result["boost"] = 0.10  # Min boost
                logger.info(f"{symbol}: Insider cluster detected. Boost +0.10")
            elif finviz_insider_boost and recent_sales >= 2:
                # FinViz cross-validated + some UW sales = moderate boost
                result["boost"] = 0.08
                logger.info(f"{symbol}: FinViz-confirmed insider selling. Boost +0.08")
            
            if real_trade_count > 0:
                logger.debug(
                    f"{symbol}: Insider analysis — {real_trade_count} real trades, "
                    f"{total_sales} sales, {c_level_sales} C-level, "
                    f"{recent_sales} recent, {large_sales} large"
                )

        except Exception as e:
            logger.debug(f"Error analyzing insider activity for {symbol}: {e}")

        return result

    async def _analyze_congress_activity(self, symbol: str) -> Dict[str, Any]:
        """
        Analyze congressional trading patterns per Final Architect Blueprint.
        
        Focus on SELL clusters only in regulated sectors.
        Use as weak confirmation (+0.05 to +0.08).
        
        Returns:
            Dict with signals and boost value
        """
        result = {
            "congress_selling": False,
            "sector_relevant": False,
            "boost": 0.0
        }

        try:
            congress_trades = await self.unusual_whales.get_congress_trades(limit=100)

            if not congress_trades:
                return result

            # Filter for this symbol
            symbol_trades = [t for t in congress_trades 
                           if str(t.get('ticker', '') or '').upper() == symbol.upper()]
            
            if not symbol_trades:
                return result

            # Count sells
            sell_count = 0
            for trade in symbol_trades:
                trans_type = str(trade.get('transaction_type', '') or '').lower()
                if 'sale' in trans_type or 'sell' in trans_type:
                    sell_count += 1

            # Congress selling: 2+ sell transactions
            result["congress_selling"] = sell_count >= 2

            # Check if in regulated sector (defense, pharma, energy, tech)
            # This would require sector lookup - simplified for now
            regulated_keywords = ['defense', 'pharma', 'bio', 'energy', 'oil', 'gas', 
                                 'tech', 'bank', 'finance', 'health']
            # Could enhance with sector data from Polygon

            # Calculate boost per Architect Blueprint (+0.05 to +0.08)
            if result["congress_selling"]:
                result["boost"] = 0.08 if sell_count >= 3 else 0.05
                logger.info(f"{symbol}: Congress selling detected ({sell_count} transactions). Boost +{result['boost']:.2f}")

        except Exception as e:
            logger.debug(f"Error analyzing congress activity for {symbol}: {e}")

        return result

    def _calculate_distribution_score(self, signal: DistributionSignal) -> float:
        """
        Calculate composite distribution score with PRE-BREAKDOWN signal priority.
        
        FEB 1, 2026 FIX: System was detecting moves AFTER they happened!
        ================================================================
        
        NEW APPROACH:
        - PRE-BREAKDOWN signals (predictive) get 1.5x weight
        - POST-BREAKDOWN signals (reactive) get 0.7x weight
        - This prioritizes EARLY detection over late confirmation
        
        PRE-BREAKDOWN (PREDICTIVE) - Higher Weight:
        - Dark pool distribution, put OI accumulation, call selling at bid
        - IV inversion, skew steepening, flat price + rising volume
        - Insider/C-level selling
        
        POST-BREAKDOWN (REACTIVE) - Lower Weight:
        - High RVOL red day (price already dropped)
        - Gap down no recovery (move already happened)
        - Multi-day weakness (trend already started)
        """
        from putsengine.signal_priority import (
            calculate_priority_score, 
            get_signal_priority_summary,
            is_predictive_signal_dominant
        )
        
        # Use the new signal priority system
        priority_score, breakdown = calculate_priority_score(signal.signals)
        summary = get_signal_priority_summary(signal.signals)
        
        # Log PRE vs POST signal analysis
        pre_count = summary["pre_breakdown_count"]
        post_count = summary["post_breakdown_count"]
        pre_score = summary["pre_breakdown_score"]
        post_score = summary["post_breakdown_score"]
        timing_rec = summary["timing_recommendation"]
        
        if pre_count > 0 or post_count > 0:
            logger.info(
                f"{signal.symbol}: Signal Priority Analysis - "
                f"PRE: {pre_count} signals ({pre_score:.2f}), "
                f"POST: {post_count} signals ({post_score:.2f}), "
                f"Timing: {timing_rec}"
            )
        
        # ===================================================================
        # BONUS: Add extra weight for strong predictive (PRE) signals
        # This ensures early detection candidates get prioritized
        # ===================================================================
        predictive_bonus = 0.0
        
        if is_predictive_signal_dominant(signal.signals):
            # Strong predictive signals - add bonus
            predictive_bonus = 0.10
            logger.info(f"{signal.symbol}: PREDICTIVE SIGNALS DOMINANT - Early entry candidate (+0.10 bonus)")
        
        # ===================================================================
        # SPECIAL CASE: PRE-EARNINGS with front-run distribution
        # ===================================================================
        is_pre_earnings = signal.signals.get("is_pre_earnings", False)
        pre_earnings_adjustment = 0.0
        
        if is_pre_earnings:
            # Check for strong front-run distribution signals (PRE-breakdown)
            has_dark_pool = signal.repeated_sell_blocks
            has_put_flow = signal.put_buying_at_ask or signal.signals.get("rising_put_oi", False)
            has_call_selling = signal.call_selling_at_bid
            has_vwap_loss = signal.vwap_loss
            
            # Count PRE-breakdown signals in pre-earnings context
            pre_earnings_pre_signals = sum([
                has_dark_pool, has_put_flow, has_call_selling,
                signal.signals.get("c_level_selling", False),
                signal.signals.get("insider_cluster", False),
            ])
            
            if pre_earnings_pre_signals >= 3 and has_vwap_loss:
                # Strong front-run: 3+ PRE signals + VWAP lost
                pre_earnings_adjustment = 0.15
                logger.info(
                    f"{signal.symbol}: PRE-EARNINGS FRONT-RUN DETECTED! "
                    f"{pre_earnings_pre_signals} predictive signals + VWAP loss (+0.15)"
                )
            elif pre_earnings_pre_signals >= 2:
                # Moderate front-run: 2+ PRE signals
                pre_earnings_adjustment = 0.08
                logger.info(
                    f"{signal.symbol}: Pre-earnings with {pre_earnings_pre_signals} "
                    f"predictive signals (+0.08)"
                )
            elif pre_earnings_pre_signals == 0:
                # No PRE signals in pre-earnings = risky
                pre_earnings_adjustment = -0.05
                logger.debug(f"{signal.symbol}: Pre-earnings penalty (no predictive signals)")
        
        # ===================================================================
        # FINAL SCORE CALCULATION
        # ===================================================================
        final_score = priority_score + predictive_bonus + pre_earnings_adjustment
        
        # Log what contributed
        if final_score > 0:
            pre_signals = summary.get("pre_signals", [])
            post_signals = summary.get("post_signals", [])
            if pre_signals:
                logger.debug(f"{signal.symbol}: PRE-breakdown signals: {pre_signals}")
            if post_signals:
                logger.debug(f"{signal.symbol}: POST-breakdown signals: {post_signals}")
        
        return min(max(final_score, 0.0), 1.0)  # Clamp between 0 and 1

    def calculate_sector_velocity_boost(
        self, 
        symbol: str, 
        peer_scores: Dict[str, float],
        has_distribution: bool,
        has_liquidity: bool
    ) -> float:
        """
        ARCHITECT-4 ADDITION: Sector Velocity Boost for High-Beta Names.
        
        This fixes CIFR / PLUG / ACHR-type misses without corrupting the core engine.
        
        Final Rule:
            if symbol in HIGH_BETA_GROUP:
                if peers_with_score > 0.30 >= 3:
                    sector_boost = +0.05 to +0.10 (max)
        
        Hard constraints (per Architect-4):
        - Apply ONLY if distribution_present AND liquidity_present
        - Never apply to large caps
        - Never apply in index-pinned regimes
        
        Args:
            symbol: Ticker to evaluate
            peer_scores: Dict of peer symbol -> score
            has_distribution: True if distribution signals present
            has_liquidity: True if liquidity vacuum present
            
        Returns:
            Boost value (0.0 to 0.10)
        """
        # Check if symbol is in high-beta universe
        if not self.config.is_high_beta(symbol):
            return 0.0
        
        # HARD CONSTRAINT: Must have both distribution AND liquidity
        if not has_distribution or not has_liquidity:
            logger.debug(f"{symbol}: Sector boost rejected - missing distribution/liquidity")
            return 0.0
        
        # Get sector peers
        peers = self.config.get_sector_peers(symbol)
        if not peers:
            return 0.0
        
        # Count peers with score >= 0.30
        qualifying_peers = sum(
            1 for peer in peers 
            if peer_scores.get(peer, 0) >= self.config.SECTOR_PEER_MIN_SCORE
        )
        
        # Need at least 3 qualifying peers
        if qualifying_peers < self.config.SECTOR_VELOCITY_MIN_PEERS:
            return 0.0
        
        # Calculate boost (capped at 0.10)
        # More peers = higher boost
        if qualifying_peers >= 5:
            boost = self.config.SECTOR_VELOCITY_BOOST_MAX  # 0.10
        elif qualifying_peers >= 4:
            boost = 0.08
        else:  # 3 peers
            boost = self.config.SECTOR_VELOCITY_BOOST_MIN  # 0.05
        
        logger.info(
            f"{symbol}: SECTOR VELOCITY BOOST +{boost:.2f} "
            f"({qualifying_peers} peers with score >= {self.config.SECTOR_PEER_MIN_SCORE})"
        )
        
        return boost

    async def get_distribution_candidates(
        self,
        symbols: List[str],
        min_score: float = 0.3
    ) -> List[DistributionSignal]:
        """
        Screen multiple symbols for distribution patterns.

        Args:
            symbols: List of symbols to analyze
            min_score: Minimum distribution score threshold

        Returns:
            List of DistributionSignals sorted by score descending
        """
        candidates = []

        for symbol in symbols:
            try:
                signal = await self.analyze(symbol)
                if signal.score >= min_score:
                    candidates.append(signal)
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")
                continue

        # Sort by score descending
        candidates.sort(key=lambda x: x.score, reverse=True)

        logger.info(
            f"Distribution screening: {len(candidates)}/{len(symbols)} "
            f"candidates above {min_score} threshold"
        )

        return candidates
