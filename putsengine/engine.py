"""
PutsEngine - Main Execution Pipeline and Orchestrator.

This is the core engine that ties all layers together into
a single deterministic pipeline for PUT detection.

Pipeline Flow:
1. Market Regime Check (GATE)
2. Universe Scan → Shortlist (≤15)
3. Distribution Detection
4. Liquidity Vacuum Check
5. Acceleration Window Timing
6. Dealer/Put Wall Check (GATE)
7. Final Scoring
8. Strike/DTE Selection
9. Trade Execution (if criteria met)

Daily Execution Windows:
- 09:30-10:30: Initial scan (Alpaca)
- 10:30-12:00: Flow analysis (Unusual Whales)
- 14:30-15:30: Final confirmation & execution
"""

import asyncio
import json
from datetime import datetime, date, time, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Tuple
import pytz
from loguru import logger

from putsengine.config import Settings, EngineConfig, get_settings
from putsengine.models import (
    PutCandidate, MarketRegimeData, DailyReport,
    BlockReason, TradeExecution, OptionsContract
)
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient
from putsengine.clients.unusual_whales_client import UnusualWhalesClient
from putsengine.clients.finviz_client import FinVizClient
from putsengine.layers.market_regime import MarketRegimeLayer
from putsengine.layers.distribution import DistributionLayer
from putsengine.layers.liquidity import LiquidityVacuumLayer
from putsengine.layers.acceleration import AccelerationWindowLayer
from putsengine.layers.dealer import DealerPositioningLayer
from putsengine.scoring.scorer import PutScorer
from putsengine.scoring.strike_selector import StrikeSelector


