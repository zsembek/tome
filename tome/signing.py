"""Short-lived signed URLs for assets (images).

Why: a browser's `<img src>` cannot send an Authorization header, and putting a
long-lived token in the URL is insecure (it leaks into nginx/proxy logs, browser
history, Referer). Instead, the frontend requests a signature for a specific key
with a short TTL from an authorized endpoint and embeds it in the image URL.

Signature = HMAC-SHA256(secret, "<key>:<exp>"). The secret is TOME_SECRET.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time

from tome.config import get_config

log = logging.getLogger(__name__)
DEFAULT_TTL = 600  # 10 minutes


def _secret() -> bytes:
    s = get_config().secret
    if s:
        return s.encode("utf-8")
    # Fallback (NOT for production): stable within the process, but not across restarts.
    log.warning("TOME_SECRET is not set — asset signatures are weak. Please set TOME_SECRET.")
    return b"tome-insecure-default-secret-change-me"


def sign(key: str, exp: int) -> str:
    return hmac.new(_secret(), f"{key}:{exp}".encode("utf-8"), hashlib.sha256).hexdigest()


def signed_url(key: str, ttl: int = DEFAULT_TTL, now: int | None = None) -> str:
    exp = int(now if now is not None else time.time()) + ttl
    return f"/v1/assets/{key}?exp={exp}&sig={sign(key, exp)}"


def verify(key: str, exp: int | None, sig: str | None, now: int | None = None) -> bool:
    if not exp or not sig:
        return False
    if int(now if now is not None else time.time()) > int(exp):
        return False
    return hmac.compare_digest(sig, sign(key, int(exp)))
