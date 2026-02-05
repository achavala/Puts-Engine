"""
Zero-Hour Gap Scanner - Day 0 Execution Confirmation

ARCHITECT-4 VALIDATED (Feb 1, 2026):
=====================================
This is the HIGHEST ROI remaining addition.

THE PROBLEM:
Institutions often:
1. Accumulate footprints on Day -1 (captured by EWS)
2. Execute the damage via pre-market gaps on Day 0

THE SOLUTION:
Run at 09:15 AM ET, ONLY on IPI ≥ 0.60 names.
Check if the "vacuum is open" by detecting:
- Pre-market gap down vs prior close
- Spread behavior degradation
- Bid collapse in pre-market

This is CONFIRMATION, not a new signal.

CORRECT INTERPRETATION:
- IPI ≥ 0.60 AND gap down → "Vacuum is open" → ACT
- IPI ≥ 0.60 AND gap up → "Pressure absorbed" → WAIT
- IPI < 0.60 → Not checked (not enough institutional pressure)

SCHEDULE:
- Run at 09:15 AM ET (15 minutes before market open)
- Only checks symbols with IPI ≥ 0.60 from last EWS scan
"""

import asyncio
import json
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import pytz
from loguru import logger


EST = pytz.timezone("US/Eastern")


class ZeroHourVerdict(Enum):
    """Zero-hour confirmation verdicts."""
    VACUUM_OPEN = "vacuum_open"       # IPI confirmed + gap down → ACT
    PRESSURE_ABSORBED = "absorbed"     # IPI but gap up → WAIT
    SPREAD_COLLAPSE = "spread_collapse"  # Severe spread widening → URGENT
    NO_CONFIRMATION = "no_confirmation"  # IPI but neutral gap → MONITOR


@dataclass
class ZeroHourAlert:
    """A zero-hour confirmation alert."""
    symbol: str
    verdict: ZeroHourVerdict
    ipi: float
    prior_close: float
    premarket_bid: float
    premarket_ask: float
    gap_pct: float
    spread_pct: float
    timestamp: datetime
    recommendation: str = ""
    
    @property
    def is_actionable(self) -> bool:
        """True if this alert suggests immediate action."""
        return self.verdict in [ZeroHourVerdict.VACUUM_OPEN, ZeroHourVerdict.SPREAD_COLLAPSE]


# File paths
EARLY_WARNING_FILE = Path(__file__).parent.parent / "early_warning_alerts.json"
ZERO_HOUR_FILE = Path(__file__).parent.parent / "zero_hour_alerts.json"


