"""
Liquidity Vacuum Layer - Layer 3 in the PUT detection pipeline.

This is where most PUT engines fail by omission.
It's not enough to have sellers - buyers must STEP AWAY.

Detection signals (at least 1 required):
- Bid size collapsing
- Spread widening
- Volume up but price progress down
- VWAP retest fails twice

Interpretation: Downside accelerates only when liquidity disappears.
"""

from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from loguru import logger
import numpy as np

from putsengine.config import EngineConfig, Settings
from putsengine.models import LiquidityVacuum, PriceBar
from putsengine.clients.alpaca_client import AlpacaClient
from putsengine.clients.polygon_client import PolygonClient


class LiquidityVacuumLayer:
    """
    Liquidity Vacuum Detection Layer.

    This layer identifies when buyers have stepped away from a stock,
    creating conditions for accelerated downside.

    Key insight: Selling alone doesn't crash stocks. The absence of
    buyers is what allows prices to fall rapidly.
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
        self.config = EngineConfig

    async def analyze(
        self, 
        symbol: str,
        include_sector_context: bool = False
    ) -> LiquidityVacuum:
        """
        Perform liquidity vacuum analysis for a symbol.

        Args:
            symbol: Stock ticker to analyze
            include_sector_context: If True, also analyze sector peers (ARCHITECT-4)

        Returns:
            LiquidityVacuum with detection results and score
        """
        logger.info(f"Analyzing liquidity vacuum for {symbol}...")

        vacuum = LiquidityVacuum(
            symbol=symbol,
            timestamp=datetime.now(),
            score=0.0
        )

        try:
            # Get intraday bars
            minute_bars = await self.polygon.get_minute_bars(
                symbol=symbol,
                from_date=date.today() - timedelta(days=2),
                limit=2000
            )

            # Get quotes for bid/ask analysis
            quote_data = await self.alpaca.get_latest_quote(symbol)

            # Get snapshot for current market data
            snapshot = await self.polygon.get_snapshot(symbol)

            # 1. Bid size collapsing (ARCHITECT-4: ADV-normalized)
            vacuum.bid_collapsing = await self._detect_bid_collapse(
                symbol, quote_data, snapshot, minute_bars
            )

            # 2. Spread widening (ARCHITECT-4: 15-min persistence)
            vacuum.spread_widening = await self._detect_spread_widening(
                symbol, quote_data, snapshot, minute_bars
            )

            # 3. Volume with no price progress
            if minute_bars:
                vacuum.volume_no_progress = self._detect_volume_no_progress(minute_bars)

            # 4. VWAP retest failures
            if minute_bars:
                vacuum.vwap_retest_failed = self._detect_vwap_retest_failure(minute_bars)

            # Calculate base score
            vacuum.score = self._calculate_liquidity_score(vacuum)

            # ============================================================
            # ARCHITECT-4 ENHANCEMENT: Sector Context Analysis
            # ============================================================
            # Compare against sector peers to determine if signal is
            # IDIOSYNCRATIC (only this stock) or SECTOR_WIDE (multiple peers)
            # ============================================================
            sector_context = None
            if include_sector_context and vacuum.score > 0:
                sector_context = await self.analyze_sector_context(symbol, vacuum)
                
                # Apply sector context boost/dampen
                if sector_context and sector_context.get("context_boost", 0) != 0:
                    original_score = vacuum.score
                    vacuum.score = max(0, min(1.0, vacuum.score + sector_context["context_boost"]))
                    logger.info(
                        f"{symbol}: Sector context adjustment: {original_score:.2f} → {vacuum.score:.2f} "
                        f"({sector_context['context_type']}, boost={sector_context['context_boost']:+.2f})"
                    )

            active_signals = sum([
                vacuum.bid_collapsing,
                vacuum.spread_widening,
                vacuum.volume_no_progress,
                vacuum.vwap_retest_failed
            ])

            sector_str = ""
            if sector_context:
                sector_str = f", Sector={sector_context['context_type']}"

            logger.info(
                f"{symbol} liquidity vacuum: "
                f"Score={vacuum.score:.2f}, "
                f"Active signals={active_signals}/4{sector_str}"
            )

        except Exception as e:
            logger.error(f"Error in liquidity analysis for {symbol}: {e}")

        return vacuum

    async def _detect_bid_collapse(
        self,
        symbol: str,
        quote_data: Dict,
        snapshot: Dict,
        minute_bars: Optional[List] = None
    ) -> bool:
        """
        Detect if bid size is collapsing.

        When market makers reduce bid sizes, it signals
        they expect lower prices and don't want to accumulate.
        
        ARCHITECT-4 REFINEMENT: ADV-Normalized Bid Collapse
        ====================================================
        Added dual-condition for precision:
        1. bid_size < 30% of avg_print_size_1000 (rolling baseline)
        2. bid_size < 0.5% of ADV_shares (stock-relative normalization)
        
        This reduces false positives for stocks with irregular print sizes.
        """
        try:
            # Get current bid size
            current_bid_size = 0
            if quote_data and "quote" in quote_data:
                current_bid_size = quote_data["quote"].get("bs", 0)
            elif snapshot and "ticker" in snapshot:
                current_bid_size = snapshot["ticker"].get("lastQuote", {}).get("bidsize", 0)

            if current_bid_size == 0:
                return False

            # Get historical quote data for comparison
            # We'll use trades as a proxy for typical liquidity
            trades = await self.polygon.get_trades(
                symbol=symbol,
                from_date=date.today() - timedelta(days=1),
                limit=1000
            )

            if not trades:
                return False

            # Calculate avg_print_size_1000 (rolling baseline from recent trades)
            avg_print_size_1000 = np.mean([t.get("size", 0) for t in trades])

            # CONDITION 1: Bid collapse relative to print size
            # bid_size < 30% of avg_print_size_1000
            threshold_print = avg_print_size_1000 * self.config.BID_COLLAPSE_THRESHOLD
            collapse_vs_print = current_bid_size < threshold_print
            
            # ARCHITECT-4 REFINEMENT: ADV-normalized condition
            # CONDITION 2: bid_size < 0.5% of ADV_shares
            # ADV proxy: avg minute volume × 390 (minutes in trading day)
            collapse_vs_adv = False
            if minute_bars and len(minute_bars) > 0:
                avg_minute_volume = np.mean([b.volume for b in minute_bars])
                adv_shares = avg_minute_volume * 390  # Approx ADV
                threshold_adv = adv_shares * 0.005  # 0.5% of ADV
                collapse_vs_adv = current_bid_size < threshold_adv
                
                if collapse_vs_print and collapse_vs_adv:
                    logger.info(
                        f"{symbol}: BID COLLAPSE CONFIRMED (dual-condition) - "
                        f"bid={current_bid_size:,}, print_threshold={threshold_print:,.0f}, "
                        f"adv_threshold={threshold_adv:,.0f}"
                    )
            
            # Require BOTH conditions for confirmed collapse (high precision)
            # Fall back to single condition if ADV data unavailable
            if minute_bars and len(minute_bars) > 0:
                return collapse_vs_print and collapse_vs_adv
            else:
                return collapse_vs_print

        except Exception as e:
            logger.warning(f"Error detecting bid collapse for {symbol}: {e}")
            return False

    async def _detect_spread_widening(
        self,
        symbol: str,
        quote_data: Dict,
        snapshot: Dict,
        minute_bars: Optional[List] = None
    ) -> bool:
        """
        Detect if bid-ask spread is widening.

        Widening spreads indicate market makers are less
        confident in fair value - expecting volatility.
        
        ARCHITECT-4 REFINEMENT: Persistence Window
        ==========================================
        Spread widening signal requires persistence:
        - Signal must persist ≥ 60% of last 15 minutes
        - This converts tick noise into a real regime
        - Uses minute bar high-low range as spread proxy
        
        NOTE: Baseline spread estimated from low-volume bar ranges (proxy method).
        """
        try:
            # Get current spread
            bid = 0.0
            ask = 0.0

            if quote_data and "quote" in quote_data:
                bid = float(quote_data["quote"].get("bp", 0))
                ask = float(quote_data["quote"].get("ap", 0))
            elif snapshot and "ticker" in snapshot:
                quote = snapshot["ticker"].get("lastQuote", {})
                bid = float(quote.get("P", 0))  # Polygon uses P for bid
                ask = float(quote.get("p", 0))  # and p for ask

            if bid == 0 or ask == 0:
                return False

            current_spread = ask - bid
            mid_price = (bid + ask) / 2
            spread_pct = current_spread / mid_price if mid_price > 0 else 0

            # Get historical bars to estimate normal spread
            bars = await self.polygon.get_minute_bars(
                symbol=symbol,
                from_date=date.today() - timedelta(days=5),
                limit=1000
            )

            if not bars:
                return False

            # Estimate typical spread from high-low range during low volume periods
            # NOTE: This is a PROXY method, not true quote spread history
            avg_volume = np.mean([b.volume for b in bars])
            typical_ranges = []
            for bar in bars:
                if bar.volume < avg_volume * 0.5:
                    # Low volume bar - range approximates spread
                    range_pct = (bar.high - bar.low) / bar.close if bar.close > 0 else 0
                    typical_ranges.append(range_pct)

            if not typical_ranges:
                # Default: spread > 0.5% is wide for liquid stocks
                normal_spread = 0.0025  # 0.25% baseline
            else:
                normal_spread = np.mean(typical_ranges)
            
            threshold = normal_spread * self.config.SPREAD_WIDENING_THRESHOLD
            current_wide = spread_pct > threshold
            
            # ============================================================
            # ARCHITECT-4 REFINEMENT: 15-Minute Persistence Window
            # ============================================================
            # Require spread widening to persist for ≥60% of last 15 minutes
            # This converts tick noise into a real regime
            # ============================================================
            
            if minute_bars and len(minute_bars) >= 15:
                # Get last 15 minutes of bars
                today = date.today()
                today_bars = [b for b in minute_bars if b.timestamp.date() == today]
                
                if len(today_bars) >= 15:
                    recent_15 = today_bars[-15:]
                    
                    # Count bars where range (spread proxy) exceeded threshold
                    wide_count = 0
                    for bar in recent_15:
                        bar_range_pct = (bar.high - bar.low) / bar.close if bar.close > 0 else 0
                        if bar_range_pct > threshold:
                            wide_count += 1
                    
                    persistence_pct = wide_count / 15
                    
                    # Require 60%+ persistence for confirmed spread widening
                    if current_wide and persistence_pct >= 0.60:
                        logger.info(
                            f"{symbol}: SPREAD WIDENING CONFIRMED (persistence={persistence_pct:.0%}) - "
                            f"current_spread={spread_pct:.4f}, threshold={threshold:.4f}"
                        )
                        return True
                    elif current_wide:
                        logger.debug(
                            f"{symbol}: Spread wide but not persistent ({persistence_pct:.0%} < 60%)"
                        )
                        return False
            
            # Fallback: just use current spread if persistence check unavailable
            return current_wide

        except Exception as e:
            logger.warning(f"Error detecting spread widening for {symbol}: {e}")
            return False

    def _detect_volume_no_progress(self, bars: List[PriceBar]) -> bool:
        """
        Detect high volume with no price progress.

        When volume spikes but price doesn't move, it means
        selling is being absorbed. But if this continues,
        buyers eventually exhaust - creating vacuum.
        """
        if len(bars) < 60:
            return False

        # Get today's bars
        today = date.today()
        today_bars = [b for b in bars if b.timestamp.date() == today]

        if len(today_bars) < 30:
            return False

        # Analyze last 30 minutes
        recent = today_bars[-30:]

        # Calculate volume vs price change
        total_volume = sum(b.volume for b in recent)
        avg_volume = np.mean([b.volume for b in today_bars[:-30]]) if len(today_bars) > 30 else total_volume / 30

        # Price change over period
        price_start = recent[0].open
        price_end = recent[-1].close
        price_change = abs(price_end - price_start) / price_start if price_start > 0 else 0

        # Volume is elevated (>1.5x normal)
        volume_elevated = total_volume > avg_volume * 30 * 1.5

        # Price change is minimal (< 0.5%)
        price_minimal = price_change < 0.005

        return volume_elevated and price_minimal

    def _detect_vwap_retest_failure(self, bars: List[PriceBar]) -> bool:
        """
        Detect multiple failed VWAP reclaim attempts.

        When price fails to reclaim VWAP twice, it confirms
        institutional selling pressure and buyer exhaustion.
        """
        if len(bars) < 100:
            return False

        # Get today's bars
        today = date.today()
        today_bars = [b for b in bars if b.timestamp.date() == today]

        if len(today_bars) < 50:
            return False

        # Calculate VWAP
        vwap = self._calculate_vwap(today_bars)
        current_price = today_bars[-1].close

        # Only relevant if currently below VWAP
        if current_price >= vwap:
            return False

        # Count failed reclaim attempts
        failed_reclaims = 0
        in_retest = False

        for bar in today_bars:
            if not in_retest and bar.low < vwap:
                # Price dipped below VWAP
                in_retest = True
            elif in_retest and bar.high >= vwap:
                # Price attempted to reclaim
                if bar.close < vwap:
                    # But closed below = failed reclaim
                    failed_reclaims += 1
                    in_retest = False

        return failed_reclaims >= 2

    def _calculate_vwap(self, bars: List[PriceBar]) -> float:
        """Calculate VWAP from price bars."""
        if not bars:
            return 0.0

        total_volume = 0
        total_vwap = 0.0

        for bar in bars:
            typical_price = (bar.high + bar.low + bar.close) / 3
            total_vwap += typical_price * bar.volume
            total_volume += bar.volume

        return total_vwap / total_volume if total_volume > 0 else bars[-1].close

    def _calculate_liquidity_score(self, vacuum: LiquidityVacuum) -> float:
        """
        Calculate liquidity vacuum score.

        Each signal contributes 25% to the score.
        At least one signal is required for a non-zero score.
        """
        signals = [
            vacuum.bid_collapsing,
            vacuum.spread_widening,
            vacuum.volume_no_progress,
            vacuum.vwap_retest_failed
        ]

        signal_count = sum(1 for s in signals if s)

        if signal_count == 0:
            return 0.0

        return min(signal_count * 0.25, 1.0)
    
    # =========================================================================
    # ARCHITECT-4 ENHANCEMENT: Sector-Relative Liquidity Analysis
    # =========================================================================
    
    # Market cap tier weights for liquidity-weighted aggregation
    # ARCHITECT-4 REFINEMENT: Weight peers by liquidity significance
    MARKET_CAP_WEIGHTS = {
        "mega_cap_tech": 1.0,    # Mega caps = highest weight
        "cloud_saas": 0.8,       # Large/mid growth
        "high_vol_tech": 0.6,    # High vol = more liquid
        "space_aerospace": 0.7,  # Mixed cap
        "nuclear_energy": 0.5,   # Mid cap
        "materials_mining": 0.5,
        "silver_miners": 0.3,    # Small cap
        "gaming": 0.5,
        "auto_retail": 0.5,
        "biotech_pharma": 0.6,
        "financial": 0.8,
        "healthcare": 0.7,
        "retail": 0.6,
        "telecom": 0.8,          # T, VZ, TMUS = highly liquid
        "travel": 0.5,
        "china_adr": 0.4,
    }
    
    # Individual mega-cap stock weights (override sector weights)
    MEGA_CAP_STOCKS = {
        "AAPL": 1.0, "MSFT": 1.0, "GOOGL": 1.0, "AMZN": 1.0, "META": 1.0,
        "NVDA": 1.0, "TSLA": 1.0, "AMD": 0.9, "INTC": 0.8, "AVGO": 0.9,
        "T": 0.9, "VZ": 0.9, "TMUS": 0.85, "CMCSA": 0.8,
        "BA": 0.8, "LMT": 0.7, "GE": 0.8,
        "JPM": 1.0, "BAC": 0.9, "GS": 0.9,
    }
    
    def _get_sector_for_symbol(self, symbol: str) -> Optional[str]:
        """Get the sector name for a given symbol."""
        for sector_name, tickers in self.config.UNIVERSE_SECTORS.items():
            if symbol in tickers:
                return sector_name
        return None
    
    def _get_sector_peers(self, symbol: str, max_peers: int = 5) -> List[str]:
        """Get peer symbols from the same sector (excluding the target)."""
        sector = self._get_sector_for_symbol(symbol)
        if not sector:
            return []
        
        peers = [t for t in self.config.UNIVERSE_SECTORS.get(sector, []) 
                 if t != symbol]
        return peers[:max_peers]
    
    def _get_peer_weight(self, symbol: str) -> float:
        """
        Get liquidity weight for a peer symbol.
        
        ARCHITECT-4 REFINEMENT 1: Liquidity-weighted peer aggregation
        Uses individual stock weights for mega-caps, falls back to sector weight.
        """
        # Check individual mega-cap weights first
        if symbol in self.MEGA_CAP_STOCKS:
            return self.MEGA_CAP_STOCKS[symbol]
        
        # Fall back to sector weight
        sector = self._get_sector_for_symbol(symbol)
        if sector and sector in self.MARKET_CAP_WEIGHTS:
            return self.MARKET_CAP_WEIGHTS[sector]
        
        # Default weight for unknown
        return 0.5
    
    async def analyze_sector_context(
        self,
        symbol: str,
        vacuum: LiquidityVacuum
    ) -> Dict[str, Any]:
        """
        Analyze liquidity vacuum in sector context.
        
        ARCHITECT-4 RECOMMENDED ENHANCEMENT (WITH REFINEMENTS)
        ======================================================
        Compares the target symbol's liquidity signals against sector peers
        to determine if the signal is:
        - IDIOSYNCRATIC: Only this stock shows liquidity withdrawal
        - SECTOR_WIDE: Multiple peers show similar patterns
        
        REFINEMENT 1: Liquidity-weighted peer aggregation
        - Weight peers by ADV/market cap tier (mega=1.0, mid=0.5, small=0.25)
        - Makes "50% of peers affected" economically meaningful
        
        REFINEMENT 2: Same-signal confirmation
        - Only count peers showing at least one of the SAME signals as target
        - Prevents mixing spread-only stress with bid-collapse stress
        
        Returns:
            Dict with sector context analysis
        """
        result = {
            "sector_name": None,
            "peer_count": 0,
            "peers_with_bid_collapse": 0,
            "peers_with_spread_widening": 0,
            "peers_with_vwap_loss": 0,
            "sector_liquidity_ratio": 0.0,
            "weighted_sector_ratio": 0.0,  # NEW: Liquidity-weighted ratio
            "same_signal_ratio": 0.0,       # NEW: Same-signal confirmation ratio
            "is_sector_wide": False,
            "context_type": "UNKNOWN",
            "context_boost": 0.0,
            "peer_details": []
        }
        
        try:
            # Get sector and peers
            sector = self._get_sector_for_symbol(symbol)
            if not sector:
                logger.debug(f"{symbol}: No sector found, skipping sector context")
                return result
            
            result["sector_name"] = sector
            peers = self._get_sector_peers(symbol, max_peers=5)
            
            if not peers:
                logger.debug(f"{symbol}: No peers found in {sector}")
                return result
            
            result["peer_count"] = len(peers)
            
            # Get target's signals for same-signal comparison
            target_has_bid_collapse = vacuum.bid_collapsing
            target_has_spread_widening = vacuum.spread_widening
            
            # Quick liquidity check on each peer
            total_weight = 0.0
            weighted_issues = 0.0
            same_signal_count = 0
            
            for peer in peers:
                try:
                    peer_weight = self._get_peer_weight(peer)
                    total_weight += peer_weight
                    
                    peer_analysis = {
                        "symbol": peer,
                        "weight": peer_weight,
                        "bid_collapse": False,
                        "spread_widening": False,
                        "vwap_loss": False,
                        "same_signal_match": False  # NEW: Track same-signal match
                    }
                    
                    # Get peer quote and snapshot
                    peer_quote = await self.alpaca.get_latest_quote(peer)
                    peer_snapshot = await self.polygon.get_snapshot(peer)
                    
                    # Quick bid size check
                    if peer_quote and "quote" in peer_quote:
                        peer_bid_size = peer_quote["quote"].get("bs", 0)
                        if peer_bid_size > 0 and peer_bid_size < 100:
                            peer_analysis["bid_collapse"] = True
                            result["peers_with_bid_collapse"] += 1
                        
                        # Quick spread check
                        bid = float(peer_quote["quote"].get("bp", 0))
                        ask = float(peer_quote["quote"].get("ap", 0))
                        if bid > 0 and ask > 0:
                            spread_pct = (ask - bid) / ((bid + ask) / 2)
                            if spread_pct > 0.005:
                                peer_analysis["spread_widening"] = True
                                result["peers_with_spread_widening"] += 1
                    
                    # Quick VWAP check from snapshot
                    if peer_snapshot and "ticker" in peer_snapshot:
                        ticker_data = peer_snapshot["ticker"]
                        current_price = ticker_data.get("lastTrade", {}).get("p", 0)
                        vwap = ticker_data.get("day", {}).get("vw", 0)
                        if current_price > 0 and vwap > 0 and current_price < vwap:
                            peer_analysis["vwap_loss"] = True
                            result["peers_with_vwap_loss"] += 1
                    
                    # ============================================================
                    # ARCHITECT-4 REFINEMENT 2: Same-Signal Confirmation
                    # ============================================================
                    # Only count peer if it shows at least one of the SAME signals
                    # as the target. This prevents mixing heterogeneous signals.
                    # ============================================================
                    same_signal = False
                    if target_has_bid_collapse and peer_analysis["bid_collapse"]:
                        same_signal = True
                    if target_has_spread_widening and peer_analysis["spread_widening"]:
                        same_signal = True
                    
                    peer_analysis["same_signal_match"] = same_signal
                    
                    # Check if peer has any liquidity issues
                    has_any_issue = (
                        peer_analysis["bid_collapse"] or 
                        peer_analysis["spread_widening"] or 
                        peer_analysis["vwap_loss"]
                    )
                    
                    if has_any_issue:
                        # ============================================================
                        # ARCHITECT-4 REFINEMENT 1: Liquidity-Weighted Aggregation
                        # ============================================================
                        # Weight peers by liquidity significance
                        # VZ/TMUS with stress >> GSAT/ONDS with stress
                        # ============================================================
                        weighted_issues += peer_weight
                    
                    if same_signal:
                        same_signal_count += 1
                    
                    result["peer_details"].append(peer_analysis)
                    
                except Exception as e:
                    logger.debug(f"Error checking peer {peer}: {e}")
                    continue
            
            # Calculate unweighted sector liquidity ratio (original)
            peers_with_issues = sum(
                1 for p in result["peer_details"]
                if p["bid_collapse"] or p["spread_widening"] or p["vwap_loss"]
            )
            
            if result["peer_count"] > 0:
                result["sector_liquidity_ratio"] = peers_with_issues / result["peer_count"]
            
            # Calculate WEIGHTED sector ratio (REFINEMENT 1)
            if total_weight > 0:
                result["weighted_sector_ratio"] = weighted_issues / total_weight
            
            # Calculate same-signal ratio (REFINEMENT 2)
            if result["peer_count"] > 0:
                result["same_signal_ratio"] = same_signal_count / result["peer_count"]
            
            # ============================================================
            # FINAL CONTEXT DETERMINATION
            # ============================================================
            # Use WEIGHTED ratio as primary (economically meaningful)
            # Require SAME-SIGNAL confirmation for SECTOR_WIDE (directional agreement)
            # ============================================================
            
            # Primary metric: weighted sector ratio
            weighted_ratio = result["weighted_sector_ratio"]
            same_signal_ratio = result["same_signal_ratio"]
            
            # For SECTOR_WIDE, require both:
            # 1. Weighted ratio >= 50%
            # 2. At least one peer with same-signal match
            if weighted_ratio >= 0.50 and same_signal_count >= 1:
                result["is_sector_wide"] = True
                result["context_type"] = "SECTOR_WIDE"
                result["context_boost"] = 0.10
                logger.info(
                    f"{symbol}: SECTOR-WIDE LIQUIDITY WITHDRAWAL - "
                    f"weighted_ratio={weighted_ratio:.0%}, same_signal={same_signal_count}/{result['peer_count']} peers"
                )
            elif weighted_ratio >= 0.25:
                result["context_type"] = "MIXED"
                result["context_boost"] = 0.05
                logger.info(
                    f"{symbol}: Mixed sector liquidity - "
                    f"weighted_ratio={weighted_ratio:.0%}, same_signal={same_signal_count} peers"
                )
            else:
                result["context_type"] = "IDIOSYNCRATIC"
                result["context_boost"] = -0.03
                logger.info(
                    f"{symbol}: IDIOSYNCRATIC liquidity signal - "
                    f"weighted_ratio={weighted_ratio:.0%}, same_signal={same_signal_count} peers"
                )
            
        except Exception as e:
            logger.warning(f"Error in sector context analysis for {symbol}: {e}")
        
        return result

    async def has_liquidity_vacuum(
        self,
        symbol: str,
        min_score: float = 0.25
    ) -> bool:
        """
        Quick check if symbol shows liquidity vacuum.

        Args:
            symbol: Stock ticker
            min_score: Minimum score threshold (default 0.25 = 1 signal)

        Returns:
            True if liquidity vacuum detected
        """
        vacuum = await self.analyze(symbol)
        return vacuum.score >= min_score

    async def screen_for_vacuum(
        self,
        symbols: List[str],
        min_score: float = 0.25
    ) -> List[LiquidityVacuum]:
        """
        Screen multiple symbols for liquidity vacuum.

        Args:
            symbols: List of symbols to screen
            min_score: Minimum score threshold

        Returns:
            List of symbols showing liquidity vacuum
        """
        results = []

        for symbol in symbols:
            try:
                vacuum = await self.analyze(symbol)
                if vacuum.score >= min_score:
                    results.append(vacuum)
            except Exception as e:
                logger.error(f"Error screening {symbol}: {e}")
                continue

        # Sort by score descending
        results.sort(key=lambda x: x.score, reverse=True)

        return results