class PutsEngine:
    """
    Main PUT Options Trading Engine.

    Implements the complete pipeline for identifying -5% to -20%
    moves 1-10 days ahead with asymmetric put P&L.

    Key principles:
    - Calls = acceleration engines
    - Puts = permission engines
    - Flow is leading, price is lagging
    - Empty days are a feature, not a bug
    """

    def __init__(self, settings: Optional[Settings] = None):
        """Initialize the PutsEngine with all components."""
        self.settings = settings or get_settings()
        self.config = EngineConfig

        # Initialize API clients
        self.alpaca = AlpacaClient(self.settings)
        self.polygon = PolygonClient(self.settings)
        self.unusual_whales = UnusualWhalesClient(self.settings)
        
        # FinViz client (optional - for technical screening enhancement)
        self.finviz = FinVizClient(self.settings) if self.settings.finviz_api_key else None
        if self.finviz:
            logger.info("FinViz integration enabled")

        # Initialize layers
        self.market_regime = MarketRegimeLayer(
            self.alpaca, self.polygon, self.unusual_whales, self.settings
        )
        self.distribution = DistributionLayer(
            self.alpaca, self.polygon, self.unusual_whales, self.settings
        )
        self.liquidity = LiquidityVacuumLayer(
            self.alpaca, self.polygon, self.settings
        )
        self.acceleration = AccelerationWindowLayer(
            self.alpaca, self.polygon, self.unusual_whales, self.settings
        )
        self.dealer = DealerPositioningLayer(
            self.alpaca, self.polygon, self.unusual_whales, self.settings
        )

        # Initialize scoring and selection
        self.scorer = PutScorer(self.settings)
        self.strike_selector = StrikeSelector(
            self.alpaca, self.polygon, self.settings
        )

        # State tracking
        self.daily_report: Optional[DailyReport] = None
        self.candidates: List[PutCandidate] = []
        self.api_calls = {"alpaca": 0, "polygon": 0, "unusual_whales": 0, "finviz": 0}
        
        # Caching for performance
        self._cached_regime: Optional[MarketRegimeData] = None
        self._regime_cache_time: Optional[datetime] = None
        self._regime_cache_ttl = 300  # 5 minutes cache
        
        # File-based caching for market regime (persists across dashboard reloads)
        self._regime_cache_file = Path(__file__).parent.parent / "market_regime_cache.json"
        self._regime_file_cache_ttl = 1800  # 30 minutes for file cache

        logger.info("PutsEngine initialized")

    async def close(self):
        """Close all API connections."""
        await self.alpaca.close()
        await self.polygon.close()
        await self.unusual_whales.close()
        if self.finviz:
            await self.finviz.close()

    async def run_daily_pipeline(
        self,
        universe: Optional[List[str]] = None
    ) -> DailyReport:
        """
        Run the complete daily pipeline.

        Args:
            universe: Optional list of symbols to scan.
                     If None, uses a default liquid universe.

        Returns:
            DailyReport with all analysis results
        """
        logger.info("=" * 60)
        logger.info("Starting daily PUT pipeline")
        logger.info("=" * 60)

        # Initialize daily report
        self.daily_report = DailyReport(
            date=date.today(),
            total_scanned=0,
            shortlist_count=0,
            passed_gates=0,
            trades_executed=0
        )

        try:
            # STEP 1: Market Regime Check (GATE)
            logger.info("\n>>> LAYER 1: Market Regime Check")
            regime = await self.market_regime.analyze()
            self.daily_report.market_regime = regime

            if not regime.is_tradeable:
                logger.warning(
                    f"Market regime NOT tradeable: {regime.block_reasons}"
                )
                return self.daily_report

            logger.info(f"Market regime: {regime.regime.value} - TRADEABLE")

            # STEP 2: Universe Scan
            logger.info("\n>>> LAYER 2: Universe Scan")
            if universe is None:
                universe = await self._get_default_universe()

            self.daily_report.total_scanned = len(universe)
            logger.info(f"Scanning {len(universe)} symbols...")

            # Build initial shortlist (<=15 names)
            shortlist = await self._build_shortlist(universe)
            self.daily_report.shortlist_count = len(shortlist)
            logger.info(f"Shortlist: {len(shortlist)} candidates")

            if not shortlist:
                logger.info("No candidates passed initial screening")
                return self.daily_report

            # STEP 3: Deep Analysis on Shortlist
            logger.info("\n>>> LAYER 3-6: Deep Analysis")
            candidates = await self._analyze_shortlist(shortlist)

            # STEP 4: Final Scoring
            logger.info("\n>>> LAYER 7: Final Scoring")
            actionable = self._score_and_filter(candidates)
            self.daily_report.passed_gates = len(actionable)

            if not actionable:
                logger.info("No candidates passed all gates and scoring")
                return self.daily_report

            # STEP 5: Vega Gate - Volatility Structure Selection (Architect-4)
            logger.info("\n>>> LAYER 7.5: Vega Gate (IV Regime Check)")
            from putsengine.gates.vega_gate import apply_vega_gate
            
            for candidate in actionable:
                try:
                    candidate, vega_result = await apply_vega_gate(
                        candidate,
                        alpaca_client=self.alpaca,
                        polygon_client=self.polygon
                    )
                    if vega_result:
                        logger.info(
                            f"  {candidate.symbol}: IV Rank={vega_result.iv_rank:.0f}%, "
                            f"Decision={vega_result.decision.value}, "
                            f"Structure={vega_result.recommended_structure}"
                        )
                except Exception as e:
                    logger.debug(f"Vega Gate error for {candidate.symbol}: {e}")

            # STEP 6: Strike Selection
            logger.info("\n>>> LAYER 8: Strike/DTE Selection")
            for candidate in actionable[:self.settings.max_daily_trades]:
                # Apply Vega Gate adjustments to DTE if needed
                dte_adjustment = candidate.vega_gate_dte_add if hasattr(candidate, 'vega_gate_dte_add') else 0
                
                contract = await self.strike_selector.select_contract(
                    candidate, 
                    dte_adjustment=dte_adjustment
                )
                if contract:
                    candidate.contract_symbol = contract.symbol
                    candidate.recommended_strike = contract.strike
                    candidate.recommended_expiration = contract.expiration
                    candidate.recommended_delta = contract.delta
                    candidate.entry_price = contract.mid_price

            self.daily_report.candidates = actionable[:self.settings.max_daily_trades]

            # STEP 6: Trade Execution (if enabled)
            # Note: Actual execution is optional and should be explicitly called
            logger.info("\n>>> Pipeline Complete")
            logger.info(f"Actionable candidates: {len(actionable)}")
            for c in actionable[:5]:
                logger.info(
                    f"  {c.symbol}: Score={c.composite_score:.2f}, "
                    f"Contract={c.contract_symbol}"
                )

        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            raise

        return self.daily_report

    async def _get_default_universe(self) -> List[str]:
        """
        Get default universe of liquid, optionable stocks.

        Returns top losers and high-volume stocks as candidates.
        Organized by sector for comprehensive coverage.
        """
        universe = set()

        try:
            # Get top losers
            losers = await self.polygon.get_gainers_losers("losers")
            for ticker in losers[:30]:
                symbol = ticker.get("ticker", "")
                if symbol and not symbol.startswith("$"):
                    universe.add(symbol)

        except Exception as e:
            logger.warning(f"Error getting losers: {e}")

        # Comprehensive universe by sector
        sectors = {
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
            # Space & Aerospace (10)
            "space_aerospace": [
                "RKLB", "ASTS", "SPCE", "PL", "RDW", "LUNR", "BA", "LMT", "RTX", "NOC"
            ],
            # Nuclear & Energy (10)
            "nuclear_energy": [
                "OKLO", "SMR", "CCJ", "LEU", "NNE", "CEG", "VST", "NRG", "FSLR", "ENPH"
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
            # Fintech (9)
            "fintech": [
                "SQ", "PYPL", "AFRM", "UPST", "SOFI", "HOOD", "NU", "BILL", "FOUR"
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
            # Telecom (5)
            "telecom": [
                "T", "VZ", "TMUS", "CMCSA"
            ],
        }

        # Add all sectors to universe
        for sector_name, tickers in sectors.items():
            universe.update(tickers)

        logger.info(f"Universe loaded: {len(universe)} unique tickers across {len(sectors)} sectors")
        return list(universe)

    async def _build_shortlist(
        self,
        universe: List[str]
    ) -> List[str]:
        """
        Build initial shortlist from universe.

        Filters for:
        - Overextended stocks (RSI > 70 or recent run-up)
        - Below VWAP
        - Elevated volume

        Returns max 15 names.
        """
        shortlist = []

        for symbol in universe:
            try:
                # Quick screening using Polygon snapshot
                snapshot = await self.polygon.get_snapshot(symbol)

                if not snapshot or "ticker" not in snapshot:
                    continue

                ticker = snapshot["ticker"]

                # Get day data
                day_data = ticker.get("day", {})
                if not day_data:
                    continue

                # Check if down today
                day_change = float(day_data.get("c", 0)) - float(day_data.get("o", 0))
                if day_change >= 0:
                    continue  # Only interested in stocks that are down

                # Check volume (above average)
                volume = int(day_data.get("v", 0))
                prev_volume = int(ticker.get("prevDay", {}).get("v", 1))
                if volume < prev_volume * 0.8:
                    continue

                # Check VWAP
                vwap = float(day_data.get("vw", 0))
                current = float(day_data.get("c", 0))
                if vwap > 0 and current >= vwap:
                    continue  # Must be below VWAP

                shortlist.append(symbol)

                if len(shortlist) >= 15:
                    break

            except Exception as e:
                logger.debug(f"Error screening {symbol}: {e}")
                continue

        return shortlist

    async def _analyze_shortlist(
        self,
        shortlist: List[str]
    ) -> List[PutCandidate]:
        """
        Perform deep analysis on shortlist candidates.

        Runs all layers: Distribution, Liquidity, Acceleration, Dealer
        """
        candidates = []

        for i, symbol in enumerate(shortlist):
            logger.info(f"\nAnalyzing [{i+1}/{len(shortlist)}]: {symbol}")

            candidate = PutCandidate(
                symbol=symbol,
                timestamp=datetime.now(),
                shortlist_position=i + 1
            )

            try:
                # Get current price
                quote = await self.alpaca.get_latest_quote(symbol)
                if quote and "quote" in quote:
                    candidate.current_price = float(quote["quote"].get("ap", 0))

                # Layer 3: Distribution Detection
                distribution = await self.distribution.analyze(symbol)
                candidate.distribution = distribution
                candidate.distribution_score = distribution.score

                if distribution.score < 0.3:
                    candidate.block_reasons.append(BlockReason.NO_DISTRIBUTION)
                    candidates.append(candidate)
                    continue
                    
                # NEW: Earnings Proximity Block (per Final Architect Report)
                # "Never buy puts BEFORE earnings"
                if distribution.signals.get("is_pre_earnings", False):
                    candidate.block_reasons.append(BlockReason.EARNINGS_PROXIMITY)
                    logger.warning(f"{symbol}: BLOCKED - Pre-earnings period")
                    candidates.append(candidate)
                    continue
                    
                # NEW: Check Borrow Status / Squeeze Risk
                borrow_status = await self.alpaca.check_borrow_status(symbol)
                if borrow_status.get("squeeze_risk", False):
                    candidate.block_reasons.append(BlockReason.HTB_SQUEEZE_RISK)
                    logger.warning(f"{symbol}: BLOCKED - HTB squeeze risk")
                    candidates.append(candidate)
                    continue

                # Layer 4: Liquidity Vacuum
                liquidity = await self.liquidity.analyze(symbol)
                candidate.liquidity = liquidity
                candidate.liquidity_score = liquidity.score

                # Layer 5: Acceleration Window
                acceleration = await self.acceleration.analyze(symbol)
                candidate.acceleration = acceleration

                if acceleration.is_late_entry:
                    candidate.block_reasons.append(BlockReason.LATE_IV_SPIKE)
                    candidates.append(candidate)
                    continue

                # Layer 6: Dealer Positioning (GATE)
                is_blocked, dealer_reasons, gex_data = await self.dealer.analyze(symbol)
                candidate.gex_data = gex_data
                candidate.dealer_score = await self.dealer.get_dealer_score(symbol)

                if is_blocked:
                    candidate.block_reasons.extend(dealer_reasons)
                    candidates.append(candidate)
                    continue

                # Candidate passed all gates
                candidate.passed_all_gates = True
                candidates.append(candidate)

            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")
                continue

        return candidates

    def _score_and_filter(
        self,
        candidates: List[PutCandidate]
    ) -> List[PutCandidate]:
        """Score candidates and filter by threshold."""
        for candidate in candidates:
            if candidate.passed_all_gates:
                candidate.composite_score = self.scorer.score_candidate(candidate)

        # Filter actionable
        actionable = [
            c for c in candidates
            if c.passed_all_gates and self.scorer.is_actionable(c)
        ]

        # Sort by score
        actionable.sort(key=lambda x: x.composite_score, reverse=True)

        return actionable

    async def execute_trade(
        self,
        candidate: PutCandidate,
        dry_run: bool = True
    ) -> Optional[TradeExecution]:
        """
        Execute a trade for a candidate.

        Args:
            candidate: PutCandidate with contract selected
            dry_run: If True, simulate without actual execution

        Returns:
            TradeExecution record or None
        """
        if not candidate.contract_symbol:
            logger.error("No contract selected for candidate")
            return None

        if not candidate.entry_price:
            logger.error("No entry price for candidate")
            return None

        logger.info(
            f"{'[DRY RUN] ' if dry_run else ''}Executing trade: "
            f"{candidate.symbol} - {candidate.contract_symbol}"
        )

        # Get account info for position sizing
        account = await self.alpaca.get_account()
        account_value = float(account.get("equity", 0))

        if account_value <= 0:
            logger.error("Could not get account value")
            return None

        # Get contract for position sizing
        contract = OptionsContract(
            symbol=candidate.contract_symbol,
            underlying=candidate.symbol,
            expiration=candidate.recommended_expiration or date.today(),
            strike=candidate.recommended_strike or 0,
            option_type="put",
            bid=candidate.entry_price * 0.98,
            ask=candidate.entry_price * 1.02,
            last=candidate.entry_price,
            volume=0,
            open_interest=0,
            implied_volatility=0,
            delta=candidate.recommended_delta or -0.30,
            gamma=0,
            theta=0,
            vega=0,
            dte=14
        )

        # Calculate position size
        quantity = self.strike_selector.calculate_position_size(
            contract, account_value
        )

        if quantity <= 0:
            logger.error("Position size calculation returned 0")
            return None

        logger.info(
            f"Order: BUY {quantity} {candidate.contract_symbol} "
            f"@ ${candidate.entry_price:.2f}"
        )

        execution = TradeExecution(
            symbol=candidate.symbol,
            contract_symbol=candidate.contract_symbol,
            timestamp=datetime.now(),
            side="buy",
            quantity=quantity,
            price=candidate.entry_price,
            order_id="",
            status="pending",
            candidate=candidate
        )

        if dry_run:
            execution.status = "simulated"
            execution.order_id = "DRY_RUN"
            logger.info(f"[DRY RUN] Order simulated: {execution}")
            return execution

        # Actual execution
        try:
            order_result = await self.alpaca.submit_order(
                symbol=candidate.contract_symbol,
                qty=quantity,
                side="buy",
                order_type="limit",
                time_in_force="day",
                limit_price=candidate.entry_price
            )

            execution.order_id = order_result.get("id", "")
            execution.status = order_result.get("status", "error")

            logger.info(f"Order submitted: {execution.order_id}")

            if self.daily_report:
                self.daily_report.trades_executed += 1

        except Exception as e:
            logger.error(f"Order execution failed: {e}")
            execution.status = "error"

        return execution

    def _is_market_open(self) -> bool:
        """Check if US stock market is currently open."""
        est = pytz.timezone('US/Eastern')
        now = datetime.now(est)
        
        # Weekend check
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        
        # Market hours: 9:30 AM - 4:00 PM ET
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        
        return market_open <= now <= market_close

    def _load_regime_from_file(self) -> Optional[MarketRegimeData]:
        """Load cached market regime from file."""
        try:
            if not self._regime_cache_file.exists():
                return None
            
            with open(self._regime_cache_file, 'r') as f:
                data = json.load(f)
            
            # Check if cache is still valid
            cache_time = datetime.fromisoformat(data.get('cache_time', '2000-01-01'))
            now = datetime.now()
            age_seconds = (now - cache_time).total_seconds()
            
            # Use 30-minute TTL for file cache
            if age_seconds > self._regime_file_cache_ttl:
                logger.debug(f"File cache expired (age: {age_seconds/60:.1f} min)")
                return None
            
            # Reconstruct MarketRegimeData from cached data
            from putsengine.models import MarketRegime
            regime_data = data.get('regime_data', {})
            
            return MarketRegimeData(
                timestamp=datetime.fromisoformat(regime_data.get('timestamp', datetime.now().isoformat())),
                regime=MarketRegime(regime_data.get('regime', 'bullish_neutral')),
                spy_below_vwap=regime_data.get('spy_below_vwap', False),
                qqq_below_vwap=regime_data.get('qqq_below_vwap', False),
                index_gex=regime_data.get('index_gex', 0),
                vix_level=regime_data.get('vix_level', 20.0),
                vix_change=regime_data.get('vix_change', 0.0),
                is_tradeable=regime_data.get('is_tradeable', False),
                block_reasons=[BlockReason(r) for r in regime_data.get('block_reasons', [])],
                is_passive_inflow_window=regime_data.get('is_passive_inflow_window', False),
                passive_inflow_reason=regime_data.get('passive_inflow_reason'),
                below_zero_gamma=regime_data.get('below_zero_gamma', False)
            )
        except Exception as e:
            logger.debug(f"Failed to load regime from file cache: {e}")
            return None

    def _save_regime_to_file(self, regime: MarketRegimeData):
        """Save market regime to file cache."""
        try:
            data = {
                'cache_time': datetime.now().isoformat(),
                'regime_data': {
                    'timestamp': regime.timestamp.isoformat(),
                    'regime': regime.regime.value,
                    'spy_below_vwap': regime.spy_below_vwap,
                    'qqq_below_vwap': regime.qqq_below_vwap,
                    'index_gex': regime.index_gex,
                    'vix_level': regime.vix_level,
                    'vix_change': regime.vix_change,
                    'is_tradeable': regime.is_tradeable,
                    'block_reasons': [r.value for r in regime.block_reasons],
                    'is_passive_inflow_window': regime.is_passive_inflow_window,
                    'passive_inflow_reason': regime.passive_inflow_reason,
                    'below_zero_gamma': regime.below_zero_gamma
                }
            }
            with open(self._regime_cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.debug("Saved regime to file cache")
        except Exception as e:
            logger.debug(f"Failed to save regime to file cache: {e}")

    async def get_cached_regime(self, force_refresh: bool = False) -> MarketRegimeData:
        """
        Get market regime with intelligent caching.
        
        Caching Strategy:
        1. Memory cache (5 min TTL) - fastest
        2. File cache (30 min TTL) - persists across dashboard reloads
        3. Skip UW API calls when market is closed (use file cache)
        4. Only make fresh API calls during market hours or when force_refresh=True
        """
        now = datetime.now()
        market_is_open = self._is_market_open()
        
        # Check memory cache first
        if (not force_refresh and 
            self._cached_regime is not None and 
            self._regime_cache_time is not None and
            (now - self._regime_cache_time).total_seconds() <= self._regime_cache_ttl):
            logger.debug("Using memory-cached market regime")
            return self._cached_regime
        
        # If market is closed, use file cache (don't waste API calls)
        if not market_is_open and not force_refresh:
            file_regime = self._load_regime_from_file()
            if file_regime:
                logger.info("Market closed - using file-cached regime (no UW API calls)")
                self._cached_regime = file_regime
                self._regime_cache_time = now
                return file_regime
        
        # Check file cache before making API calls
        if not force_refresh:
            file_regime = self._load_regime_from_file()
            if file_regime:
                logger.debug("Using file-cached market regime")
                self._cached_regime = file_regime
                self._regime_cache_time = now
                return file_regime
        
        # Make fresh API call (only during market hours or forced refresh)
        logger.info("Fetching fresh market regime from APIs...")
        self._cached_regime = await self.market_regime.analyze(force_api_call=force_refresh)
        self._regime_cache_time = now
        
        # Save to file cache for persistence
        self._save_regime_to_file(self._cached_regime)
        
        return self._cached_regime

    async def run_single_symbol(
        self,
        symbol: str,
        fast_mode: bool = True
    ) -> PutCandidate:
        """
        Run complete analysis on a single symbol.
        
        Args:
            symbol: Stock ticker to analyze
            fast_mode: If True, uses caching and skips expensive calls for low-score candidates

        Returns:
            Fully analyzed PutCandidate
        """
        candidate = PutCandidate(
            symbol=symbol,
            timestamp=datetime.now()
        )

        try:
            # Use cached market regime (saves 1 API call per ticker)
            regime = await self.get_cached_regime()
            
            # FAST MODE: Quick price check first
            quote = await self.alpaca.get_latest_quote(symbol)
            if quote and "quote" in quote:
                candidate.current_price = float(quote["quote"].get("ap", 0))
            
            if candidate.current_price == 0:
                candidate.composite_score = 0.0
                return candidate

            # Distribution analysis (core signal)
            candidate.distribution = await self.distribution.analyze(symbol)
            candidate.distribution_score = candidate.distribution.score

            # FAST MODE: Early exit if distribution score too low
            if fast_mode and candidate.distribution_score < 0.25:
                candidate.block_reasons.append(BlockReason.NO_DISTRIBUTION)
                candidate.composite_score = candidate.distribution_score * 0.3
                return candidate

            # Liquidity check
            candidate.liquidity = await self.liquidity.analyze(symbol)
            candidate.liquidity_score = candidate.liquidity.score

            # FAST MODE: Early exit if liquidity too low
            if fast_mode and candidate.liquidity_score < 0.2:
                candidate.composite_score = (candidate.distribution_score * 0.3 + 
                                            candidate.liquidity_score * 0.15)
                return candidate

            # Acceleration window (timing)
            candidate.acceleration = await self.acceleration.analyze(symbol)

            if candidate.acceleration.is_late_entry:
                candidate.block_reasons.append(BlockReason.LATE_IV_SPIKE)
                if fast_mode:
                    candidate.composite_score = 0.3
                    return candidate

            # Dealer positioning (most expensive - UW API)
            is_blocked, reasons, gex = await self.dealer.analyze(symbol)
            candidate.gex_data = gex
            candidate.dealer_score = await self.dealer.get_dealer_score(symbol)
            
            if is_blocked:
                candidate.block_reasons.extend(reasons)

            if candidate.distribution_score < 0.3:
                candidate.block_reasons.append(BlockReason.NO_DISTRIBUTION)

            candidate.passed_all_gates = len(candidate.block_reasons) == 0

            # Score the candidate
            candidate.composite_score = self.scorer.score_candidate(candidate)

            # Only select contract for high-scoring candidates (saves API calls)
            if candidate.composite_score >= 0.60:
                contract = await self.strike_selector.select_contract(candidate)
                if contract:
                    candidate.contract_symbol = contract.symbol
                    candidate.recommended_strike = contract.strike
                    candidate.recommended_expiration = contract.expiration
                    candidate.recommended_delta = contract.delta
                    candidate.entry_price = contract.mid_price

        except Exception as e:
            logger.debug(f"Error analyzing {symbol}: {e}")
            candidate.composite_score = 0.0

        return candidate

    def get_status(self) -> Dict:
        """Get current engine status."""
        return {
            "timestamp": datetime.now().isoformat(),
            "daily_report": {
                "date": str(self.daily_report.date) if self.daily_report else None,
                "scanned": self.daily_report.total_scanned if self.daily_report else 0,
                "shortlist": self.daily_report.shortlist_count if self.daily_report else 0,
                "passed_gates": self.daily_report.passed_gates if self.daily_report else 0,
                "trades": self.daily_report.trades_executed if self.daily_report else 0
            },
            "api_usage": {
                "unusual_whales_remaining": self.unusual_whales.remaining_calls
            }
        }
