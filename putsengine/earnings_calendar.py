"""
Earnings Calendar Integration - Flag tickers reporting after close

PURPOSE: Know BEFORE market close which tickers are reporting earnings today.
         This enables:
         1. Pre-earnings put positioning (if distribution signals present)
         2. After-hours scanning focus on earnings names
         3. Next-day gap scanner prioritization

DATA SOURCES:
- Unusual Whales: /api/earnings-calendar
- Polygon: /v3/reference/tickers/{ticker}/events (backup)
- Manual override list for important names

SCAN SCHEDULE:
- 7:00 AM ET: Fetch today's earnings calendar
- 3:00 PM ET: Alert on tickers reporting after close
- 4:30 PM ET: Prioritize AH scan on earnings names

EARNINGS TIMING:
- BMO: Before Market Open (pre-market gap risk)
- AMC: After Market Close (after-hours gap risk)
"""

import asyncio
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Set
import pytz
from loguru import logger
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path


class EarningsTiming(Enum):
    """When earnings are reported."""
    BMO = "bmo"  # Before Market Open
    AMC = "amc"  # After Market Close
    UNKNOWN = "unknown"


@dataclass
class EarningsEvent:
    """Earnings event for a ticker."""
    symbol: str
    report_date: date
    timing: EarningsTiming
    eps_estimate: Optional[float] = None
    revenue_estimate: Optional[float] = None
    previous_eps: Optional[float] = None
    market_cap: Optional[float] = None
    
    @property
    def is_today(self) -> bool:
        return self.report_date == date.today()
    
    @property
    def is_after_close(self) -> bool:
        return self.timing == EarningsTiming.AMC
    
    @property
    def is_before_open(self) -> bool:
        return self.timing == EarningsTiming.BMO


