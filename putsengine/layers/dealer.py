"""
Dealer Positioning Layer - Put Wall / Dealer Pin Detection.

This is a MANDATORY gate that overrides ALL other engines.

Put Wall Detection:
- Massive put OI within ±1% of price
- Repeated bounces from that level
- IV not expanding (dealers confident in pin)

Why this matters:
Dealers will BUY DIPS to defend their put positions,
creating support that causes theta bleed for put buyers.

Rule: Never buy puts into a put wall.
"""

from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Tuple
from loguru import logger
import numpy as np

from putsengine.config import EngineConfig, Settings
from putsengine.models import GEXData, PriceBar, BlockReason
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient


class DealerPositioningLayer:
    """
    Dealer Positioning and Put Wall Detection Layer.

    This layer identifies dealer positioning that would work
    AGAINST put positions. Dealer hedging flows can override
    fundamental/technical signals.

    Key insight: Dealers control short-term price action.
    If dealers are defending a level, you cannot short through it.
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

    async def analyze(self, symbol: str) -> Tuple[bool, List[BlockReason], Optional[GEXData]]:
        """
        Analyze dealer positioning for a symbol.

        Args:
            symbol: Stock ticker to analyze

        Returns:
            Tuple of (is_blocked, block_reasons, gex_data)
        """
        logger.info(f"Analyzing dealer positioning for {symbol}...")

        block_reasons = []
        gex_data = None

        try:
            # Get current price
            quote = await self.alpaca.get_latest_quote(symbol)
            current_price = 0.0
            if quote and "quote" in quote:
                current_price = float(quote["quote"].get("ap", 0))

            if current_price == 0:
                # Fallback to snapshot
                snapshot = await self.polygon.get_snapshot(symbol)
                if snapshot and "ticker" in snapshot:
                    current_price = float(
                        snapshot["ticker"].get("lastTrade", {}).get("p", 0)
                    )

            if current_price == 0:
                logger.warning(f"Could not get current price for {symbol}")
                return (False, [], None)

            # Get GEX data
            gex_data = await self.unusual_whales.get_gex_data(symbol)

            # Check 1: Put Wall Detection
            put_wall_block = await self._check_put_wall(
                symbol, current_price, gex_data
            )
            if put_wall_block:
                block_reasons.append(BlockReason.PUT_WALL_SUPPORT)

            # Check 2: Positive GEX (dealers will buy dips)
            if gex_data and gex_data.net_gex > self.config.GEX_NEUTRAL_THRESHOLD:
                # Positive GEX = dealers long gamma = mean reversion
                block_reasons.append(BlockReason.POSITIVE_GEX)
                logger.warning(
                    f"{symbol}: BLOCKED - Positive GEX ({gex_data.net_gex:,.0f})"
                )

            # Check 3: Price at/above GEX flip level (dealer support)
            if gex_data and gex_data.gex_flip_level:
                if current_price >= gex_data.gex_flip_level * 0.99:  # Within 1%
                    # Price at flip level - dealers may defend
                    if gex_data.net_gex > 0:
                        block_reasons.append(BlockReason.POSITIVE_GEX)

            is_blocked = len(block_reasons) > 0

            logger.info(
                f"{symbol} dealer positioning: "
                f"Blocked={is_blocked}, "
                f"GEX={gex_data.net_gex if gex_data else 'N/A'}, "
                f"Put Wall={put_wall_block}"
            )

        except Exception as e:
            logger.error(f"Error in dealer analysis for {symbol}: {e}")

        return (is_blocked, block_reasons, gex_data)

    async def _check_put_wall(
        self,
        symbol: str,
        current_price: float,
        gex_data: Optional[GEXData]
    ) -> bool:
        """
        MANDATORY GATE: Check if there's a put wall near current price.
        
        Per Final Architect Blueprint:
        "This gate overrides ALL engines."
        
        Put wall = massive put OI that dealers will defend.
        Dealers will BUY DIPS to defend their put positions,
        creating support that causes theta bleed for put buyers.

        Detection (ANY triggers block):
        1. Large put OI within ±1% of price (>20% concentration)
        2. Historical bounces from that level (3+ bounces)
        3. IV not expanding (dealers confident in pin)
        
        Rule: Never buy puts into a put wall.
        """
        put_wall_detected = False
        put_wall_strike = None
        put_wall_strength = 0  # 0-3 based on signals
        
        try:
            # === SIGNAL 1: Check put wall from GEX data ===
            if gex_data and gex_data.put_wall:
                proximity = abs(current_price - gex_data.put_wall) / current_price
                if proximity <= self.config.PUT_WALL_PROXIMITY:
                    put_wall_detected = True
                    put_wall_strike = gex_data.put_wall
                    put_wall_strength += 1
                    logger.warning(
                        f"{symbol}: Put wall at {gex_data.put_wall:.2f} "
                        f"(current: {current_price:.2f}, proximity: {proximity:.2%})"
                    )

            # === SIGNAL 2: Check OI concentration by strike ===
            oi_data = await self.unusual_whales.get_oi_by_strike(symbol)
            
            # Handle both list and dict responses
            if isinstance(oi_data, list):
                data_list = oi_data
            elif isinstance(oi_data, dict):
                data_list = oi_data.get("data", [])
            else:
                data_list = []

            if data_list:
                max_put_oi = 0
                max_put_strike = None

                for strike_data in data_list:
                    if not isinstance(strike_data, dict):
                        continue
                    strike = float(strike_data.get("strike", strike_data.get("strike_price", 0)))
                    put_oi = int(strike_data.get("put_oi", strike_data.get("put_open_interest", 0)))

                    # Check if strike is within 5% of current price
                    if current_price > 0 and abs(strike - current_price) / current_price <= 0.05:
                        if put_oi > max_put_oi:
                            max_put_oi = put_oi
                            max_put_strike = strike

                if max_put_strike:
                    # Check if this is a significant put wall (>15% concentration)
                    total_put_oi = sum(
                        int(s.get("put_oi", s.get("put_open_interest", 0)))
                        for s in data_list if isinstance(s, dict)
                    )

                    concentration = max_put_oi / total_put_oi if total_put_oi > 0 else 0
                    
                    # Put wall = >15% of total put OI at one strike (lowered from 20%)
                    if concentration > 0.15:
                        proximity = abs(current_price - max_put_strike) / current_price
                        if proximity <= self.config.PUT_WALL_PROXIMITY * 1.5:  # Slightly wider
                            put_wall_detected = True
                            put_wall_strike = max_put_strike
                            put_wall_strength += 1
                            logger.warning(
                                f"{symbol}: OI concentration at {max_put_strike:.2f} "
                                f"({max_put_oi:,} contracts, {concentration:.1%} of total)"
                            )

            # === SIGNAL 3: Check historical bounces from put wall level ===
            if put_wall_strike:
                has_bounces = await self._check_historical_bounces(symbol, put_wall_strike)
                if has_bounces:
                    put_wall_strength += 1
                    logger.warning(f"{symbol}: Historical bounces detected at {put_wall_strike:.2f}")

            # === SIGNAL 4: Check if IV is NOT expanding (dealers confident) ===
            # If IV is low/stable, dealers are confident in their defense
            try:
                iv_data = await self.unusual_whales.get_iv_rank(symbol)
                if iv_data:
                    # Handle response format
                    if isinstance(iv_data, list) and len(iv_data) > 0:
                        iv_info = iv_data[0]
                    elif isinstance(iv_data, dict):
                        iv_info = iv_data.get("data", iv_data)
                        if isinstance(iv_info, list) and len(iv_info) > 0:
                            iv_info = iv_info[0]
                    else:
                        iv_info = {}
                    
                    if isinstance(iv_info, dict):
                        iv_change = float(iv_info.get("iv_change_1d", iv_info.get("iv_change", 0)) or 0)
                        iv_rank = float(iv_info.get("iv_rank", 50) or 50)
                        
                        # IV stable or declining + low rank = dealers confident
                        if iv_change <= 0.05 and iv_rank < 50:
                            if put_wall_detected:
                                put_wall_strength += 1
                                logger.warning(f"{symbol}: IV stable ({iv_change:+.1%}), IV rank {iv_rank:.0f}% - dealers confident")
            except Exception as e:
                logger.debug(f"Error checking IV for put wall: {e}")

            # === FINAL DECISION ===
            # Block if put wall detected with any strength
            if put_wall_detected:
                logger.warning(
                    f"{symbol}: PUT WALL BLOCK - Level: ${put_wall_strike:.2f}, "
                    f"Strength: {put_wall_strength}/4 signals. "
                    f"This gate overrides ALL engines."
                )
                return True

            return False

        except Exception as e:
            logger.warning(f"Error checking put wall for {symbol}: {e}")
            return False

    async def _check_historical_bounces(
        self,
        symbol: str,
        level: float
    ) -> bool:
        """
        Check if price has bounced from a level multiple times.

        Repeated bounces indicate strong support, likely from
        dealer hedging activity.
        """
        try:
            # Get daily bars
            bars = await self.polygon.get_daily_bars(
                symbol=symbol,
                from_date=date.today() - timedelta(days=30)
            )

            if len(bars) < 10:
                return False

            bounces = 0
            for bar in bars:
                # Check if bar touched level and bounced
                if bar.low <= level * 1.01 and bar.close > level * 1.02:
                    bounces += 1

            # 3+ bounces = strong support
            return bounces >= 3

        except Exception as e:
            logger.warning(f"Error checking bounces for {symbol}: {e}")
            return False

    async def get_dealer_score(self, symbol: str) -> float:
        """
        Calculate dealer positioning score for the PUT candidate.

        Higher score = better for puts (negative GEX, no put walls)
        Lower score = worse for puts (positive GEX, put walls present)

        Returns:
            Score from 0.0 to 1.0
        """
        score = 0.5  # Start neutral

        try:
            is_blocked, block_reasons, gex_data = await self.analyze(symbol)

            if is_blocked:
                return 0.0  # Hard block = 0 score

            if gex_data:
                # Negative GEX is good for puts
                if gex_data.net_gex < 0:
                    score += 0.25
                    # Very negative = even better
                    if gex_data.net_gex < -1000000:
                        score += 0.15

                # Dealer delta negative = bearish
                if gex_data.dealer_delta < 0:
                    score += 0.10

                # Price below GEX flip = dealers short gamma
                quote = await self.alpaca.get_latest_quote(symbol)
                if quote and "quote" in quote:
                    current_price = float(quote["quote"].get("ap", 0))
                    if gex_data.gex_flip_level and current_price < gex_data.gex_flip_level:
                        score += 0.15

        except Exception as e:
            logger.warning(f"Error calculating dealer score for {symbol}: {e}")

        return min(max(score, 0.0), 1.0)

    async def is_put_blocked(self, symbol: str) -> Tuple[bool, List[BlockReason]]:
        """
        Quick check if put position would be blocked by dealer positioning.

        Returns:
            Tuple of (is_blocked, list_of_reasons)
        """
        is_blocked, reasons, _ = await self.analyze(symbol)
        return (is_blocked, reasons)

    async def get_optimal_strike_range(
        self,
        symbol: str
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Get optimal strike range based on dealer positioning.

        Avoid strikes with heavy put OI (put walls).
        Target strikes below put walls for better risk/reward.

        Returns:
            Tuple of (min_strike, max_strike) or (None, None) if blocked
        """
        try:
            # Get current price
            quote = await self.alpaca.get_latest_quote(symbol)
            if not quote or "quote" not in quote:
                return (None, None)

            current_price = float(quote["quote"].get("ap", 0))
            if current_price == 0:
                return (None, None)

            # Get GEX data for put wall
            gex_data = await self.unusual_whales.get_gex_data(symbol)

            # Default range: 5-15% OTM
            min_strike = current_price * 0.85
            max_strike = current_price * 0.95

            if gex_data and gex_data.put_wall:
                # If put wall exists, target below it
                if gex_data.put_wall < current_price:
                    # Put wall is support - strikes should be below it
                    max_strike = min(max_strike, gex_data.put_wall * 0.98)

            return (min_strike, max_strike)

        except Exception as e:
            logger.warning(f"Error getting strike range for {symbol}: {e}")
            return (None, None)

    async def screen_for_dealer_support(
        self,
        symbols: List[str]
    ) -> Dict[str, Tuple[bool, float]]:
        """
        Screen symbols for dealer support/blocking.

        Returns:
            Dict of symbol -> (is_blocked, dealer_score)
        """
        results = {}

        for symbol in symbols:
            try:
                is_blocked, _, _ = await self.analyze(symbol)
                score = await self.get_dealer_score(symbol)
                results[symbol] = (is_blocked, score)
            except Exception as e:
                logger.error(f"Error screening {symbol}: {e}")
                results[symbol] = (False, 0.5)

        return results
