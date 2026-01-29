"""
Sector Correlation Scanner - Detect sector-wide weakness cascades

PURPOSE: When one name in a sector shows bearish signals, auto-scan and flag ALL peers.
         This would have caught MP → USAR → LAC cascade on Jan 28.

CORE PRINCIPLE (Institutional):
- High-beta sectors move TOGETHER
- One weak name = entire sector at risk
- Smart money exits sector leaders FIRST, then cascades to smaller names

SECTORS TRACKED:
- rare_earth: MP, USAR, LAC, ALB, LTHM, SQM (China exposure)
- evtol: JOBY, ACHR, LILM, EVTL (certification/funding risk)
- lithium: LAC, ALB, LTHM, SQM (EV demand risk)
- crypto_miners: RIOT, MARA, CIFR, CLSK (Bitcoin correlation)
- cloud_security: NET, CRWD, ZS, PANW (Tech sector sentiment)

DETECTION LOGIC:
1. Sector leader shows 2+ bearish signals
2. Auto-scan all sector peers
3. Apply sector_correlation_boost to peers
4. Inject peers into DUI for Gamma Drain confirmation
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Set, Tuple
import pytz
from loguru import logger
from dataclasses import dataclass
from enum import Enum


# Sector definitions with leaders and followers
CORRELATED_SECTORS = {
    "rare_earth": {
        "leaders": ["MP", "ALB"],  # Larger caps, move first
        "followers": ["USAR", "LAC", "LTHM", "SQM"],  # Smaller, follow
        "keywords": ["china", "rare earth", "tariff", "export"],
        "correlation_strength": 0.85,  # High correlation
    },
    "evtol": {
        "leaders": ["JOBY"],
        "followers": ["ACHR", "LILM", "EVTL"],
        "keywords": ["faa", "certification", "evtol", "air taxi"],
        "correlation_strength": 0.80,
    },
    "lithium": {
        "leaders": ["ALB", "SQM"],
        "followers": ["LAC", "LTHM"],
        "keywords": ["lithium", "ev demand", "battery"],
        "correlation_strength": 0.75,
    },
    "crypto_miners": {
        "leaders": ["MARA", "RIOT"],
        "followers": ["CIFR", "CLSK", "HUT", "BITF", "WULF"],
        "keywords": ["bitcoin", "crypto", "mining", "halving"],
        "correlation_strength": 0.90,
    },
    "cloud_security": {
        "leaders": ["NET", "CRWD"],
        "followers": ["ZS", "PANW", "FTNT", "OKTA"],
        "keywords": ["cybersecurity", "cloud", "breach", "hack"],
        "correlation_strength": 0.70,
    },
    "cloud_saas": {
        "leaders": ["MSFT", "NOW"],  # Largest caps, move first
        "followers": ["TEAM", "WDAY", "TWLO", "CRM", "SNOW", "DDOG"],
        "keywords": ["enterprise software", "saas", "cloud", "subscription"],
        "correlation_strength": 0.85,  # High correlation - earnings contagion
    },
    "nuclear_uranium": {
        "leaders": ["CCJ", "UUUU"],
        "followers": ["LEU", "DNN", "UEC", "URG", "SMR", "OKLO"],
        "keywords": ["uranium", "nuclear", "energy", "reactor"],
        "correlation_strength": 0.80,
    },
    "china_adr": {
        "leaders": ["BABA", "JD", "PDD"],
        "followers": ["BIDU", "NIO", "XPEV", "LI", "BILI"],
        "keywords": ["china", "adr", "delisting", "audit"],
        "correlation_strength": 0.85,
    },
    "travel_airlines": {
        "leaders": ["DAL", "UAL"],
        "followers": ["AAL", "LUV", "JBLU", "CCL", "RCL"],
        "keywords": ["airline", "travel", "fuel", "demand"],
        "correlation_strength": 0.75,
    },
}


@dataclass
class SectorAlert:
    """Alert for sector-wide weakness detection."""
    sector: str
    leader_symbol: str
    leader_signals: List[str]
    leader_score: float
    affected_peers: List[str]
    correlation_strength: float
    alert_time: str
    
    @property
    def severity(self) -> str:
        if self.leader_score >= 0.50:
            return "CRITICAL"
        elif self.leader_score >= 0.35:
            return "HIGH"
        else:
            return "MEDIUM"


class SectorCorrelationScanner:
    """
    Scans for sector-wide weakness patterns.
    
    This scanner would have caught:
    - MP weakness → auto-flag USAR, LAC
    - JOBY weakness → auto-flag ACHR, LILM, EVTL
    
    INSTITUTIONAL LOGIC:
    When a sector leader shows distribution signals:
    1. All followers are at risk
    2. Apply correlation boost to followers
    3. Inject into DUI for confirmation
    """
    
    # Minimum signals on leader to trigger sector alert
    MIN_LEADER_SIGNALS = 2
    
    # Score boost for correlated peers
    BASE_CORRELATION_BOOST = 0.10
    
    def __init__(self, alpaca_client, uw_client):
        self.alpaca_client = alpaca_client
        self.uw_client = uw_client
        self._alerts: Dict[str, SectorAlert] = {}
    
    def get_sector_for_symbol(self, symbol: str) -> Optional[str]:
        """Get the sector a symbol belongs to."""
        for sector, config in CORRELATED_SECTORS.items():
            if symbol in config["leaders"] or symbol in config["followers"]:
                return sector
        return None
    
    def get_sector_peers(self, symbol: str) -> List[str]:
        """Get all peers in the same sector (excluding self)."""
        sector = self.get_sector_for_symbol(symbol)
        if not sector:
            return []
        
        config = CORRELATED_SECTORS[sector]
        all_in_sector = config["leaders"] + config["followers"]
        return [s for s in all_in_sector if s != symbol]
    
    def is_sector_leader(self, symbol: str) -> bool:
        """Check if symbol is a sector leader."""
        for config in CORRELATED_SECTORS.values():
            if symbol in config["leaders"]:
                return True
        return False
    
    async def check_sector_cascade(
        self,
        leader_symbol: str,
        leader_signals: List[str],
        leader_score: float
    ) -> Optional[SectorAlert]:
        """
        Check if a leader's weakness should trigger sector-wide alert.
        
        Args:
            leader_symbol: The symbol showing signals
            leader_signals: List of bearish signals detected
            leader_score: Current score
            
        Returns:
            SectorAlert if cascade detected, None otherwise
        """
        # Must have minimum signals
        if len(leader_signals) < self.MIN_LEADER_SIGNALS:
            return None
        
        # Get sector
        sector = self.get_sector_for_symbol(leader_symbol)
        if not sector:
            return None
        
        config = CORRELATED_SECTORS[sector]
        
        # Leader check - only leaders can trigger cascade
        if leader_symbol not in config["leaders"]:
            return None
        
        # Get followers to alert
        followers = config["followers"]
        
        # Create alert
        alert = SectorAlert(
            sector=sector,
            leader_symbol=leader_symbol,
            leader_signals=leader_signals,
            leader_score=leader_score,
            affected_peers=followers,
            correlation_strength=config["correlation_strength"],
            alert_time=datetime.now().isoformat()
        )
        
        logger.warning(
            f"SECTOR CASCADE DETECTED: {sector.upper()} | "
            f"Leader: {leader_symbol} (score {leader_score:.2f}, {len(leader_signals)} signals) | "
            f"Affected: {', '.join(followers)}"
        )
        
        return alert
    
    async def inject_peers_to_dui(self, alert: SectorAlert) -> int:
        """
        Inject affected peers into Dynamic Universe Injection.
        
        Args:
            alert: SectorAlert with leader and peer info
            
        Returns:
            Number of peers injected
        """
        from putsengine.config import DynamicUniverseManager
        
        dui = DynamicUniverseManager()
        injected = 0
        
        # Calculate boost based on correlation strength
        boost = self.BASE_CORRELATION_BOOST * alert.correlation_strength
        
        for peer in alert.affected_peers:
            # Calculate peer score = leader_score * correlation * 0.8
            peer_score = alert.leader_score * alert.correlation_strength * 0.8
            peer_score = max(0.30, min(peer_score + boost, 0.50))  # Clamp to 0.30-0.50
            
            dui.promote_from_distribution(
                symbol=peer,
                score=peer_score,
                signals=[
                    "sector_correlation",
                    f"leader_{alert.leader_symbol}_weak",
                    f"sector_{alert.sector}"
                ]
            )
            injected += 1
            
            logger.info(
                f"DUI: Injected {peer} via sector correlation | "
                f"Leader: {alert.leader_symbol} | Score: {peer_score:.2f}"
            )
        
        return injected
    
    async def run_sector_scan(self, candidates: Dict[str, Dict]) -> Dict:
        """
        Run sector correlation scan on current candidates.
        
        Args:
            candidates: Dict of {symbol: {score, signals}} from main scan
            
        Returns:
            Dict with sector alerts and injection count
        """
        et = pytz.timezone('US/Eastern')
        now = datetime.now(et)
        
        logger.info(f"Sector Correlation Scanner: Starting at {now.strftime('%H:%M ET')}")
        
        alerts = []
        total_injected = 0
        
        # Check each candidate for sector cascade
        for symbol, data in candidates.items():
            score = data.get("score", 0)
            signals = data.get("signals", [])
            
            # Only check if score is meaningful
            if score < 0.25:
                continue
            
            # Check for cascade
            alert = await self.check_sector_cascade(symbol, signals, score)
            
            if alert:
                alerts.append(alert)
                injected = await self.inject_peers_to_dui(alert)
                total_injected += injected
        
        logger.info(
            f"Sector Correlation Scanner: Complete | "
            f"Alerts: {len(alerts)} | Peers Injected: {total_injected}"
        )
        
        return {
            "alerts": alerts,
            "injected_count": total_injected,
            "scan_time": now.isoformat()
        }


async def run_sector_correlation_scan(candidates: Dict[str, Dict]) -> Dict:
    """
    Run sector correlation scan on candidates.
    
    Should be called after main scan to detect sector cascades.
    
    Args:
        candidates: Dict of {symbol: {score, signals}}
        
    Returns:
        Scan results with alerts and injections
    """
    scanner = SectorCorrelationScanner(None, None)  # Clients not needed for basic scan
    return await scanner.run_sector_scan(candidates)


# Export sector groups for use in config
SECTOR_GROUPS = {
    sector: config["leaders"] + config["followers"]
    for sector, config in CORRELATED_SECTORS.items()
}
