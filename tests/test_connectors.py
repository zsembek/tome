"""S7: ingestion-time PII/secret redaction + conversation transcript import."""
import pytest

pytestmark = pytest.mark.integration


def test_ingestion_redacts_secrets(db_fresh):
    from tome.config import Config
    from tome.pipeline.run import ingest
    cfg = Config()
    cfg.extract_primary = "passthrough"; cfg.extract_fallback = ""
    cfg.embed_enabled = False; cfg.graph_enabled = False
    cfg.ingest_redact = True
    did = ingest(db_fresh, workspace_id=db_fresh.default_workspace(),
                 file_bytes=b"# Doc\n\nDeploy key sk-abcdEFGH1234567890ijklMNOP must stay secret.\n",
                 filename="d.md", mime="text/markdown", title_override="D", cfg=cfg)
    content = "\n".join(p["content"] for p in db_fresh.get_document_parts(did, None))
    assert "sk-abcdEFGH1234567890ijklMNOP" not in content
    assert "must stay secret" in content  # surrounding text preserved


def test_transcript_import_rest(api_client):
    r = api_client.post("/v1/memory/transcript", json={
        "transcript": "user: I prefer metric units and SI notation\nassistant: understood, will use metric",
        "session_id": "t1", "consolidate": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["observed"] >= 2 and body["episodic_id"]
    rec = api_client.get("/v1/memory/recall", params={"q": "metric units"}).json()["results"]
    assert any("metric" in h["content"].lower() for h in rec)


def test_transcript_import_accepts_list_of_turns(api_client):
    r = api_client.post("/v1/memory/transcript", json={
        "transcript": [{"role": "user", "text": "the turbine is model HT-900"},
                       {"role": "assistant", "text": "logged turbine HT-900"}],
        "session_id": "t2", "consolidate": False})
    assert r.status_code == 200
    assert r.json()["observed"] == 2
