"""
Vega Gate - Institutional Volatility Structure Selection

PURPOSE: Prevent buying puts after IV expansion.
This is the highest-ROI enhancement for P&L quality.

DECISION LOGIC (Architect-4 Approved):

IF IV Rank < 60:
    Use Long Put (default structure)

ELIF 60 ≤ IV Rank ≤ 80:
    Reduce size OR widen DTE (less gamma decay)

ELIF IV Rank > 80:
    SWITCH STRUCTURE:
        → Bear Call Spread (defined risk, short vega)
        → Same directional thesis
        → Vega-neutral / short vega
        → Turn IV crush into second edge

Why this matters:
- You still profit from downside
- You stop paying for inflated volatility
- IV crush becomes an ally, not an enemy
- This is institutional options structuring

Data Sources:
- IV Rank: Calculated from historical IV (Polygon/Alpaca)
- Current IV: From options chain (Alpaca/Unusual Whales)
- IV Percentile: 52-week IV ranking
"""

from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Tuple
from enum import Enum
from loguru import logger

from putsengine.models import OptionsContract, PutCandidate


class VegaDecision(Enum):
    """Vega gate decision outcomes."""
    LONG_PUT = "long_put"                    # IV < 60 → Default, optimal
    LONG_PUT_REDUCED = "long_put_reduced"    # 60 ≤ IV ≤ 80 → Reduce size
    LONG_PUT_WIDER_DTE = "long_put_wider_dte"  # 60 ≤ IV ≤ 80 → Widen DTE
    BEAR_CALL_SPREAD = "bear_call_spread"    # IV > 80 → Structure switch
    REJECT = "reject"                         # IV too extreme, skip entirely


@dataclass
class VegaGateResult:
    """Result from Vega Gate analysis."""
    symbol: str
    iv_rank: float                    # 0-100 scale
    iv_percentile: float              # 52-week percentile
    current_iv: float                 # Current ATM IV
    historical_iv_avg: float          # 30-day average IV
    decision: VegaDecision
    size_multiplier: float            # 1.0 = full, 0.5 = half, 0 = skip
    dte_adjustment: int               # Days to add to DTE
    recommended_structure: str         # e.g., "Long Put", "Bear Call Spread"
    reasoning: str
    timestamp: datetime
    
    @property
    def should_switch_structure(self) -> bool:
        """Check if we should switch from Long Put to Bear Call Spread."""
        return self.decision == VegaDecision.BEAR_CALL_SPREAD
    
    @property
    def is_tradeable(self) -> bool:
        """Check if any trade is recommended."""
        return self.decision != VegaDecision.REJECT


