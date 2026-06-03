"""WI-2.5: RBAC scope enforcement across endpoints (secure mode, real users)."""
import os

import pytest

DSN = os.environ.get("TOME_TEST_DSN")


@pytest.mark.integration
def test_rbac_scope_matrix(monkeypatch):
    if not DSN:
        pytest.skip("TOME_TEST_DSN is not set")
    # Run the gateway in SECURE mode (conftest defaults to TOME_OPEN=true).
    monkeypatch.setenv("TOME_OPEN", "false")
    monkeypatch.setenv("TOME_SECRET", "matrix-test-secret-1234567890-abcdef")
    # neutralize the env admin-seed (a local .env may define it) so bootstrap is available
    monkeypatch.setenv("TOME_ADMIN_EMAIL", "")
    monkeypatch.setenv("TOME_ADMIN_PASSWORD", "")
    import tome.config as cfgmod
    import api.deps as deps
    cfgmod._cfg = None
    deps.close_db()
    deps._scope_cache.clear()   # drop scopes cached by earlier open-mode tests (TTL window)

    from fastapi.testclient import TestClient
    import api.main as m
    from api.ratelimit import RateLimiter
    saved_lim = m._limiter
    m._limiter = RateLimiter(per_min=0)   # disable RL for the matrix

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
            c.post("/v1/users", headers=H(adm),
                   json={"email": "e@e.io", "password": "editorpass1", "role": "editor"})
            vt = c.post("/v1/auth/login",
                        json={"email": "v@v.io", "password": "viewerpass1"}).json()["token"]
            et = c.post("/v1/auth/login",
                        json={"email": "e@e.io", "password": "editorpass1"}).json()["token"]

            assert c.get("/v1/folders").status_code == 401                       # unauthenticated
            assert c.get("/v1/folders", headers=H(vt)).status_code == 200        # read: viewer ok
            assert c.post("/v1/folders", headers=H(vt),
                          json={"path": "X"}).status_code == 403                 # write: viewer denied
            assert c.post("/v1/folders", headers=H(et),
                          json={"path": "Y"}).status_code == 200                 # write: editor ok
            assert c.get("/v1/users", headers=H(vt)).status_code == 403          # admin: viewer denied
            assert c.get("/v1/users", headers=H(et)).status_code == 403          # admin: editor denied
            assert c.get("/v1/users", headers=H(adm)).status_code == 200         # admin: admin ok
    finally:
        m._limiter = saved_lim
        try:
            _drop()
        finally:
            cfgmod._cfg = None
