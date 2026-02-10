"""
Data models for PutsEngine.
Defines all data structures used throughout the trading system.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Optional, List, Dict, Any


class TradeSignal(Enum):
    """Trade signal strength."""
    STRONG_BEARISH = "strong_bearish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    BULLISH = "bullish"
    STRONG_BULLISH = "strong_bullish"


class MarketRegime(Enum):
    """Market regime classification."""
    BEARISH_EXPANSION = "bearish_expansion"
    BEARISH_NEUTRAL = "bearish_neutral"
    NEUTRAL = "neutral"
    BULLISH_NEUTRAL = "bullish_neutral"
    BULLISH_EXPANSION = "bullish_expansion"
    PINNED = "pinned"


class BlockReason(Enum):
    """Reasons for blocking a trade."""
    POSITIVE_GEX = "positive_gex_regime"
    BUYBACK_WINDOW = "buyback_window_active"
    EARNINGS_MOMENTUM = "earnings_momentum"
    LATE_IV_SPIKE = "late_iv_spike"
    NO_DISTRIBUTION = "no_distribution_detected"
    PUT_WALL_SUPPORT = "put_wall_support"
    INDEX_PINNED = "index_pinned"
    INSUFFICIENT_LIQUIDITY = "insufficient_liquidity"
    SCORE_TOO_LOW = "score_below_threshold"
    # New per Final Architect Report
    PASSIVE_INFLOW_WINDOW = "passive_inflow_window"  # Day 1-3 or 28-31
    EARNINGS_PROXIMITY = "earnings_proximity"  # Within 2 weeks of earnings
    HTB_SQUEEZE_RISK = "htb_squeeze_risk"  # Hard-to-borrow transition
    SNAPBACK_ONLY = "snapback_only"  # Engine 3 alone - blocked


@dataclass
class PriceBar:
    """OHLCV price bar data."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: Optional[float] = None


@dataclass
class OptionsContract:
    """Options contract data."""
    symbol: str
    underlying: str
    expiration: date
    strike: float
    option_type: str  # 'call' or 'put'
    bid: float
    ask: float
    last: float
    volume: int
    open_interest: int
    implied_volatility: float
    delta: float
    gamma: float
    theta: float
    vega: float
    dte: int

    @property
    def mid_price(self) -> float:
        """Calculate mid price."""
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        """Calculate bid-ask spread."""
        return self.ask - self.bid

    @property
    def spread_pct(self) -> float:
        """Calculate spread as percentage of mid."""
        mid = self.mid_price
        return self.spread / mid if mid > 0 else float('inf')


@dataclass
class OptionsFlow:
    """Options flow data from Unusual Whales."""
    timestamp: datetime
    symbol: str
    underlying: str
    expiration: date
    strike: float
    option_type: str
    side: str  # 'bid', 'ask', 'mid'
    size: int
    premium: float
    spot_price: float
    implied_volatility: float
    delta: float
    gamma: float = 0.0  # FEB 8, 2026: Per-trade gamma for Greek-weighted flow
    vega: float = 0.0   # FEB 8, 2026: Per-trade vega for volatility sensitivity weighting
    is_sweep: bool = False
    is_block: bool = False
    sentiment: str = "neutral"  # 'bullish', 'bearish', 'neutral'


@dataclass
class DarkPoolPrint:
    """Dark pool transaction data."""
    timestamp: datetime
    symbol: str
    price: float
    size: int
    exchange: str
    is_buy: Optional[bool] = None
    # FEB 8, 2026: NBBO depth for violence scoring
    # Thin books (small quantities) + large prints = violent conditions
    nbbo_bid_quantity: int = 0
    nbbo_ask_quantity: int = 0


@dataclass
class GEXData:
    """Gamma Exposure (GEX) data."""
    symbol: str
    timestamp: datetime
    net_gex: float
    call_gex: float
    put_gex: float
    gex_flip_level: Optional[float] = None
    dealer_delta: float = 0.0
    put_wall: Optional[float] = None
    call_wall: Optional[float] = None
    # Zero-Gamma / Volatility Trigger per Architect
    zero_gamma_level: Optional[float] = None
    below_zero_gamma: bool = False