class VegaGate:
    """
    Vega Gate - Volatility-Aware Structure Selection.
    
    Prevents overpaying for volatility by:
    1. Tracking IV Rank (where is IV vs its own history)
    2. Adjusting position sizing based on IV regime
    3. Switching structures when IV is elevated
    
    ARCHITECT-4 UPDATE (Feb 1, 2026):
    EWS → Vega Gate Coupling:
    - If EWS level == ACT (IPI ≥ 0.70) AND IV Rank > 85:
      → Force Bear Call Spread structure
    - This prevents the classic failure: "Correct early warning → expensive puts → IV crush"
    
    This is the difference between "right on direction, wrong on structure"
    and capturing alpha efficiently.
    """
    
    # IV Rank thresholds (Architect-4 approved)
    IV_RANK_OPTIMAL = 60          # Below this: Long Put optimal
    IV_RANK_ELEVATED = 80         # Above this: Consider spread
    IV_RANK_EXTREME = 95          # Above this: Maybe skip entirely
    
    # EWS coupling threshold (Architect-4 Feb 1, 2026)
    EWS_FORCE_SPREAD_IV = 85      # If EWS=ACT and IV > 85, force spread
    
    # Size adjustments by IV regime
    SIZE_MULTIPLIERS = {
        "optimal": 1.0,           # IV < 60: Full size
        "elevated": 0.60,         # 60-80: Reduced size
        "extreme": 0.30,          # >80: Minimal or switch structure
    }
    
    # DTE adjustments (wider DTE = less gamma decay pressure)
    DTE_ADDITIONS = {
        "optimal": 0,             # IV < 60: Normal DTE
        "elevated": 5,            # 60-80: Add 5 days
        "extreme": 7,             # >80: Add 7 days (if still using puts)
    }
    
    def __init__(
        self,
        alpaca_client=None,
        polygon_client=None,
        unusual_whales_client=None
    ):
        self.alpaca = alpaca_client
        self.polygon = polygon_client
        self.uw = unusual_whales_client
    
    async def analyze(
        self,
        symbol: str,
        candidate: Optional[PutCandidate] = None,
        current_price: Optional[float] = None,
        ews_level: Optional[str] = None,
        ews_ipi: Optional[float] = None
    ) -> VegaGateResult:
        """
        Perform Vega Gate analysis for a symbol.
        
        Args:
            symbol: Stock ticker
            candidate: Optional PutCandidate with price data
            current_price: Current stock price (if candidate not provided)
            ews_level: Optional EWS pressure level ("act", "prepare", "watch", "none")
            ews_ipi: Optional EWS Institutional Pressure Index (0-1)
        
        Returns:
            VegaGateResult with decision and adjustments
            
        ARCHITECT-4 COUPLING (Feb 1, 2026):
        If ews_level == "act" AND iv_rank > 85:
            → Force Bear Call Spread structure
        This prevents: "Correct early warning → expensive puts → IV crush"
        """
        logger.info(f"Vega Gate: Analyzing IV regime for {symbol}")
        
        price = current_price or (candidate.current_price if candidate else 0)
        
        # Get IV data
        iv_data = await self._get_iv_data(symbol, price)
        
        iv_rank = iv_data.get("iv_rank", 50)
        iv_percentile = iv_data.get("iv_percentile", 50)
        current_iv = iv_data.get("current_iv", 0.30)
        historical_iv = iv_data.get("historical_iv", 0.30)
        
        # Make decision (default logic)
        decision, size_mult, dte_adj, structure, reasoning = self._make_decision(
            iv_rank, iv_percentile, current_iv, historical_iv
        )
        
        # ================================================================
        # EWS → VEGA GATE COUPLING (Architect-4 Feb 1, 2026)
        # If EWS shows ACT level (IPI ≥ 0.70) AND IV Rank > 85,
        # FORCE Bear Call Spread even if default logic says otherwise.
        # 
        # Why: Early warning is strong, but IV is expensive.
        # Don't let IV crush destroy the correct directional thesis.
        # ================================================================
        ews_override_applied = False
        if ews_level == "act" and iv_rank > self.EWS_FORCE_SPREAD_IV:
            ews_override_applied = True
            decision = VegaDecision.BEAR_CALL_SPREAD
            size_mult = self.SIZE_MULTIPLIERS["extreme"]
            dte_adj = self.DTE_ADDITIONS["extreme"]
            structure = "Bear Call Spread (EWS Override)"
            reasoning = (
                f"⚡ EWS → VEGA GATE COUPLING ACTIVATED: "
                f"EWS Level=ACT (IPI={ews_ipi:.2f}) AND IV Rank={iv_rank:.0f}% (>85). "
                f"FORCE Bear Call Spread to avoid IV crush on otherwise correct early warning. "
                f"This is structure optimization, not signal change."
            )
            logger.warning(
                f"Vega Gate {symbol}: EWS OVERRIDE - ACT level + high IV → "
                f"Forcing Bear Call Spread"
            )
        
        result = VegaGateResult(
            symbol=symbol,
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            current_iv=current_iv,
            historical_iv_avg=historical_iv,
            decision=decision,
            size_multiplier=size_mult,
            dte_adjustment=dte_adj,
            recommended_structure=structure,
            reasoning=reasoning,
            timestamp=datetime.now()
        )
        
        logger.info(
            f"Vega Gate {symbol}: IV Rank={iv_rank:.0f}%, "
            f"Decision={decision.value}, Size={size_mult:.0%}, "
            f"DTE+{dte_adj}, Structure={structure}"
            f"{' [EWS Override]' if ews_override_applied else ''}"
        )
        
        return result
    
    def _make_decision(
        self,
        iv_rank: float,
        iv_percentile: float,
        current_iv: float,
        historical_iv: float
    ) -> Tuple[VegaDecision, float, int, str, str]:
        """
        Make Vega Gate decision based on IV regime.
        
        Returns:
            (decision, size_multiplier, dte_adjustment, structure, reasoning)
        """
        # Use the higher of IV Rank and IV Percentile for safety
        iv_metric = max(iv_rank, iv_percentile)
        
        # OPTIMAL REGIME: IV < 60
        if iv_metric < self.IV_RANK_OPTIMAL:
            return (
                VegaDecision.LONG_PUT,
                self.SIZE_MULTIPLIERS["optimal"],
                self.DTE_ADDITIONS["optimal"],
                "Long Put",
                f"IV Rank {iv_rank:.0f}% is optimal. Long Put is the correct structure."
            )
        
        # ELEVATED REGIME: 60 ≤ IV ≤ 80
        elif iv_metric <= self.IV_RANK_ELEVATED:
            # Offer two options: reduced size OR wider DTE
            # Default to reduced size as it's more capital-efficient
            return (
                VegaDecision.LONG_PUT_REDUCED,
                self.SIZE_MULTIPLIERS["elevated"],
                self.DTE_ADDITIONS["elevated"],
                "Long Put (Reduced)",
                f"IV Rank {iv_rank:.0f}% is elevated. Reduce size to 60% "
                f"and/or add +5 DTE to reduce gamma decay pressure."
            )
        
        # EXTREME REGIME: IV > 80
        elif iv_metric <= self.IV_RANK_EXTREME:
            return (
                VegaDecision.BEAR_CALL_SPREAD,
                self.SIZE_MULTIPLIERS["extreme"],
                self.DTE_ADDITIONS["extreme"],
                "Bear Call Spread",
                f"IV Rank {iv_rank:.0f}% is extreme. SWITCH to Bear Call Spread: "
                f"same directional thesis, short vega, defined risk. "
                f"IV crush becomes your ally."
            )
        
        # BEYOND EXTREME: IV > 95 (rare, usually event-driven)
        else:
            return (
                VegaDecision.REJECT,
                0.0,
                0,
                "SKIP",
                f"IV Rank {iv_rank:.0f}% is beyond extreme (>95%). "
                f"Volatility premium too high even for spreads. "
                f"Wait for IV normalization or skip this trade."
            )
    
    async def _get_iv_data(
        self,
        symbol: str,
        current_price: float
    ) -> Dict:
        """
        Get IV Rank and IV Percentile data.
        
        Data sources:
        1. Alpaca options chain → Current ATM IV
        2. Polygon historical IV → 52-week IV history
        3. Calculate IV Rank and Percentile
        """
        result = {
            "iv_rank": 50.0,
            "iv_percentile": 50.0,
            "current_iv": 0.30,
            "historical_iv": 0.30,
        }
        
        try:
            # 1. Get current ATM IV from options chain
            current_iv = await self._get_current_atm_iv(symbol, current_price)
            if current_iv:
                result["current_iv"] = current_iv
            
            # 2. Get historical IV data (52-week)
            historical_data = await self._get_historical_iv(symbol)
            if historical_data:
                result["historical_iv"] = historical_data.get("avg_iv", 0.30)
                
                # Calculate IV Rank: (current - low) / (high - low) * 100
                iv_high = historical_data.get("iv_high", current_iv * 1.5)
                iv_low = historical_data.get("iv_low", current_iv * 0.5)
                
                if iv_high > iv_low:
                    iv_rank = ((current_iv - iv_low) / (iv_high - iv_low)) * 100
                    result["iv_rank"] = max(0, min(100, iv_rank))
                
                # IV Percentile: % of days current IV was higher
                if "iv_percentile" in historical_data:
                    result["iv_percentile"] = historical_data["iv_percentile"]
                else:
                    # Estimate from rank (rough approximation)
                    result["iv_percentile"] = result["iv_rank"]
            
        except Exception as e:
            logger.warning(f"Error getting IV data for {symbol}: {e}")
        
        return result
    
    async def _get_current_atm_iv(
        self,
        symbol: str,
        current_price: float
    ) -> Optional[float]:
        """Get current ATM implied volatility."""
        if not self.alpaca:
            return None
        
        try:
            # Get nearest expiration options chain
            exp_date = self._get_nearest_friday()
            chain = await self.alpaca.get_options_chain(
                underlying=symbol,
                expiration_date=exp_date,
                min_strike=current_price * 0.95,
                max_strike=current_price * 1.05,
                option_type="put"
            )
            
            if not chain:
                return None
            
            # Find ATM option (closest strike to current price)
            atm_contract = min(
                chain,
                key=lambda c: abs(c.strike - current_price),
                default=None
            )
            
            if atm_contract and atm_contract.implied_volatility > 0:
                return atm_contract.implied_volatility
            
        except Exception as e:
            logger.debug(f"Error getting ATM IV for {symbol}: {e}")
        
        return None
    
    async def _get_historical_iv(
        self,
        symbol: str,
        lookback_days: int = 252
    ) -> Optional[Dict]:
        """
        Get historical IV data for IV Rank calculation.
        
        Ideally from Polygon's historical options data or
        calculate from historical realized volatility as proxy.
        """
        if not self.polygon:
            return None
        
        try:
            # Get daily bars for realized volatility calculation
            from_date = date.today() - timedelta(days=lookback_days)
            bars = await self.polygon.get_daily_bars(
                symbol=symbol,
                from_date=from_date,
                to_date=date.today()
            )
            
            if not bars or len(bars) < 20:
                return None
            
            # Calculate realized volatility windows
            import numpy as np
            
            # Get daily returns
            closes = [bar.close for bar in bars]
            returns = np.diff(np.log(closes))
            
            # Calculate rolling 20-day realized volatility (annualized)
            window = 20
            if len(returns) < window:
                return None
            
            rv_values = []
            for i in range(len(returns) - window + 1):
                window_returns = returns[i:i + window]
                rv = np.std(window_returns) * np.sqrt(252)
                rv_values.append(rv)
            
            if not rv_values:
                return None
            
            # Use realized volatility as IV proxy
            # (In production, would use actual historical IV data)
            rv_array = np.array(rv_values)
            
            return {
                "avg_iv": float(np.mean(rv_array)),
                "iv_high": float(np.percentile(rv_array, 95)),
                "iv_low": float(np.percentile(rv_array, 5)),
                "iv_percentile": float(
                    (np.sum(rv_array < rv_array[-1]) / len(rv_array)) * 100
                ),
                "current_rv": float(rv_array[-1]) if len(rv_array) > 0 else 0.30,
            }
            
        except Exception as e:
            logger.debug(f"Error getting historical IV for {symbol}: {e}")
        
        return None
    
    def _get_nearest_friday(self) -> date:
        """Get nearest Friday expiration date."""
        today = date.today()
        days_until_friday = (4 - today.weekday() + 7) % 7
        if days_until_friday == 0:
            days_until_friday = 7
        return today + timedelta(days=days_until_friday)
    
    def get_spread_recommendation(
        self,
        symbol: str,
        current_price: float,
        target_move_pct: float = 0.05
    ) -> Dict:
        """
        Generate Bear Call Spread recommendation when IV is elevated.
        
        Bear Call Spread structure:
        - Sell Call at Strike A (slightly OTM)
        - Buy Call at Strike B (further OTM)
        - Max profit: Net credit received
        - Max loss: Strike B - Strike A - Net credit
        - Profit if stock stays below Strike A
        
        This is the correct structure when:
        - Bearish thesis is intact
        - But IV is too expensive for long puts
        """
        # Calculate spread strikes
        short_strike = round(current_price * 1.02, 0)  # 2% OTM call to sell
        long_strike = round(current_price * 1.07, 0)   # 7% OTM call to buy
        
        return {
            "structure": "Bear Call Spread",
            "symbol": symbol,
            "short_call_strike": short_strike,
            "long_call_strike": long_strike,
            "spread_width": long_strike - short_strike,
            "thesis": "Bearish - stock expected to decline or stay flat",
            "max_profit": "Net credit received (defined at entry)",
            "max_loss": f"${long_strike - short_strike} - credit received",
            "break_even": f"Short strike + credit received",
            "vega_exposure": "Short vega (benefits from IV crush)",
            "expiration_guidance": "14-21 DTE optimal for theta decay",
            "rationale": (
                "When IV Rank > 80, long puts overpay for volatility. "
                "Bear Call Spread captures directional thesis with short vega. "
                "IV crush becomes profit, not loss."
            )
        }


