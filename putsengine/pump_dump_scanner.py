"""
Pump-and-Dump Reversal Pattern Detector

PURPOSE: Detect strong up moves (+5%+) followed by immediate reversal.
This pattern would have caught OKLO, CLS, FSLR on Jan 27-28.

PATTERN:
1. Day 1: Strong move UP (+5% to +15%)
2. Day 2: Reversal DOWN (-5% to -15%)
3. Volume spike on reversal day
4. Often happens around news/earnings

INSTITUTIONAL LOGIC:
- Strong up moves without fundamentals = distribution opportunity
- "Buy the rumor, sell the news" pattern
- Reversal day shows institutional exit
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
from loguru import logger
from dataclasses import dataclass

from putsengine.clients.alpaca_client import AlpacaClient


@dataclass
class PumpDumpPattern:
    """Detected pump-and-dump reversal pattern."""
    symbol: str
    pump_date: date
    pump_pct: float
    dump_date: date
    dump_pct: float
    pump_volume: int
    dump_volume: int
    volume_ratio: float
    score: float
    confidence: float


class PumpDumpScanner:
    """
    Scans for pump-and-dump reversal patterns.
    
    Detects:
    - Strong up move (+5%+) on day 1
    - Reversal down (-5%+) on day 2
    - Volume confirmation
    """
    
    # Thresholds
    MIN_PUMP_PCT = 0.05  # 5% minimum pump
    MIN_DUMP_PCT = 0.05  # 5% minimum dump
    MIN_VOLUME_RATIO = 1.2  # 20% volume increase on dump day
    
    def __init__(self, alpaca_client: AlpacaClient):
        self.alpaca = alpaca_client
    
    async def detect_pattern(self, symbol: str) -> Optional[PumpDumpPattern]:
        """
        Detect pump-and-dump pattern for a symbol.
        
        Args:
            symbol: Ticker symbol
            
        Returns:
            PumpDumpPattern if detected, None otherwise
        """
        try:
            # Get last 5 days of bars
            bars = await self.alpaca.get_bars(symbol, "1Day", limit=5)
            
            if len(bars) < 2:
                return None
            
            # Check last 2 days for pump-then-dump
            day_before = bars[-2]
            today = bars[-1]
            
            # Calculate day-over-day changes
            day_before_change = ((day_before.close - day_before.open) / day_before.open) * 100
            today_change = ((today.close - today.open) / today.open) * 100
            
            # Check for pump (day before) and dump (today)
            is_pump = day_before_change >= (self.MIN_PUMP_PCT * 100)
            is_dump = today_change <= -(self.MIN_DUMP_PCT * 100)
            
            if not (is_pump and is_dump):
                return None
            
            # Check volume
            avg_volume = sum(b.volume for b in bars[:-1]) / (len(bars) - 1)
            volume_ratio = today.volume / avg_volume if avg_volume > 0 else 1.0
            
            if volume_ratio < self.MIN_VOLUME_RATIO:
                return None  # Not enough volume confirmation
            
            # Calculate score based on magnitude
            pump_magnitude = abs(day_before_change) / 100
            dump_magnitude = abs(today_change) / 100
            
            # Score = (pump + dump) * volume_confirmation
            base_score = (pump_magnitude + dump_magnitude) * 0.5
            volume_boost = min(0.3, (volume_ratio - 1.0) * 0.1)
            score = min(0.70, base_score + volume_boost)
            
            # Confidence based on pattern strength
            confidence = min(0.95, 0.60 + (pump_magnitude + dump_magnitude) * 0.15)
            
            return PumpDumpPattern(
                symbol=symbol,
                pump_date=day_before.timestamp.date(),
                pump_pct=day_before_change,
                dump_date=today.timestamp.date(),
                dump_pct=today_change,
                pump_volume=day_before.volume,
                dump_volume=today.volume,
                volume_ratio=volume_ratio,
                score=score,
                confidence=confidence
            )
            
        except Exception as e:
            logger.debug(f"Failed to detect pump-dump for {symbol}: {e}")
            return None
    
    async def scan_universe(self, symbols: List[str]) -> Dict[str, PumpDumpPattern]:
        """
        Scan universe for pump-and-dump patterns.
        
        Args:
            symbols: List of ticker symbols
            
        Returns:
            Dict of {symbol: PumpDumpPattern}
        """
        results = {}
        
        for symbol in symbols:
            try:
                pattern = await self.detect_pattern(symbol)
                if pattern:
                    results[symbol] = pattern
                    logger.warning(
                        f"PUMP-DUMP DETECTED: {symbol} | "
                        f"Pump: {pattern.pump_pct:+.1f}% on {pattern.pump_date} | "
                        f"Dump: {pattern.dump_pct:+.1f}% on {pattern.dump_date} | "
                        f"Score: {pattern.score:.2f}"
                    )
            except Exception as e:
                logger.debug(f"Error scanning {symbol}: {e}")
        
        return results


async def run_pump_dump_scan(
    alpaca_client: AlpacaClient,
    symbols: List[str]
) -> Dict:
    """
    Run pump-and-dump reversal scan.
    
    Args:
        alpaca_client: AlpacaClient instance
        symbols: List of symbols to scan
        
    Returns:
        Dict with detected patterns
    """
    scanner = PumpDumpScanner(alpaca_client)
    patterns = await scanner.scan_universe(symbols)
    
    logger.info(
        f"Pump-Dump Scan: {len(symbols)} scanned, "
        f"{len(patterns)} patterns detected"
    )
    
    return {
        "patterns": patterns,
        "scan_time": datetime.now().isoformat(),
        "symbols_scanned": len(symbols),
        "patterns_count": len(patterns)
    }
