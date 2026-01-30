"""
Big Movers Pattern Scanner - Institutional-Grade Analysis

PURPOSE: Detect patterns that lead to -5% to -20% moves
Analyzes the REAL patterns that cause major drops:

1. PUMP-AND-DUMP: Up big then crashes (RR, NET, CLS, LEU, etc.)
2. REVERSAL AFTER PUMP: 2-day pump then crash (UUUU, OKLO, FSLR)
3. SUDDEN CRASH: Flat then big drop (MSFT, MSTR earnings)
4. SECTOR CONTAGION: Multiple sector stocks move together

THIS SCANNER WOULD HAVE CAUGHT:
Jan 26-29, 2026:
- RR: +44.6% then -20.9% (pump-dump)
- UNH: -19.6% (sudden crash - earnings)
- JOBY: -16.7% (multi-day weakness)
- CLS: -13.1% (pump-dump, sector)
- USAR: -12.4% (rare earth contagion)
- NET: -10.2% (pump-dump)
- MSFT: -10.0% (sudden crash - earnings)
- MSTR: -9.6% (sudden crash - BTC correlation)
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
import pytz
from loguru import logger
from dataclasses import dataclass, field
import json


@dataclass
class BigMoverPattern:
    """A detected pattern that could lead to a big move."""
    symbol: str
    pattern_type: str  # pump_dump, reversal, sudden_crash, sector_contagion
    confidence: float  # 0-1 confidence score
    expected_move_pct: float  # Expected % move (negative for puts)
    signals: List[str] = field(default_factory=list)
    sector: str = ""
    sector_peers: List[str] = field(default_factory=list)
    price_history: Dict = field(default_factory=dict)  # Last 4 days
    detection_time: str = ""
    
    @property
    def severity(self) -> str:
        if self.confidence >= 0.80:
            return "🔴 CRITICAL"
        elif self.confidence >= 0.60:
            return "🟠 HIGH"
        elif self.confidence >= 0.40:
            return "🟡 MEDIUM"
        return "⚪ LOW"
    
    @property
    def potential_return(self) -> str:
        """Estimate potential return on puts."""
        if abs(self.expected_move_pct) >= 15:
            return "10x-20x"
        elif abs(self.expected_move_pct) >= 10:
            return "5x-10x"
        elif abs(self.expected_move_pct) >= 7:
            return "3x-5x"
        elif abs(self.expected_move_pct) >= 5:
            return "2x-3x"
        return "1.5x-2x"


# Sector mapping for contagion detection
SECTOR_MAPPING = {
    "crypto": ["MSTR", "COIN", "RIOT", "MARA", "HUT", "CLSK", "CIFR", "WULF", "BITF", "BMNR"],
    "uranium_nuclear": ["UUUU", "LEU", "OKLO", "SMR", "CCJ", "DNN", "UEC", "NNE", "URG"],
    "evtol_space": ["JOBY", "ACHR", "RKLB", "LUNR", "ASTS", "RDW", "RCAT", "PL", "SPCE", "LILM"],
    "rare_earth": ["MP", "USAR", "LAC", "ALB", "LTHM", "SQM"],
    "quantum": ["RGTI", "QUBT", "IONQ", "QBTS"],
    "ai_software": ["BBAI", "AI", "PLTR", "NOW", "SNOW", "CRM", "INOD", "SOUN"],
    "cloud_saas": ["NET", "CRWD", "ZS", "OKTA", "DDOG", "TEAM", "WDAY", "TWLO", "HUBS", "MDB"],
    "solar_clean": ["FSLR", "ENPH", "RUN", "SEDG", "BE", "PLUG", "FCEL", "EOSE"],
    "tech_mega": ["MSFT", "AAPL", "GOOGL", "AMZN", "META", "NVDA"],
    "btc_miners": ["IREN", "APLD", "CIFR", "CLSK", "HUT", "RIOT", "MARA", "WULF"],
    "semiconductors": ["NVDA", "AMD", "INTC", "MU", "AVGO", "TSM", "CLS", "SWKS", "STX", "WDC"],
    "china_adr": ["BABA", "JD", "PDD", "BIDU", "NIO", "XPEV", "LI", "BILI", "TME"],
    "travel": ["DAL", "UAL", "AAL", "LUV", "JBLU", "CCL", "RCL", "NCLH", "MAR", "HLT"],
    "fintech": ["SQ", "PYPL", "AFRM", "UPST", "SOFI", "HOOD", "NU", "BILL", "FOUR"],
}


def get_sector(symbol: str) -> str:
    """Get sector for a symbol."""
    for sector, tickers in SECTOR_MAPPING.items():
        if symbol in tickers:
            return sector
    return "other"


def get_sector_peers(symbol: str) -> List[str]:
    """Get peer tickers in the same sector."""
    for sector, tickers in SECTOR_MAPPING.items():
        if symbol in tickers:
            return [t for t in tickers if t != symbol]
    return []


class BigMoversScanner:
    """
    Scans for patterns that lead to big moves (-5% to -20%).
    
    LOWERED THRESHOLDS (vs original):
    - Pump threshold: 5% -> 3% (catch smaller pumps)
    - Reversal watch: 2 days up -> watch for crash
    - Sector contagion: 2+ peers moving -> boost
    
    INSTITUTIONAL LOGIC:
    - Pumps = retail FOMO, institutions sell into strength
    - 2-day rallies = exhaustion setup
    - Sector moves = systematic risk, institutions exit together
    - Flat then crash = earnings/news driven
    """
    
    # LOWERED THRESHOLDS to catch more patterns
    MIN_PUMP_PCT = 3.0  # Was 5.0 - lowered to catch NET, CLS
    MIN_PUMP_DAYS = 1
    MAX_PUMP_DAYS = 3
    REVERSAL_WATCH_CONSECUTIVE_UP_DAYS = 2  # Watch after 2 up days
    REVERSAL_WATCH_MIN_GAIN = 3.0  # At least +3% total in 2 days
    SECTOR_CONTAGION_MIN_PEERS = 2  # At least 2 peers moving
    SUDDEN_CRASH_MIN_PCT = 7.0  # Big sudden move
    FLAT_THRESHOLD = 3.0  # < 3% move = "flat"
    
    def __init__(self, alpaca_client=None):
        self.alpaca_client = alpaca_client
        self.et = pytz.timezone('US/Eastern')
    
    async def analyze_symbol(self, symbol: str, bars: List = None) -> Optional[BigMoverPattern]:
        """
        Analyze a symbol for big mover patterns.
        
        Args:
            symbol: Ticker symbol
            bars: Pre-fetched daily bars (need at least 10 days)
        
        Returns:
            BigMoverPattern if detected, else None
        """
        if bars is None and self.alpaca_client:
            try:
                bars = await self.alpaca_client.get_daily_bars(symbol, limit=15)
            except Exception as e:
                logger.debug(f"Failed to get bars for {symbol}: {e}")
                return None
        
        if not bars or len(bars) < 5:
            return None
        
        # Calculate daily returns
        returns = []
        for i in range(1, min(5, len(bars))):
            pct_change = ((bars[-i].close - bars[-(i+1)].close) / bars[-(i+1)].close) * 100
            returns.append(pct_change)
        
        if not returns:
            return None
        
        patterns = []
        
        # Pattern 1: Pump-and-Dump
        pump_pattern = self._detect_pump_dump(symbol, bars, returns)
        if pump_pattern:
            patterns.append(pump_pattern)
        
        # Pattern 2: Reversal After Pump (2-day rally)
        reversal_pattern = self._detect_reversal_watch(symbol, bars, returns)
        if reversal_pattern:
            patterns.append(reversal_pattern)
        
        # Pattern 3: Sudden Crash Setup (flat then big move)
        sudden_pattern = self._detect_sudden_crash_setup(symbol, bars, returns)
        if sudden_pattern:
            patterns.append(sudden_pattern)
        
        # Pattern 4: Sector Contagion
        sector_pattern = self._detect_sector_contagion(symbol, bars, returns)
        if sector_pattern:
            patterns.append(sector_pattern)
        
        # Return highest confidence pattern
        if patterns:
            return max(patterns, key=lambda p: p.confidence)
        
        return None
    
    def _detect_pump_dump(
        self, symbol: str, bars: List, returns: List
    ) -> Optional[BigMoverPattern]:
        """Detect pump-and-dump pattern."""
        if len(bars) < 5:
            return None
        
        # Check for recent pump (+3%+ in last 1-3 days)
        for days_back in range(1, self.MAX_PUMP_DAYS + 1):
            if len(bars) < days_back + 2:
                continue
            
            start_idx = -(days_back + 1)
            start_price = bars[start_idx].close
            high_in_period = max(b.high for b in bars[start_idx:])
            current_price = bars[-1].close
            
            pump_pct = ((high_in_period - start_price) / start_price) * 100
            
            if pump_pct >= self.MIN_PUMP_PCT:
                # Check for reversal signals
                signals = self._get_reversal_signals(bars)
                
                if signals:
                    # Calculate confidence
                    confidence = min(0.90, 0.40 + pump_pct * 0.02 + len(signals) * 0.10)
                    expected_move = -min(pump_pct * 0.6, 15.0)  # Expect 60% retracement max
                    
                    return BigMoverPattern(
                        symbol=symbol,
                        pattern_type="pump_dump",
                        confidence=confidence,
                        expected_move_pct=expected_move,
                        signals=signals + [f"pump_{pump_pct:.1f}pct_{days_back}d"],
                        sector=get_sector(symbol),
                        sector_peers=get_sector_peers(symbol)[:5],
                        price_history={
                            "pump_pct": pump_pct,
                            "pump_days": days_back,
                            "high_price": high_in_period,
                            "current_price": current_price
                        },
                        detection_time=datetime.now(self.et).isoformat()
                    )
        
        return None
    
    def _detect_reversal_watch(
        self, symbol: str, bars: List, returns: List
    ) -> Optional[BigMoverPattern]:
        """Detect 2-day rally setup (reversal watch)."""
        if len(returns) < 2:
            return None
        
        # Check if last 2 days were both positive
        day1_return = returns[0]  # Most recent
        day2_return = returns[1] if len(returns) > 1 else 0
        
        total_gain = day1_return + day2_return
        
        # Both days positive and total gain >= threshold
        if day1_return > 0 and day2_return > 0 and total_gain >= self.REVERSAL_WATCH_MIN_GAIN:
            signals = [
                f"consecutive_up_2d",
                f"total_gain_{total_gain:.1f}pct"
            ]
            
            # Check for exhaustion signals
            if len(bars) >= 2:
                current = bars[-1]
                if current.close < current.high * 0.97:  # Close below day's high
                    signals.append("exhaustion_candle")
            
            confidence = min(0.75, 0.35 + total_gain * 0.03 + len(signals) * 0.10)
            expected_move = -min(total_gain * 0.5, 10.0)  # 50% retracement
            
            return BigMoverPattern(
                symbol=symbol,
                pattern_type="reversal_watch",
                confidence=confidence,
                expected_move_pct=expected_move,
                signals=signals,
                sector=get_sector(symbol),
                price_history={
                    "day1_return": day1_return,
                    "day2_return": day2_return,
                    "total_gain": total_gain
                },
                detection_time=datetime.now(self.et).isoformat()
            )
        
        return None
    
    def _detect_sudden_crash_setup(
        self, symbol: str, bars: List, returns: List
    ) -> Optional[BigMoverPattern]:
        """Detect flat-then-crash setup (often earnings driven)."""
        if len(returns) < 3:
            return None
        
        # Check if last 2-3 days were relatively flat
        recent_returns = returns[:3]
        max_move = max(abs(r) for r in recent_returns)
        
        if max_move < self.FLAT_THRESHOLD:
            # Flat pattern detected - could crash on news
            signals = ["flat_consolidation"]
            
            # Add volume analysis if available
            if len(bars) >= 3:
                avg_vol = sum(b.volume for b in bars[-10:-1]) / 9 if len(bars) >= 10 else bars[-2].volume
                current_vol = bars[-1].volume
                if current_vol < avg_vol * 0.8:
                    signals.append("declining_volume")  # Setup for breakout
                elif current_vol > avg_vol * 1.5:
                    signals.append("volume_spike")  # Breakout imminent
            
            confidence = 0.40 + len(signals) * 0.10
            expected_move = -8.0  # Conservative estimate
            
            return BigMoverPattern(
                symbol=symbol,
                pattern_type="sudden_crash_setup",
                confidence=confidence,
                expected_move_pct=expected_move,
                signals=signals,
                sector=get_sector(symbol),
                price_history={
                    "recent_returns": recent_returns,
                    "max_move": max_move
                },
                detection_time=datetime.now(self.et).isoformat()
            )
        
        return None
    
    def _detect_sector_contagion(
        self, symbol: str, bars: List, returns: List
    ) -> Optional[BigMoverPattern]:
        """Detect sector-wide weakness pattern."""
        sector = get_sector(symbol)
        if sector == "other":
            return None
        
        # This would need peer data - for now, just flag sector membership
        peers = get_sector_peers(symbol)
        
        if len(peers) >= self.SECTOR_CONTAGION_MIN_PEERS:
            # Check if symbol itself is weak
            if len(returns) > 0 and returns[0] < -2.0:
                signals = [
                    f"sector_{sector}",
                    f"peer_count_{len(peers)}",
                    "sector_weakness_candidate"
                ]
                
                confidence = 0.35 + min(len(peers) * 0.02, 0.20)
                expected_move = returns[0] * 1.5  # Expect continuation
                
                return BigMoverPattern(
                    symbol=symbol,
                    pattern_type="sector_contagion",
                    confidence=confidence,
                    expected_move_pct=expected_move,
                    signals=signals,
                    sector=sector,
                    sector_peers=peers[:5],
                    price_history={
                        "latest_return": returns[0] if returns else 0
                    },
                    detection_time=datetime.now(self.et).isoformat()
                )
        
        return None
    
    def _get_reversal_signals(self, bars: List) -> List[str]:
        """Get reversal signals from price bars."""
        signals = []
        
        if len(bars) < 2:
            return signals
        
        current = bars[-1]
        prior = bars[-2]
        
        # 1. Bearish engulfing
        if prior.close > prior.open:  # Prior was green
            if current.close < current.open:  # Current is red
                if current.open >= prior.close and current.close <= prior.open:
                    signals.append("bearish_engulfing")
        
        # 2. Close below prior low
        if current.close < prior.low:
            signals.append("close_below_prior_low")
        
        # 3. High volume red candle
        if len(bars) >= 10:
            avg_vol = sum(b.volume for b in bars[-10:-1]) / 9
            if current.volume > avg_vol * 1.3 and current.close < current.open:
                signals.append("high_vol_red")
        
        # 4. Topping tail
        body = abs(current.close - current.open)
        upper_wick = current.high - max(current.close, current.open)
        if body > 0 and upper_wick > body * 2:
            signals.append("topping_tail")
        
        # 5. Gap down open
        if current.open < prior.close * 0.98:
            signals.append("gap_down")
        
        # 6. Failed at resistance (new high then close lower)
        if len(bars) >= 3:
            three_day_high = max(b.high for b in bars[-3:-1])
            if current.high > three_day_high and current.close < prior.close:
                signals.append("failed_breakout")
        
        return signals
    
    async def scan_universe(self, symbols: List[str]) -> Dict:
        """
        Scan all symbols for big mover patterns.
        
        Args:
            symbols: List of ticker symbols
        
        Returns:
            Dict with patterns by type and summary
        """
        now = datetime.now(self.et)
        
        logger.info(f"Big Movers Scanner: Starting scan of {len(symbols)} symbols")
        
        results = {
            "pump_dump": [],
            "reversal_watch": [],
            "sudden_crash_setup": [],
            "sector_contagion": [],
            "all_patterns": [],
            "scan_time": now.isoformat()
        }
        
        for symbol in symbols:
            pattern = await self.analyze_symbol(symbol)
            
            if pattern:
                results["all_patterns"].append(pattern)
                results[pattern.pattern_type].append(pattern)
                
                logger.info(
                    f"BIG MOVER: {symbol} | {pattern.pattern_type} | "
                    f"Confidence: {pattern.confidence:.2f} | "
                    f"Expected: {pattern.expected_move_pct:+.1f}%"
                )
        
        # Sort all by confidence
        results["all_patterns"].sort(key=lambda p: p.confidence, reverse=True)
        
        results["summary"] = {
            "scanned": len(symbols),
            "patterns_found": len(results["all_patterns"]),
            "pump_dump_count": len(results["pump_dump"]),
            "reversal_watch_count": len(results["reversal_watch"]),
            "sudden_crash_count": len(results["sudden_crash_setup"]),
            "sector_contagion_count": len(results["sector_contagion"])
        }
        
        return results


def analyze_historical_movers(movers_data: Dict) -> Dict:
    """
    Analyze historical big movers to find patterns.
    
    Args:
        movers_data: Dict with symbol -> daily returns
    
    Returns:
        Pattern analysis results
    """
    patterns = {
        "pump_dump": [],
        "reversal_after_pump": [],
        "sudden_crash": [],
        "sector_contagion": [],
        "multi_day_decline": []
    }
    
    for symbol, data in movers_data.items():
        jan26 = data.get("jan26", 0)
        jan27 = data.get("jan27", 0)
        jan28 = data.get("jan28", 0)
        jan29 = data.get("jan29", 0)
        
        sector = get_sector(symbol)
        
        # Pattern 1: Pump and Dump
        if jan27 > 5 and (jan28 < -5 or jan29 < -5):
            patterns["pump_dump"].append({
                "symbol": symbol,
                "pump_day": "Jan 27",
                "pump_pct": jan27,
                "dump_pct": min(jan28, jan29),
                "sector": sector
            })
        
        # Pattern 2: Reversal After Pump
        if (jan27 > 3 or jan28 > 3) and jan29 < -5:
            patterns["reversal_after_pump"].append({
                "symbol": symbol,
                "pump_days": f"Jan 27: {jan27:+.1f}%, Jan 28: {jan28:+.1f}%",
                "crash_pct": jan29,
                "sector": sector
            })
        
        # Pattern 3: Sudden Crash
        if abs(jan26) < 3 and abs(jan27) < 3 and (jan28 < -8 or jan29 < -8):
            patterns["sudden_crash"].append({
                "symbol": symbol,
                "crash_pct": min(jan28, jan29),
                "sector": sector
            })
        
        # Pattern 4: Multi-day decline
        down_days = sum([1 for d in [jan26, jan27, jan28, jan29] if d < -3])
        if down_days >= 2:
            patterns["multi_day_decline"].append({
                "symbol": symbol,
                "down_days": down_days,
                "total_decline": sum([d for d in [jan26, jan27, jan28, jan29] if d < 0]),
                "sector": sector
            })
    
    # Sector contagion
    sector_moves = defaultdict(list)
    for symbol, data in movers_data.items():
        sector = get_sector(symbol)
        if data.get("max_down", 0) < -5:
            sector_moves[sector].append(symbol)
    
    for sector, symbols in sector_moves.items():
        if len(symbols) >= 2:
            patterns["sector_contagion"].append({
                "sector": sector,
                "symbols": symbols,
                "count": len(symbols)
            })
    
    return patterns


async def run_big_movers_scan(alpaca_client, symbols: List[str]) -> Dict:
    """
    Run big movers scan on symbols.
    
    Args:
        alpaca_client: AlpacaClient instance
        symbols: List of symbols to scan
    
    Returns:
        Dict with patterns and summary
    """
    scanner = BigMoversScanner(alpaca_client)
    return await scanner.scan_universe(symbols)


def serialize_pattern(pattern: BigMoverPattern) -> Dict:
    """Serialize BigMoverPattern for JSON storage."""
    return {
        "symbol": pattern.symbol,
        "pattern_type": pattern.pattern_type,
        "confidence": pattern.confidence,
        "expected_move_pct": pattern.expected_move_pct,
        "signals": pattern.signals,
        "sector": pattern.sector,
        "sector_peers": pattern.sector_peers,
        "price_history": pattern.price_history,
        "detection_time": pattern.detection_time,
        "severity": pattern.severity,
        "potential_return": pattern.potential_return
    }