# ============================================================================
# INTEGRATION HELPER FUNCTIONS
# ============================================================================

async def apply_vega_gate(
    candidate: PutCandidate,
    alpaca_client=None,
    polygon_client=None,
    ews_level: Optional[str] = None,
    ews_ipi: Optional[float] = None
) -> Tuple[PutCandidate, VegaGateResult]:
    """
    Apply Vega Gate to a PutCandidate and adjust accordingly.
    
    This is the main integration point for the scoring pipeline.
    
    Args:
        candidate: The PutCandidate to analyze
        alpaca_client: AlpacaClient for options data
        polygon_client: PolygonClient for historical IV
        ews_level: Optional EWS level ("act", "prepare", "watch", "none")
        ews_ipi: Optional EWS IPI score (0-1)
    
    Returns:
        Updated candidate and VegaGateResult
        
    ARCHITECT-4 (Feb 1, 2026):
    If EWS data is provided, the coupling rule applies:
    - EWS=ACT AND IV Rank > 85 → Force Bear Call Spread
    """
    gate = VegaGate(
        alpaca_client=alpaca_client,
        polygon_client=polygon_client
    )
    
    result = await gate.analyze(
        symbol=candidate.symbol,
        candidate=candidate,
        ews_level=ews_level,
        ews_ipi=ews_ipi
    )
    
    # Apply adjustments to candidate
    if result.decision == VegaDecision.LONG_PUT_REDUCED:
        # Add flag for reduced sizing
        candidate.vega_gate_sizing = result.size_multiplier
        candidate.vega_gate_dte_add = result.dte_adjustment
        
    elif result.decision == VegaDecision.BEAR_CALL_SPREAD:
        # Flag for structure switch
        candidate.vega_gate_structure_switch = True
        candidate.vega_gate_recommended = result.recommended_structure
        
    elif result.decision == VegaDecision.REJECT:
        # Flag as not tradeable due to IV
        candidate.vega_gate_rejected = True
    
    # Store full result in candidate
    candidate.vega_gate_result = result
    
    return candidate, result


def format_vega_gate_display(result: VegaGateResult) -> str:
    """Format VegaGateResult for dashboard display."""
    icons = {
        VegaDecision.LONG_PUT: "🟢",
        VegaDecision.LONG_PUT_REDUCED: "🟡",
        VegaDecision.LONG_PUT_WIDER_DTE: "🟡",
        VegaDecision.BEAR_CALL_SPREAD: "🔴",
        VegaDecision.REJECT: "⛔",
    }
    
    icon = icons.get(result.decision, "⚪")
    
    return (
        f"{icon} IV Rank: {result.iv_rank:.0f}% | "
        f"Structure: {result.recommended_structure} | "
        f"Size: {result.size_multiplier:.0%}"
    )
