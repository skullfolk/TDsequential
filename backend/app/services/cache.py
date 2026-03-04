"""
Cache Service — TTL-based in-memory cache (per symbol).
Prevents Engine re-runs within the same 4H window.
Thread-safe for concurrent access from APScheduler + FastAPI.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_TTL_SECONDS = 4 * 60 * 60   # 4 hours


@dataclass
class CacheEntry:
    data: dict
    stored_at: float = field(default_factory=time.time)

    def is_fresh(self, ttl: int = _TTL_SECONDS) -> bool:
        return (time.time() - self.stored_at) < ttl

    def age_seconds(self) -> float:
        return time.time() - self.stored_at


class ReportCache:
    def __init__(self, ttl_seconds: int = _TTL_SECONDS):
        self._store: dict[str, CacheEntry] = {}
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    def get(self, symbol: str) -> Optional[dict]:
        with self._lock:
            entry = self._store.get(symbol)
            if entry is None:
                logger.debug("Cache MISS for %s", symbol)
                return None
            if entry.is_fresh(self._ttl):
                logger.debug("Cache HIT for %s (age=%.0fs)", symbol, entry.age_seconds())
                return {**entry.data, "_cache_age_seconds": entry.age_seconds(), "_stale": False}
            else:
                # Return stale data with flag
                logger.warning("Cache STALE for %s (age=%.0fs) — returning last known good", symbol, entry.age_seconds())
                return {**entry.data, "_cache_age_seconds": entry.age_seconds(), "_stale": True}

    def set(self, symbol: str, data: dict) -> None:
        with self._lock:
            self._store[symbol] = CacheEntry(data=data)
            logger.info("Cache SET for %s", symbol)

    def invalidate(self, symbol: str) -> None:
        with self._lock:
            self._store.pop(symbol, None)
            logger.info("Cache INVALIDATED for %s", symbol)


# Global singleton
report_cache = ReportCache()

