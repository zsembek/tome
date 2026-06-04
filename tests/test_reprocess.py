"""Reprocess: re-run the current extraction pipeline on a document's stored original,
so extraction fixes (mojibake/encoding repair, OCR) apply to already-imported documents
without a manual re-upload."""
import pytest

pytestmark = pytest.mark.integration


def test_reprocess_reextracts_and_replaces(api_client, ingest):
    job = ingest("manual.md", "# Manual\n\nRoutine maintenance of the centrifugal pump and seals.")
    doc_id = job["document_id"]
    assert doc_id

    r = api_client.post(f"/v1/documents/{doc_id}/reprocess")
    assert r.status_code == 200
    new_id = r.json()["new_id"]
    assert new_id and r.json()["old_id"] == doc_id

    # the reprocessed document is retrievable and keeps its content
    content = api_client.get(f"/v1/documents/{new_id}/content")
    assert content.status_code == 200
    assert "maintenance" in content.json()["markdown"].lower()

    # the action is audited
    events = api_client.get("/v1/audit").json()["events"]
    assert any(e["action"] == "document.reprocess" for e in events)

    # the stored original SURVIVES reprocess (so it can be reprocessed again)
    from tome.db import DB
    from tome.reindex import _source_key
    from tome.storage import get_store
    db = DB()
    key = _source_key(db, new_id)
    assert key, "reprocessed document lost its source asset"
    assert get_store().get(key), "stored original was purged by reprocess"


def test_reprocess_missing_document_is_400(api_client):
    assert api_client.post("/v1/documents/999999/reprocess").status_code == 400
