"""
Configuration management for PutsEngine.
Loads settings from environment variables and .env file.
"""

from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Alpaca API
    alpaca_api_key: str = Field(..., description="Alpaca API key")
    alpaca_secret_key: str = Field(..., description="Alpaca secret key")
    alpaca_base_url: str = Field(
        default="https://paper-api.alpaca.markets/v2",
        description="Alpaca base URL"
    )

    # Polygon / Massive API
    polygon_api_key: str = Field(..., description="Polygon.io API key")
    massive_api_key: Optional[str] = Field(default=None, description="Massive API key")

    # Unusual Whales API
    unusual_whales_api_key: str = Field(..., description="Unusual Whales API key")

    # ============================================================================
    # ENGINE CONFIGURATION - ARCHITECT-4 CLASS A/B SEPARATION
    # ============================================================================
    # 
    # CLASS A: Core Institutional Puts (Original logic)
    #   - Score >= 0.68
    #   - All 3 permissions required (Gamma + Liquidity + Incentive)
    #   - Full size (up to 5 contracts)
    #   - High expectancy, low frequency
    #
    # CLASS B: High-Beta Reaction Puts (New logic, constrained)
    #   - Score 0.25-0.45
    #   - High-beta universe ONLY
    #   - Max 1-2 contracts
    #   - Mixed expectancy, higher frequency
    #
    # CLASS C: Monitor Only (Never traded)
    #   - Dark pool signal alone
    #   - No VWAP loss / liquidity vacuum
    #
    class_a_min_score: float = Field(default=0.68, ge=0.50, le=1.0)  # Core threshold
    class_b_min_score: float = Field(default=0.25, ge=0.15, le=0.50)  # High-beta threshold
    class_b_max_score: float = Field(default=0.45, ge=0.30, le=0.67)  # Cap for Class B
    
    # Legacy threshold (uses Class A)
    min_score_threshold: float = Field(default=0.68, ge=0.0, le=1.0)
    
    max_daily_trades: int = Field(default=5, ge=1, le=10)
    max_daily_class_b_trades: int = Field(default=2, ge=1, le=3)  # Limit Class B
    max_position_size: float = Field(default=0.05, ge=0.01, le=0.20)
    max_class_b_contracts: int = Field(default=2, ge=1, le=2)  # Max 2 contracts Class B

    # DTE and Delta constraints
    dte_min: int = Field(default=7, ge=1)
    dte_max: int = Field(default=21, le=45)
    delta_min: float = Field(default=-0.40, ge=-1.0, le=0.0)
    delta_max: float = Field(default=-0.25, ge=-1.0, le=0.0)

    # API Rate Limits
    uw_daily_limit: int = Field(default=5000, description="Unusual Whales daily API limit")
    polygon_rate_limit: int = Field(default=5, description="Polygon requests per second")

    # Logging
    log_level: str = Field(default="INFO")
    log_file: str = Field(default="logs/putsengine.log")

    @property
    def alpaca_data_url(self) -> str:
        """Data API URL for Alpaca."""
        return "https://data.alpaca.markets/v2"

    @property
    def alpaca_options_url(self) -> str:
        """Options API URL for Alpaca."""
        return "https://data.alpaca.markets/v1beta1"


