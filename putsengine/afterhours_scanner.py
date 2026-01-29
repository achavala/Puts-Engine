"""
After-Hours Scanner - Detect moves happening after 4 PM ET

PURPOSE: Catch moves like MP (-10.68% AH), USAR (-13.31% AH), LAC (-8.74% AH), JOBY (-11.48% AH)
         that happen AFTER market close but BEFORE next day's open.

SCAN TIMES:
- 4:30 PM ET - First AH scan (30 min after close)
- 6:00 PM ET - Mid-evening scan
- 8:00 PM ET - Final evening scan

DETECTION THRESHOLDS:
- >= 5% move: CRITICAL - Inject to DUI with high score
- >= 3% move: HIGH - Inject to DUI with medium score
- >= 2% move: WATCHING - Monitor for next day

DATA SOURCE: Alpaca extended hours data
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Set
import pytz
from loguru import logger
from dataclasses import dataclass
from enum import Enum


class AHAlertSeverity(Enum):
    """After-hours alert severity levels."""
    CRITICAL = "critical"    # >= 5% move
    HIGH = "high"           # >= 3% move
    WATCHING = "watching"   # >= 2% move


@dataclass
class AfterHoursAlert:
    """Alert for after-hours move detection."""
    symbol: str
    close_price: float
    ah_price: float
    ah_change_pct: float
    severity: AHAlertSeverity
    direction: str  # "DOWN" or "UP"
    volume: int
    alert_time: str
    
    @property
    def is_bearish(self) -> bool:
        return self.direction == "DOWN"


class AfterHoursScanner:
    """
    Scans for significant after-hours moves.
    
    This scanner would have caught:
    - MP: -10.68% AH
    - USAR: -13.31% AH
    - LAC: -8.74% AH
    - JOBY: -11.48% AH
    """
    
    # Detection thresholds (for DOWN moves - puts)
    CRITICAL_THRESHOLD = 0.05    # 5%+ down = CRITICAL
    HIGH_THRESHOLD = 0.03        # 3%+ down = HIGH
    WATCHING_THRESHOLD = 0.02    # 2%+ down = WATCHING
    
    # Minimum volume filter
    MIN_AH_VOLUME = 10000  # Minimum after-hours volume
    
    def __init__(self, alpaca_client):
        """
        Initialize after-hours scanner.
        
        Args:
            alpaca_client: AlpacaClient for price data
        """
        self.alpaca_client = alpaca_client
        self._alerts: Dict[str, AfterHoursAlert] = {}
    
    async def scan_single(self, symbol: str) -> Optional[AfterHoursAlert]:
        """
        Scan a single ticker for after-hours move.
        
        Args:
            symbol: Ticker symbol
            
        Returns:
            AfterHoursAlert if significant move detected, None otherwise
        """
        try:
            # Get latest bar (includes extended hours if available)
            bar = await self.alpaca_client.get_latest_bar(symbol)
            if not bar:
                return None
            
            close_price = bar.close
            
            # Get extended hours quote
            quote = await self.alpaca_client.get_latest_quote(symbol)
            if not quote:
                return None
            
            # Use ask price as AH price (more reliable than last trade)
            ah_price = quote.get("ap", close_price)
            if ah_price == 0:
                ah_price = quote.get("bp", close_price)
            
            if ah_price == 0 or close_price == 0:
                return None
            
            # Calculate change
            change_pct = (ah_price - close_price) / close_price
            
            # Determine severity and direction
            abs_change = abs(change_pct)
            direction = "DOWN" if change_pct < 0 else "UP"
            
            # Only track significant DOWN moves (for puts)
            if direction == "DOWN" and abs_change >= self.WATCHING_THRESHOLD:
                if abs_change >= self.CRITICAL_THRESHOLD:
                    severity = AHAlertSeverity.CRITICAL
                elif abs_change >= self.HIGH_THRESHOLD:
                    severity = AHAlertSeverity.HIGH
                else:
                    severity = AHAlertSeverity.WATCHING
                
                alert = AfterHoursAlert(
                    symbol=symbol,
                    close_price=close_price,
                    ah_price=ah_price,
                    ah_change_pct=change_pct * 100,  # Convert to percentage
                    severity=severity,
                    direction=direction,
                    volume=bar.volume,
                    alert_time=datetime.now().isoformat()
                )
                
                return alert
            
            return None
            
        except Exception as e:
            logger.debug(f"AH scan failed for {symbol}: {e}")
            return None
    
    async def run_full_scan(self, universe: Set[str]) -> Dict[str, List[AfterHoursAlert]]:
        """
        Run after-hours scan on entire universe.
        
        Args:
            universe: Set of tickers to scan
            
        Returns:
            Dict with alerts categorized by severity
        """
        et = pytz.timezone('US/Eastern')
        now = datetime.now(et)
        
        logger.info(f"After-Hours Scanner: Starting scan of {len(universe)} tickers at {now.strftime('%H:%M ET')}")
        
        results = {
            "critical": [],
            "high": [],
            "watching": [],
        }
        
        scanned = 0
        alerts_found = 0
        
        for symbol in universe:
            try:
                alert = await self.scan_single(symbol)
                
                if alert and alert.is_bearish:
                    alerts_found += 1
                    severity = alert.severity.value
                    results[severity].append(alert)
                    
                    if alert.severity == AHAlertSeverity.CRITICAL:
                        logger.warning(
                            f"AH ALERT CRITICAL: {symbol} {alert.ah_change_pct:+.2f}% | "
                            f"Close: ${alert.close_price:.2f} -> AH: ${alert.ah_price:.2f}"
                        )
                    elif alert.severity == AHAlertSeverity.HIGH:
                        logger.info(
                            f"AH ALERT HIGH: {symbol} {alert.ah_change_pct:+.2f}% | "
                            f"Close: ${alert.close_price:.2f} -> AH: ${alert.ah_price:.2f}"
                        )
                
                scanned += 1
                
                # Rate limiting
                if scanned % 50 == 0:
                    await asyncio.sleep(0.5)
                    logger.info(f"AH Scanner: {scanned}/{len(universe)} scanned, {alerts_found} alerts")
                    
            except Exception as e:
                logger.debug(f"AH scan failed for {symbol}: {e}")
        
        # Sort by change magnitude
        for severity in results:
            results[severity].sort(key=lambda x: x.ah_change_pct)  # Most negative first
        
        logger.info(
            f"After-Hours Scanner: Complete - {scanned} scanned, {alerts_found} bearish alerts "
            f"(Critical: {len(results['critical'])}, High: {len(results['high'])}, "
            f"Watching: {len(results['watching'])})"
        )
        
        return results
    
    async def inject_to_dui(self, results: Dict[str, List[AfterHoursAlert]]) -> int:
        """
        Inject after-hours alerts into Dynamic Universe Injection.
        
        Args:
            results: Results from run_full_scan()
            
        Returns:
            Number of tickers injected
        """
        from putsengine.config import DynamicUniverseManager
        
        dui = DynamicUniverseManager()
        injected = 0
        
        # Inject critical alerts (>= 5% down)
        for alert in results.get("critical", []):
            dui.promote_from_liquidity(
                symbol=alert.symbol,
                score=0.60,  # High score for critical AH move
                signals=[
                    f"ah_drop_{abs(alert.ah_change_pct):.1f}pct",
                    "after_hours_critical"
                ]
            )
            injected += 1
            logger.warning(f"DUI: Injected CRITICAL AH alert {alert.symbol} ({alert.ah_change_pct:+.2f}%)")
        
        # Inject high alerts (>= 3% down)
        for alert in results.get("high", []):
            dui.promote_from_liquidity(
                symbol=alert.symbol,
                score=0.45,  # Medium score for high AH move
                signals=[
                    f"ah_drop_{abs(alert.ah_change_pct):.1f}pct",
                    "after_hours_high"
                ]
            )
            injected += 1
            logger.info(f"DUI: Injected HIGH AH alert {alert.symbol} ({alert.ah_change_pct:+.2f}%)")
        
        return injected


async def run_afterhours_scan(alpaca_client, universe: Set[str] = None) -> Dict:
    """
    Run after-hours scan.
    
    This should be called at:
    - 4:30 PM ET
    - 6:00 PM ET
    - 8:00 PM ET
    
    Args:
        alpaca_client: AlpacaClient instance
        universe: Set of tickers to scan (default: all tickers from config)
        
    Returns:
        Scan results with injected count
    """
    from putsengine.config import EngineConfig
    
    if universe is None:
        universe = set(EngineConfig.get_all_tickers())
    
    scanner = AfterHoursScanner(alpaca_client)
    
    # Run the scan
    results = await scanner.run_full_scan(universe)
    
    # Inject into DUI
    injected = await scanner.inject_to_dui(results)
    
    # Add summary
    results["summary"] = {
        "scan_time": datetime.now().isoformat(),
        "total_alerts": sum(len(v) for k, v in results.items() if k != "summary"),
        "injected_to_dui": injected,
        "critical_count": len(results.get("critical", [])),
        "high_count": len(results.get("high", [])),
        "watching_count": len(results.get("watching", [])),
    }
    
    return results
