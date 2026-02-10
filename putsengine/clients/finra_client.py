"""
FINRA Short Volume Data Client.

Per Final Architect Report:
"You don't need Ortex. FINRA Daily Short Volume (free) is sufficient."

Uses FINRA's free daily short sale volume data to detect:
- Whether selling is new shorts or long liquidation
- Rising short volume + falling price = institutional conviction
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
import aiohttp
from loguru import logger

from putsengine.config import Settings
from putsengine.models import ShortInterestData


class FINRAClient:
    """
    Client for FINRA Short Volume Data.
    
    Data source: https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data
    
    This is FREE data that provides daily short sale volume for all securities.
    """
    
    # FINRA provides short volume via their data browser
    # We'll use a simplified approach that can be enhanced with actual FINRA API
    BASE_URL = "https://cdn.finra.org/equity/regsho/daily"
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_loop_id: Optional[int] = None  # Track which event loop owns the session
        self._cache: Dict[str, Dict[str, Any]] = {}  # Cache short data
        self._cache_date: Optional[date] = None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session, auto-healing on event loop change."""
        try:
            current_loop_id = id(asyncio.get_running_loop())
        except RuntimeError:
            current_loop_id = None
        
        needs_new = (
            self._session is None
            or self._session.closed
            or self._session_loop_id != current_loop_id
        )
        
        if needs_new:
            if self._session is not None:
                try:
                    if not self._session.closed:
                        await self._session.close()
                except Exception:
                    pass
                self._session = None
            
            self._session = aiohttp.ClientSession()
            self._session_loop_id = current_loop_id
        
        return self._session
        
    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            try:
                await self._session.close()
            except Exception:
                pass
        self._session = None
        self._session_loop_id = None

    async def get_short_volume(
        self,
        symbol: str,
        lookback_days: int = 5
    ) -> ShortInterestData:
        """
        Get short volume data for a symbol.
        
        Per Architect:
        - Rising short volume + falling price = institutional conviction
        - Use as liquidity confirmation
        
        Args:
            symbol: Stock ticker
            lookback_days: Days to analyze for trend
            
        Returns:
            ShortInterestData with short volume metrics
        """
        result = ShortInterestData(
            symbol=symbol,
            timestamp=datetime.now()
        )
        
        try:
            # For now, we'll use a heuristic approach based on available data
            # In production, this would fetch actual FINRA data files
            
            # Try to get short interest from Unusual Whales or calculate from flow
            # This is a placeholder that can be enhanced with actual FINRA data
            
            logger.debug(f"Checking short volume for {symbol}")
            
            # Note: Actual FINRA data requires parsing their daily files
            # Format: CNMSshvol{YYYYMMDD}.txt
            # Fields: Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
            
            # For now, return default values
            # The ETB→HTB check in Alpaca client is more actionable
            
        except Exception as e:
            logger.debug(f"Error getting short volume for {symbol}: {e}")
            
        return result

    async def check_short_squeeze_risk(
        self,
        symbol: str,
        short_interest_pct: float = 0.0,
        days_to_cover: float = 0.0,
        is_htb: bool = False
    ) -> Dict[str, Any]:
        """
        Assess short squeeze risk.
        
        Per Architect:
        "HTB transition = penalty for puts (squeeze risk)"
        
        High squeeze risk conditions:
        - HTB + high short interest (>20%)
        - Days to cover > 5
        - Rising short volume on declining price
        
        Returns:
            Dict with squeeze risk assessment
        """
        result = {
            "symbol": symbol,
            "squeeze_risk_score": 0.0,  # 0-1
            "is_high_risk": False,
            "risk_factors": []
        }
        
        risk_score = 0.0
        
        # HTB = significant risk factor
        if is_htb:
            risk_score += 0.4
            result["risk_factors"].append("hard_to_borrow")
            
        # High short interest
        if short_interest_pct > 20:
            risk_score += 0.3
            result["risk_factors"].append(f"high_short_interest_{short_interest_pct:.1f}%")
        elif short_interest_pct > 10:
            risk_score += 0.15
            result["risk_factors"].append(f"elevated_short_interest_{short_interest_pct:.1f}%")
            
        # Days to cover
        if days_to_cover > 5:
            risk_score += 0.2
            result["risk_factors"].append(f"high_days_to_cover_{days_to_cover:.1f}")
        elif days_to_cover > 3:
            risk_score += 0.1
            result["risk_factors"].append(f"moderate_days_to_cover_{days_to_cover:.1f}")
            
        result["squeeze_risk_score"] = min(risk_score, 1.0)
        result["is_high_risk"] = risk_score >= 0.5
        
        if result["is_high_risk"]:
            logger.warning(
                f"{symbol}: HIGH SQUEEZE RISK - Score: {risk_score:.2f}, "
                f"Factors: {result['risk_factors']}"
            )
            
        return result

    def calculate_short_volume_trend(
        self,
        volumes: List[Dict[str, int]]
    ) -> Dict[str, Any]:
        """
        Calculate short volume trend from historical data.
        
        Per Architect:
        "Rising short volume + falling price = institutional conviction"
        
        Args:
            volumes: List of {short_volume, total_volume, price} dicts
            
        Returns:
            Dict with trend analysis
        """
        if not volumes or len(volumes) < 2:
            return {"trend": "insufficient_data", "conviction": 0.0}
            
        # Calculate short volume ratios
        ratios = []
        prices = []
        for v in volumes:
            total = v.get("total_volume", 1)
            short = v.get("short_volume", 0)
            price = v.get("price", 0)
            if total > 0:
                ratios.append(short / total)
                prices.append(price)
                
        if len(ratios) < 2:
            return {"trend": "insufficient_data", "conviction": 0.0}
            
        # Check trend
        ratio_trend = ratios[-1] - ratios[0]  # Change in short ratio
        price_trend = (prices[-1] - prices[0]) / prices[0] if prices[0] > 0 else 0
        
        result = {
            "short_ratio_current": ratios[-1],
            "short_ratio_change": ratio_trend,
            "price_change": price_trend,
            "trend": "neutral",
            "conviction": 0.0
        }
        
        # Rising short volume + falling price = institutional conviction (bearish)
        if ratio_trend > 0.05 and price_trend < -0.02:
            result["trend"] = "bearish_conviction"
            result["conviction"] = min(abs(ratio_trend) * 5, 1.0)
            
        # Rising short volume + rising price = potential squeeze setup
        elif ratio_trend > 0.05 and price_trend > 0.02:
            result["trend"] = "squeeze_setup"
            result["conviction"] = min(abs(ratio_trend) * 3, 1.0)
            
        # Falling short volume = shorts covering
        elif ratio_trend < -0.05:
            result["trend"] = "short_covering"
            result["conviction"] = min(abs(ratio_trend) * 3, 1.0)
            
        return result
