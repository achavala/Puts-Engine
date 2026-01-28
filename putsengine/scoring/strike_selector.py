"""
Strike and DTE Selection - Institutional-Grade Contract Selection for PUT trades.

CORE PRINCIPLES (Puts):
- Cheap stocks: % OTM works
- Expensive stocks: Dollar distance works
- Delta ALWAYS gates
- Puts = faster moves than calls, can bias closer to ATM

PRICE TIERS:
- $10-$30:    10-16% below spot, delta -0.20 to -0.30
- $30-$100:   7-12% below spot, delta -0.22 to -0.32
- $100-$300:  4-8% below spot, delta -0.25 to -0.35
- $300-$500:  $15-$35 below spot, delta -0.25 to -0.40
- $500-$800:  $20-$50 below spot, delta -0.22 to -0.35
- $800-$1200: $30-$70 below spot, delta -0.20 to -0.30
- $1200+:     $40-$90 below spot, delta >= -0.20

DTE SELECTION:
- Class A (>=0.68): nearest Friday with 7-12 DTE
- Class B (0.35-0.44): next Friday with 12-21 DTE
"""

from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass
from enum import Enum
from loguru import logger

from putsengine.config import Settings
from putsengine.models import OptionsContract, PutCandidate
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient


class PriceTier(Enum):
    """Price tiers for strike selection logic."""
    GAMMA_SWEET_SPOT = "gamma_sweet_spot"   # $10-$30
    LOW_MID = "low_mid"                      # $30-$100
    MID = "mid"                              # $100-$300
    HIGH = "high"                            # $300-$500
    PREMIUM = "premium"                      # $500-$800
    ULTRA_PREMIUM = "ultra_premium"          # $800-$1200
    MEGA = "mega"                            # $1200+


@dataclass
class StrikeTarget:
    """Target strike parameters for a price tier."""
    tier: PriceTier
    price_range: Tuple[float, float]
    
    # For lower-priced stocks: use % below spot
    pct_below_min: float = 0.0
    pct_below_max: float = 0.0
    
    # For higher-priced stocks: use dollar distance
    dollar_below_min: float = 0.0
    dollar_below_max: float = 0.0
    
    # Delta band
    delta_min: float = -0.40
    delta_max: float = -0.20
    
    # Target multiple
    target_multiple: str = "3x-6x"
    
    # Use dollars instead of percentage
    use_dollars: bool = False


# Strike selection rules by price tier
STRIKE_RULES: Dict[PriceTier, StrikeTarget] = {
    PriceTier.GAMMA_SWEET_SPOT: StrikeTarget(
        tier=PriceTier.GAMMA_SWEET_SPOT,
        price_range=(10, 30),
        pct_below_min=0.10,   # 10% below spot
        pct_below_max=0.16,   # 16% below spot
        delta_min=-0.30,
        delta_max=-0.20,
        target_multiple="4x-8x",
        use_dollars=False
    ),
    PriceTier.LOW_MID: StrikeTarget(
        tier=PriceTier.LOW_MID,
        price_range=(30, 100),
        pct_below_min=0.07,   # 7% below spot
        pct_below_max=0.12,   # 12% below spot
        delta_min=-0.32,
        delta_max=-0.22,
        target_multiple="3x-6x",
        use_dollars=False
    ),
    PriceTier.MID: StrikeTarget(
        tier=PriceTier.MID,
        price_range=(100, 300),
        pct_below_min=0.04,   # 4% below spot
        pct_below_max=0.08,   # 8% below spot
        delta_min=-0.35,
        delta_max=-0.25,
        target_multiple="2.5x-5x",
        use_dollars=False
    ),
    PriceTier.HIGH: StrikeTarget(
        tier=PriceTier.HIGH,
        price_range=(300, 500),
        dollar_below_min=15,  # $15 below spot
        dollar_below_max=35,  # $35 below spot
        delta_min=-0.40,
        delta_max=-0.25,
        target_multiple="2x-4x",
        use_dollars=True      # DO NOT use % OTM
    ),
    PriceTier.PREMIUM: StrikeTarget(
        tier=PriceTier.PREMIUM,
        price_range=(500, 800),
        dollar_below_min=20,  # $20 below spot
        dollar_below_max=50,  # $50 below spot
        delta_min=-0.35,
        delta_max=-0.22,
        target_multiple="2x-3.5x",
        use_dollars=True
    ),
    PriceTier.ULTRA_PREMIUM: StrikeTarget(
        tier=PriceTier.ULTRA_PREMIUM,
        price_range=(800, 1200),
        dollar_below_min=30,  # $30 below spot
        dollar_below_max=70,  # $70 below spot
        delta_min=-0.30,
        delta_max=-0.20,
        target_multiple="1.5x-3x",
        use_dollars=True
    ),
    PriceTier.MEGA: StrikeTarget(
        tier=PriceTier.MEGA,
        price_range=(1200, float('inf')),
        dollar_below_min=40,  # $40 below spot
        dollar_below_max=90,  # $90 below spot
        delta_min=-0.25,
        delta_max=-0.20,
        target_multiple="1.5x-2.5x",
        use_dollars=True
    ),
}