@dataclass
class EarningsData:
    """Earnings proximity data for catalyst detection."""
    symbol: str
    timestamp: datetime
    next_earnings_date: Optional[date] = None
    days_to_earnings: Optional[int] = None
    is_pre_earnings: bool = False  # Within 14 days before
    is_post_earnings: bool = False  # Within 2 days after
    recent_guidance: Optional[str] = None  # "positive", "negative", "neutral"
    has_gap_down: bool = False
    vwap_reclaim_failed: bool = False  # Post-earnings check


@dataclass
class ShortInterestData:
    """Short interest and borrow data per Architect requirements."""
    symbol: str
    timestamp: datetime
    short_volume: int = 0
    short_volume_ratio: float = 0.0  # Short vol / total vol
    easy_to_borrow: bool = True
    was_easy_to_borrow: bool = True  # Previous status
    etb_to_htb_transition: bool = False  # Critical signal
    days_to_cover: float = 0.0
    short_interest_pct: float = 0.0
    squeeze_risk: bool = False  # HTB + high short interest


@dataclass
class MarketRegimeData:
    """Market regime analysis results."""
    timestamp: datetime
    regime: MarketRegime
    spy_below_vwap: bool
    qqq_below_vwap: bool
    index_gex: float
    vix_level: float
    vix_change: float
    vvix_level: Optional[float] = None
    is_tradeable: bool = False
    block_reasons: List[BlockReason] = field(default_factory=list)
    # New per Final Architect Report
    is_passive_inflow_window: bool = False
    passive_inflow_reason: str = ""  # "month_start", "month_end", "quarter_end"
    below_zero_gamma: bool = False  # Index below zero-gamma trigger
    # Gap 2 Fix: scan_allowed is LESS strict than tradeable.
    # Allows Distribution/Liquidity/Gamma engines to run and produce data
    # even in neutral/bullish regimes so Convergence always has engine data.
    is_scan_allowed: bool = True
    # Gap 2 Fix: Scan-allowed is less strict than tradeable
    # Allows distribution/liquidity analysis even in neutral/passive markets
    is_scan_allowed: bool = True


class EngineType(Enum):
    """Anti-Trinity Engine Types per Final Architect Blueprint."""
    GAMMA_DRAIN = "gamma_drain"           # Engine 1: Flow-driven, highest conviction
    DISTRIBUTION_TRAP = "distribution_trap"  # Engine 2: Event-driven, confirmation-heavy
    SNAPBACK = "snapback"                 # Engine 3: Overextension, CONSTRAINED
    NONE = "none"                         # No engine triggered


@dataclass
class DistributionSignal:
    """Distribution detection signal."""
    symbol: str
    timestamp: datetime
    score: float  # 0-1
    signals: Dict[str, bool] = field(default_factory=dict)
    # Price-volume signals
    flat_price_rising_volume: bool = False
    failed_breakout: bool = False
    lower_highs_flat_rsi: bool = False
    vwap_loss: bool = False
    # Options signals
    call_selling_at_bid: bool = False
    put_buying_at_ask: bool = False
    rising_put_oi: bool = False
    skew_steepening: bool = False
    # Dark pool signals
    repeated_sell_blocks: bool = False
    # Insider/Congress signals (per Architect Blueprint)
    c_level_selling: bool = False
    insider_cluster: bool = False
    congress_selling: bool = False


@dataclass
class LiquidityVacuum:
    """Liquidity vacuum detection."""
    symbol: str
    timestamp: datetime
    score: float  # 0-1
    bid_collapsing: bool = False
    spread_widening: bool = False
    volume_no_progress: bool = False
    vwap_retest_failed: bool = False


