"""WI-3.0b: revoking access takes effect immediately.

The scope cache (30s TTL) must be invalidated on logout, user disable/role
change, and api-key deletion — otherwise a revoked principal keeps access for
up to the TTL window. Memory scoping relies on correct scopes, so this matters."""
import os

import pytest

DSN = os.environ.get("TOME_TEST_DSN")


@pytest.mark.integration
def test_revocation_is_immediate(monkeypatch):
    if not DSN:
        pytest.skip("TOME_TEST_DSN is not set")
    monkeypatch.setenv("TOME_OPEN", "false")
    monkeypatch.setenv("TOME_SECRET", "invalidation-test-secret-1234567890")
    monkeypatch.setenv("TOME_ADMIN_EMAIL", "")
    monkeypatch.setenv("TOME_ADMIN_PASSWORD", "")
    import tome.config as cfgmod
    import api.deps as deps
    cfgmod._cfg = None
    deps.close_db()
    deps._scope_cache.clear()

    from fastapi.testclient import TestClient
    import api.main as m
    from api.ratelimit import RateLimiter
    saved = m._limiter
    m._limiter = RateLimiter(per_min=0)

    def _drop():
        d = deps.get_db()
        with d.pool.connection() as c, c.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS tome_test CASCADE")
        deps.close_db()

    _drop()
    try:
        with TestClient(m.app) as c:
            def H(t):
                return {"Authorization": f"Bearer {t}"}

            adm = c.post("/v1/auth/bootstrap",
                         json={"email": "a@a.io", "password": "adminpass1"}).json()["token"]
            c.post("/v1/users", headers=H(adm),
                   json={"email": "v@v.io", "password": "viewerpass1", "role": "viewer"})
            vt = c.post("/v1/auth/login",
                        json={"email": "v@v.io", "password": "viewerpass1"}).json()["token"]

            # warm the cache: viewer can read
            assert c.get("/v1/folders", headers=H(vt)).status_code == 200

            # logout invalidates that token immediately (no 30s stale window)
            assert c.post("/v1/auth/logout", headers=H(vt)).status_code == 200
            assert c.get("/v1/folders", headers=H(vt)).status_code == 401

            # log back in, warm cache again, then admin disables the user
            vt2 = c.post("/v1/auth/login",
                         json={"email": "v@v.io", "password": "viewerpass1"}).json()["token"]
            assert c.get("/v1/folders", headers=H(vt2)).status_code == 200
            uid = [u for u in c.get("/v1/users", headers=H(adm)).json()["users"]
                   if u["email"] == "v@v.io"][0]["id"]
            assert c.patch(f"/v1/users/{uid}", headers=H(adm),
                           json={"disabled": True}).status_code == 200
            # disabled user loses access at once
            assert c.get("/v1/folders", headers=H(vt2)).status_code == 401
    finally:
        m._limiter = saved
        try:
            _drop()
        finally:
            cfgmod._cfg = None
            deps._scope_cache.clear()
