"""Durable jobs/processing view: list all jobs (per-file status) + download original."""
import pytest

pytestmark = pytest.mark.integration


def test_jobs_list_and_download_original(api_client, ingest):
    job = ingest("manual.md", "# Manual\n\nHello world content for the original file.\n", folder="T/Jobs")
    assert job["status"] == "done"

    jobs = api_client.get("/v1/jobs").json()["jobs"]
    assert jobs, "jobs list is empty"
    j = [x for x in jobs if x.get("filename") == "manual.md"][0]
    assert j["status"] == "done"
    assert j["document_id"] and j["source_key"]          # original is linked
    assert "pages_total" in j and "pages_done" in j        # per-page progress fields present

    # download the ORIGINAL uploaded file
    r = api_client.get(f"/v1/documents/{j['document_id']}/source")
    assert r.status_code == 200
    assert b"Hello world content" in r.content


def test_source_download_404_when_absent(api_client):
    assert api_client.get("/v1/documents/999999/source").status_code == 404
