"""In-process token-bucket rate limiter (per worker).

Lightweight anti-abuse / anti-DoS. For multi-replica deployments a shared store
(Redis) would be needed; documented as a known limitation."""
from __future__ import annotations

import threading
import time


class RateLimiter:
    def __init__(self, per_min: int, burst: int = 0, clock=time.monotonic):
        self.rate = (per_min or 0) / 60.0          # tokens per second
        self.cap = float(burst or per_min or 1)
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.rate > 0

    def allow(self, key: str) -> bool:
        if not self.enabled:
            return True
        now = self._clock()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.cap, now))
            tokens = min(self.cap, tokens + (now - last) * self.rate)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1.0, now)
            return True
