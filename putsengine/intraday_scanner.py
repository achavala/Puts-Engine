"""
Intraday Big Mover Scanner - REAL-TIME Same-Day Detection

CREATED FEB 2, 2026

PURPOSE:
Detect stocks that are dropping significantly DURING the trading day.
This scanner uses REAL-TIME quotes, not historical daily bars.

CRITICAL FIX:
Previous scanners used get_daily_bars() which only has data through previous close.
This scanner uses get_current_price() and get_intraday_change() for LIVE data.

DETECTION THRESHOLDS:
- CRITICAL: > 10% intraday drop
- HIGH: 5-10% intraday drop
- MEDIUM: 3-5% intraday drop
"""

import asyncio
from datetime import datetime, date
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from loguru import logger

from putsengine.config import Settings, get_settings
from putsengine.clients.polygon_client import PolygonClient


@dataclass
class IntradayAlert:
    """Alert for intraday big mover."""
    symbol: str
    current_price: float
    prev_close: float
    change_pct: float
    change_abs: float
    severity: str  # CRITICAL, HIGH, MEDIUM
    detected_at: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "current_price": self.current_price,
            "prev_close": self.prev_close,
            "change_pct": round(self.change_pct, 2),
            "change_abs": round(self.change_abs, 2),
            "severity": self.severity,
            "detected_at": self.detected_at.isoformat(),
        }


class IntradayScanner:
    """
    Scanner for detecting intraday big movers using REAL-TIME data.
    """
    
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.polygon = PolygonClient(self.settings)  # Using Polygon/Massive for real-time data
        
        # Detection thresholds
        self.critical_threshold = -10.0  # > 10% drop
        self.high_threshold = -5.0       # 5-10% drop
        self.medium_threshold = -3.0     # 3-5% drop
    
    async def close(self):
        """Close client connections."""
        await self.polygon.close()
    
    async def scan_symbol(self, symbol: str) -> Optional[IntradayAlert]:
        """
        Scan a single symbol for intraday movement.
        
        Returns IntradayAlert if significant drop detected, None otherwise.
        """
        try:
            change_pct = await self.polygon.get_intraday_change(symbol)
            
            if change_pct is None:
                return None
            
            # Only interested in significant drops
            if change_pct >= self.medium_threshold:
                return None
            
            # Determine severity
            if change_pct <= self.critical_threshold:
                severity = "CRITICAL"
            elif change_pct <= self.high_threshold:
                severity = "HIGH"
            else:
                severity = "MEDIUM"
            
            return IntradayAlert(
                symbol=symbol,
                current_price=change["current_price"],
                prev_close=change["prev_close"],
                change_pct=change_pct,
                change_abs=change["change_abs"],
                severity=severity,
                detected_at=datetime.now()
            )
            
        except Exception as e:
            logger.debug(f"Error scanning {symbol}: {e}")
            return None
    
    async def scan_universe(self, symbols: List[str]) -> List[IntradayAlert]:
        """
        Scan all symbols for intraday big movers.
        
        Returns list of alerts sorted by severity (CRITICAL first) then by drop %.
        """
        logger.info(f"Starting intraday scan of {len(symbols)} symbols...")
        
        alerts = []
        
        # Process in batches to avoid overwhelming API
        batch_size = 50
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            
            # Scan batch concurrently
            tasks = [self.scan_symbol(sym) for sym in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, IntradayAlert):
                    alerts.append(result)
            
            # Small delay between batches
            if i + batch_size < len(symbols):
                await asyncio.sleep(1)
        
        # Sort by severity then by change %
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
        alerts.sort(key=lambda x: (severity_order.get(x.severity, 3), x.change_pct))
        
        logger.info(f"Intraday scan complete: {len(alerts)} alerts found")
        return alerts


async def run_intraday_scan(symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Run the intraday scanner on given symbols or full universe.
    
    Returns list of alert dictionaries.
    """
    settings = get_settings()
    scanner = IntradayScanner(settings)
    
    try:
        # Get universe if not provided
        if symbols is None:
            from putsengine.config import Settings
            s = Settings()
            symbols = []
            for sector, tickers in s.UNIVERSE_SECTORS.items():
                symbols.extend(tickers)
            symbols = list(set(symbols))
        
        alerts = await scanner.scan_universe(symbols)
        
        # Log significant finds
        critical = [a for a in alerts if a.severity == "CRITICAL"]
        high = [a for a in alerts if a.severity == "HIGH"]
        
        if critical:
            logger.warning(f"🚨 CRITICAL INTRADAY DROPS: {[a.symbol for a in critical]}")
        if high:
            logger.warning(f"⚠️ HIGH INTRADAY DROPS: {[a.symbol for a in high]}")
        
        return [a.to_dict() for a in alerts]
        
    finally:
        await scanner.close()


# For direct execution
if __name__ == "__main__":
    import json
    
    async def main():
        print("=" * 60)
        print("INTRADAY BIG MOVER SCANNER")
        print("=" * 60)
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}")
        print()
        
        alerts = await run_intraday_scan()
        
        print(f"Found {len(alerts)} intraday drops:")
        print()
        
        for alert in alerts:
            print(f"{alert['severity']:8} | {alert['symbol']:6} | "
                  f"${alert['current_price']:.2f} | {alert['change_pct']:+.2f}%")
        
        # Save to file
        with open("intraday_alerts.json", "w") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "alerts": alerts
            }, f, indent=2)
        
        print()
        print(f"Saved to intraday_alerts.json")
    
    asyncio.run(main())
