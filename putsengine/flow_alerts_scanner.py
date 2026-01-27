"""
Market-Wide Flow Alerts Scanner

PURPOSE: Catch unusual put activity on ANY ticker, not just our universe.

PROBLEM: We only scan put flow for 175 tickers. UNH massive put buying was invisible.

SOLUTION: Use Unusual Whales /api/option-trades/flow-alerts for market-wide alerts.
         Any ticker with >$1M put premium gets auto-injected into DUI.

API ENDPOINT: /api/option-trades/flow-alerts
- Returns unusual options activity across ALL tickers
- Includes put sweeps, block trades, unusual premium
- Limited API calls (use wisely per budget)

SCAN FREQUENCY:
- Every 30 minutes during market hours
- Extra scan at 9:35 AM (opening flow)
- Extra scan at 3:30 PM (closing flow)
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
import pytz
from loguru import logger


class FlowAlertsScanner:
    """
    Market-wide unusual flow alerts scanner.
    
    Uses Unusual Whales global flow alerts to catch puts on ANY ticker.
    """
    
    # Thresholds for different alert levels
    CRITICAL_PREMIUM = 5_000_000     # $5M+ = CRITICAL
    CLASS_B_PREMIUM = 1_000_000      # $1M+ = CLASS B
    WATCHING_PREMIUM = 500_000       # $500K+ = WATCHING
    
    # Only care about bearish flow
    BEARISH_SENTIMENTS = {"BEARISH", "VERY BEARISH", "EXTREMELY BEARISH"}
    
    def __init__(self, uw_client):
        """
        Initialize flow alerts scanner.
        
        Args:
            uw_client: UnusualWhalesClient instance
        """
        self.uw_client = uw_client
        self._last_scan_time: Optional[datetime] = None
        
    async def scan_flow_alerts(self, limit: int = 100) -> Dict[str, List[Dict]]:
        """
        Scan market-wide flow alerts for unusual put activity.
        
        Returns:
            Dict with categories:
            - critical: Premium >= $5M
            - class_b: Premium >= $1M
            - watching: Premium >= $500K
        """
        et = pytz.timezone('US/Eastern')
        now = datetime.now(et)
        
        logger.info(f"Flow Alerts Scanner: Starting scan at {now.strftime('%H:%M ET')}")
        
        results = {
            "critical": [],
            "class_b": [],
            "watching": [],
        }
        
        try:
            # Get global flow alerts from UW
            alerts = await self.uw_client.get_global_flow_alerts(limit=limit)
            
            if not alerts:
                logger.warning("Flow Alerts Scanner: No alerts returned from UW API")
                return results
            
            # Filter for bearish/put activity
            for alert in alerts:
                # Skip if not bearish
                sentiment = alert.get("sentiment", "").upper()
                if sentiment not in self.BEARISH_SENTIMENTS:
                    continue
                
                # Skip if not a put
                option_type = alert.get("option_type", "").upper()
                if option_type != "PUT" and "PUT" not in alert.get("description", "").upper():
                    continue
                
                # Get premium
                premium = float(alert.get("premium", 0) or 0)
                if premium < self.WATCHING_PREMIUM:
                    continue
                
                # Build alert info
                symbol = alert.get("ticker") or alert.get("symbol")
                if not symbol:
                    continue
                
                alert_info = {
                    "symbol": symbol,
                    "premium": premium,
                    "sentiment": sentiment,
                    "option_type": option_type,
                    "strike": alert.get("strike"),
                    "expiry": alert.get("expiry") or alert.get("expiration"),
                    "volume": alert.get("volume"),
                    "open_interest": alert.get("open_interest"),
                    "description": alert.get("description", "")[:200],
                    "scan_time": now.isoformat(),
                }
                
                # Categorize by premium
                if premium >= self.CRITICAL_PREMIUM:
                    results["critical"].append(alert_info)
                    logger.warning(
                        f"Flow Alert: CRITICAL PUT - {symbol} ${premium/1e6:.1f}M premium"
                    )
                elif premium >= self.CLASS_B_PREMIUM:
                    results["class_b"].append(alert_info)
                    logger.info(
                        f"Flow Alert: CLASS B PUT - {symbol} ${premium/1e6:.1f}M premium"
                    )
                else:
                    results["watching"].append(alert_info)
            
            # Sort by premium
            for category in results:
                results[category].sort(key=lambda x: x["premium"], reverse=True)
            
            self._last_scan_time = now
            
            # Summary
            total = sum(len(v) for v in results.values())
            logger.info(
                f"Flow Alerts Scanner: {total} bearish alerts found "
                f"(Critical: {len(results['critical'])}, Class B: {len(results['class_b'])}, "
                f"Watching: {len(results['watching'])})"
            )
            
        except Exception as e:
            logger.error(f"Flow Alerts Scanner failed: {e}")
        
        return results
    
    async def inject_alerts_to_dui(self, alert_results: Dict[str, List[Dict]]) -> int:
        """
        Inject significant flow alerts into Dynamic Universe Injection (DUI).
        
        Args:
            alert_results: Results from scan_flow_alerts()
            
        Returns:
            Number of tickers injected
        """
        from putsengine.config import DynamicUniverseManager
        
        dui = DynamicUniverseManager()
        injected = 0
        seen_symbols = set()  # Avoid duplicates
        
        # Inject critical alerts with high score
        for alert in alert_results.get("critical", []):
            symbol = alert["symbol"]
            if symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)
            
            dui.promote_from_distribution(
                symbol=symbol,
                score=0.55,  # High score for critical flow
                signals=[
                    "critical_put_flow",
                    f"premium_{alert['premium']/1e6:.0f}M",
                    alert["sentiment"].lower().replace(" ", "_")
                ]
            )
            injected += 1
            logger.warning(f"DUI: Injected CRITICAL flow {symbol} (${alert['premium']/1e6:.1f}M put premium)")
        
        # Inject class B alerts
        for alert in alert_results.get("class_b", []):
            symbol = alert["symbol"]
            if symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)
            
            dui.promote_from_distribution(
                symbol=symbol,
                score=0.40,
                signals=[
                    "large_put_flow",
                    f"premium_{alert['premium']/1e6:.1f}M",
                    alert["sentiment"].lower().replace(" ", "_")
                ]
            )
            injected += 1
        
        # Inject watching alerts
        for alert in alert_results.get("watching", []):
            symbol = alert["symbol"]
            if symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)
            
            dui.promote_from_liquidity(
                symbol=symbol,
                score=0.32,
                signals=[
                    "put_flow_watch",
                    f"premium_{alert['premium']/1e3:.0f}K"
                ]
            )
            injected += 1
        
        return injected


async def run_flow_alerts_scan(uw_client) -> Dict:
    """
    Run market-wide flow alerts scan and inject results into DUI.
    
    This should be called:
    - Every 30 minutes during market hours
    - Extra at 9:35 AM (opening flow)
    - Extra at 3:30 PM (closing flow)
    
    Returns:
        Scan results with injected count
    """
    scanner = FlowAlertsScanner(uw_client)
    
    # Run the scan
    results = await scanner.scan_flow_alerts()
    
    # Inject into DUI
    injected = await scanner.inject_alerts_to_dui(results)
    
    # Add summary
    results["summary"] = {
        "scan_time": datetime.now().isoformat(),
        "total_alerts": sum(len(v) for k, v in results.items() if k != "summary"),
        "injected_to_dui": injected,
        "critical_count": len(results.get("critical", [])),
        "class_b_count": len(results.get("class_b", [])),
        "watching_count": len(results.get("watching", [])),
    }
    
    return results