class StrikeSelector:
    """
    Institutional-Grade Strike and DTE Selection Engine.
    
    Implements:
    - Price-tier based strike selection (% vs dollar distance)
    - Delta gating (always enforced)
    - ATR-based adaptive strike selection (institutional way)
    - Liquidity gates (spread, OI, volume)
    - Put wall safety check
    
    Delta Target Band: -0.25 to -0.40
    Sweet Spot: -0.325
    """

    # Universal liquidity gates
    DELTA_FLOOR = -0.18           # Too far OTM = lottery (REJECT)
    MAX_SPREAD_PCT = 0.10         # >10% spreads bleed (REJECT)
    MIN_OI = 300                  # Minimum open interest
    MIN_VOLUME = 50               # Minimum volume (relaxed)
    MIN_OI_FOR_LOW_VOLUME = 800   # If volume low, require higher OI
    VOLUME_OI_RATIO = 0.20        # Alternative: volume/OI >= 0.2
    
    # Delta targets
    IDEAL_DELTA = -0.325          # Sweet spot
    DELTA_MIN = -0.40             # Minimum delta (most aggressive)
    DELTA_MAX = -0.25             # Maximum delta (most conservative)
    
    # DTE rules
    CLASS_A_DTE_MIN = 7
    CLASS_A_DTE_MAX = 12
    CLASS_B_DTE_MIN = 12
    CLASS_B_DTE_MAX = 21
    
    # ATR multipliers by price tier (institutional approach)
    ATR_MULTIPLIERS = {
        PriceTier.GAMMA_SWEET_SPOT: 2.0,
        PriceTier.LOW_MID: 1.7,
        PriceTier.MID: 1.5,
        PriceTier.HIGH: 1.3,
        PriceTier.PREMIUM: 1.3,
        PriceTier.ULTRA_PREMIUM: 1.2,
        PriceTier.MEGA: 1.2,
    }

    def __init__(
        self,
        alpaca: AlpacaClient,
        polygon: PolygonClient,
        settings: Settings
    ):
        self.alpaca = alpaca
        self.polygon = polygon
        self.settings = settings

    def get_price_tier(self, price: float) -> PriceTier:
        """Determine price tier for strike selection logic."""
        if price < 10:
            return PriceTier.GAMMA_SWEET_SPOT  # Treat very cheap same as gamma sweet spot
        elif price < 30:
            return PriceTier.GAMMA_SWEET_SPOT
        elif price < 100:
            return PriceTier.LOW_MID
        elif price < 300:
            return PriceTier.MID
        elif price < 500:
            return PriceTier.HIGH
        elif price < 800:
            return PriceTier.PREMIUM
        elif price < 1200:
            return PriceTier.ULTRA_PREMIUM
        else:
            return PriceTier.MEGA

    def calculate_target_strike(
        self,
        spot_price: float,
        atr: Optional[float] = None
    ) -> Tuple[float, float, str]:
        """
        Calculate target strike range based on price tier.
        
        Args:
            spot_price: Current stock price
            atr: 14-day ATR (if available, uses institutional approach)
            
        Returns:
            Tuple of (min_strike, max_strike, reasoning)
        """
        tier = self.get_price_tier(spot_price)
        rules = STRIKE_RULES[tier]
        
        # If ATR available, use institutional approach
        if atr and atr > 0:
            k = self.ATR_MULTIPLIERS.get(tier, 1.5)
            target_distance = k * atr
            
            min_strike = spot_price - target_distance * 1.3
            max_strike = spot_price - target_distance * 0.7
            
            reason = f"ATR-based: {k}x ATR({atr:.2f})=${target_distance:.2f} below spot"
            
        elif rules.use_dollars:
            # Dollar-distance for expensive stocks
            min_strike = spot_price - rules.dollar_below_max
            max_strike = spot_price - rules.dollar_below_min
            
            reason = f"Tier={tier.value}, ${rules.dollar_below_min}-${rules.dollar_below_max} below spot"
            
        else:
            # Percentage-based for cheaper stocks
            min_strike = spot_price * (1 - rules.pct_below_max)
            max_strike = spot_price * (1 - rules.pct_below_min)
            
            reason = f"Tier={tier.value}, {rules.pct_below_min*100:.0f}%-{rules.pct_below_max*100:.0f}% below spot"
        
        return (min_strike, max_strike, reason)

    def get_delta_range(self, spot_price: float) -> Tuple[float, float]:
        """Get delta range for price tier."""
        tier = self.get_price_tier(spot_price)
        rules = STRIKE_RULES[tier]
        return (rules.delta_min, rules.delta_max)

    def get_dte_range(self, score: float) -> Tuple[int, int]:
        """
        Get DTE range based on candidate score.
        
        - Class A (>=0.68): 7-12 DTE (nearest Friday)
        - Class B (0.35-0.67): 12-21 DTE (more time, less gamma whipsaw)
        """
        if score >= 0.68:
            return (self.CLASS_A_DTE_MIN, self.CLASS_A_DTE_MAX)
        else:
            return (self.CLASS_B_DTE_MIN, self.CLASS_B_DTE_MAX)

    def apply_universal_filters(
        self,
        contract: OptionsContract,
        spot_price: float
    ) -> Tuple[bool, str]:
        """
        Apply universal liquidity and delta filters.
        
        Returns:
            Tuple of (passed, rejection_reason)
        """
        # Delta floor - too far OTM = lottery
        if contract.delta != 0 and contract.delta > self.DELTA_FLOOR:
            return (False, f"Delta too shallow ({contract.delta:.2f} > {self.DELTA_FLOOR})")
        
        # Spread check - >10% spreads bleed
        if contract.spread_pct > self.MAX_SPREAD_PCT:
            return (False, f"Spread too wide ({contract.spread_pct:.1%} > {self.MAX_SPREAD_PCT:.0%})")
        
        # OI check
        if contract.open_interest < self.MIN_OI:
            return (False, f"OI too low ({contract.open_interest} < {self.MIN_OI})")
        
        # Volume check with OI fallback
        if contract.volume < self.MIN_VOLUME and contract.open_interest < self.MIN_OI_FOR_LOW_VOLUME:
            # Alternative: check volume/OI ratio
            if contract.open_interest > 0:
                vol_oi_ratio = contract.volume / contract.open_interest
                if vol_oi_ratio < self.VOLUME_OI_RATIO:
                    return (False, f"Volume too low ({contract.volume}) and OI ratio poor ({vol_oi_ratio:.2f})")
            else:
                return (False, f"Volume too low ({contract.volume}) and no OI fallback")
        
        # Must be OTM
        if contract.strike >= spot_price:
            return (False, "Not OTM")
        
        return (True, "Passed")

    def check_late_entry_filter(
        self,
        contract: OptionsContract,
        iv_spike_intraday: float,
        price_down_from_high_pct: float
    ) -> Tuple[bool, str]:
        """
        Late entry filter - avoid paying for the move.
        
        If IV has spiked >20% and price is already down >5%, we're late.
        """
        if iv_spike_intraday > 0.20 and price_down_from_high_pct > 0.05:
            return (False, f"Late entry: IV up {iv_spike_intraday:.0%}, price down {price_down_from_high_pct:.0%}")
        return (True, "Passed")

    async def select_contract(
        self,
        candidate: PutCandidate,
        atr: Optional[float] = None
    ) -> Optional[OptionsContract]:
        """
        Select optimal put contract for a candidate.
        
        Implements full institutional-grade selection logic.
        
        Args:
            candidate: PutCandidate with price data populated
            atr: 14-day ATR for adaptive strike selection
            
        Returns:
            Optimal OptionsContract or None if no suitable contract found
        """
        symbol = candidate.symbol
        current_price = candidate.current_price
        score = candidate.score

        if current_price == 0:
            logger.warning(f"No current price for {symbol}")
            return None

        # Get price tier info
        tier = self.get_price_tier(current_price)
        rules = STRIKE_RULES[tier]
        
        # Calculate target strike range
        min_strike, max_strike, strike_reason = self.calculate_target_strike(
            current_price, atr
        )
        
        # Get delta range for this tier
        delta_min, delta_max = self.get_delta_range(current_price)
        
        # Get DTE range based on score
        dte_min, dte_max = self.get_dte_range(score)
        
        logger.info(
            f"Selecting put for {symbol} | "
            f"Price: ${current_price:.2f} | Tier: {tier.value} | "
            f"Target Strike: ${min_strike:.2f}-${max_strike:.2f} | "
            f"Delta: {delta_min} to {delta_max} | "
            f"DTE: {dte_min}-{dte_max} | "
            f"Reason: {strike_reason}"
        )

        try:
            # Get valid expirations
            valid_expirations = self._get_valid_expirations(dte_min, dte_max)
            
            if not valid_expirations:
                logger.warning(f"No valid expirations for {symbol} in DTE range {dte_min}-{dte_max}")
                return None

            # Get options chain with price-tier appropriate bounds
            all_contracts = []
            for exp_date in valid_expirations[:3]:  # Limit API calls
                contracts = await self.alpaca.get_options_chain(
                    underlying=symbol,
                    expiration_date=exp_date,
                    option_type="put",
                    strike_price_gte=min_strike * 0.95,  # 5% buffer
                    strike_price_lte=max_strike * 1.05   # 5% buffer
                )
                all_contracts.extend(contracts)

            if not all_contracts:
                logger.warning(f"No put contracts found for {symbol}")
                return None

            # Get quotes for contracts
            contract_symbols = [c.symbol for c in all_contracts[:50]]
            quotes = await self.alpaca.get_options_quotes(contract_symbols)

            # Enrich contracts with quote data
            enriched_contracts = self._enrich_with_quotes(all_contracts, quotes)

            # Filter contracts with institutional logic
            valid_contracts = []
            for contract in enriched_contracts:
                # Apply universal filters
                passed, reason = self.apply_universal_filters(contract, current_price)
                if not passed:
                    logger.debug(f"Rejected {contract.symbol}: {reason}")
                    continue
                
                # Check DTE
                if not (dte_min <= contract.dte <= dte_max):
                    continue
                
                # Check delta in tier-specific range
                if contract.delta != 0:
                    if not (delta_min <= contract.delta <= delta_max):
                        logger.debug(f"Rejected {contract.symbol}: delta {contract.delta:.2f} not in [{delta_min}, {delta_max}]")
                        continue
                
                # Check strike in target range
                if not (min_strike <= contract.strike <= max_strike):
                    logger.debug(f"Rejected {contract.symbol}: strike ${contract.strike:.2f} not in [${min_strike:.2f}, ${max_strike:.2f}]")
                    continue
                
                valid_contracts.append(contract)

            if not valid_contracts:
                logger.warning(f"No valid contracts after filtering for {symbol}")
                return None

            # Rank and select best contract
            best = self._rank_and_select(valid_contracts, current_price, tier)

            if best:
                logger.info(
                    f"SELECTED: {best.symbol} | "
                    f"Strike: ${best.strike:.2f} | "
                    f"DTE: {best.dte} | "
                    f"Delta: {best.delta:.2f} | "
                    f"Mid: ${best.mid_price:.2f} | "
                    f"Spread: {best.spread_pct:.1%} | "
                    f"OI: {best.open_interest} | "
                    f"Reason: {strike_reason}"
                )

            return best

        except Exception as e:
            logger.error(f"Error selecting contract for {symbol}: {e}")
            return None

    def _get_valid_expirations(self, dte_min: int, dte_max: int) -> List[date]:
        """Get list of valid expiration dates (Fridays only) within DTE range."""
        today = date.today()
        expirations = []

        # Check each day for potential expiration
        for days in range(dte_min, dte_max + 1):
            exp_date = today + timedelta(days=days)
            # Options typically expire on Fridays
            if exp_date.weekday() == 4:  # Friday
                expirations.append(exp_date)

        return expirations

    def _enrich_with_quotes(
        self,
        contracts: List[OptionsContract],
        quotes: Dict[str, Dict]
    ) -> List[OptionsContract]:
        """Enrich contracts with quote data."""
        for contract in contracts:
            if contract.symbol in quotes:
                quote = quotes[contract.symbol]
                contract.bid = float(quote.get("bp", 0))
                contract.ask = float(quote.get("ap", 0))
                contract.last = float(quote.get("last", {}).get("p", 0))

                # Get greeks if available
                if "greeks" in quote:
                    greeks = quote["greeks"]
                    contract.delta = float(greeks.get("delta", 0))
                    contract.gamma = float(greeks.get("gamma", 0))
                    contract.theta = float(greeks.get("theta", 0))
                    contract.vega = float(greeks.get("vega", 0))
                    contract.implied_volatility = float(greeks.get("iv", 0))

        return contracts

    def _rank_and_select(
        self,
        contracts: List[OptionsContract],
        current_price: float,
        tier: PriceTier
    ) -> Optional[OptionsContract]:
        """
        Rank contracts and select the best one.
        
        Ranking criteria:
        1. Delta closest to sweet spot (-0.325)
        2. Liquidity (tighter spread better)
        3. DTE (prefer middle of range)
        4. OI/Volume
        5. Premium value
        """
        if not contracts:
            return None

        rules = STRIKE_RULES[tier]
        
        def score_contract(c: OptionsContract) -> float:
            score = 0.0

            # 1. Delta score - ideal is -0.325 (30% weight)
            if c.delta != 0:
                delta_diff = abs(c.delta - self.IDEAL_DELTA)
                delta_score = max(0, 1.0 - delta_diff * 4)
                score += delta_score * 0.30

            # 2. Liquidity score - tighter spread better (25% weight)
            if c.spread_pct > 0:
                spread_score = max(0, 1.0 - c.spread_pct * 10)
                score += spread_score * 0.25

            # 3. DTE score - prefer middle of range (15% weight)
            ideal_dte = 14
            dte_diff = abs(c.dte - ideal_dte)
            dte_score = max(0, 1.0 - dte_diff / 10)
            score += dte_score * 0.15

            # 4. OI/Volume score (15% weight)
            oi_score = min(c.open_interest / 3000, 1.0)
            vol_score = min(c.volume / 500, 1.0) if c.volume > 0 else 0
            liquidity_score = oi_score * 0.7 + vol_score * 0.3
            score += liquidity_score * 0.15

            # 5. Premium score (15% weight)
            # Prefer $1-$8 range for reasonable size and liquidity
            mid = c.mid_price
            if 1.0 <= mid <= 5.0:
                premium_score = 1.0
            elif 5.0 < mid <= 8.0:
                premium_score = 0.9
            elif 0.50 <= mid < 1.0:
                premium_score = 0.7
            elif 8.0 < mid <= 15.0:
                premium_score = 0.6
            else:
                premium_score = 0.3
            score += premium_score * 0.15

            return score

        # Score and sort
        scored = [(c, score_contract(c)) for c in contracts]
        scored.sort(key=lambda x: x[1], reverse=True)

        return scored[0][0] if scored else None

    def format_contract_output(
        self,
        contract: OptionsContract,
        spot_price: float,
        reason: str
    ) -> Dict:
        """
        Format contract details for output.
        
        Returns dict with:
        - expiry
        - strike_put
        - delta
        - spread_pct
        - oi, volume
        - reason
        """
        tier = self.get_price_tier(spot_price)
        rules = STRIKE_RULES[tier]
        
        return {
            "expiry": contract.expiration.strftime("%Y-%m-%d") if contract.expiration else "",
            "strike_put": contract.strike,
            "delta": contract.delta,
            "spread_pct": contract.spread_pct,
            "oi": contract.open_interest,
            "volume": contract.volume,
            "mid_price": contract.mid_price,
            "bid": contract.bid,
            "ask": contract.ask,
            "dte": contract.dte,
            "iv": contract.implied_volatility,
            "tier": tier.value,
            "target_multiple": rules.target_multiple,
            "reason": reason,
        }

    async def get_contract_details(
        self,
        contract_symbol: str
    ) -> Optional[OptionsContract]:
        """Get detailed information for a specific contract."""
        try:
            details = await self.polygon.get_options_contract(contract_symbol)
            if not details:
                return None

            # Parse contract details
            contract_data = details.get("results", {})

            exp_str = contract_data.get("expiration_date", "")
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date() if exp_str else date.today()
            dte = (exp_date - date.today()).days

            return OptionsContract(
                symbol=contract_symbol,
                underlying=contract_data.get("underlying_ticker", ""),
                expiration=exp_date,
                strike=float(contract_data.get("strike_price", 0)),
                option_type=contract_data.get("contract_type", "put"),
                bid=0.0,
                ask=0.0,
                last=0.0,
                volume=0,
                open_interest=0,
                implied_volatility=0.0,
                delta=0.0,
                gamma=0.0,
                theta=0.0,
                vega=0.0,
                dte=dte
            )

        except Exception as e:
            logger.error(f"Error getting contract details: {e}")
            return None

    def calculate_position_size(
        self,
        contract: OptionsContract,
        account_value: float,
        max_risk_pct: float = 0.02,
        candidate_class: str = "A"
    ) -> int:
        """
        Calculate position size based on risk management.
        
        Class A: Up to 5 contracts
        Class B: 1-2 contracts max
        
        Args:
            contract: Selected options contract
            account_value: Total account value
            max_risk_pct: Maximum risk per trade (default 2%)
            candidate_class: "A" or "B"
            
        Returns:
            Number of contracts to trade
        """
        if contract.mid_price <= 0:
            return 0

        # Maximum dollar risk
        max_risk = account_value * max_risk_pct

        # Cost per contract (x100 for options)
        cost_per_contract = contract.mid_price * 100

        # Max contracts based on risk
        max_contracts = int(max_risk / cost_per_contract)

        # Apply position size limits
        max_position_value = account_value * self.settings.max_position_size
        max_by_position = int(max_position_value / cost_per_contract)

        contracts = min(max_contracts, max_by_position)

        # Class-based limits
        if candidate_class == "A":
            contracts = min(contracts, 5)  # Class A: up to 5 contracts
        else:
            contracts = min(contracts, 2)  # Class B: 1-2 contracts max

        # Minimum 1 contract
        return max(1, contracts)

    def validate_entry(
        self,
        contract: OptionsContract,
        current_underlying_price: float
    ) -> Tuple[bool, str]:
        """
        Final validation before entry.
        
        Checks:
        - Contract still valid
        - Spread acceptable
        - Still OTM
        - Delta in range
        - Reasonable bid/ask
        
        Returns:
            Tuple of (is_valid, reason)
        """
        # Check OTM
        if contract.strike >= current_underlying_price:
            return (False, "Contract no longer OTM")

        # Check spread
        if contract.spread_pct > self.MAX_SPREAD_PCT * 1.5:
            return (False, f"Spread too wide: {contract.spread_pct:.1%}")

        # Check bid exists
        if contract.bid <= 0:
            return (False, "No bid available")

        # Check delta still in range (with some buffer)
        if contract.delta != 0:
            if contract.delta > self.DELTA_FLOOR:
                return (False, f"Delta too shallow: {contract.delta:.2f}")
            if contract.delta < self.DELTA_MIN * 1.2:
                return (False, f"Delta too aggressive: {contract.delta:.2f}")

        return (True, "Valid")

    def check_put_wall_safety(
        self,
        strike: float,
        put_wall_strike: Optional[float],
        put_wall_oi: int,
        bounce_count: int,
        iv_expanding: bool
    ) -> Tuple[bool, str]:
        """
        Check if strike is safe from put wall / dealer support.
        
        REJECT if:
        - Put wall within +/- 1% and price has bounced there 3+ times
        - IV not expanding (dealers defending)
        
        This prevents buying puts into dealer bid support.
        """
        if put_wall_strike is None:
            return (True, "No put wall detected")
        
        # Check if our strike is near put wall
        distance_pct = abs(strike - put_wall_strike) / strike
        
        if distance_pct < 0.01:  # Within 1%
            if bounce_count >= 3 and not iv_expanding:
                return (False, f"Put wall at ${put_wall_strike:.2f} with {bounce_count} bounces, IV stable - dealers defending")
            elif bounce_count >= 3:
                logger.warning(f"Caution: Put wall at ${put_wall_strike:.2f} with {bounce_count} bounces, but IV expanding")
        
        return (True, "Safe from put wall")
