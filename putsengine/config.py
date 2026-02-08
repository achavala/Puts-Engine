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

    # FinViz API (Elite subscription)
    finviz_api_key: Optional[str] = Field(default=None, description="FinViz Elite API key")

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
    # LOWERED Jan 30 2026 - Was 0.68, missed APP(0.63), ASTS(0.65), IREN(0.63), OKLO(0.64)
    class_a_min_score: float = Field(default=0.60, ge=0.45, le=1.0)  # Core threshold (was 0.68)
    class_b_min_score: float = Field(default=0.20, ge=0.10, le=0.50)  # High-beta threshold (was 0.25)
    class_b_max_score: float = Field(default=0.55, ge=0.30, le=0.67)  # Cap for Class B (was 0.45)
    
    # Legacy threshold (uses Class A) - LOWERED
    min_score_threshold: float = Field(default=0.60, ge=0.0, le=1.0)  # Was 0.68
    
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
    uw_daily_limit: int = Field(default=15000, description="Unusual Whales daily API limit (Feb 8, 2026: new key, 15k/day)")
    # FEB 2, 2026: Updated for Options Advanced ($199/mo) plan - UNLIMITED API calls
    polygon_rate_limit: int = Field(default=100, description="Polygon requests per second (unlimited for paid plans)")

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

    # Universe by Sector - EXPANDED Jan 2026 to catch more moves
    # Previous misses: NET, MP, USAR, LAC, CVNA, UNH
    UNIVERSE_SECTORS = {
        # Mega Cap Tech (15)
        "mega_cap_tech": [
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
            "AMD", "INTC", "AVGO", "ORCL", "CRM", "ADBE", "NFLX"
        ],
        # Cloud / SaaS - HIGH PRIORITY (NEW SECTOR - missed NET)
        "cloud_saas": [
            "NET",    # Cloudflare - CRITICAL - missed 10% drop
            "CRWD",   # CrowdStrike
            "ZS",     # Zscaler
            "DDOG",   # Datadog
            "MDB",    # MongoDB
            "SNOW",   # Snowflake
            "PANW",   # Palo Alto Networks
            "FTNT",   # Fortinet
            "OKTA",   # Okta
            "NOW",    # ServiceNow
            "WDAY",   # Workday
            "TEAM",   # Atlassian
            "HUBS",   # HubSpot
            "TWLO",   # Twilio
            "ZM",     # Zoom
            "DOCU",   # DocuSign
        ],
        # High Vol Tech (15)
        "high_vol_tech": [
            "SMCI", "PLTR", "COIN", "HOOD", "SOFI", "PATH", "MSTR",
            "UPST", "AFRM", "RBLX", "DKNG", "RIVN", "LCID", "NIO"
        ],
        # Materials / Mining / Rare Earth - EXPANDED (missed MP, USAR, LAC)
        "materials_mining": [
            "MP",     # MP Materials - CRITICAL - missed 10%+ AH drop
            "USAR",   # USA Rare Earth - CRITICAL - missed 17%+ drop
            "LAC",    # Lithium Americas - CRITICAL - missed 13% drop
            "ALB",    # Albemarle - Lithium
            "SQM",    # Sociedad Quimica - Lithium
            "LTHM",   # Livent - Lithium
            "FCX",    # Freeport McMoRan - Copper
            "NEM",    # Newmont Mining - Gold
            "GOLD",   # Barrick Gold
            "AA",     # Alcoa - Aluminum
            "X",      # US Steel
            "NUE",    # Nucor Steel
            "CLF",    # Cleveland Cliffs - Iron ore
            "VALE",   # Vale - Iron ore/Nickel
            "RIO",    # Rio Tinto
            "BHP",    # BHP Group
        ],
        # SILVER MINERS - NEW SECTOR Jan 30 (missed AG -15%, CDE -15%, HL -13%)
        "silver_miners": [
            "AG",     # First Majestic Silver - MISSED -15.38% Jan 30!
            "CDE",    # Coeur Mining - MISSED -15.65% Jan 30!
            "HL",     # Hecla Mining - MISSED -13.07% Jan 30!
            "PAAS",   # Pan American Silver
            "MAG",    # MAG Silver
            "EXK",    # Endeavour Silver
            "SVM",    # Silvercorp Metals
            "FSM",    # Fortuna Silver Mines
            "SILV",   # SilverCrest Metals
        ],
        # GAMING - NEW SECTOR Jan 30 (missed U/Unity -23%)
        "gaming": [
            "U",      # Unity Software - MISSED -23.26% Jan 30!
            "EA",     # Electronic Arts
            "TTWO",   # Take-Two Interactive
            "ZNGA",   # Zynga (if trading)
            "SKLZ",   # Skillz
            "PLTK",   # Playtika
            "GLBE",   # Global-E Online
        ],
        # Auto / Used Cars / EV - NEW SECTOR (missed CVNA)
        "auto_retail": [
            "CVNA",   # Carvana - CRITICAL - missed 14% drop
            "KMX",    # CarMax
            "AN",     # AutoNation
            "PAG",    # Penske Auto
            "LAD",    # Lithia Motors
            "CPRT",   # Copart - Auto auctions
            "IAA",    # IAA Inc
            "VRM",    # Vroom (if still trading)
            "LOTZ",   # CarLotz
        ],
        # Space & Aerospace (15) - Added eVTOL names
        "space_aerospace": [
            "RKLB", "ASTS", "SPCE", "PL", "RDW", "LUNR", "BA", "LMT", "RTX", "NOC",
            "ACHR", "JOBY", "LILM", "EVTL", "GE"
        ],
        # Nuclear & Energy (14) - Added more uranium
        "nuclear_energy": [
            "OKLO", "SMR", "CCJ", "LEU", "NNE", "CEG", "VST", "NRG", "FSLR", "ENPH",
            "UUUU", "DNN", "UEC", "URG"
        ],
        # Quantum Computing (4)
        "quantum": [
            "IONQ", "RGTI", "QBTS", "QUBT"
        ],
        # AI & Data Centers (15)
        "ai_datacenters": [
            "IREN", "NBIS", "APLD", "CLSK", "HUT", "MARA", "RIOT", "CIFR",
            "APP", "AI", "BBAI", "SOUN", "PLTR", "PATH", "AISP"
        ],
        # Biotech (12)
        "biotech": [
            "MRNA", "BNTX", "NVAX", "VRTX", "REGN", "ILMN", "CRSP", "EDIT",
            "NTLA", "BEAM", "EXAS", "ISRG"
        ],
        # Crypto Related (12) - Added BMNR, CRCL (Circle Internet - missed -7.91% Feb 2)
        "crypto": [
            "MSTR", "COIN", "MARA", "RIOT", "HUT", "CLSK", "CIFR", "GLXY",
            "BITF", "WULF", "BMNR", "CRCL"
        ],
        # Semiconductors (27) - Added TXN, SNDK, LITE, COHR
        "semiconductors": [
            "NVDA", "AMD", "INTC", "MU", "AVGO", "QCOM", "TSM", "ASML", "AMAT",
            "LRCX", "KLAC", "MRVL", "ON", "SWKS", "STX", "WDC", "CRDO", "ALAB",
            "RMBS", "CLS", "ARM", "WOLF", "TXN", "SNDK", "LITE", "COHR", "UMAC"
        ],
        # Meme Stocks (6)
        "meme": [
            "GME", "AMC", "BBBY", "BB", "KOSS", "CLOV"
        ],
        # Fintech & InsurTech (12)
        "fintech": [
            "SQ", "PYPL", "AFRM", "UPST", "SOFI", "HOOD", "NU", "BILL", "FOUR",
            "LMND", "ROOT", "HIPO"
        ],
        # Healthcare & Insurance (26) - EXPANDED after missing ELV -14%, CVS -14%, HUM -21%
        "healthcare_insurance": [
            # Managed Care / Health Insurance (CRITICAL - missed big Jan 27 drops)
            "UNH",    # UnitedHealth - MISSED -19.6% Jan 27
            "HUM",    # Humana - MISSED -21.1% Jan 27
            "ELV",    # Elevance (was Anthem/ANTM) - MISSED -14.3% Jan 27
            "CVS",    # CVS Health - MISSED -14.2% Jan 27
            "CI",     # Cigna
            "CNC",    # Centene
            "MOH",    # Molina Healthcare
            # Telehealth & Digital Health
            "HIMS", "TDOC", "OSCR", "AMWL", "TEM",
            # Pharma (often moves with insurance on policy news)
            "PFE", "JNJ", "MRK", "LLY", "ABBV", "BMY", "GILD",
            # Hospital / Healthcare Services
            "HCA", "THC", "UHS", "CYH",
        ],
        # MEDICAL DEVICES - NEW SECTOR Feb 4 (missed BSX -17.69%!)
        "medical_devices": [
            "BSX",    # Boston Scientific - MISSED -17.69% Feb 4!
            "MDT",    # Medtronic
            "ABT",    # Abbott Labs
            "SYK",    # Stryker
            "ISRG",   # Intuitive Surgical
            "EW",     # Edwards Lifesciences
            "ZBH",    # Zimmer Biomet
            "BDX",    # Becton Dickinson
            "HOLX",   # Hologic
            "BAX",    # Baxter
            "ALGN",   # Align Technology
            "DXCM",   # Dexcom
            "PODD",   # Insulet
        ],
        # Industrials / Clean Energy (14) - Added EOSE, SERV
        "industrials": [
            "INOD", "BE", "PLUG", "FCEL", "BLDP", "TLN", "GEV", "AMSC", "LTBR",
            "CAT", "DE", "CMI", "EOSE", "SERV"
        ],
        # Defense / Aerospace Volatile (5) - Added RR, RCAT, CRWV
        "defense_volatile": [
            "RR",      # Rolls Royce - CRITICAL - had +44.6% then -20.9%
            "RCAT",    # Red Cat Holdings - drone company
            "CRWV",    # CrowdStrike variant
            "KTOS",    # Kratos Defense
            "PLTR",    # Palantir
        ],
        # Major ETFs (12)
        "etfs": [
            "SPY", "QQQ", "IWM", "DIA", "TQQQ", "SQQQ", "ARKK", "XLF", "XLE", "XLK",
            "XLB", "XLI"
        ],
        # Financials (12)
        "financials": [
            "JPM", "BAC", "GS", "MS", "V", "MA", "AXP", "C", "WFC", "BRK.B",
            "SCHW", "USB"
        ],
        # Consumer / Retail (15)
        "consumer": [
            "DIS", "NFLX", "SBUX", "NKE", "MCD", "TGT", "WMT", "COST", "HD", "LOW",
            "AMZN", "BABA", "JD", "PDD", "EBAY"
        ],
        # Telecom & Wireless (7) - Added NOK
        "telecom": [
            "T", "VZ", "TMUS", "CMCSA", "ONDS", "GSAT", "NOK"
        ],
        # Travel / Airlines / Leisure (12) - NEW SECTOR
        "travel": [
            "DAL", "UAL", "AAL", "LUV", "JBLU",
            "CCL", "RCL", "NCLH",
            "MAR", "HLT", "ABNB", "BKNG"
        ],
        # China ADRs (10) - NEW SECTOR - volatile on tariff news
        "china_adr": [
            "BABA", "JD", "PDD", "BIDU", "NIO", "XPEV", "LI", "BILI", "TME", "IQ"
        ],
        # ========================================================================
        # FEB 3, 2026 CRASH FIX: MISSING SECTORS THAT CAUSED 186% OPPORTUNITY LOSS
        # ========================================================================
        # CONSULTING / IT SERVICES - missed ACN -9.71%
        "consulting": [
            "ACN",    # Accenture - MISSED -9.71% Feb 3!
            "IBM",    # IBM
            "INFY",   # Infosys
            "WIT",    # Wipro
            "CTSH",   # Cognizant
            "EPAM",   # EPAM Systems
        ],
        # PRIVATE EQUITY / ALT ASSET MANAGERS - missed KKR -9.68%
        "alt_asset_mgmt": [
            "KKR",    # KKR & Co - MISSED -9.68% Feb 3!
            "BX",     # Blackstone
            "APO",    # Apollo Global
            "ARES",   # Ares Management
            "CG",     # Carlyle Group
            "OWL",    # Blue Owl Capital
        ],
        # CREDIT BUREAUS / DATA SERVICES - missed TRU -12.56%
        "credit_data": [
            "TRU",    # TransUnion - MISSED -12.56% Feb 3!
            "EFX",    # Equifax
            "EXPN",   # Experian
            "FDS",    # FactSet
            "SPGI",   # S&P Global
            "MCO",    # Moody's
            "MSCI",   # MSCI
        ],
        # INTERNATIONAL PHARMA ADRs - missed NVO -14.35%
        "pharma_adr": [
            "NVO",    # Novo Nordisk - MISSED -14.35% Feb 3!
            "AZN",    # AstraZeneca
            "SNY",    # Sanofi
            "GSK",    # GSK
            "RHHBY",  # Roche
            "TAK",    # Takeda
        ],
        # REAL ESTATE TECH - missed CSGP -15.02%
        "realestate_tech": [
            "CSGP",   # CoStar Group - MISSED -15.02% Feb 3!
            "ZG",     # Zillow
            "RDFN",   # Redfin
            "OPEN",   # Opendoor
            "COMP",   # Compass
            "RL",     # RealtyMogul
        ],
        # E-COMMERCE / PAYMENTS EXPANSION - missed SHOP -9.89%, INTU -11.13%
        "ecommerce_payments": [
            "SHOP",   # Shopify - MISSED -9.89% Feb 3!
            "INTU",   # Intuit - MISSED -11.13% Feb 3!
            "FIS",    # Fidelity National
            "FISV",   # Fiserv
            "GPN",    # Global Payments
            "ADYEN",  # Adyen (if traded)
            "PYPL",   # Already in fintech but critical
        ],
        # E-COMMERCE RETAIL - NEW SECTOR Feb 4 (missed W -13.03%!)
        "ecommerce_retail": [
            "W",      # Wayfair - MISSED -13.03% Feb 4!
            "ETSY",   # Etsy
            "CHWY",   # Chewy
            "WISH",   # ContextLogic
            "FVRR",   # Fiverr
            "UPWK",   # Upwork
            "RVLV",   # Revolve
            "REAL",   # TheRealReal
            "PRTS",   # CarParts
            "FLWS",   # 1-800-Flowers
            "OSTK",   # Overstock
        ],
        # ELECTRONICS MANUFACTURING - NEW SECTOR Feb 4 (missed TTMI -10.37%!)
        "electronics_mfg": [
            "TTMI",   # TTM Technologies - MISSED -10.37% Feb 4!
            "FLEX",   # Flex Ltd
            "JABIL",  # Jabil
            "SANM",   # Sanmina
            "PLXS",   # Plexus
            "CGNX",   # Cognex
            "MKSI",   # MKS Instruments
            "ENTG",   # Entegris
            "LRCX",   # Lam Research
            "KLAC",   # KLA Corp
        ],
        # TRAVEL OTAs - missed EXPE -15.26%
        "travel_ota": [
            "EXPE",   # Expedia - MISSED -15.26% Feb 3!
            "BKNG",   # Booking Holdings
            "TRIP",   # TripAdvisor
            "TCOM",   # Trip.com
            "MMYT",   # MakeMyTrip
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
        "nuclear": ["UUUU", "CCJ", "LEU", "DNN", "SMR", "OKLO", "UEC", "URG"],
        # Meme stocks - sentiment driven
        "meme": ["GME", "AMC", "BBBY", "BB", "KOSS", "CLOV"],
        # Rare Earth / Materials - move together on China news
        "rare_earth": ["MP", "USAR", "LAC", "ALB", "LTHM", "SQM"],
        # Cloud/Cybersecurity - correlated
        "cloud_security": ["NET", "CRWD", "ZS", "PANW", "FTNT", "OKTA"],
        # China ADRs - move together on tariff/policy news
        "china_adr": ["BABA", "JD", "PDD", "BIDU", "NIO", "XPEV", "LI"],
        # Used car / Auto retail - correlated
        "auto_retail": ["CVNA", "KMX", "AN", "VRM"],
        # SILVER MINERS - NEW Jan 30 (AG -15%, CDE -15%, HL -13% - all crashed together!)
        "silver_miners": ["AG", "CDE", "HL", "PAAS", "MAG", "EXK", "SVM", "FSM", "SILV"],
        # GAMING - NEW Jan 30 (Unity -23% - correlated with RBLX, EA)
        "gaming": ["U", "RBLX", "EA", "TTWO", "SKLZ", "PLTK"],
        # AI/Data Center - NEW Jan 30 (APP -15%, NBIS -10%, IREN -9% - all crashed together!)
        "ai_datacenter": ["APP", "NBIS", "IREN", "AI", "BBAI", "SOUN", "PLTR"],
        # ========================================================================
        # FEB 4, 2026 CRASH FIX: NEW CORRELATION GROUPS
        # ========================================================================
        # Medical Devices - correlated (BSX -17.69%, MDT, ABT, SYK move together)
        "medical_devices": ["BSX", "MDT", "ABT", "SYK", "ISRG", "EW", "ZBH", "DXCM"],
        # E-Commerce Retail - correlated (W -13.03%, ETSY, CHWY move together)
        "ecommerce_retail": ["W", "ETSY", "CHWY", "WISH", "RVLV", "OSTK"],
        # Electronics Mfg - correlated (TTMI -10.37%, FLEX, JABIL move together)
        "electronics_mfg": ["TTMI", "FLEX", "JABIL", "SANM", "CGNX", "MKSI"],
        # ========================================================================
        # FEB 3, 2026 CRASH FIX: EARNINGS CLUSTER CORRELATION GROUPS
        # ========================================================================
        # SaaS earnings cluster (HUBS, SNOW, CRWD crash together)
        "saas_earnings": ["HUBS", "SNOW", "DDOG", "MDB", "CRWD", "ZS", "OKTA", "NET"],
        # Fintech earnings cluster (PYPL, SHOP, INTU crash together)
        "fintech_earnings": ["PYPL", "SHOP", "INTU", "SQ", "AFRM", "SOFI", "HOOD"],
        # Travel earnings cluster (EXPE, ABNB, BKNG crash together)
        "travel_earnings": ["EXPE", "ABNB", "BKNG", "MAR", "HLT", "TRIP"],
        # Semiconductor earnings (AMD, RMBS, LITE crash together)
        "semi_earnings": ["AMD", "RMBS", "LITE", "MU", "NVDA", "AVGO", "MRVL"],
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

    # ============================================================================
    # ARCHITECT-4 ADDITION: DYNAMIC UNIVERSE INJECTION (DUI)
    # ============================================================================
    # 
    # PURPOSE: Catch moves like PL, CRSP, UUUU that aren't in static universe
    # but show structural signals (distribution/liquidity) FIRST.
    #
    # KEY PRINCIPLE: Dynamic candidates are NOT "top movers" - they are
    # STRUCTURE-VALIDATED names that Engine 2/3 discovered.
    #
    # PIPELINE:
    #   STATIC_CORE_UNIVERSE
    #           │
    #           ▼
    #   ENGINE 2: DISTRIBUTION  ──┐
    #   ENGINE 3: LIQUIDITY     ──┤
    #           │                 │
    #           ▼                 ▼
    #   DYNAMIC UNIVERSE INJECTION (DUI)  ← Promotes E2/E3 hits
    #           │
    #           ▼
    #   ENGINE 1: GAMMA DRAIN (CONFIRMATION)
    #           │
    #           ▼
    #   FINAL CANDIDATES
    #
    # RULES:
    # 1. Only Distribution/Liquidity Engine hits can be promoted (NOT momentum)
    # 2. Minimum score >= 0.30 to promote
    # 3. TTL = 3 trading days (auto-expire if no Gamma confirmation)
    # 4. Must be below VWAP for promotion
    
    # DUI Configuration
    DUI_MIN_SCORE_FOR_PROMOTION = 0.30  # Minimum score to promote to dynamic set
    DUI_TTL_TRADING_DAYS = 3  # Auto-expire after 3 days without confirmation
    DUI_REQUIRE_BELOW_VWAP = True  # Must be below VWAP to promote
    
    # Maximum dynamic universe size (prevent bloat)
    DUI_MAX_DYNAMIC_SET_SIZE = 50
    
    # File to persist dynamic universe across restarts
    DUI_PERSISTENCE_FILE = "dynamic_universe.json"


# ============================================================================
# DYNAMIC UNIVERSE MANAGER
# ============================================================================
class DynamicUniverseManager:
    """
    Manages the Dynamic Structural Set (DUI).
    
    This is NOT a momentum scanner. It promotes tickers that:
    1. Have structural signals from Distribution/Liquidity engines
    2. Meet minimum score threshold (0.30)
    3. Are below VWAP (optional but recommended)
    
    Tickers expire automatically after TTL if not confirmed by Gamma Drain.
    """
    
    _instance = None
    _dynamic_set: dict = {}  # {symbol: {score, source, added_date, expires_date}}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_persisted()
        return cls._instance
    
    def _load_persisted(self):
        """Load persisted dynamic universe from file."""
        import json
        from pathlib import Path
        from datetime import datetime
        
        persistence_file = Path(EngineConfig.DUI_PERSISTENCE_FILE)
        if persistence_file.exists():
            try:
                with open(persistence_file, 'r') as f:
                    data = json.load(f)
                    # Filter out expired entries
                    today = datetime.now().date().isoformat()
                    self._dynamic_set = {
                        symbol: info 
                        for symbol, info in data.items()
                        if info.get('expires_date', '') >= today
                    }
            except Exception:
                self._dynamic_set = {}
        else:
            self._dynamic_set = {}
    
    def _persist(self):
        """Persist dynamic universe to file."""
        import json
        from pathlib import Path
        
        persistence_file = Path(EngineConfig.DUI_PERSISTENCE_FILE)
        with open(persistence_file, 'w') as f:
            json.dump(self._dynamic_set, f, indent=2)
    
    def promote_from_distribution(self, symbol: str, score: float, signals: list = None):
        """
        Promote a symbol from Distribution Engine hit.
        
        Args:
            symbol: Ticker symbol
            score: Distribution score (must be >= 0.30)
            signals: List of signals detected
        """
        self._promote(symbol, score, "distribution", signals or [])
    
    def promote_from_liquidity(self, symbol: str, score: float, signals: list = None):
        """
        Promote a symbol from Liquidity Engine hit.
        
        Args:
            symbol: Ticker symbol
            score: Liquidity score (must be >= 0.30)
            signals: List of signals detected
        """
        self._promote(symbol, score, "liquidity", signals or [])
    
    def inject_symbol(self, symbol: str, source: str, reason: str, score: float, 
                      signals: list = None, ttl_days: int = 3):
        """
        Inject a symbol into DUI from any scanner (e.g., EWS, earnings priority).
        
        This is a generic injection method that allows custom sources and TTL.
        
        Args:
            symbol: Ticker symbol
            source: Source scanner name (e.g., 'early_warning', 'earnings_priority')
            reason: Human-readable reason for injection
            score: Score/IPI value
            signals: List of detected signals/footprints
            ttl_days: Time-to-live in calendar days (default 3)
        """
        from datetime import datetime, timedelta
        
        # Check minimum score (use lower threshold for EWS since IPI scale is different)
        min_score = 0.30 if source != 'early_warning' else 0.50
        if score < min_score:
            return
        
        # Calculate expiry
        today = datetime.now().date()
        expires = today + timedelta(days=ttl_days)
        
        # Check if new or update
        is_new = symbol not in self._dynamic_set
        
        # Add or update
        self._dynamic_set[symbol] = {
            'score': score,
            'source': source,
            'reason': reason,
            'signals': signals or [],
            'added_date': today.isoformat(),
            'expires_date': expires.isoformat()
        }
        
        # Log injection event
        action = "INJECTED" if is_new else "UPDATED"
        self._log_promotion(
            f"DUI: {action} {symbol} | Source: {source} | Score: {score:.2f} | "
            f"Reason: {reason} | Expires: {expires.isoformat()}"
        )
        
        self._persist()
    
    def _promote(self, symbol: str, score: float, source: str, signals: list):
        """Internal promotion logic with debug logging."""
        from datetime import datetime, timedelta
        
        # Check minimum score
        if score < EngineConfig.DUI_MIN_SCORE_FOR_PROMOTION:
            return
        
        # Check max size
        if len(self._dynamic_set) >= EngineConfig.DUI_MAX_DYNAMIC_SET_SIZE:
            # Remove lowest score to make room
            if symbol not in self._dynamic_set:
                lowest = min(self._dynamic_set.items(), key=lambda x: x[1].get('score', 0))
                if lowest[1].get('score', 0) < score:
                    del self._dynamic_set[lowest[0]]
                    self._log_promotion(f"DUI: Removed {lowest[0]} (score {lowest[1].get('score', 0):.2f}) to make room")
                else:
                    return  # Don't add if lower than all existing
        
        # Calculate expiry (TTL in trading days ≈ calendar days + weekends)
        today = datetime.now().date()
        # Rough estimate: 3 trading days ≈ 5 calendar days
        expires = today + timedelta(days=EngineConfig.DUI_TTL_TRADING_DAYS + 2)
        
        # Check if new or update
        is_new = symbol not in self._dynamic_set
        
        # Add or update
        self._dynamic_set[symbol] = {
            'score': score,
            'source': source,
            'signals': signals,
            'added_date': today.isoformat(),
            'expires_date': expires.isoformat()
        }
        
        # Log promotion event
        action = "PROMOTED" if is_new else "UPDATED"
        signals_str = ', '.join(signals[:3]) if signals else 'none'
        self._log_promotion(
            f"DUI: {action} {symbol} | Source: {source} | Score: {score:.2f} | "
            f"Signals: {signals_str} | Expires: {expires.isoformat()}"
        )
        
        self._persist()
    
    def _log_promotion(self, message: str):
        """Log promotion events to file for debug/audit."""
        from datetime import datetime
        from pathlib import Path
        
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / "dui_promotions.log"
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, 'a') as f:
            f.write(f"[{timestamp}] {message}\n")
    
    def get_dynamic_set(self) -> set:
        """Get current dynamic structural set."""
        self._cleanup_expired()
        return set(self._dynamic_set.keys())
    
    def get_dynamic_details(self) -> dict:
        """Get full details of dynamic set."""
        self._cleanup_expired()
        return dict(self._dynamic_set)
    
    def get_final_scan_universe(self) -> set:
        """
        Get the final scan universe combining:
        - Static Core Universe (always-on)
        - Dynamic Structural Set (promoted from E2/E3 hits)
        
        This is what Engine 1 (Gamma Drain) should scan.
        """
        static_universe = set(EngineConfig.get_all_tickers())
        dynamic_universe = self.get_dynamic_set()
        return static_universe.union(dynamic_universe)
    
    def _cleanup_expired(self):
        """Remove expired entries."""
        from datetime import datetime
        
        today = datetime.now().date().isoformat()
        expired = [
            symbol for symbol, info in self._dynamic_set.items()
            if info.get('expires_date', '') < today
        ]
        
        for symbol in expired:
            del self._dynamic_set[symbol]
        
        if expired:
            self._persist()
    
    def remove(self, symbol: str):
        """Manually remove a symbol from dynamic set."""
        if symbol in self._dynamic_set:
            del self._dynamic_set[symbol]
            self._persist()
    
    def clear(self):
        """Clear entire dynamic set."""
        self._dynamic_set = {}
        self._persist()
    
    def is_dynamic(self, symbol: str) -> bool:
        """Check if symbol is in dynamic set."""
        return symbol in self._dynamic_set
    
    def get_promotion_source(self, symbol: str) -> str:
        """Get the source that promoted this symbol."""
        if symbol in self._dynamic_set:
            return self._dynamic_set[symbol].get('source', 'unknown')
        return None


def get_settings() -> Settings:
    """Get application settings, loading from .env file."""
    return Settings()
