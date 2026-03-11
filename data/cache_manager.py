"""
data/cache_manager.py — In-memory cache with TTL for Arunabha Hybrid Bot v1.0
Avoids redundant API calls across the same scan cycle.
"""

import asyncio
import time
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CacheEntry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl: float):
        self.value = value
        self.expires_at = time.monotonic() + ttl


class CacheManager:
    """Thread-safe async in-memory TTL cache."""

    def __init__(self):
        self._store: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if time.monotonic() > entry.expires_at:
                del self._store[key]
                return None
            return entry.value

    async def set(self, key: str, value: Any, ttl: float = 300.0) -> None:
        async with self._lock:
            self._store[key] = CacheEntry(value, ttl)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def clear_expired(self) -> int:
        now = time.monotonic()
        async with self._lock:
            expired = [k for k, v in self._store.items() if now > v.expires_at]
            for k in expired:
                del self._store[k]
        return len(expired)

    async def keys(self) -> list[str]:
        async with self._lock:
            return list(self._store.keys())

    async def size(self) -> int:
        async with self._lock:
            return len(self._store)


cache = CacheManager()
