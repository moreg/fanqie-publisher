from datetime import datetime, timedelta
from threading import Lock
from typing import Optional
from dataclasses import dataclass


@dataclass
class CacheEntry:
    data: any
    timestamp: datetime


class SimpleCache:
    def __init__(self, ttl_seconds: int = 300):
        self._cache: dict[str, CacheEntry] = {}
        self._lock = Lock()
        self._ttl = timedelta(seconds=ttl_seconds)

    def get(self, key: str) -> Optional[any]:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if datetime.now() - entry.timestamp > self._ttl:
                del self._cache[key]
                return None
            return entry.data

    def set(self, key: str, value: any):
        with self._lock:
            self._cache[key] = CacheEntry(data=value, timestamp=datetime.now())

    def delete(self, key: str):
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()


fanqie_books_cache = SimpleCache(ttl_seconds=300)
