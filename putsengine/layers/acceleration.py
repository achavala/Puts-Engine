"""
Acceleration Window Layer - Layer 4 in the PUT detection pipeline.

This layer handles TIMING - not idea generation.
Entry timing is critical for put options due to theta decay.

24-48h Pre-Entry Checklist (preferred, not mandatory):
- Price below VWAP, 20-EMA, prior low
- Failed reclaim attempts
- Put volume rising but IV still reasonable
- Net delta turning negative
- Gamma flipping short

HARD BLOCK - Late Entry Filter:
IF IV spikes >20% same session AND put volume explodes late day
-> SKIP (you are late, negative expectancy)
"""

from datetime import datetime, date, timedelta
from typing import Optional, List, Dict
from loguru import logger
import numpy as np

from putsengine.config import EngineConfig, Settings
from putsengine.models import AccelerationWindow, PriceBar, GEXData, EngineType
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient


class AccelerationWindowLayer:
    """
    Acceleration Window Detection Layer.

    This layer determines if timing is right for put entry.
    The best puts are bought BEFORE the move, not during.

    Key insight: Late puts = negative expectancy.
    IV expansion happens first, then price moves.
    If you buy after IV spikes, you're paying for the move.
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

    async def analyze(self, symbol: str) -> AccelerationWindow:
        """
        Analyze acceleration window timing for a symbol.

        Args:
            symbol: Stock ticker to analyze

        Returns:
            AccelerationWindow with timing analysis
        """
        logger.info(f"Analyzing acceleration window for {symbol}...")

        window = AccelerationWindow(
            symbol=symbol,
            timestamp=datetime.now()
        )

        try:
            # Get price data
            minute_bars = await self.polygon.get_minute_bars(
                symbol=symbol,
                from_date=date.today() - timedelta(days=5),
                limit=5000
            )

            daily_bars = await self.polygon.get_daily_bars(
                symbol=symbol,
                from_date=date.today() - timedelta(days=30)
            )

            if not minute_bars or not daily_bars:
                logger.warning(f"Insufficient data for {symbol}")
                return window

            # Calculate indicators
            current_price = minute_bars[-1].close
            vwap = self._calculate_today_vwap(minute_bars)
            ema_20 = self._calculate_ema([b.close for b in daily_bars], 20)
            prior_low = self._get_prior_low(daily_bars)

            # 1. Price below VWAP
            window.price_below_vwap = current_price < vwap

            # 2. Price below 20-EMA
            window.price_below_ema20 = current_price < ema_20 if ema_20 else False

            # 3. Price below prior low
            window.price_below_prior_low = current_price < prior_low if prior_low else False

            # 4. Failed reclaim attempts
            window.failed_reclaim = self._detect_failed_reclaims(minute_bars, vwap)

            # 5. Put volume rising with reasonable IV
            volume_iv = await self._check_put_volume_iv(symbol)
            window.put_volume_rising = volume_iv.get("volume_rising", False)
            window.iv_reasonable = volume_iv.get("iv_reasonable", True)

            # 6. Net delta turning negative
            window.net_delta_negative = await self._check_net_delta(symbol)

            # 7. Gamma flipping short + Zero-Gamma Trigger Detection
            # Per Final Architect: "Price below Zero-Gamma / Volatility Trigger"
            gamma_result = await self._check_gamma_flip(symbol)
            window.gamma_flipping_short = gamma_result[0]
            
            # Store zero-gamma info for reporting (if we have the fields)
            below_zero_gamma = gamma_result[1]
            zero_gamma_level = gamma_result[2]
            
            if below_zero_gamma:
                logger.info(
                    f"{symbol}: Zero-Gamma trigger active - "
                    f"price below ${zero_gamma_level:.2f if zero_gamma_level else 'N/A'}"
                )

            # 8. RSI Overbought Detection (for Engine 3 - Snapback)
            # Per Architect: RSI > 75 required for snapback
            rsi_values = self._calculate_rsi([b.close for b in daily_bars], period=14)
            if rsi_values and len(rsi_values) > 0:
                current_rsi = rsi_values[-1]
                window.rsi_overbought = current_rsi > 75
            
            # 9. Lower High Formation (for Engine 3 - Snapback)
            # Per Architect: Lower high must be formed for valid snapback
            window.lower_high_formed = self._detect_lower_high(daily_bars)

            # CRITICAL: Check for late entry (HARD BLOCK)
            window.is_late_entry = await self._check_late_entry(symbol, minute_bars)

            # Determine if window is valid (includes Anti-Trinity engine detection)
            window.is_valid = self._evaluate_window(window)

            logger.info(
                f"{symbol} acceleration window: "
                f"Valid={window.is_valid}, "
                f"Engine={window.engine_type.value}, "
                f"Late={window.is_late_entry}, "
                f"SnapbackOnly={window.is_snapback_only}, "
                f"VWAP={window.price_below_vwap}, "
                f"EMA20={window.price_below_ema20}"
            )

        except Exception as e:
            logger.error(f"Error in acceleration analysis for {symbol}: {e}")

        return window

    def _calculate_today_vwap(self, bars: List[PriceBar]) -> float:
        """Calculate VWAP for today's session."""
        today = date.today()
        today_bars = [b for b in bars if b.timestamp.date() == today]

        if not today_bars:
            return 0.0

        total_volume = 0
        total_vwap = 0.0

        for bar in today_bars:
            typical_price = (bar.high + bar.low + bar.close) / 3
            total_vwap += typical_price * bar.volume
            total_volume += bar.volume

        return total_vwap / total_volume if total_volume > 0 else today_bars[-1].close

    def _calculate_ema(self, prices: List[float], period: int) -> Optional[float]:
        """Calculate Exponential Moving Average."""
        if len(prices) < period:
            return None

        multiplier = 2 / (period + 1)
        ema = np.mean(prices[:period])  # Start with SMA

        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema

        return ema

    def _get_prior_low(self, daily_bars: List[PriceBar]) -> Optional[float]:
        """Get the prior session's low."""
        if len(daily_bars) < 2:
            return None

        # Get yesterday's low
        return daily_bars[-2].low

    def _calculate_rsi(self, prices: List[float], period: int = 14) -> List[float]:
        """
        Calculate RSI indicator.
        Per Architect: RSI > 75 indicates overbought (snapback condition).
        """
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

    def _detect_lower_high(self, daily_bars: List[PriceBar]) -> bool:
        """
        Detect if price is forming lower highs.
        Per Architect: Required for Engine 3 (Snapback) validity.
        
        Lower high = most recent swing high is lower than prior swing high.
        This indicates distribution / exhaustion.
        """
        if len(daily_bars) < 10:
            return False

        # Get recent 10 bars
        recent = daily_bars[-10:]
        highs = [b.high for b in recent]

        # Find the two most recent local highs
        local_highs = []
        for i in range(1, len(highs) - 1):
            if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
                local_highs.append(highs[i])

        # Need at least 2 local highs to compare
        if len(local_highs) < 2:
            return False

        # Check if most recent high is lower than prior high
        return local_highs[-1] < local_highs[-2]

    def _detect_failed_reclaims(
        self,
        bars: List[PriceBar],
        vwap: float
    ) -> bool:
        """Detect failed reclaim attempts of VWAP."""
        today = date.today()
        today_bars = [b for b in bars if b.timestamp.date() == today]

        if len(today_bars) < 30:
            return False

        failed_reclaims = 0
        below_vwap = False

        for bar in today_bars:
            if bar.close < vwap:
                below_vwap = True
            elif below_vwap and bar.high >= vwap:
                # Attempted reclaim
                if bar.close < vwap:
                    failed_reclaims += 1
                    below_vwap = True  # Still below
                else:
                    below_vwap = False  # Successful reclaim

        return failed_reclaims >= 2

    async def _check_put_volume_iv(self, symbol: str) -> Dict[str, bool]:
        """
        Check if put volume is rising with reasonable IV.

        Rising put volume is bullish for puts.
        But if IV has already spiked, opportunity is gone.
        """
        result = {"volume_rising": False, "iv_reasonable": True}

        try:
            # Get options volume data
            volume_data = await self.unusual_whales.get_options_volume(symbol)

            if not volume_data:
                return result

            # Handle both dict with "data" key and direct response
            data = volume_data.get("data", volume_data) if isinstance(volume_data, dict) else volume_data

            # If data is a list, get first element
            if isinstance(data, list):
                if len(data) == 0:
                    return result
                data = data[0]

            if not isinstance(data, dict):
                return result

            # Check put volume trend
            put_volume = data.get("put_volume", 0)
            put_volume_avg = data.get("put_volume_avg", put_volume)

            if put_volume_avg > 0:
                result["volume_rising"] = put_volume > put_volume_avg * 1.2

            # Check IV level
            iv_rank = data.get("iv_rank", 50)
            iv_change = data.get("iv_change_1d", 0)

            # IV is reasonable if:
            # - IV rank below 70 (not already elevated)
            # - IV change today < 20%
            result["iv_reasonable"] = (
                iv_rank < 70 and
                iv_change < self.config.IV_SPIKE_THRESHOLD
            )

        except Exception as e:
            logger.warning(f"Error checking put volume/IV for {symbol}: {e}")

        return result

    async def _check_net_delta(self, symbol: str) -> bool:
        """Check if net delta is turning negative (bearish)."""
        try:
            gex_data = await self.unusual_whales.get_gex_data(symbol)

            if gex_data and gex_data.dealer_delta < 0:
                return True

        except Exception as e:
            logger.warning(f"Error checking net delta for {symbol}: {e}")

        return False

    async def _check_gamma_flip(self, symbol: str) -> tuple:
        """
        Check if gamma is flipping to short.
        
        Per Final Architect Report:
        "Price below Zero-Gamma / Volatility Trigger" is PRIMARY ENGINE 1 signal.

        When dealers flip from long gamma to short gamma,
        they go from buying dips to selling dips - amplifying moves.
        
        Returns:
            Tuple of (is_gamma_short, below_zero_gamma, zero_gamma_level)
        """
        is_gamma_short = False
        below_zero_gamma = False
        zero_gamma_level = None
        
        try:
            gex_data = await self.unusual_whales.get_gex_data(symbol)

            if gex_data:
                # Current price below GEX flip level = dealers short gamma
                current_quote = await self.alpaca.get_latest_quote(symbol)
                if current_quote and "quote" in current_quote:
                    current_price = float(current_quote["quote"].get("ap", 0))
                    
                    # Zero-Gamma / Volatility Trigger level
                    if gex_data.gex_flip_level:
                        zero_gamma_level = gex_data.gex_flip_level
                        below_zero_gamma = current_price < gex_data.gex_flip_level
                        
                        if below_zero_gamma:
                            is_gamma_short = True
                            logger.info(
                                f"{symbol}: BELOW ZERO-GAMMA TRIGGER - "
                                f"Price ${current_price:.2f} < Trigger ${zero_gamma_level:.2f}"
                            )

                # Or simply negative GEX
                if gex_data.net_gex < 0:
                    is_gamma_short = True

        except Exception as e:
            logger.warning(f"Error checking gamma flip for {symbol}: {e}")

        return (is_gamma_short, below_zero_gamma, zero_gamma_level)

    async def _check_late_entry(
        self,
        symbol: str,
        bars: List[PriceBar]
    ) -> bool:
        """
        CRITICAL: Check if we're too late for entry.

        Late entry conditions (ANY = block):
        - IV spiked >20% same session
        - Put volume exploded in last hour
        - Price already broke down significantly

        Late puts have negative expectancy due to:
        - Elevated IV = expensive premiums
        - Theta decay on already-moved options
        - Mean reversion risk after initial move
        """
        try:
            # Check IV spike
            volume_data = await self.unusual_whales.get_options_volume(symbol)
            if volume_data:
                # Handle both dict with "data" key and direct response
                data = volume_data.get("data", volume_data) if isinstance(volume_data, dict) else volume_data
                if isinstance(data, list) and len(data) > 0:
                    data = data[0]
                if isinstance(data, dict):
                    iv_change = data.get("iv_change_1d", 0)
                    if iv_change > self.config.IV_SPIKE_THRESHOLD:
                        logger.warning(f"{symbol}: LATE ENTRY - IV spiked {iv_change:.1%}")
                        return True

            # Check for volume explosion in last hour
            today = date.today()
            today_bars = [b for b in bars if b.timestamp.date() == today]

            if len(today_bars) > 60:
                last_hour = today_bars[-60:]
                earlier = today_bars[:-60]

                last_hour_vol = sum(b.volume for b in last_hour)
                earlier_avg_vol = sum(b.volume for b in earlier) / len(earlier) * 60 if earlier else last_hour_vol

                if last_hour_vol > earlier_avg_vol * 2:
                    # Check if price dropped significantly too
                    last_hour_change = (last_hour[-1].close - last_hour[0].open) / last_hour[0].open
                    if last_hour_change < -0.03:  # >3% drop in last hour
                        logger.warning(f"{symbol}: LATE ENTRY - Volume explosion + price drop")
                        return True

            # Check if already broken down significantly today
            if today_bars:
                day_high = max(b.high for b in today_bars)
                current = today_bars[-1].close
                intraday_drop = (current - day_high) / day_high

                if intraday_drop < -0.05:  # >5% drop from day high
                    logger.warning(f"{symbol}: LATE ENTRY - Already down {intraday_drop:.1%} today")
                    return True

        except Exception as e:
            logger.warning(f"Error checking late entry for {symbol}: {e}")

        return False

    def _evaluate_window(self, window: AccelerationWindow) -> bool:
        """
        Evaluate if acceleration window is valid for entry.
        
        Per Final Architect Blueprint - Anti-Trinity Engine Architecture:
        
        Engine 1 (Gamma Drain): Flow-driven, highest conviction
          - Negative GEX + delta flipping negative
          - Put sweeps detected
          
        Engine 2 (Distribution Trap): Event-driven
          - Gap up → red close
          - Failed breakout + call selling
          
        Engine 3 (Snapback): CONSTRAINED - NEVER triggers alone
          - RSI > 75
          - Lower high formed
          - MUST be confirmed by Engine 1 or 2

        Requirements:
        - NOT a late entry (hard requirement)
        - NOT snapback-only (Engine 3 cannot trigger alone)
        - Price weakness (at least 2 of: below VWAP, EMA20, prior low)
        - Either failed reclaim OR put volume rising
        - IV must be reasonable
        """
        # === HARD BLOCKS ===
        
        # Block: Late entry
        if window.is_late_entry:
            return False

        # Block: IV unreasonable
        if not window.iv_reasonable:
            return False

        # === ANTI-TRINITY ENGINE DETECTION ===
        
        # Engine 1: Gamma Drain (Flow-Driven)
        # Conditions: Negative gamma/delta + put volume rising
        engine_1_active = (
            window.net_delta_negative and 
            window.gamma_flipping_short and
            window.put_volume_rising
        )
        
        # Engine 2: Distribution Trap (Event-Driven)
        # Conditions: Failed reclaim + price weakness
        price_weakness = sum([
            window.price_below_vwap,
            window.price_below_ema20,
            window.price_below_prior_low
        ])
        engine_2_active = window.failed_reclaim and price_weakness >= 2
        
        # Engine 3: Snapback (Overextension) - CONSTRAINED
        # Conditions: RSI overbought + lower high + price weakness
        # Per Architect: "NEVER allow Engine 3 to trigger alone"
        engine_3_active = window.rsi_overbought and window.lower_high_formed
        
        # Determine primary engine
        if engine_1_active:
            window.engine_type = EngineType.GAMMA_DRAIN
        elif engine_2_active:
            window.engine_type = EngineType.DISTRIBUTION_TRAP
        elif engine_3_active:
            window.engine_type = EngineType.SNAPBACK
        else:
            window.engine_type = EngineType.NONE
        
        # === CRITICAL CONSTRAINT: Snapback Cannot Trigger Alone ===
        # Per Architect Blueprint: "Engine 3 must be confirmed by Engine 1 or 2"
        if engine_3_active and not (engine_1_active or engine_2_active):
            window.is_snapback_only = True
            logger.warning(
                f"BLOCKED: Snapback-only signal. Engine 3 cannot trigger alone. "
                f"RSI overbought but no gamma drain or distribution confirmation."
            )
            return False
        
        # === STANDARD VALIDATION ===
        
        if price_weakness < 2:
            return False

        # Need either failed reclaim or put volume confirmation
        confirmation = window.failed_reclaim or window.put_volume_rising

        if not confirmation:
            return False

        return True

    async def is_in_acceleration_window(self, symbol: str) -> bool:
        """Quick check if symbol is in valid acceleration window."""
        window = await self.analyze(symbol)
        return window.is_valid

    async def screen_acceleration(
        self,
        symbols: List[str]
    ) -> List[AccelerationWindow]:
        """
        Screen symbols for valid acceleration windows.

        Returns only symbols with valid timing for put entry.
        """
        valid_windows = []

        for symbol in symbols:
            try:
                window = await self.analyze(symbol)
                if window.is_valid:
                    valid_windows.append(window)
            except Exception as e:
                logger.error(f"Error screening {symbol}: {e}")
                continue

        logger.info(
            f"Acceleration screening: {len(valid_windows)}/{len(symbols)} "
            f"symbols in valid window"
        )

        return valid_windows
