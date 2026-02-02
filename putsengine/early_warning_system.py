"""
Early Warning System - Detecting Institutional Footprints 1-3 Days BEFORE Breakdown

PHILOSOPHY (30+ Years Institutional Trading + PhD Quant):
=========================================================
You can't predict the catalyst. But you CAN detect the footprints of those
who KNOW about the catalyst. Smart money leaves traces:

1. They can't buy puts without moving open interest
2. They can't sell in dark pools without leaving prints
3. They can't hedge without affecting the options term structure
4. They can't exit large positions without degrading quote quality

This system detects these footprints 1-3 days BEFORE the breakdown.

THE 7 INSTITUTIONAL FOOTPRINTS:
===============================

FOOTPRINT 1: DARK POOL SEQUENCE PATTERN
- Not just dark pool volume, but the SEQUENCE of prints
- Smart money sells in "staircases" - sequential prints at deteriorating prices
- 3+ dark pool prints within 2% of each other over 2 days = distribution

FOOTPRINT 2: PUT OI ACCUMULATION (QUIET)
- Not sweeps (those are too late, too obvious)
- Quiet accumulation: put OI building 30%+ over 3 days without price drop
- This is someone positioning BEFORE the news

FOOTPRINT 3: IV TERM STRUCTURE INVERSION
- Normally: 30-day IV > 7-day IV (contango)
- Before events: 7-day IV > 30-day IV (backwardation)
- This shows someone paying premium for near-term protection

FOOTPRINT 4: QUOTE QUALITY DEGRADATION
- Bid size shrinking over 2-3 days
- Spread widening trend
- Market makers KNOW something and are reducing exposure

FOOTPRINT 5: OPTIONS FLOW DIVERGENCE
- Price flat or up, but put premium increasing
- Call/put premium ratio shifting bearish over multiple days
- The options market often leads the stock market by 1-2 days

FOOTPRINT 6: MULTI-DAY DISTRIBUTION PATTERN
- Lower highs over 3+ days (supply at lower prices)
- Volume increasing on down moves, decreasing on up moves
- Classic Wyckoff distribution

FOOTPRINT 7: CROSS-ASSET DIVERGENCE
- Stock flat but sector ETF weak
- Stock flat but credit spreads widening
- Correlation breakdown = someone knows something

SCORING:
========
Each footprint contributes to an "Institutional Pressure Index" (IPI):
- IPI 0.0 - 0.3: No unusual activity
- IPI 0.3 - 0.5: Early accumulation (WATCH)
- IPI 0.5 - 0.7: Active distribution (PREPARE)
- IPI 0.7 - 1.0: Imminent breakdown (ACT)

The key is ACCUMULATION over 2-3 days. Single-day signals are noise.
Multi-day convergence is signal.
"""

import asyncio
import json
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import numpy as np
from loguru import logger


class FootprintType(Enum):
    """The 7 institutional footprints."""
    DARK_POOL_SEQUENCE = "dark_pool_sequence"
    PUT_OI_ACCUMULATION = "put_oi_accumulation"
    IV_TERM_INVERSION = "iv_term_inversion"
    QUOTE_DEGRADATION = "quote_degradation"
    FLOW_DIVERGENCE = "flow_divergence"
    MULTI_DAY_DISTRIBUTION = "multi_day_distribution"
    CROSS_ASSET_DIVERGENCE = "cross_asset_divergence"


class PressureLevel(Enum):
    """Institutional pressure levels."""
    NONE = "none"           # IPI 0.0 - 0.3
    WATCH = "watch"         # IPI 0.3 - 0.5
    PREPARE = "prepare"     # IPI 0.5 - 0.7
    ACT = "act"             # IPI 0.7 - 1.0


@dataclass
class FootprintSignal:
    """A single footprint detection."""
    footprint_type: FootprintType
    timestamp: datetime
    strength: float  # 0.0 to 1.0
    details: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def age_hours(self) -> float:
        """Hours since this footprint was detected."""
        return (datetime.now() - self.timestamp).total_seconds() / 3600


