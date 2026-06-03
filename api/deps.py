"""Shared API dependencies: singleton DB, scope authentication, workspace.

Access model (secure-by-default):
  • TOME_OPEN=true → open mode (no authorization): all scopes.
    Acceptable only on localhost / a trusted network.
  • TOME_API_KEY (master) → all scopes (read/write/admin).
  • The Bearer token is looked up among api_keys (its scopes), then among user
    sessions (scopes = role: admin/editor/viewer).
  • The required scope is derived from the HTTP method: GET → read, otherwise → write.
    Managing keys/webhooks/users → admin.
"""
from __future__ import annotations

import hmac
import time

from fastapi import Header, HTTPException, Request

from tome.config import get_config
from tome.db import DB

_db: DB | None = None
ALL = {"read", "write", "admin"}

# TTL cache of scope resolution by token (reduces SQL queries on EVERY request)
_scope_cache: dict[str, tuple[float, set]] = {}
_SCOPE_TTL = 30.0


def get_db() -> DB:
    global _db
    if _db is None:
        _db = DB()
    return _db


def close_db() -> None:
    """Close the singleton DB pool (called on app shutdown to avoid leaked threads)."""
    global _db
    if _db is not None:
        try:
            _db.close()
        finally:
            _db = None


def init_db() -> DB:
    db = get_db()
    if not db.schema_ready():
        db.init_schema()
    return db


def current_workspace() -> int:
    return get_db().default_workspace()


def _resolve_scopes(token: str) -> set[str]:
    now = time.monotonic()
    cached = _scope_cache.get(token)
    if cached and now - cached[0] < _SCOPE_TTL:
        return cached[1]
    scopes = _resolve_scopes_uncached(token)
    _scope_cache[token] = (now, scopes)
    return scopes


def _resolve_scopes_uncached(token: str) -> set[str]:
    cfg = get_config()
    db = get_db()
    if cfg.tome_open:                       # explicit open mode
        return set(ALL)
    # constant-time comparison of the master key (protection against timing attacks)
    if cfg.api_key and token and hmac.compare_digest(token, cfg.api_key):
        return set(ALL)
    if token:
        row = db.verify_api_key(token)      # service api key
        if row:
            return set(row.get("scopes") or [])
        sess = db.verify_session(token)     # user session (role→scopes)
        if sess:
            return set(sess.get("scopes") or [])
    return set()


def _token(authorization: str | None) -> str:
    return (authorization or "").removeprefix("Bearer ").strip()


def _enforce(needed: str, authorization: str | None):
    scopes = _resolve_scopes(_token(authorization))
    if not scopes:
        raise HTTPException(status_code=401, detail="invalid or missing api key")
    if needed not in scopes:
        raise HTTPException(status_code=403, detail=f"requires '{needed}' scope")


def require_auth(request: Request, authorization: str | None = Header(default=None)):
    """Global check: GET → read, mutations → write.
    The token is accepted ONLY in the Authorization header (never in the URL —
    so the secret does not end up in logs/history). For images, short-lived
    signed links are used (see /v1/assets/sign)."""
    needed = "read" if request.method in ("GET", "HEAD", "OPTIONS") else "write"
    scopes = _resolve_scopes(_token(authorization))
    if not scopes:
        raise HTTPException(status_code=401, detail="authentication required")
    if needed not in scopes:
        raise HTTPException(status_code=403, detail=f"requires '{needed}' scope")


def require_admin(authorization: str | None = Header(default=None)):
    _enforce("admin", authorization)


def current_token(authorization: str | None = Header(default=None)) -> str:
    return _token(authorization)


def current_user(authorization: str | None = Header(default=None)) -> dict:
    """Current principal. Session → a real user; master/open/api-key →
    a synthetic admin principal. 401 if nothing is recognized."""
    cfg = get_config()
    tok = _token(authorization)
    if tok:
        sess = get_db().verify_session(tok)
        if sess:
            return {"email": sess["email"], "role": sess["role"],
                    "scopes": sorted(sess["scopes"]), "via": "session"}
    scopes = _resolve_scopes(tok)
    if not scopes:
        raise HTTPException(status_code=401, detail="authentication required")
    via = "open" if cfg.tome_open else ("master" if (cfg.api_key and tok) else "api_key")
    return {"email": None, "role": "admin" if "admin" in scopes else "service",
            "scopes": sorted(scopes), "via": via}
