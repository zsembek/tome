"""Webhook security: HMAC-SHA256 signing + SSRF protection.

Signing: X-Tome-Signature = "sha256=<hex>" over the exact request body bytes,
using the per-webhook secret. SSRF: refuse delivery to private/loopback/
link-local/reserved addresses and non-http(s) schemes (blocks cloud metadata
endpoints like 169.254.169.254)."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import socket
from urllib.parse import urlparse


def sign_webhook(body: bytes, secret: str | None) -> str | None:
    """HMAC-SHA256 signature header value, or None if no secret is configured."""
    if not secret:
        return None
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def is_safe_webhook_url(url: str, *, allow_hosts: set[str] | None = None) -> bool:
    """True if the URL is safe to call (public http/https host). DNS is resolved
    and every resolved IP must be public."""
    try:
        u = urlparse(url)
    except Exception:
        return False
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    host = u.hostname
    if allow_hosts and host in allow_hosts:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip.split("%")[0])  # strip zone id if present
        except ValueError:
            return False
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            return False
    return True


def parse_allow_hosts(raw: str | None) -> set[str]:
    return {h.strip() for h in (raw or "").split(",") if h.strip()}
