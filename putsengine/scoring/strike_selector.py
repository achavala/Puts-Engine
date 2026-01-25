"""
Strike and DTE Selection - Contract selection for PUT trades.

Final Rules:
- 7-21 DTE only
- Delta -0.25 to -0.40
- Slightly OTM
- No lottery puts
- Prefer IV expansion AFTER entry
"""

from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Tuple
from loguru import logger

from putsengine.config import Settings
from putsengine.models import OptionsContract, PutCandidate
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient


class StrikeSelector:
    """
    Strike and DTE Selection Engine.

    Selects optimal put contracts based on:
    - DTE constraints (7-21 days)
    - Delta range (-0.25 to -0.40)
    - Liquidity (spread, volume)
    - Risk/reward profile
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

        # DTE constraints
        self.dte_min = settings.dte_min
        self.dte_max = settings.dte_max

        # Delta constraints
        self.delta_min = settings.delta_min
        self.delta_max = settings.delta_max

        # Liquidity constraints
        self.max_spread_pct = 0.10  # 10% max spread
        self.min_volume = 100  # Minimum daily volume
        self.min_oi = 500  # Minimum open interest

    async def select_contract(
        self,
        candidate: PutCandidate
    ) -> Optional[OptionsContract]:
        """
        Select optimal put contract for a candidate.

        Args:
            candidate: PutCandidate with price data populated

        Returns:
            Optimal OptionsContract or None if no suitable contract found
        """
        symbol = candidate.symbol
        current_price = candidate.current_price

        if current_price == 0:
            logger.warning(f"No current price for {symbol}")
            return None

        logger.info(
            f"Selecting put contract for {symbol} "
            f"(price: ${current_price:.2f})"
        )

        try:
            # Get available expirations
            valid_expirations = self._get_valid_expirations()

            # Get options chain
            all_contracts = []
            for exp_date in valid_expirations[:5]:  # Limit API calls
                contracts = await self.alpaca.get_options_chain(
                    underlying=symbol,
                    expiration_date=exp_date,
                    option_type="put",
                    strike_price_gte=current_price * 0.80,  # 20% OTM max
                    strike_price_lte=current_price * 0.98   # 2% OTM min
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

            # Filter and rank contracts
            valid_contracts = self._filter_contracts(
                enriched_contracts, current_price
            )

            if not valid_contracts:
                logger.warning(f"No valid contracts after filtering for {symbol}")
                return None

            # Select best contract
            best = self._rank_and_select(valid_contracts, current_price)

            if best:
                logger.info(
                    f"Selected: {best.symbol} "
                    f"(strike: ${best.strike:.2f}, "
                    f"DTE: {best.dte}, "
                    f"delta: {best.delta:.2f}, "
                    f"mid: ${best.mid_price:.2f})"
                )

            return best

        except Exception as e:
            logger.error(f"Error selecting contract for {symbol}: {e}")
            return None

    def _get_valid_expirations(self) -> List[date]:
        """Get list of valid expiration dates within DTE range."""
        today = date.today()
        expirations = []

        # Check each day for potential expiration
        for days in range(self.dte_min, self.dte_max + 1):
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

    def _filter_contracts(
        self,
        contracts: List[OptionsContract],
        current_price: float
    ) -> List[OptionsContract]:
        """Filter contracts by selection criteria."""
        valid = []

        for contract in contracts:
            # DTE check
            if not (self.dte_min <= contract.dte <= self.dte_max):
                continue

            # Delta check (puts have negative delta)
            if contract.delta != 0:
                if not (self.delta_min <= contract.delta <= self.delta_max):
                    continue

            # Liquidity checks
            if contract.bid <= 0 or contract.ask <= 0:
                continue

            spread_pct = contract.spread_pct
            if spread_pct > self.max_spread_pct:
                continue

            if contract.volume < self.min_volume and contract.open_interest < self.min_oi:
                continue

            # Strike check - must be OTM
            if contract.strike >= current_price:
                continue

            # No lottery puts - strike should be within 20% of price
            if contract.strike < current_price * 0.80:
                continue

            valid.append(contract)

        logger.debug(f"Filtered to {len(valid)} valid contracts")
        return valid

    def _rank_and_select(
        self,
        contracts: List[OptionsContract],
        current_price: float
    ) -> Optional[OptionsContract]:
        """
        Rank contracts and select the best one.

        Ranking criteria:
        1. Delta in target range (-0.30 to -0.35 ideal)
        2. Liquidity (tighter spread better)
        3. DTE (prefer 14-17 days)
        4. Premium value (not too cheap, not too expensive)
        """
        if not contracts:
            return None

        def score_contract(c: OptionsContract) -> float:
            score = 0.0

            # Delta score - ideal is -0.30 to -0.35
            ideal_delta = -0.325
            if c.delta != 0:
                delta_diff = abs(c.delta - ideal_delta)
                score += max(0, 1.0 - delta_diff * 5)  # 20% weight

            # Liquidity score
            if c.spread_pct > 0:
                spread_score = max(0, 1.0 - c.spread_pct * 10)
                score += spread_score * 0.25  # 25% weight

            # DTE score - ideal is 14-17 days
            ideal_dte = 15
            dte_diff = abs(c.dte - ideal_dte)
            dte_score = max(0, 1.0 - dte_diff / 10)
            score += dte_score * 0.20  # 20% weight

            # OI/Volume score
            oi_score = min(c.open_interest / 5000, 1.0)
            score += oi_score * 0.15  # 15% weight

            # Premium score - prefer $1-$5 range for manageable size
            mid = c.mid_price
            if 1.0 <= mid <= 5.0:
                premium_score = 1.0
            elif 0.50 <= mid < 1.0:
                premium_score = 0.7
            elif 5.0 < mid <= 10.0:
                premium_score = 0.7
            else:
                premium_score = 0.3
            score += premium_score * 0.20  # 20% weight

            return score

        # Score and sort
        scored = [(c, score_contract(c)) for c in contracts]
        scored.sort(key=lambda x: x[1], reverse=True)

        return scored[0][0] if scored else None

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
        max_risk_pct: float = 0.02
    ) -> int:
        """
        Calculate position size based on risk management.

        Args:
            contract: Selected options contract
            account_value: Total account value
            max_risk_pct: Maximum risk per trade (default 2%)

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
        - Reasonable bid/ask

        Returns:
            Tuple of (is_valid, reason)
        """
        # Check OTM
        if contract.strike >= current_underlying_price:
            return (False, "Contract no longer OTM")

        # Check spread
        if contract.spread_pct > self.max_spread_pct * 1.5:
            return (False, f"Spread too wide: {contract.spread_pct:.1%}")

        # Check bid exists
        if contract.bid <= 0:
            return (False, "No bid available")

        # Check delta still in range
        if contract.delta != 0:
            if not (self.delta_min * 1.2 <= contract.delta <= self.delta_max * 0.8):
                return (False, f"Delta out of range: {contract.delta:.2f}")

        return (True, "Valid")
