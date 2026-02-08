"""
UNUSUAL WHALES API STRATEGY - Stay within 6K daily limit.

With 6,000 API calls/day and 163 tickers:

STRATEGY:
=========
1. Tiered scanning - not all tickers need full UW analysis
2. Cached results - don't re-fetch within cache window
3. Priority-based - high-beta gets more frequent updates

API CALL BUDGET:
================
- Options Flow: 1 call per ticker
- Dark Pool: 1 call per ticker  
- GEX Data: 1 call (market-wide, not per ticker)
- Insider: 1 call per ticker
- Congress: 1 call per ticker

Full analysis per ticker = 4 calls
Market-wide (GEX, etc.) = 5 calls per scan

TIER SYSTEM:
============
Tier 1 (HIGH PRIORITY) - 38 high-beta tickers
  - Full UW analysis every 30 min
  - 38 × 4 = 152 calls per scan
  - 17 scans/day × 152 = 2,584 calls

Tier 2 (MEDIUM) - 60 liquid tickers (mega-cap, semis, etc.)
  - UW analysis every 1 hour
  - 60 × 4 = 240 calls per scan
  - 8 scans/day × 240 = 1,920 calls

Tier 3 (LOW) - 65 remaining tickers
  - UW analysis every 2 hours
  - 65 × 4 = 260 calls per scan
  - 4 scans/day × 260 = 1,040 calls

Market-wide calls: 17 × 5 = 85 calls

TOTAL: 2,584 + 1,920 + 1,040 + 85 = 5,629 calls/day (WITHIN 6K LIMIT!)

CACHING:
========
- Tier 1: 25 min cache
- Tier 2: 55 min cache
- Tier 3: 115 min cache
- Market-wide: 25 min cache
"""

from datetime import datetime, timedelta
from typing import Dict, Set, Optional
from dataclasses import dataclass, field
from enum import Enum
import asyncio

from putsengine.config import EngineConfig


class APITier(Enum):
    """API call priority tiers."""
    HIGH = "high"      # Every 30 min (high-beta)
    MEDIUM = "medium"  # Every 1 hour (liquid names)
    LOW = "low"        # Every 2 hours (others)


@dataclass
class CachedData:
    """Cached API response with timestamp."""
    data: any
    timestamp: datetime
    ttl_minutes: int = 30
    
    def is_valid(self) -> bool:
        """Check if cache is still valid."""
        age = (datetime.now() - self.timestamp).total_seconds() / 60
        return age < self.ttl_minutes


@dataclass  
class APIBudget:
    """Track API call budget."""
    daily_limit: int = 15000  # Feb 8, 2026: new UW API key, 15k/day
    calls_today: int = 0
    last_reset: datetime = field(default_factory=datetime.now)
    
    def can_call(self, num_calls: int = 1) -> bool:
        """Check if we have budget for calls."""
        self._check_reset()
        return (self.calls_today + num_calls) <= self.daily_limit
    
    def record_calls(self, num_calls: int = 1):
        """Record API calls made."""
        self._check_reset()
        self.calls_today += num_calls
    
    def _check_reset(self):
        """Reset counter if new day."""
        now = datetime.now()
        if now.date() > self.last_reset.date():
            self.calls_today = 0
            self.last_reset = now
    
    def remaining(self) -> int:
        """Get remaining calls for today."""
        self._check_reset()
        return self.daily_limit - self.calls_today