class EngineConfig:
    """Static configuration for the PUT engine layers."""

    # Market Regime Gates
    INDEX_SYMBOLS = ["SPY", "QQQ", "IWM"]

    # Universe by Sector
    UNIVERSE_SECTORS = {
        # Mega Cap Tech (15)
        "mega_cap_tech": [
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
            "AMD", "INTC", "AVGO", "ORCL", "CRM", "ADBE", "NFLX"
        ],
        # High Vol Tech (15)
        "high_vol_tech": [
            "SMCI", "PLTR", "SNOW", "COIN", "HOOD", "SOFI", "PATH", "MSTR",
            "UPST", "AFRM", "RBLX", "DKNG", "RIVN", "LCID", "NIO"
        ],
        # Space & Aerospace (14) - Added eVTOL names
        "space_aerospace": [
            "RKLB", "ASTS", "SPCE", "PL", "RDW", "LUNR", "BA", "LMT", "RTX", "NOC",
            "ACHR", "JOBY", "LILM", "EVTL"  # eVTOL - often move together with space
        ],
        # Nuclear & Energy (12) - Added UUUU, DNN
        "nuclear_energy": [
            "OKLO", "SMR", "CCJ", "LEU", "NNE", "CEG", "VST", "NRG", "FSLR", "ENPH",
            "UUUU", "DNN"  # Uranium plays - CRITICAL for sector moves
        ],
        # Quantum Computing (4)
        "quantum": [
            "IONQ", "RGTI", "QBTS", "QUBT"
        ],
        # AI & Data Centers (12)
        "ai_datacenters": [
            "IREN", "NBIS", "APLD", "CLSK", "HUT", "MARA", "RIOT", "CIFR",
            "APP", "AI", "BBAI", "SOUN"
        ],
        # Biotech (10)
        "biotech": [
            "MRNA", "BNTX", "NVAX", "VRTX", "REGN", "ILMN", "CRSP", "EDIT",
            "NTLA", "BEAM"
        ],
        # Crypto Related (10)
        "crypto": [
            "MSTR", "COIN", "MARA", "RIOT", "HUT", "CLSK", "CIFR", "GLXY",
            "BITF", "WULF"
        ],
        # Semiconductors (20)
        "semiconductors": [
            "NVDA", "AMD", "INTC", "MU", "AVGO", "QCOM", "TSM", "ASML", "AMAT",
            "LRCX", "KLAC", "MRVL", "ON", "SWKS", "STX", "WDC", "CRDO", "ALAB",
            "RMBS", "CLS"
        ],
        # Meme Stocks (6)
        "meme": [
            "GME", "AMC", "BBBY", "BB", "KOSS", "CLOV"
        ],
        # Fintech & InsurTech (12) - Added LMND, ROOT, HIPO
        "fintech": [
            "SQ", "PYPL", "AFRM", "UPST", "SOFI", "HOOD", "NU", "BILL", "FOUR",
            "LMND", "ROOT", "HIPO"  # InsurTech - high beta, move with fintech
        ],
        # Healthcare (5)
        "healthcare": [
            "HIMS", "TDOC", "OSCR", "AMWL", "TEM"
        ],
        # Industrials (9)
        "industrials": [
            "INOD", "BE", "PLUG", "FCEL", "BLDP", "TLN", "GEV", "AMSC", "LTBR"
        ],
        # Major ETFs (10)
        "etfs": [
            "SPY", "QQQ", "IWM", "DIA", "TQQQ", "SQQQ", "ARKK", "XLF", "XLE", "XLK"
        ],
        # Financials (9)
        "financials": [
            "JPM", "BAC", "GS", "MS", "V", "MA", "AXP", "C", "WFC"
        ],
        # Consumer (10)
        "consumer": [
            "DIS", "NFLX", "SBUX", "NKE", "MCD", "TGT", "WMT", "COST", "HD", "LOW"
        ],
        # Telecom & Wireless (6) - Added ONDS
        "telecom": [
            "T", "VZ", "TMUS", "CMCSA",
            "ONDS", "GSAT"  # Wireless/satellite
        ],
    }

    @classmethod
    def get_all_tickers(cls) -> list:
        """Get all unique tickers from all sectors."""
        all_tickers = set()
        for tickers in cls.UNIVERSE_SECTORS.values():
            all_tickers.update(tickers)
        return list(all_tickers)

    @classmethod
    def get_sector_tickers(cls, sector: str) -> list:
        """Get tickers for a specific sector."""
        return cls.UNIVERSE_SECTORS.get(sector, [])

    # Distribution Detection Thresholds
    # LOWERED from 1.5 to 1.3 to catch more moves - institutional moves often 1.3x-2.0x
    VOLUME_SPIKE_THRESHOLD = 1.3  # 1.3x average volume (was 1.5)
    RSI_OVERBOUGHT = 70
    RSI_OVERSOLD = 30
    FAILED_BREAKOUT_THRESHOLD = 0.02  # 2% retracement
    # RVOL thresholds for distribution detection
    RVOL_HIGH_THRESHOLD = 1.5  # 1.5x is elevated (was 2.0)
    RVOL_EXTREME_THRESHOLD = 2.0  # 2.0x is extreme institutional activity

    # Liquidity Vacuum Thresholds
    BID_COLLAPSE_THRESHOLD = 0.30  # 30% reduction in bid size
    SPREAD_WIDENING_THRESHOLD = 1.5  # 1.5x normal spread

    # Options Flow Thresholds
    PUT_CALL_RATIO_BEARISH = 1.2  # Above this is bearish
    IV_SPIKE_THRESHOLD = 0.20  # 20% IV increase = late entry
    SKEW_STEEPENING_THRESHOLD = 0.05  # Put IV - Call IV increase

    # Dealer / GEX Thresholds
    GEX_NEUTRAL_THRESHOLD = 0  # Below this is bearish
    PUT_WALL_PROXIMITY = 0.01  # 1% from price

    # Scoring Weights (LOCKED per Final Architect Report - DO NOT MODIFY)
    # Must sum to 1.0 excluding hard blocks
    SCORE_WEIGHTS = {
        "distribution_quality": 0.30,      # Primary alpha layer
        "dealer_positioning": 0.20,        # GEX / Delta
        "liquidity_vacuum": 0.15,          # Buyer withdrawal
        "options_flow": 0.15,              # Put buying / call selling
        "catalyst_proximity": 0.10,        # Earnings / events
        "sentiment_divergence": 0.05,      # Retail vs smart money
        "technical_alignment": 0.05        # VWAP / EMA / RSI
    }
    
    # Passive Inflow Windows (HARD BLOCKS)
    PASSIVE_INFLOW_MONTH_START_DAYS = [1, 2, 3]  # Day 1-3
    PASSIVE_INFLOW_MONTH_END_DAYS = [28, 29, 30, 31]  # Day 28-31
    PASSIVE_INFLOW_QUARTER_END_MONTHS = [3, 6, 9, 12]  # Mar, Jun, Sep, Dec

    # Time Windows
    MARKET_OPEN = "09:30"
    INITIAL_SCAN_END = "10:30"
    FLOW_ANALYSIS_END = "12:00"
    FINAL_CONFIRMATION_START = "14:30"
    FINAL_CONFIRMATION_END = "15:30"

    # Universe filters
    MIN_MARKET_CAP = 1_000_000_000  # $1B minimum
    MIN_AVG_VOLUME = 500_000  # 500K shares/day
    MIN_OPTIONS_VOLUME = 1000  # 1000 contracts/day
    MAX_SPREAD_PCT = 0.05  # 5% max bid-ask spread
    
    # ============================================================================
    # ARCHITECT-4 ADDITION: HIGH-BETA GROUPS FOR CLASS B TRADES
    # ============================================================================
    # These tickers can use Class B logic (lower threshold, sector correlation)
    # DO NOT add large caps here - they stay Class A only
    
    HIGH_BETA_GROUPS = {
        # Crypto miners - move together with Bitcoin
        "crypto_miners": ["RIOT", "MARA", "CIFR", "CLSK", "HUT", "BITF", "WULF"],
        # eVTOL / Aviation - move together
        "evtol": ["ACHR", "JOBY", "LILM", "EVTL"],
        # Clean energy - correlated
        "clean_energy": ["PLUG", "FCEL", "BE", "BLDP", "ENPH", "FSLR"],
        # Space / Satellite - correlated
        "space": ["LUNR", "PL", "RKLB", "SPCE", "ASTS"],
        # Quantum computing - correlated
        "quantum": ["IONQ", "RGTI", "QBTS", "QUBT"],
        # Nuclear / Uranium - correlated
        "nuclear": ["UUUU", "CCJ", "LEU", "DNN", "SMR", "OKLO"],
        # Meme stocks - sentiment driven
        "meme": ["GME", "AMC", "BBBY", "BB", "KOSS", "CLOV"],
    }
    
    # Flatten all high-beta tickers for quick lookup
    @classmethod
    def get_high_beta_tickers(cls) -> set:
        """Get all high-beta tickers (Class B eligible)."""
        tickers = set()
        for group in cls.HIGH_BETA_GROUPS.values():
            tickers.update(group)
        return tickers
    
    @classmethod
    def get_sector_peers(cls, symbol: str) -> list:
        """Get peer tickers in the same high-beta sector."""
        for group_name, tickers in cls.HIGH_BETA_GROUPS.items():
            if symbol in tickers:
                return [t for t in tickers if t != symbol]
        return []
    
    @classmethod
    def is_high_beta(cls, symbol: str) -> bool:
        """Check if symbol is in high-beta universe."""
        return symbol in cls.get_high_beta_tickers()
    
    # ============================================================================
    # ARCHITECT-4 ADDITION: SECTOR VELOCITY BOOST CONSTRAINTS
    # ============================================================================
    # Per Architect: "Apply ONLY if distribution_present AND liquidity_present"
    SECTOR_VELOCITY_MIN_PEERS = 3  # Minimum peers with score > 0.30
    SECTOR_VELOCITY_BOOST_MIN = 0.05
    SECTOR_VELOCITY_BOOST_MAX = 0.10
    SECTOR_PEER_MIN_SCORE = 0.30  # Peer must have this score to count


def get_settings() -> Settings:
    """Get application settings, loading from .env file."""
    return Settings()
