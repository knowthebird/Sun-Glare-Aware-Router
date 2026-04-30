from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass
class CacheEntry(Generic[V]):
    value: V
    expires_at: float


class TTLCache(Generic[K, V]):
    def __init__(self, ttl_s: float, max_entries: int = 128) -> None:
        self.ttl_s = ttl_s
        self.max_entries = max_entries
        self._entries: dict[K, CacheEntry[V]] = {}
        self._lock = threading.Lock()

    def get(self, key: K) -> V | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at < time.monotonic():
                self._entries.pop(key, None)
                return None
            return entry.value

    def set(self, key: K, value: V) -> None:
        with self._lock:
            if len(self._entries) >= self.max_entries:
                oldest_key = next(iter(self._entries))
                self._entries.pop(oldest_key, None)
            self._entries[key] = CacheEntry(
                value=value, expires_at=time.monotonic() + self.ttl_s
            )


class RateLimiter:
    def __init__(self, min_interval_s: float) -> None:
        self.min_interval_s = max(0.0, min_interval_s)
        self._lock = threading.Lock()
        self._next_allowed_at = 0.0

    def wait(self) -> None:
        if self.min_interval_s <= 0:
            return
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next_allowed_at - now
            if sleep_for > 0:
                time.sleep(sleep_for)
                now = time.monotonic()
            self._next_allowed_at = now + self.min_interval_s