class UnusualWhalesAPIStrategy:
    """
    Manages Unusual Whales API calls to stay within daily limits.
    
    Uses tiered approach:
    - Tier 1 (HIGH): High-beta tickers, every 30 min
    - Tier 2 (MEDIUM): Liquid names, every 1 hour
    - Tier 3 (LOW): Others, every 2 hours
    """
    
    # Cache TTLs by tier (in minutes)
    CACHE_TTL = {
        APITier.HIGH: 25,    # 25 min (refresh every 30)
        APITier.MEDIUM: 55,  # 55 min (refresh every 60)
        APITier.LOW: 115,    # 115 min (refresh every 120)
    }
    
    def __init__(self):
        self.config = EngineConfig
        self.budget = APIBudget()
        
        # Cache for different data types
        self._flow_cache: Dict[str, CachedData] = {}
        self._darkpool_cache: Dict[str, CachedData] = {}
        self._insider_cache: Dict[str, CachedData] = {}
        self._congress_cache: Dict[str, CachedData] = {}
        self._gex_cache: Optional[CachedData] = None
        
        # Define tiers
        self._tier_assignments = self._assign_tiers()
    
    def _assign_tiers(self) -> Dict[str, APITier]:
        """Assign each ticker to an API tier."""
        assignments = {}
        
        # Tier 1 (HIGH): All high-beta tickers
        high_beta = self.config.get_high_beta_tickers()
        for ticker in high_beta:
            assignments[ticker] = APITier.HIGH
        
        # Tier 2 (MEDIUM): Mega-cap, semiconductors, financials, ETFs
        medium_sectors = ["mega_cap_tech", "semiconductors", "financials", "etfs"]
        for sector in medium_sectors:
            for ticker in self.config.UNIVERSE_SECTORS.get(sector, []):
                if ticker not in assignments:
                    assignments[ticker] = APITier.MEDIUM
        
        # Tier 3 (LOW): Everything else
        all_tickers = set(self.config.get_all_tickers())
        for ticker in all_tickers:
            if ticker not in assignments:
                assignments[ticker] = APITier.LOW
        
        return assignments
    
    def get_tier(self, symbol: str) -> APITier:
        """Get the API tier for a symbol."""
        return self._tier_assignments.get(symbol, APITier.LOW)
    
    def get_cache_ttl(self, symbol: str) -> int:
        """Get cache TTL in minutes for a symbol."""
        tier = self.get_tier(symbol)
        return self.CACHE_TTL[tier]
    
    def should_fetch_flow(self, symbol: str) -> bool:
        """Check if we should fetch options flow for this symbol."""
        if not self.budget.can_call(1):
            return False
        
        cached = self._flow_cache.get(symbol)
        if cached and cached.is_valid():
            return False
        
        return True
    
    def should_fetch_darkpool(self, symbol: str) -> bool:
        """Check if we should fetch dark pool data for this symbol."""
        if not self.budget.can_call(1):
            return False
        
        cached = self._darkpool_cache.get(symbol)
        if cached and cached.is_valid():
            return False
        
        return True
    
    def should_fetch_insider(self, symbol: str) -> bool:
        """Check if we should fetch insider data for this symbol."""
        if not self.budget.can_call(1):
            return False
        
        cached = self._insider_cache.get(symbol)
        if cached and cached.is_valid():
            return False
        
        return True
    
    def should_fetch_gex(self) -> bool:
        """Check if we should fetch GEX data (market-wide)."""
        if not self.budget.can_call(1):
            return False
        
        if self._gex_cache and self._gex_cache.is_valid():
            return False
        
        return True
    
    def cache_flow(self, symbol: str, data: any):
        """Cache options flow data."""
        ttl = self.get_cache_ttl(symbol)
        self._flow_cache[symbol] = CachedData(data, datetime.now(), ttl)
        self.budget.record_calls(1)
    
    def cache_darkpool(self, symbol: str, data: any):
        """Cache dark pool data."""
        ttl = self.get_cache_ttl(symbol)
        self._darkpool_cache[symbol] = CachedData(data, datetime.now(), ttl)
        self.budget.record_calls(1)
    
    def cache_insider(self, symbol: str, data: any):
        """Cache insider data."""
        ttl = self.get_cache_ttl(symbol)
        self._insider_cache[symbol] = CachedData(data, datetime.now(), ttl)
        self.budget.record_calls(1)
    
    def cache_gex(self, data: any):
        """Cache GEX data."""
        self._gex_cache = CachedData(data, datetime.now(), 25)
        self.budget.record_calls(1)
    
    def get_cached_flow(self, symbol: str) -> Optional[any]:
        """Get cached flow data if valid."""
        cached = self._flow_cache.get(symbol)
        return cached.data if cached and cached.is_valid() else None
    
    def get_cached_darkpool(self, symbol: str) -> Optional[any]:
        """Get cached dark pool data if valid."""
        cached = self._darkpool_cache.get(symbol)
        return cached.data if cached and cached.is_valid() else None
    
    def get_cached_gex(self) -> Optional[any]:
        """Get cached GEX data if valid."""
        return self._gex_cache.data if self._gex_cache and self._gex_cache.is_valid() else None
    
    def get_budget_status(self) -> Dict:
        """Get current API budget status."""
        return {
            "daily_limit": self.budget.daily_limit,
            "calls_today": self.budget.calls_today,
            "remaining": self.budget.remaining(),
            "utilization_pct": (self.budget.calls_today / self.budget.daily_limit) * 100,
        }
    
    def get_tier_counts(self) -> Dict[str, int]:
        """Get count of tickers in each tier."""
        counts = {tier.value: 0 for tier in APITier}
        for tier in self._tier_assignments.values():
            counts[tier.value] += 1
        return counts


# Singleton instance
_strategy: Optional[UnusualWhalesAPIStrategy] = None


def get_api_strategy() -> UnusualWhalesAPIStrategy:
    """Get the singleton API strategy instance."""
    global _strategy
    if _strategy is None:
        _strategy = UnusualWhalesAPIStrategy()
    return _strategy
