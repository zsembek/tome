"""WI-3.3: memory over REST + MCP, with per-agent scoping and RBAC.

Open-mode functional coverage uses the integration `api_client`; RBAC is
checked in secure mode (viewer may recall but not write)."""
import os

import pytest

DSN = os.environ.get("TOME_TEST_DSN")
pytestmark = pytest.mark.integration


def test_memory_rest_crud(api_client):
    c = api_client
    r = c.post("/v1/memory", json={"content": "## Note\n\nThe turbine spins at 3000 rpm.",
                                   "title": "turbine", "tier": "semantic"})
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    # recall (read)
    rec = c.get("/v1/memory/recall", params={"q": "turbine rpm"}).json()["results"]
    assert any("turbine" in h["content"] for h in rec)
    # get by id + list
    assert c.get(f"/v1/memory/{mid}").json()["content"].startswith("## Note")
    assert any(m["id"] == mid for m in c.get("/v1/memory").json()["memories"])
    # observe + consolidate (write); LLM unconfigured -> deterministic raw roll-up
    c.post("/v1/memory/observe", json={"content": "user asked about turbines", "session_id": "s1"})
    cons = c.post("/v1/memory/consolidate", json={"session_id": "s1"}).json()
    assert cons["episodic_id"]
    # forget (write)
    assert c.delete(f"/v1/memory/{mid}").status_code == 200
    assert c.get(f"/v1/memory/{mid}").status_code == 404


def test_memory_rest_agent_scoping(api_client):
    c = api_client
    c.post("/v1/memory", headers={"X-Agent-Id": "a1"},
           json={"content": "private alpha note", "scope": "agent"})
    c.post("/v1/memory", headers={"X-Agent-Id": "a1"},
           json={"content": "shared beta note", "scope": "shared"})
    a2 = c.get("/v1/memory/recall", headers={"X-Agent-Id": "a2"},
               params={"q": "alpha beta note"}).json()["results"]
    blob = " ".join(h["content"] for h in a2)
    assert "shared beta note" in blob and "private alpha note" not in blob


def test_memory_mcp_tools(db_fresh):
    import mcp_server.server as srv
    srv._db = db_fresh
    try:
        r = srv.remember(content="mcp note about hydraulic turbines", tier="semantic")
        assert r["id"]
        hits = srv.recall(query="turbines")
        assert any("turbines" in h["content"] for h in hits)
        lst = srv.list_memory()
        assert any(m["id"] == r["id"] for m in lst)
        obs = srv.observe(content="agent observed a turbine event", session_id="m1")
        assert obs["id"]
        cons = srv.consolidate(session_id="m1")
        assert cons["episodic_id"]
        assert srv.forget(memory_id=r["id"])["deleted"] == r["id"]
    finally:
        srv._db = None


def test_memory_rbac(monkeypatch):
    if not DSN:
        pytest.skip("TOME_TEST_DSN is not set")
    monkeypatch.setenv("TOME_OPEN", "false")
    monkeypatch.setenv("TOME_SECRET", "memory-rbac-secret-1234567890-abcd")
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
            c.post("/v1/users", headers=H(adm),
                   json={"email": "e@e.io", "password": "editorpass1", "role": "editor"})
            vt = c.post("/v1/auth/login", json={"email": "v@v.io", "password": "viewerpass1"}).json()["token"]
            et = c.post("/v1/auth/login", json={"email": "e@e.io", "password": "editorpass1"}).json()["token"]

            # viewer: recall (read) ok, remember (write) denied
            assert c.get("/v1/memory/recall", headers=H(vt), params={"q": "x"}).status_code == 200
            assert c.post("/v1/memory", headers=H(vt),
                          json={"content": "v cannot write"}).status_code == 403
            # editor: remember ok
            assert c.post("/v1/memory", headers=H(et),
                          json={"content": "editor can write"}).status_code == 200
    finally:
        m._limiter = saved
        try:
            _drop()
        finally:
            cfgmod._cfg = None
            deps._scope_cache.clear()
