"""Thread-safe per-provider interval limiter (shared process-wide).

Applied to LLM/embed calls based on provider_min_interval_sec from the settings,
to avoid hitting the provider's rate limit when many worker threads run at
once."""
from __future__ import annotations

import threading
import time

_locks: dict[str, threading.Lock] = {}
_last: dict[str, float] = {}
_guard = threading.Lock()


def throttle(key: str, min_interval: float) -> None:
    if min_interval <= 0:
        return
    with _guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        now = time.monotonic()
        wait = min_interval - (now - _last.get(key, 0.0))
        if wait > 0:
            time.sleep(wait)
        _last[key] = time.monotonic()