class EarningsCalendar:
    """
    Manages earnings calendar data.
    
    Fetches and caches earnings dates for all universe tickers.
    Provides alerts for tickers reporting today.
    """
    
    # Cache file for earnings data
    CACHE_FILE = "earnings_calendar_cache.json"
    CACHE_EXPIRY_HOURS = 6  # Refresh cache every 6 hours
    
    def __init__(self, uw_client=None, polygon_client=None):
        """
        Initialize earnings calendar.
        
        Args:
            uw_client: UnusualWhalesClient for earnings data
            polygon_client: PolygonClient as backup
        """
        self.uw_client = uw_client
        self.polygon_client = polygon_client
        self._cache: Dict[str, EarningsEvent] = {}
        self._cache_timestamp: Optional[datetime] = None
        self._load_cache()
    
    def _load_cache(self):
        """Load cached earnings data from file."""
        cache_path = Path(self.CACHE_FILE)
        if cache_path.exists():
            try:
                with open(cache_path, 'r') as f:
                    data = json.load(f)
                    self._cache_timestamp = datetime.fromisoformat(data.get("timestamp", "2000-01-01"))
                    
                    # Check if cache is expired
                    age_hours = (datetime.now() - self._cache_timestamp).total_seconds() / 3600
                    if age_hours < self.CACHE_EXPIRY_HOURS:
                        for symbol, event_data in data.get("events", {}).items():
                            self._cache[symbol] = EarningsEvent(
                                symbol=symbol,
                                report_date=date.fromisoformat(event_data["report_date"]),
                                timing=EarningsTiming(event_data["timing"]),
                                eps_estimate=event_data.get("eps_estimate"),
                                revenue_estimate=event_data.get("revenue_estimate"),
                            )
                        logger.info(f"Loaded {len(self._cache)} earnings events from cache")
            except Exception as e:
                logger.debug(f"Failed to load earnings cache: {e}")
    
    def _save_cache(self):
        """Save earnings data to cache file."""
        try:
            cache_data = {
                "timestamp": datetime.now().isoformat(),
                "events": {
                    symbol: {
                        "report_date": event.report_date.isoformat(),
                        "timing": event.timing.value,
                        "eps_estimate": event.eps_estimate,
                        "revenue_estimate": event.revenue_estimate,
                    }
                    for symbol, event in self._cache.items()
                }
            }
            with open(self.CACHE_FILE, 'w') as f:
                json.dump(cache_data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save earnings cache: {e}")
    
    async def fetch_earnings_calendar(self, days_ahead: int = 7) -> List[EarningsEvent]:
        """
        Fetch earnings calendar from Unusual Whales.
        
        Args:
            days_ahead: Number of days to fetch
            
        Returns:
            List of EarningsEvent objects
        """
        events = []
        
        if self.uw_client:
            try:
                # Fetch from UW API
                today = date.today()
                end_date = today + timedelta(days=days_ahead)
                
                # UW endpoint: /api/earnings-calendar
                response = await self.uw_client.get_earnings_calendar(
                    start_date=today.isoformat(),
                    end_date=end_date.isoformat()
                )
                
                if response and isinstance(response, list):
                    for item in response:
                        symbol = item.get("ticker") or item.get("symbol")
                        if not symbol:
                            continue
                        
                        # Parse timing
                        timing_str = item.get("time", "").lower()
                        if "before" in timing_str or "bmo" in timing_str:
                            timing = EarningsTiming.BMO
                        elif "after" in timing_str or "amc" in timing_str:
                            timing = EarningsTiming.AMC
                        else:
                            timing = EarningsTiming.UNKNOWN
                        
                        # Parse date
                        date_str = item.get("date") or item.get("report_date")
                        if date_str:
                            try:
                                report_date = date.fromisoformat(date_str[:10])
                            except:
                                report_date = today
                        else:
                            report_date = today
                        
                        event = EarningsEvent(
                            symbol=symbol,
                            report_date=report_date,
                            timing=timing,
                            eps_estimate=item.get("eps_estimate"),
                            revenue_estimate=item.get("revenue_estimate"),
                        )
                        events.append(event)
                        self._cache[symbol] = event
                    
                    self._save_cache()
                    logger.info(f"Fetched {len(events)} earnings events from UW")
                    
            except Exception as e:
                logger.error(f"Failed to fetch earnings calendar from UW: {e}")
        
        return events
    
    def get_today_earnings(self, universe: Set[str] = None) -> Dict[str, List[EarningsEvent]]:
        """
        Get tickers reporting earnings today.
        
        Args:
            universe: Optional filter for specific tickers
            
        Returns:
            Dict with 'bmo' and 'amc' lists
        """
        today = date.today()
        
        results = {
            "bmo": [],  # Before Market Open
            "amc": [],  # After Market Close
        }
        
        for symbol, event in self._cache.items():
            if event.report_date != today:
                continue
            
            if universe and symbol not in universe:
                continue
            
            if event.timing == EarningsTiming.BMO:
                results["bmo"].append(event)
            elif event.timing == EarningsTiming.AMC:
                results["amc"].append(event)
            else:
                # Unknown timing - add to AMC for safety
                results["amc"].append(event)
        
        return results
    
    def get_amc_tickers(self, universe: Set[str] = None) -> Set[str]:
        """
        Get tickers reporting AFTER market close today.
        
        These are the high-priority tickers for after-hours scanning.
        """
        today_earnings = self.get_today_earnings(universe)
        return {event.symbol for event in today_earnings["amc"]}
    
    def get_bmo_tickers(self, universe: Set[str] = None) -> Set[str]:
        """
        Get tickers reporting BEFORE market open tomorrow.
        
        These are the high-priority tickers for pre-market gap scanning.
        """
        today_earnings = self.get_today_earnings(universe)
        return {event.symbol for event in today_earnings["bmo"]}
    
    def has_upcoming_earnings(self, symbol: str, days: int = 5) -> bool:
        """Check if ticker has earnings within N days."""
        if symbol not in self._cache:
            return False
        
        event = self._cache[symbol]
        days_until = (event.report_date - date.today()).days
        return 0 <= days_until <= days
    
    def get_earnings_date(self, symbol: str) -> Optional[date]:
        """Get earnings date for a ticker."""
        if symbol in self._cache:
            return self._cache[symbol].report_date
        return None


async def run_earnings_check(uw_client, universe: Set[str] = None) -> Dict:
    """
    Run daily earnings calendar check.
    
    Should be called at:
    - 7:00 AM ET: Fetch full calendar
    - 3:00 PM ET: Alert on AMC tickers
    
    Returns:
        Dict with today's earnings info
    """
    from putsengine.config import EngineConfig
    
    if universe is None:
        universe = set(EngineConfig.get_all_tickers())
    
    calendar = EarningsCalendar(uw_client=uw_client)
    
    # Fetch latest calendar
    await calendar.fetch_earnings_calendar(days_ahead=7)
    
    # Get today's earnings
    today_earnings = calendar.get_today_earnings(universe)
    
    # Log alerts
    et = pytz.timezone('US/Eastern')
    now = datetime.now(et)
    
    logger.info(f"Earnings Check at {now.strftime('%H:%M ET')}")
    
    if today_earnings["bmo"]:
        logger.info(f"BMO Earnings Today ({len(today_earnings['bmo'])} tickers):")
        for event in today_earnings["bmo"]:
            logger.info(f"  {event.symbol} - Reporting BEFORE market open")
    
    if today_earnings["amc"]:
        logger.warning(f"AMC Earnings Today ({len(today_earnings['amc'])} tickers) - WATCH FOR AH MOVES:")
        for event in today_earnings["amc"]:
            logger.warning(f"  {event.symbol} - Reporting AFTER market close")
    
    return {
        "check_time": now.isoformat(),
        "bmo_count": len(today_earnings["bmo"]),
        "amc_count": len(today_earnings["amc"]),
        "bmo_tickers": [e.symbol for e in today_earnings["bmo"]],
        "amc_tickers": [e.symbol for e in today_earnings["amc"]],
    }


# Manual high-profile earnings to always watch
# These are the "market moving" names
HIGH_PROFILE_EARNINGS = {
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "AMD", "INTC", "MU", "AVGO", "QCOM",
    "JPM", "BAC", "GS", "MS",
    "NFLX", "DIS", "SBUX", "NKE",
    "UNH", "JNJ", "PFE",
    "XOM", "CVX",
    "CAT", "BA",
}
