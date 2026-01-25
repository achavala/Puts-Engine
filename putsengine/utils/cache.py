"""
Simple caching utilities for PutsEngine.
Helps reduce API calls by caching frequently accessed data.
"""

import time
from typing import Any, Optional, Dict
from functools import wraps
from loguru import logger


class SimpleCache:
    """
    Simple in-memory cache with TTL support.

    Used to cache API responses and reduce rate limit pressure.
    """

    def __init__(self, default_ttl: int = 300):
        """
        Initialize cache.

        Args:
            default_ttl: Default time-to-live in seconds (default 5 minutes)
        """
        self._cache: Dict[str, tuple] = {}  # key -> (value, expiry_time)
        self.default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        if key not in self._cache:
            return None

        value, expiry = self._cache[key]

        if time.time() > expiry:
            del self._cache[key]
            return None

        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (uses default if None)
        """
        if ttl is None:
            ttl = self.default_ttl

        expiry = time.time() + ttl
        self._cache[key] = (value, expiry)

    def delete(self, key: str) -> bool:
        """
        Delete value from cache.

        Args:
            key: Cache key

        Returns:
            True if key was found and deleted
        """
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> None:
        """Clear all cached values."""
        self._cache.clear()

    def cleanup(self) -> int:
        """
        Remove expired entries.

        Returns:
            Number of entries removed
        """
        now = time.time()
        expired = [k for k, (_, expiry) in self._cache.items() if now > expiry]

        for key in expired:
            del self._cache[key]

        return len(expired)

    def stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return {
            "total_entries": len(self._cache),
            "expired_entries": len([
                k for k, (_, expiry) in self._cache.items()
                if time.time() > expiry
            ])
        }


def cached(ttl: int = 300, key_prefix: str = ""):
    """
    Decorator for caching function results.

    Args:
        ttl: Time-to-live in seconds
        key_prefix: Prefix for cache keys

    Example:
        @cached(ttl=60, key_prefix="quotes")
        async def get_quote(symbol: str) -> dict:
            ...
    """
    cache = SimpleCache(default_ttl=ttl)

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Build cache key from args
            key_parts = [key_prefix, func.__name__]
            key_parts.extend(str(arg) for arg in args)
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            key = ":".join(key_parts)

            # Check cache
            cached_value = cache.get(key)
            if cached_value is not None:
                logger.debug(f"Cache hit: {key}")
                return cached_value

            # Call function
            result = await func(*args, **kwargs)

            # Cache result
            if result is not None:
                cache.set(key, result, ttl)

            return result

        return wrapper

    return decorator


# Global cache instances for different data types
quote_cache = SimpleCache(default_ttl=30)  # 30 seconds for quotes
bar_cache = SimpleCache(default_ttl=60)     # 1 minute for bars
flow_cache = SimpleCache(default_ttl=120)   # 2 minutes for flow data
gex_cache = SimpleCache(default_ttl=300)    # 5 minutes for GEX data