class ZeroHourScanner:
    """
    Scans EWS high-pressure names at 9:15 AM ET for gap confirmation.
    
    This is the Day 0 execution detector that confirms whether
    institutional pressure detected on Day -1 has materialized.
    """
    
    # Thresholds
    MIN_IPI_FOR_CHECK = 0.60  # Only check names with IPI ≥ 0.60
    GAP_DOWN_THRESHOLD = -0.01  # -1% gap = bearish confirmation
    GAP_UP_THRESHOLD = 0.01    # +1% gap = pressure absorbed
    SPREAD_WARNING_PCT = 0.5   # 0.5% spread = concerning
    SPREAD_CRITICAL_PCT = 1.0  # 1.0% spread = critical
    
    def __init__(self, price_client):
        """
        Initialize zero-hour scanner.
        
        Args:
            price_client: PolygonClient (preferred) or AlpacaClient for price data
        """
        self.price_client = price_client
    
    def load_ews_alerts(self) -> Dict[str, Dict]:
        """
        Load high-pressure symbols from last EWS scan.
        
        Returns:
            Dict of symbol -> alert data for IPI ≥ 0.60
        """
        if not EARLY_WARNING_FILE.exists():
            logger.warning("No EWS alerts file found")
            return {}
        
        try:
            with open(EARLY_WARNING_FILE, 'r') as f:
                data = json.load(f)
            
            alerts = data.get("alerts", {})
            
            # Filter to IPI ≥ 0.60
            high_pressure = {
                symbol: alert
                for symbol, alert in alerts.items()
                if alert.get("ipi", 0) >= self.MIN_IPI_FOR_CHECK
            }
            
            logger.info(f"Loaded {len(high_pressure)} high-pressure symbols (IPI ≥ {self.MIN_IPI_FOR_CHECK})")
            return high_pressure
            
        except Exception as e:
            logger.error(f"Error loading EWS alerts: {e}")
            return {}
    
    async def scan_symbol(self, symbol: str, ipi: float) -> Optional[ZeroHourAlert]:
        """
        Scan a single symbol for zero-hour confirmation.
        
        Args:
            symbol: Stock ticker
            ipi: The IPI from EWS
            
        Returns:
            ZeroHourAlert if actionable, None otherwise
        """
        try:
            # Get prior close
            bars = await self.price_client.get_daily_bars(
                symbol=symbol,
                start=date.today() - timedelta(days=5),
                end=date.today()
            )
            
            if not bars or len(bars) < 1:
                return None
            
            prior_close = bars[-1].close
            
            # Get pre-market quote
            quote = await self.price_client.get_latest_quote(symbol)
            
            if not quote or "quote" not in quote:
                return None
            
            q = quote["quote"]
            bid = float(q.get("bp", 0))
            ask = float(q.get("ap", 0))
            
            if bid == 0 or ask == 0 or prior_close == 0:
                return None
            
            # Calculate metrics
            midpoint = (bid + ask) / 2
            gap_pct = (midpoint - prior_close) / prior_close
            spread_pct = (ask - bid) / bid * 100
            
            # Determine verdict
            verdict = self._determine_verdict(gap_pct, spread_pct, ipi)
            
            # Generate recommendation
            recommendation = self._generate_recommendation(verdict, symbol, ipi, gap_pct, spread_pct)
            
            alert = ZeroHourAlert(
                symbol=symbol,
                verdict=verdict,
                ipi=ipi,
                prior_close=prior_close,
                premarket_bid=bid,
                premarket_ask=ask,
                gap_pct=gap_pct * 100,  # Convert to percentage
                spread_pct=spread_pct,
                timestamp=datetime.now(EST),
                recommendation=recommendation,
            )
            
            if alert.is_actionable:
                logger.warning(
                    f"🚨 ZERO-HOUR ALERT: {symbol} - {verdict.value.upper()} | "
                    f"IPI={ipi:.2f} | Gap={gap_pct*100:+.2f}% | Spread={spread_pct:.2f}%"
                )
            
            return alert
            
        except Exception as e:
            logger.debug(f"Zero-hour scan failed for {symbol}: {e}")
            return None
    
    def _determine_verdict(self, gap_pct: float, spread_pct: float, ipi: float) -> ZeroHourVerdict:
        """
        Determine the zero-hour verdict based on gap and spread.
        
        The key insight:
        - IPI ≥ 0.60 means institutional pressure detected on Day -1
        - Gap down on Day 0 = pressure is materializing ("vacuum is open")
        - Gap up on Day 0 = pressure was absorbed (wait)
        - Spread collapse = market makers confirming weakness (urgent)
        """
        # Check for spread collapse first (most urgent)
        if spread_pct >= self.SPREAD_CRITICAL_PCT:
            return ZeroHourVerdict.SPREAD_COLLAPSE
        
        # Check gap direction
        if gap_pct <= self.GAP_DOWN_THRESHOLD:
            # Gap down confirms institutional pressure
            return ZeroHourVerdict.VACUUM_OPEN
        elif gap_pct >= self.GAP_UP_THRESHOLD:
            # Gap up suggests pressure was absorbed
            return ZeroHourVerdict.PRESSURE_ABSORBED
        else:
            # Neutral gap - need more information
            return ZeroHourVerdict.NO_CONFIRMATION
    
    def _generate_recommendation(
        self, 
        verdict: ZeroHourVerdict, 
        symbol: str, 
        ipi: float, 
        gap_pct: float, 
        spread_pct: float
    ) -> str:
        """Generate actionable recommendation based on verdict."""
        
        if verdict == ZeroHourVerdict.VACUUM_OPEN:
            return (
                f"🔴 VACUUM OPEN: {symbol} institutional pressure (IPI={ipi:.2f}) + gap down ({gap_pct*100:+.2f}%). "
                f"Day 0 execution in progress. Consider put entry at open or first bounce."
            )
        elif verdict == ZeroHourVerdict.SPREAD_COLLAPSE:
            return (
                f"🔴 SPREAD COLLAPSE: {symbol} spread at {spread_pct:.2f}% (critical). "
                f"Market makers confirming weakness. High urgency."
            )
        elif verdict == ZeroHourVerdict.PRESSURE_ABSORBED:
            return (
                f"🟡 PRESSURE ABSORBED: {symbol} had IPI={ipi:.2f} but gapped up ({gap_pct*100:+.2f}%). "
                f"Wait for re-entry. Pressure may build again."
            )
        else:
            return (
                f"👀 MONITORING: {symbol} IPI={ipi:.2f} but neutral gap ({gap_pct*100:+.2f}%). "
                f"No confirmation yet. Continue watching."
            )
    
    async def run_full_scan(self) -> Dict[str, Any]:
        """
        Run full zero-hour scan on all high-pressure EWS names.
        
        Returns:
            Dict with scan results
        """
        now_et = datetime.now(EST)
        logger.info("=" * 60)
        logger.info("ZERO-HOUR GAP SCANNER (Day 0 Execution Confirmation)")
        logger.info(f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}")
        logger.info("=" * 60)
        
        # Load high-pressure names from EWS
        ews_alerts = self.load_ews_alerts()
        
        if not ews_alerts:
            logger.info("No high-pressure names to check (IPI ≥ 0.60)")
            return {"alerts": [], "summary": {"checked": 0, "actionable": 0}}
        
        logger.info(f"Checking {len(ews_alerts)} high-pressure names...")
        
        # Scan each symbol
        alerts = []
        for symbol, ews_data in ews_alerts.items():
            ipi = ews_data.get("ipi", 0)
            alert = await self.scan_symbol(symbol, ipi)
            if alert:
                alerts.append(alert)
            await asyncio.sleep(0.1)  # Rate limiting
        
        # Separate by verdict
        vacuum_alerts = [a for a in alerts if a.verdict == ZeroHourVerdict.VACUUM_OPEN]
        collapse_alerts = [a for a in alerts if a.verdict == ZeroHourVerdict.SPREAD_COLLAPSE]
        absorbed_alerts = [a for a in alerts if a.verdict == ZeroHourVerdict.PRESSURE_ABSORBED]
        monitoring_alerts = [a for a in alerts if a.verdict == ZeroHourVerdict.NO_CONFIRMATION]
        
        # Log summary
        logger.info(f"Zero-Hour Scan Complete:")
        logger.info(f"  🔴 VACUUM OPEN: {len(vacuum_alerts)}")
        logger.info(f"  🔴 SPREAD COLLAPSE: {len(collapse_alerts)}")
        logger.info(f"  🟡 PRESSURE ABSORBED: {len(absorbed_alerts)}")
        logger.info(f"  👀 MONITORING: {len(monitoring_alerts)}")
        
        # Log actionable alerts
        actionable = vacuum_alerts + collapse_alerts
        for alert in actionable:
            logger.warning(f"  → {alert.symbol}: {alert.recommendation}")
        
        # Save results
        results = {
            "timestamp": now_et.isoformat(),
            "summary": {
                "checked": len(alerts),
                "vacuum_open": len(vacuum_alerts),
                "spread_collapse": len(collapse_alerts),
                "pressure_absorbed": len(absorbed_alerts),
                "monitoring": len(monitoring_alerts),
                "actionable": len(actionable),
            },
            "alerts": {
                alert.symbol: {
                    "verdict": alert.verdict.value,
                    "ipi": alert.ipi,
                    "gap_pct": alert.gap_pct,
                    "spread_pct": alert.spread_pct,
                    "prior_close": alert.prior_close,
                    "premarket_bid": alert.premarket_bid,
                    "premarket_ask": alert.premarket_ask,
                    "recommendation": alert.recommendation,
                    "is_actionable": alert.is_actionable,
                }
                for alert in alerts
            }
        }
        
        # Save to file
        try:
            with open(ZERO_HOUR_FILE, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            logger.info(f"Zero-hour alerts saved to {ZERO_HOUR_FILE}")
        except Exception as e:
            logger.warning(f"Could not save zero-hour alerts: {e}")
        
        logger.info("=" * 60)
        
        return results


async def run_zero_hour_scan(price_client) -> Dict[str, Any]:
    """
    Run zero-hour scan.
    
    Args:
        price_client: PolygonClient (preferred) or AlpacaClient for price data
        
    Returns:
        Dict with scan results
    """
    scanner = ZeroHourScanner(price_client)
    return await scanner.run_full_scan()


def get_zero_hour_summary() -> Dict:
    """
    Get summary of latest zero-hour alerts.
    
    Returns:
        Dict with summary data
    """
    if not ZERO_HOUR_FILE.exists():
        return {}
    
    try:
        with open(ZERO_HOUR_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}
