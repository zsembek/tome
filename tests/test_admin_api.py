"""Admin: rich stats, audit log, API-key scopes, admin password reset, webhook validation."""
import pytest

pytestmark = pytest.mark.integration


def test_stats_has_rich_fields(api_client):
    s = api_client.get("/v1/stats").json()
    for key in ("documents", "folders", "sections", "graph_entities", "memories",
                "users", "api_keys", "webhooks", "tokens_in", "jobs", "config", "pgvector"):
        assert key in s, f"stats missing {key}"
    assert "llm_provider" in s["config"] and "embed_provider" in s["config"]


def test_apikey_uses_chosen_scopes_and_is_audited(api_client):
    r = api_client.post("/v1/api-keys", json={"scopes": ["read", "write"]})
    assert r.status_code == 200 and r.json()["api_key"].startswith("tome_")
    assert set(r.json()["scopes"]) == {"read", "write"}
    events = api_client.get("/v1/audit").json()["events"]
    assert any(e["action"] == "apikey.create" for e in events)


def test_admin_can_reset_user_password(api_client):
    c = api_client
    c.post("/v1/users", json={"email": "u@x.io", "password": "initialpw1", "role": "viewer"})
    uid = [u for u in c.get("/v1/users").json()["users"] if u["email"] == "u@x.io"][0]["id"]
    assert c.patch(f"/v1/users/{uid}", json={"password": "brandnewpw9"}).status_code == 200
    # the new password works for login
    assert c.post("/v1/auth/login", json={"email": "u@x.io", "password": "brandnewpw9"}).status_code == 200
    assert c.post("/v1/auth/login", json={"email": "u@x.io", "password": "initialpw1"}).status_code == 401
    # audited
    assert any(e["action"] == "user.update" for e in c.get("/v1/audit").json()["events"])


def test_webhook_rejects_unsafe_url_and_test_404(api_client):
    # private/loopback URLs are blocked (SSRF guard)
    bad = api_client.post("/v1/webhooks", json={"url": "http://127.0.0.1:9/h", "events": ["document.ready"]})
    assert bad.status_code == 400
    # available events are advertised
    assert "document.ready" in api_client.get("/v1/webhooks").json()["available_events"]
    # testing a non-existent webhook → 404
    assert api_client.post("/v1/webhooks/999999/test").status_code == 404


def test_memory_remember_via_rest(api_client):
    r = api_client.post("/v1/memory", json={"content": "## Pref\n\nUser prefers metric units.", "tier": "semantic"})
    assert r.status_code == 200
    rec = api_client.get("/v1/memory/recall", params={"q": "metric units"}).json()["results"]
    assert any("metric" in m["content"].lower() for m in rec)