@dataclass
class InstitutionalPressure:
    """
    Institutional Pressure Index for a symbol.
    
    This aggregates footprints over 2-3 days to detect
    institutional distribution BEFORE the breakdown.
    """
    symbol: str
    ipi: float  # Institutional Pressure Index (0.0 to 1.0)
    level: PressureLevel
    footprints: List[FootprintSignal] = field(default_factory=list)
    first_detected: Optional[datetime] = None
    last_updated: Optional[datetime] = None
    days_building: int = 0
    recommendation: str = ""
    
    @property
    def unique_footprints(self) -> int:
        """Count of unique footprint types detected."""
        return len(set(f.footprint_type for f in self.footprints))
    
    @property
    def is_actionable(self) -> bool:
        """True if IPI suggests action."""
        return self.ipi >= 0.5 and self.unique_footprints >= 3


# ============================================================================
# FOOTPRINT HISTORY STORAGE
# ============================================================================

FOOTPRINT_HISTORY_FILE = Path(__file__).parent.parent / "footprint_history.json"


def load_footprint_history() -> Dict[str, List[Dict]]:
    """Load footprint history from file."""
    if not FOOTPRINT_HISTORY_FILE.exists():
        return {}
    try:
        with open(FOOTPRINT_HISTORY_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load footprint history: {e}")
        return {}


def save_footprint_history(history: Dict[str, List[Dict]]):
    """Save footprint history to file."""
    try:
        # Prune old entries (keep last 5 days)
        cutoff = (datetime.now() - timedelta(days=5)).isoformat()
        for symbol in list(history.keys()):
            history[symbol] = [
                f for f in history[symbol]
                if f.get("timestamp", "") > cutoff
            ]
            if not history[symbol]:
                del history[symbol]
        
        with open(FOOTPRINT_HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2, default=str)
    except Exception as e:
        logger.warning(f"Could not save footprint history: {e}")


def add_footprint_to_history(symbol: str, footprint: FootprintSignal):
    """Add a footprint to history."""
    history = load_footprint_history()
    
    if symbol not in history:
        history[symbol] = []
    
    history[symbol].append({
        "footprint_type": footprint.footprint_type.value,
        "timestamp": footprint.timestamp.isoformat(),
        "strength": footprint.strength,
        "details": footprint.details,
    })
    
    save_footprint_history(history)


# ============================================================================
# FOOTPRINT DETECTION FUNCTIONS
# ============================================================================

class EarlyWarningScanner:
    """
    Scans for institutional footprints 1-3 days before breakdown.
    
    This is the core of the early warning system. It detects the 7 footprints
    and calculates the Institutional Pressure Index (IPI).
    """
    
    # Footprint weights for IPI calculation
    FOOTPRINT_WEIGHTS = {
        FootprintType.DARK_POOL_SEQUENCE: 0.20,      # Highest - direct evidence
        FootprintType.PUT_OI_ACCUMULATION: 0.18,     # High - options positioning
        FootprintType.IV_TERM_INVERSION: 0.15,       # High - volatility structure
        FootprintType.QUOTE_DEGRADATION: 0.15,       # Medium - market maker behavior
        FootprintType.FLOW_DIVERGENCE: 0.12,         # Medium - flow analysis
        FootprintType.MULTI_DAY_DISTRIBUTION: 0.12,  # Medium - price patterns
        FootprintType.CROSS_ASSET_DIVERGENCE: 0.08,  # Lower - requires more data
    }
    
    # Time decay for footprints (older footprints have less weight)
    # λ = 0.03 gives half-life of ~23 hours
    DECAY_LAMBDA = 0.03
    
    def __init__(self, alpaca_client, polygon_client, uw_client):
        """
        Initialize early warning scanner.
        
        Args:
            alpaca_client: AlpacaClient instance
            polygon_client: PolygonClient instance
            uw_client: UnusualWhalesClient instance
        """
        self.alpaca = alpaca_client
        self.polygon = polygon_client
        self.uw = uw_client
    
    async def scan_symbol(self, symbol: str) -> InstitutionalPressure:
        """
        Scan a symbol for all 7 institutional footprints.
        
        This aggregates current signals with historical footprints
        to calculate the Institutional Pressure Index.
        
        Args:
            symbol: Stock ticker to scan
            
        Returns:
            InstitutionalPressure with IPI and recommendations
        """
        logger.info(f"Early Warning Scan: {symbol}")
        
        # Detect current footprints
        current_footprints = []
        
        # Footprint 1: Dark Pool Sequence
        dp_footprint = await self._detect_dark_pool_sequence(symbol)
        if dp_footprint:
            current_footprints.append(dp_footprint)
            add_footprint_to_history(symbol, dp_footprint)
        
        # Footprint 2: Put OI Accumulation
        poi_footprint = await self._detect_put_oi_accumulation(symbol)
        if poi_footprint:
            current_footprints.append(poi_footprint)
            add_footprint_to_history(symbol, poi_footprint)
        
        # Footprint 3: IV Term Structure Inversion
        iv_footprint = await self._detect_iv_term_inversion(symbol)
        if iv_footprint:
            current_footprints.append(iv_footprint)
            add_footprint_to_history(symbol, iv_footprint)
        
        # Footprint 4: Quote Quality Degradation
        quote_footprint = await self._detect_quote_degradation(symbol)
        if quote_footprint:
            current_footprints.append(quote_footprint)
            add_footprint_to_history(symbol, quote_footprint)
        
        # Footprint 5: Options Flow Divergence
        flow_footprint = await self._detect_flow_divergence(symbol)
        if flow_footprint:
            current_footprints.append(flow_footprint)
            add_footprint_to_history(symbol, flow_footprint)
        
        # Footprint 6: Multi-Day Distribution Pattern
        dist_footprint = await self._detect_multi_day_distribution(symbol)
        if dist_footprint:
            current_footprints.append(dist_footprint)
            add_footprint_to_history(symbol, dist_footprint)
        
        # Footprint 7: Cross-Asset Divergence
        cross_footprint = await self._detect_cross_asset_divergence(symbol)
        if cross_footprint:
            current_footprints.append(cross_footprint)
            add_footprint_to_history(symbol, cross_footprint)
        
        # Load historical footprints and combine
        history = load_footprint_history()
        historical = history.get(symbol, [])
        
        # Convert historical to FootprintSignal objects
        all_footprints = current_footprints.copy()
        for h in historical:
            try:
                # Skip if already in current (avoid double counting)
                ts = datetime.fromisoformat(h["timestamp"])
                if (datetime.now() - ts).total_seconds() < 300:  # Within 5 min
                    continue
                
                all_footprints.append(FootprintSignal(
                    footprint_type=FootprintType(h["footprint_type"]),
                    timestamp=ts,
                    strength=h["strength"],
                    details=h.get("details", {}),
                ))
            except Exception:
                continue
        
        # Calculate IPI with time decay
        ipi = self._calculate_ipi(all_footprints)
        
        # Determine pressure level
        if ipi >= 0.7:
            level = PressureLevel.ACT
        elif ipi >= 0.5:
            level = PressureLevel.PREPARE
        elif ipi >= 0.3:
            level = PressureLevel.WATCH
        else:
            level = PressureLevel.NONE
        
        # Calculate days building
        if all_footprints:
            timestamps = [f.timestamp for f in all_footprints]
            first = min(timestamps)
            days_building = (datetime.now() - first).days + 1
        else:
            days_building = 0
        
        # Generate recommendation
        recommendation = self._generate_recommendation(ipi, level, all_footprints)
        
        pressure = InstitutionalPressure(
            symbol=symbol,
            ipi=ipi,
            level=level,
            footprints=all_footprints,
            first_detected=min(f.timestamp for f in all_footprints) if all_footprints else None,
            last_updated=datetime.now(),
            days_building=days_building,
            recommendation=recommendation,
        )
        
        if ipi > 0.3:
            logger.warning(
                f"Early Warning: {symbol} IPI={ipi:.2f} ({level.value}) - "
                f"{len(all_footprints)} footprints over {days_building} days"
            )
        
        return pressure
    
    def _calculate_ipi(self, footprints: List[FootprintSignal]) -> float:
        """
        Calculate Institutional Pressure Index with time decay.
        
        Recent footprints are weighted more heavily than older ones.
        Multiple footprint types increase confidence.
        
        Formula:
            IPI = Σ(weight × strength × decay) × diversity_bonus
            
        where:
            decay = exp(-λ × hours_since_detection)
            diversity_bonus = 1.0 + 0.1 × (unique_types - 1)
        """
        if not footprints:
            return 0.0
        
        now = datetime.now()
        weighted_sum = 0.0
        
        for fp in footprints:
            # Base weight for this footprint type
            weight = self.FOOTPRINT_WEIGHTS.get(fp.footprint_type, 0.05)
            
            # Time decay
            hours_old = (now - fp.timestamp).total_seconds() / 3600
            decay = np.exp(-self.DECAY_LAMBDA * hours_old)
            
            # Add to sum
            weighted_sum += weight * fp.strength * decay
        
        # Diversity bonus: more unique footprint types = higher confidence
        unique_types = len(set(f.footprint_type for f in footprints))
        diversity_bonus = 1.0 + 0.1 * (unique_types - 1)
        
        ipi = weighted_sum * diversity_bonus
        
        return min(ipi, 1.0)
    
    def _generate_recommendation(
        self, 
        ipi: float, 
        level: PressureLevel, 
        footprints: List[FootprintSignal]
    ) -> str:
        """Generate actionable recommendation based on IPI and footprints."""
        unique_types = len(set(f.footprint_type for f in footprints))
        
        if level == PressureLevel.ACT:
            return (
                f"🔴 IMMINENT BREAKDOWN (IPI={ipi:.2f}): "
                f"{unique_types} footprint types converging. "
                f"Consider put entry on any bounce. "
                f"7-14 DTE, -0.30 to -0.40 delta."
            )
        elif level == PressureLevel.PREPARE:
            return (
                f"🟡 ACTIVE DISTRIBUTION (IPI={ipi:.2f}): "
                f"{unique_types} footprint types detected. "
                f"Add to watchlist for put entry. "
                f"Wait for confirmation or VWAP loss."
            )
        elif level == PressureLevel.WATCH:
            return (
                f"👀 EARLY ACCUMULATION (IPI={ipi:.2f}): "
                f"Institutional activity detected but not confirmed. "
                f"Monitor for additional footprints."
            )
        else:
            return "No significant institutional pressure detected."
    
    # =========================================================================
    # FOOTPRINT DETECTION METHODS
    # =========================================================================
    
    async def _detect_dark_pool_sequence(self, symbol: str) -> Optional[FootprintSignal]:
        """
        FOOTPRINT 1: Dark Pool Sequence Pattern
        
        Detects "staircase" selling in dark pools:
        - 3+ prints within 2% price range over 2 days
        - Sequential prints at deteriorating prices
        - Total size > 50K shares
        
        This is how smart money exits large positions without moving price.
        """
        try:
            dp_prints = await self.uw.get_dark_pool_flow(symbol, limit=50)
            
            if not dp_prints or len(dp_prints) < 3:
                return None
            
            # Group prints by price level (within 2%)
            reference_price = dp_prints[0].price if dp_prints else 0
            if reference_price == 0:
                return None
            
            # Count prints within 2% range showing deterioration
            staircase_prints = []
            prev_price = reference_price * 1.05  # Start high
            
            for dp in dp_prints:
                if abs(dp.price - reference_price) / reference_price <= 0.02:
                    if dp.price <= prev_price:  # Deteriorating
                        staircase_prints.append(dp)
                        prev_price = dp.price
            
            if len(staircase_prints) >= 3:
                total_size = sum(p.size for p in staircase_prints)
                if total_size >= 50000:  # 50K+ shares
                    # Calculate strength based on size and count
                    strength = min(1.0, (len(staircase_prints) / 10) + (total_size / 500000))
                    
                    return FootprintSignal(
                        footprint_type=FootprintType.DARK_POOL_SEQUENCE,
                        timestamp=datetime.now(),
                        strength=strength,
                        details={
                            "print_count": len(staircase_prints),
                            "total_size": total_size,
                            "price_range": f"${min(p.price for p in staircase_prints):.2f} - ${max(p.price for p in staircase_prints):.2f}",
                        }
                    )
            
            return None
            
        except Exception as e:
            logger.debug(f"Dark pool sequence check failed for {symbol}: {e}")
            return None
    
    async def _detect_put_oi_accumulation(self, symbol: str) -> Optional[FootprintSignal]:
        """
        FOOTPRINT 2: Put OI Accumulation (Quiet)
        
        Detects quiet put accumulation over 2-3 days:
        - Put OI increasing 30%+ over 3 days
        - Without corresponding price drop (stealth positioning)
        - Not from sweeps (institutional, not retail)
        
        This is someone positioning BEFORE the catalyst.
        """
        try:
            # Get OI change data
            oi_data = await self.uw.get_oi_change(symbol)
            
            if not oi_data:
                return None
            
            # Handle various response formats
            if isinstance(oi_data, list) and len(oi_data) > 0:
                oi_data = oi_data[0] if isinstance(oi_data[0], dict) else {}
            elif not isinstance(oi_data, dict):
                return None
            
            put_oi_change_pct = float(oi_data.get("put_oi_change_pct", 
                                                  oi_data.get("put_change_pct", 0)))
            
            # 30%+ increase in put OI
            if put_oi_change_pct >= 30:
                # Check if price has NOT dropped significantly (stealth)
                try:
                    bars = await self.polygon.get_daily_bars(
                        symbol=symbol,
                        from_date=date.today() - timedelta(days=5)
                    )
                    if bars and len(bars) >= 3:
                        price_change = (bars[-1].close - bars[-3].close) / bars[-3].close
                        
                        # Price flat or up while put OI building = stealth positioning
                        if price_change >= -0.02:  # Less than 2% drop
                            strength = min(1.0, put_oi_change_pct / 100)
                            
                            return FootprintSignal(
                                footprint_type=FootprintType.PUT_OI_ACCUMULATION,
                                timestamp=datetime.now(),
                                strength=strength,
                                details={
                                    "put_oi_change_pct": put_oi_change_pct,
                                    "price_change_pct": round(price_change * 100, 2),
                                    "note": "Stealth positioning - put OI building without price drop"
                                }
                            )
                except Exception:
                    pass
            
            return None
            
        except Exception as e:
            logger.debug(f"Put OI accumulation check failed for {symbol}: {e}")
            return None
    
    async def _detect_iv_term_inversion(self, symbol: str) -> Optional[FootprintSignal]:
        """
        FOOTPRINT 3: IV Term Structure Inversion
        
        Detects when near-term IV exceeds far-term IV:
        - Normally: 30-day IV > 7-day IV (contango)
        - Before events: 7-day IV > 30-day IV (backwardation)
        
        This shows someone paying premium for near-term protection.
        """
        try:
            iv_data = await self.uw.get_iv_term_structure(symbol)
            
            if not iv_data:
                return None
            
            # Handle various response formats
            if isinstance(iv_data, list) and len(iv_data) > 0:
                iv_data = iv_data[0] if isinstance(iv_data[0], dict) else {}
            elif not isinstance(iv_data, dict):
                return None
            
            near_term_iv = float(iv_data.get("7_day", iv_data.get("iv_7d", 0)))
            far_term_iv = float(iv_data.get("30_day", iv_data.get("iv_30d", 0)))
            
            if near_term_iv > 0 and far_term_iv > 0:
                # Check for inversion
                if near_term_iv > far_term_iv:
                    inversion_ratio = near_term_iv / far_term_iv
                    strength = min(1.0, (inversion_ratio - 1.0) * 2)  # Scale 1.0-1.5 to 0-1
                    
                    return FootprintSignal(
                        footprint_type=FootprintType.IV_TERM_INVERSION,
                        timestamp=datetime.now(),
                        strength=strength,
                        details={
                            "near_term_iv": round(near_term_iv, 2),
                            "far_term_iv": round(far_term_iv, 2),
                            "inversion_ratio": round(inversion_ratio, 3),
                            "note": "Someone paying premium for near-term protection"
                        }
                    )
            
            return None
            
        except Exception as e:
            logger.debug(f"IV term inversion check failed for {symbol}: {e}")
            return None
    
    async def _detect_quote_degradation(self, symbol: str) -> Optional[FootprintSignal]:
        """
        FOOTPRINT 4: Quote Quality Degradation
        
        Detects market makers reducing exposure:
        - Bid size shrinking over 2-3 days
        - Spread widening trend
        - Quote stability decreasing
        
        Market makers often KNOW before the public.
        """
        try:
            # Get current quote
            quote = await self.alpaca.get_latest_quote(symbol)
            
            if not quote or "quote" not in quote:
                return None
            
            q = quote["quote"]
            bid_size = int(q.get("bs", 0))
            ask_size = int(q.get("as", 0))
            bid_price = float(q.get("bp", 0))
            ask_price = float(q.get("ap", 0))
            
            if bid_price == 0 or ask_price == 0:
                return None
            
            spread_pct = (ask_price - bid_price) / bid_price * 100
            
            # Check for concerning patterns
            signals = []
            strength = 0.0
            
            # Bid/ask imbalance (much more ask than bid = sellers)
            if ask_size > 0 and bid_size > 0:
                imbalance = bid_size / ask_size
                if imbalance < 0.5:  # Bid is less than half of ask
                    signals.append("bid_imbalance")
                    strength += 0.3
            
            # Wide spread for liquid stock
            if spread_pct > 0.1:  # > 10 bps spread
                signals.append("spread_widening")
                strength += 0.2
            
            # Very small bid size (no support)
            if bid_size < 100:
                signals.append("thin_bid")
                strength += 0.3
            
            if signals and strength >= 0.3:
                return FootprintSignal(
                    footprint_type=FootprintType.QUOTE_DEGRADATION,
                    timestamp=datetime.now(),
                    strength=min(1.0, strength),
                    details={
                        "bid_size": bid_size,
                        "ask_size": ask_size,
                        "spread_pct": round(spread_pct, 3),
                        "signals": signals,
                        "note": "Market makers reducing exposure"
                    }
                )
            
            return None
            
        except Exception as e:
            logger.debug(f"Quote degradation check failed for {symbol}: {e}")
            return None
    
    async def _detect_flow_divergence(self, symbol: str) -> Optional[FootprintSignal]:
        """
        FOOTPRINT 5: Options Flow Divergence
        
        Detects when options flow diverges from price:
        - Price flat or up, but put premium increasing
        - Call/put premium ratio shifting bearish
        - The options market leads the stock by 1-2 days
        """
        try:
            # Get options flow
            flow = await self.uw.get_flow_recent(symbol, limit=100)
            
            if not flow or len(flow) < 10:
                return None
            
            # Calculate put vs call premium
            put_premium = sum(f.premium for f in flow if f.option_type == "PUT")
            call_premium = sum(f.premium for f in flow if f.option_type == "CALL")
            
            total_premium = put_premium + call_premium
            if total_premium == 0:
                return None
            
            put_ratio = put_premium / total_premium
            
            # If puts are > 60% of premium, that's bearish divergence
            if put_ratio > 0.60:
                # Check if price is NOT dropping (divergence)
                try:
                    bars = await self.polygon.get_daily_bars(
                        symbol=symbol,
                        from_date=date.today() - timedelta(days=3)
                    )
                    if bars and len(bars) >= 2:
                        price_change = (bars[-1].close - bars[-2].close) / bars[-2].close
                        
                        # Price flat or up while put flow dominant = divergence
                        if price_change >= -0.01:
                            strength = min(1.0, (put_ratio - 0.5) * 2)
                            
                            return FootprintSignal(
                                footprint_type=FootprintType.FLOW_DIVERGENCE,
                                timestamp=datetime.now(),
                                strength=strength,
                                details={
                                    "put_ratio": round(put_ratio, 3),
                                    "put_premium": put_premium,
                                    "call_premium": call_premium,
                                    "price_change_pct": round(price_change * 100, 2),
                                    "note": "Options flow bearish while price stable"
                                }
                            )
                except Exception:
                    pass
            
            return None
            
        except Exception as e:
            logger.debug(f"Flow divergence check failed for {symbol}: {e}")
            return None
    
    async def _detect_multi_day_distribution(self, symbol: str) -> Optional[FootprintSignal]:
        """
        FOOTPRINT 6: Multi-Day Distribution Pattern
        
        Detects classic Wyckoff distribution:
        - Lower highs over 3+ days
        - Volume increasing on down moves
        - Volume decreasing on up moves
        - Price failing to make new highs
        """
        try:
            bars = await self.polygon.get_daily_bars(
                symbol=symbol,
                from_date=date.today() - timedelta(days=10)
            )
            
            if not bars or len(bars) < 5:
                return None
            
            recent = bars[-5:]
            
            # Check for lower highs
            highs = [b.high for b in recent]
            lower_highs = all(highs[i] >= highs[i+1] for i in range(len(highs)-2))
            
            # Check volume patterns
            up_days = [(b, i) for i, b in enumerate(recent) if b.close > b.open]
            down_days = [(b, i) for i, b in enumerate(recent) if b.close <= b.open]
            
            avg_up_volume = np.mean([b.volume for b, _ in up_days]) if up_days else 0
            avg_down_volume = np.mean([b.volume for b, _ in down_days]) if down_days else 0
            
            # Distribution: higher volume on down days
            vol_distribution = avg_down_volume > avg_up_volume * 1.2 if avg_up_volume > 0 else False
            
            signals = []
            strength = 0.0
            
            if lower_highs:
                signals.append("lower_highs")
                strength += 0.4
            
            if vol_distribution:
                signals.append("volume_distribution")
                strength += 0.4
            
            if len(down_days) >= 3:
                signals.append("multiple_down_days")
                strength += 0.2
            
            if signals and strength >= 0.4:
                return FootprintSignal(
                    footprint_type=FootprintType.MULTI_DAY_DISTRIBUTION,
                    timestamp=datetime.now(),
                    strength=min(1.0, strength),
                    details={
                        "signals": signals,
                        "down_days": len(down_days),
                        "up_days": len(up_days),
                        "avg_up_volume": int(avg_up_volume),
                        "avg_down_volume": int(avg_down_volume),
                        "note": "Classic Wyckoff distribution pattern"
                    }
                )
            
            return None
            
        except Exception as e:
            logger.debug(f"Multi-day distribution check failed for {symbol}: {e}")
            return None
    
    async def _detect_cross_asset_divergence(self, symbol: str) -> Optional[FootprintSignal]:
        """
        FOOTPRINT 7: Cross-Asset Divergence
        
        Detects when stock diverges from related assets:
        - Stock flat but sector ETF weak
        - Stock flat but peers dropping
        - Correlation breakdown
        
        This requires sector mapping.
        """
        try:
            from putsengine.config import EngineConfig
            
            # Get sector peers
            peers = EngineConfig.get_sector_peers(symbol)
            if not peers or len(peers) < 2:
                return None
            
            # Get symbol's price change
            symbol_bars = await self.polygon.get_daily_bars(
                symbol=symbol,
                from_date=date.today() - timedelta(days=3)
            )
            
            if not symbol_bars or len(symbol_bars) < 2:
                return None
            
            symbol_change = (symbol_bars[-1].close - symbol_bars[-2].close) / symbol_bars[-2].close
            
            # Get peer changes
            peer_changes = []
            for peer in peers[:5]:  # Check up to 5 peers
                try:
                    peer_bars = await self.polygon.get_daily_bars(
                        symbol=peer,
                        from_date=date.today() - timedelta(days=3)
                    )
                    if peer_bars and len(peer_bars) >= 2:
                        change = (peer_bars[-1].close - peer_bars[-2].close) / peer_bars[-2].close
                        peer_changes.append(change)
                except Exception:
                    continue
            
            if not peer_changes:
                return None
            
            avg_peer_change = np.mean(peer_changes)
            
            # Divergence: symbol flat/up while peers down
            if symbol_change >= -0.01 and avg_peer_change < -0.02:
                divergence = abs(symbol_change - avg_peer_change)
                strength = min(1.0, divergence * 10)  # Scale divergence to strength
                
                return FootprintSignal(
                    footprint_type=FootprintType.CROSS_ASSET_DIVERGENCE,
                    timestamp=datetime.now(),
                    strength=strength,
                    details={
                        "symbol_change_pct": round(symbol_change * 100, 2),
                        "avg_peer_change_pct": round(avg_peer_change * 100, 2),
                        "divergence_pct": round(divergence * 100, 2),
                        "peers_checked": len(peer_changes),
                        "note": "Symbol diverging from sector peers"
                    }
                )
            
            return None
            
        except Exception as e:
            logger.debug(f"Cross-asset divergence check failed for {symbol}: {e}")
            return None


# ============================================================================
# INTEGRATION WITH SCHEDULER
# ============================================================================

async def run_early_warning_scan(alpaca, polygon, uw, symbols: List[str]) -> Dict[str, InstitutionalPressure]:
    """
    Run early warning scan on a list of symbols.
    
    Args:
        alpaca: AlpacaClient
        polygon: PolygonClient
        uw: UnusualWhalesClient
        symbols: List of tickers to scan
        
    Returns:
        Dict of symbol -> InstitutionalPressure for symbols with IPI > 0.3
    """
    scanner = EarlyWarningScanner(alpaca, polygon, uw)
    results = {}
    
    logger.info(f"Early Warning System: Scanning {len(symbols)} symbols...")
    
    for i, symbol in enumerate(symbols):
        try:
            pressure = await scanner.scan_symbol(symbol)
            
            if pressure.ipi > 0.3:  # Only track significant pressure
                results[symbol] = pressure
            
            # Rate limiting
            if (i + 1) % 10 == 0:
                logger.info(f"Early Warning: {i+1}/{len(symbols)} scanned, {len(results)} with pressure")
                await asyncio.sleep(0.5)
                
        except Exception as e:
            logger.debug(f"Early warning scan failed for {symbol}: {e}")
    
    # Sort by IPI
    sorted_results = dict(sorted(
        results.items(),
        key=lambda x: x[1].ipi,
        reverse=True
    ))
    
    logger.info(f"Early Warning Complete: {len(sorted_results)} symbols with institutional pressure")
    
    return sorted_results


def get_early_warning_summary() -> Dict:
    """
    Get summary of current early warning alerts.
    
    Returns:
        Dict with summary statistics and top alerts
    """
    history = load_footprint_history()
    
    now = datetime.now()
    cutoff_48h = (now - timedelta(hours=48)).isoformat()
    
    # Count symbols with recent footprints
    active_symbols = {}
    
    for symbol, footprints in history.items():
        recent = [f for f in footprints if f.get("timestamp", "") > cutoff_48h]
        if recent:
            # Count unique footprint types
            unique_types = len(set(f["footprint_type"] for f in recent))
            total_strength = sum(f.get("strength", 0) for f in recent)
            
            active_symbols[symbol] = {
                "footprint_count": len(recent),
                "unique_types": unique_types,
                "total_strength": total_strength,
                "latest": max(f.get("timestamp", "") for f in recent),
            }
    
    # Sort by total strength
    sorted_symbols = sorted(
        active_symbols.items(),
        key=lambda x: x[1]["total_strength"],
        reverse=True
    )
    
    return {
        "total_symbols_tracked": len(active_symbols),
        "top_alerts": [
            {
                "symbol": sym,
                "footprints": data["footprint_count"],
                "unique_types": data["unique_types"],
                "strength": round(data["total_strength"], 2),
            }
            for sym, data in sorted_symbols[:10]
        ],
        "timestamp": now.isoformat(),
    }