@dataclass
class AccelerationWindow:
    """Acceleration window timing analysis."""
    symbol: str
    timestamp: datetime
    is_valid: bool = False
    price_below_vwap: bool = False
    price_below_ema20: bool = False
    price_below_prior_low: bool = False
    failed_reclaim: bool = False
    put_volume_rising: bool = False
    iv_reasonable: bool = False
    net_delta_negative: bool = False
    gamma_flipping_short: bool = False
    is_late_entry: bool = False  # Hard block
    # Anti-Trinity Engine Detection (per Architect Blueprint)
    engine_type: EngineType = EngineType.NONE
    is_snapback_only: bool = False  # Hard block - snapback must be confirmed
    rsi_overbought: bool = False    # RSI > 75 (snapback condition)
    lower_high_formed: bool = False  # Required for snapback


@dataclass
class PutCandidate:
    """Complete PUT option candidate with all analysis."""
    symbol: str
    timestamp: datetime

    # Layer scores (0-1)
    distribution_score: float = 0.0
    dealer_score: float = 0.0
    liquidity_score: float = 0.0
    flow_score: float = 0.0
    catalyst_score: float = 0.0
    sentiment_score: float = 0.0
    technical_score: float = 0.0

    # Final composite score
    composite_score: float = 0.0

    # Selected contract details
    recommended_strike: Optional[float] = None
    recommended_expiration: Optional[date] = None
    recommended_delta: Optional[float] = None
    contract_symbol: Optional[str] = None
    entry_price: Optional[float] = None

    # Analysis components
    distribution: Optional[DistributionSignal] = None
    liquidity: Optional[LiquidityVacuum] = None
    acceleration: Optional[AccelerationWindow] = None
    gex_data: Optional[GEXData] = None

    # Price data
    current_price: float = 0.0
    vwap: float = 0.0
    ema_20: float = 0.0

    # Gate status
    passed_all_gates: bool = False
    block_reasons: List[BlockReason] = field(default_factory=list)
    
    # =========================================================================
    # VEGA GATE (Architect-4): Volatility-Aware Structure Selection
    # =========================================================================
    # Prevents overpaying for volatility by adjusting size or switching
    # from Long Put to Bear Call Spread when IV is elevated.
    vega_gate_iv_rank: float = 50.0          # 0-100 scale
    vega_gate_iv_percentile: float = 50.0    # 52-week percentile
    vega_gate_current_iv: float = 0.0        # Current ATM IV
    vega_gate_sizing: float = 1.0            # Size multiplier (1.0 = full)
    vega_gate_dte_add: int = 0               # Days to add to DTE
    vega_gate_structure_switch: bool = False # True = use Bear Call Spread
    vega_gate_recommended: str = "Long Put"  # Recommended structure
    vega_gate_rejected: bool = False         # True = skip due to IV
    vega_gate_result: Optional[Any] = None   # Full VegaGateResult

    # Metadata
    shortlist_position: int = 0
    flow_signals: List[OptionsFlow] = field(default_factory=list)

    def calculate_composite_score(self, weights: Dict[str, float]) -> float:
        """Calculate weighted composite score."""
        self.composite_score = (
            self.distribution_score * weights.get("distribution_quality", 0.30) +
            self.dealer_score * weights.get("dealer_positioning", 0.20) +
            self.liquidity_score * weights.get("liquidity_vacuum", 0.15) +
            self.flow_score * weights.get("options_flow", 0.15) +
            self.catalyst_score * weights.get("catalyst_proximity", 0.10) +
            self.sentiment_score * weights.get("sentiment_divergence", 0.05) +
            self.technical_score * weights.get("technical_alignment", 0.05)
        )
        return self.composite_score


@dataclass
class TradeExecution:
    """Trade execution record."""
    symbol: str
    contract_symbol: str
    timestamp: datetime
    side: str  # 'buy' or 'sell'
    quantity: int
    price: float
    order_id: str
    status: str
    candidate: PutCandidate
    fill_price: Optional[float] = None
    fill_timestamp: Optional[datetime] = None


@dataclass
class DailyReport:
    """Daily engine report."""
    date: date
    total_scanned: int
    shortlist_count: int
    passed_gates: int
    trades_executed: int
    candidates: List[PutCandidate] = field(default_factory=list)
    market_regime: Optional[MarketRegimeData] = None
    api_calls_used: Dict[str, int] = field(default_factory=dict)
