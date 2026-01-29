"""
Earnings Contagion Alert System - ARCHITECT-4 FINAL

This is NOT a trading signal. This is WEATHER.

When a mega-cap reports earnings and drops significantly,
it triggers sector-wide liquidation. This system:

1. DETECTS mega-cap earnings misses (>5% drop after earnings)
2. ALERTS on sympathy names in the risk bucket
3. INJECTS sympathy names into DUI as WATCHING
4. NEVER boosts scores directly

The correct response to earnings contagion:
- Inject sympathy names into DUI as WATCHING (0.25-0.30)
- Tighten Liquidity / VWAP requirements
- Allow SMALL Class B probes only
- Wait for Gamma confirmation for Class A

This module treats earnings contagion as "weather" - a market condition
that affects opportunity, not a direct trade signal.
"""

from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from loguru import logger

from putsengine.config import EngineConfig


# Mega-caps whose earnings can trigger sector-wide contagion
CONTAGION_TRIGGERS = {
    "MSFT": {
        "name": "Microsoft",
        "sector": "enterprise_software",
        "sympathy": ["NOW", "TEAM", "TWLO", "WDAY", "CRM", "SNOW", "DDOG", "ZS", "OKTA", "NET"],
        "supply_chain": ["CLS", "SMCI", "DELL"],  # MSFT infrastructure plays
    },
    "AAPL": {
        "name": "Apple",
        "sector": "consumer_hardware",
        "sympathy": ["QCOM", "SWKS", "AVGO", "CRUS", "LSCC"],
        "supply_chain": ["TSM", "HON", "FOXF"],
    },
    "NVDA": {
        "name": "NVIDIA",
        "sector": "ai_semiconductors",
        "sympathy": ["AMD", "MU", "MRVL", "ARM", "SMCI", "DELL"],
        "supply_chain": ["TSM", "ASML", "KLAC", "LRCX", "AMAT"],
    },
    "GOOGL": {
        "name": "Google/Alphabet",
        "sector": "digital_advertising",
        "sympathy": ["META", "SNAP", "PINS", "TTD", "PUBM"],
        "supply_chain": [],
    },
    "AMZN": {
        "name": "Amazon",
        "sector": "ecommerce_cloud",
        "sympathy": ["SHOP", "ETSY", "W", "EBAY"],
        "supply_chain": ["AMZN cloud peers: DDOG, SNOW, NET"],
    },
    "META": {
        "name": "Meta",
        "sector": "social_media",
        "sympathy": ["SNAP", "PINS", "TTD", "PUBM", "MGNI"],
        "supply_chain": [],
    },
    "TSLA": {
        "name": "Tesla",
        "sector": "ev_auto",
        "sympathy": ["RIVN", "LCID", "NIO", "XPEV", "LI"],
        "supply_chain": ["ALB", "LAC", "LTHM", "MP"],
    },
}

# High-beta names that crash in ANY risk-off event
ALWAYS_CONTAGION = [
    "MSTR", "COIN",  # Bitcoin proxies
    "ARKK", "ARKF",  # Speculative ETFs
    "JOBY", "ACHR", "LILM",  # eVTOL
    "RIOT", "MARA", "CLSK",  # Crypto miners
]


class EarningsContagionAlert:
    """
    Earnings Contagion Alert System.
    
    This system detects when mega-cap earnings trigger
    sector-wide liquidation and alerts on at-risk names.
    
    IT DOES NOT CREATE TRADES. It creates AWARENESS.
    """
    
    def __init__(self):
        self.active_alerts: Dict[str, Dict] = {}
        self.alert_expiry_hours = 48  # Contagion effects last ~2 days
    
    def check_for_contagion(
        self, 
        symbol: str, 
        drop_pct: float,
        is_post_earnings: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Check if a mega-cap drop triggers contagion alert.
        
        Args:
            symbol: The ticker that dropped
            drop_pct: Percentage drop (negative number, e.g. -0.12 for -12%)
            is_post_earnings: Whether this is after an earnings report
            
        Returns:
            Contagion alert dict if triggered, None otherwise
        """
        # Must be a contagion trigger
        if symbol not in CONTAGION_TRIGGERS:
            return None
        
        # Must be a significant drop (>5%)
        if drop_pct > -0.05:  # Remember: drop_pct is negative
            return None
        
        # Earnings-related drops have higher contagion
        min_drop = -0.05 if is_post_earnings else -0.08
        if drop_pct > min_drop:
            return None
        
        trigger_info = CONTAGION_TRIGGERS[symbol]
        
        # Build alert
        alert = {
            "type": "EARNINGS_CONTAGION",
            "trigger_symbol": symbol,
            "trigger_name": trigger_info["name"],
            "trigger_drop_pct": drop_pct,
            "sector": trigger_info["sector"],
            "is_post_earnings": is_post_earnings,
            "timestamp": datetime.now(),
            "expires": datetime.now() + timedelta(hours=self.alert_expiry_hours),
            
            # Names at risk
            "sympathy_names": trigger_info["sympathy"],
            "supply_chain": trigger_info.get("supply_chain", []),
            "high_beta_always": ALWAYS_CONTAGION,
            
            # Combined list for DUI injection
            "all_at_risk": list(set(
                trigger_info["sympathy"] + 
                trigger_info.get("supply_chain", []) + 
                ALWAYS_CONTAGION
            )),
            
            # Guidance (NOT trading signals!)
            "guidance": {
                "action": "WATCH",
                "max_class": "B",  # Only Class B without Gamma
                "size_limit": "1-2 contracts",
                "require_gamma_for_class_a": True,
                "note": f"{symbol} earnings contagion - sympathy names at risk"
            }
        }
        
        # Store active alert
        self.active_alerts[symbol] = alert
        
        logger.warning(
            f"🚨 EARNINGS CONTAGION ALERT: {symbol} dropped {drop_pct*100:.1f}% "
            f"after earnings. {len(alert['all_at_risk'])} names at risk."
        )
        
        return alert
    
    def get_active_alerts(self) -> List[Dict]:
        """Get all currently active contagion alerts."""
        now = datetime.now()
        active = []
        
        for symbol, alert in list(self.active_alerts.items()):
            if alert["expires"] > now:
                active.append(alert)
            else:
                # Expired - remove
                del self.active_alerts[symbol]
                logger.info(f"Contagion alert for {symbol} expired")
        
        return active
    
    def is_name_at_risk(self, symbol: str) -> Optional[Dict]:
        """
        Check if a symbol is at risk due to active contagion.
        
        Returns the alert dict if at risk, None otherwise.
        """
        for alert in self.get_active_alerts():
            if symbol in alert["all_at_risk"]:
                return alert
        return None
    
    def get_dui_injection_candidates(self) -> List[Dict]:
        """
        Get candidates to inject into DUI from active contagion alerts.
        
        These should be injected as WATCHING with score 0.25-0.30.
        They require Gamma confirmation to become Class A.
        
        Returns:
            List of dicts with symbol and injection metadata
        """
        candidates = []
        
        for alert in self.get_active_alerts():
            trigger = alert["trigger_symbol"]
            drop = alert["trigger_drop_pct"]
            
            for symbol in alert["all_at_risk"]:
                # Skip if already in candidates
                if any(c["symbol"] == symbol for c in candidates):
                    continue
                
                # Determine injection score based on relationship
                if symbol in alert["sympathy_names"]:
                    score = 0.28  # Direct sympathy - higher score
                    reason = f"sympathy_sell_{trigger}"
                elif symbol in alert.get("supply_chain", []):
                    score = 0.25  # Supply chain - moderate
                    reason = f"supply_chain_{trigger}"
                else:
                    score = 0.22  # High-beta/general risk-off
                    reason = "high_beta_risk_off"
                
                candidates.append({
                    "symbol": symbol,
                    "score": score,
                    "reason": reason,
                    "source": "earnings_contagion",
                    "trigger": trigger,
                    "trigger_drop": drop,
                    "max_class": "B",  # WITHOUT Gamma confirmation
                    "requires_gamma_for_a": True,
                    "note": f"Contagion from {trigger} ({drop*100:.1f}%)"
                })
        
        if candidates:
            logger.info(
                f"Earnings contagion: {len(candidates)} candidates for DUI injection"
            )
        
        return candidates


# Global instance
_contagion_alert = None

def get_contagion_alert() -> EarningsContagionAlert:
    """Get the global contagion alert instance."""
    global _contagion_alert
    if _contagion_alert is None:
        _contagion_alert = EarningsContagionAlert()
    return _contagion_alert


def check_earnings_contagion(
    symbol: str, 
    drop_pct: float, 
    is_post_earnings: bool = False
) -> Optional[Dict]:
    """
    Convenience function to check for earnings contagion.
    
    Example:
        alert = check_earnings_contagion("MSFT", -0.12, is_post_earnings=True)
        if alert:
            # MSFT dropped 12% after earnings
            # alert["all_at_risk"] contains sympathy names to watch
    """
    return get_contagion_alert().check_for_contagion(symbol, drop_pct, is_post_earnings)


def get_contagion_dui_candidates() -> List[Dict]:
    """
    Get DUI injection candidates from active contagion alerts.
    
    Call this in the scheduler to inject sympathy names into DUI.
    """
    return get_contagion_alert().get_dui_injection_candidates()
