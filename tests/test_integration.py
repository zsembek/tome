"""Integration tests against Postgres (schema tome_test). Skipped if
TOME_TEST_DSN is not set. They cover: import, sections, edits, conflicts, versions,
folders, search, assets, atlas."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DSN = os.environ.get("TOME_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="TOME_TEST_DSN is not set")

if DSN:
    os.environ["POSTGRES_DSN"] = DSN
    os.environ["TOME_SCHEMA"] = "tome_test"
    os.environ["EMBED_ENABLED"] = "false"
    os.environ["EXTRACT_PRIMARY"] = "passthrough"
    os.environ["EXTRACT_FALLBACK"] = ""
    os.environ["RUN_INPROCESS_WORKER"] = "false"
    os.environ["STRUCTURE_SMART"] = "true"
    os.environ["OPENAI_API_KEY"] = ""


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from tome.db import DB
    import api.main as m
    db = DB()
    with db.pool.connection() as c, c.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS tome_test CASCADE")
    db.close()
    with TestClient(m.app) as c:
        yield c
    dbc = DB()
    with dbc.pool.connection() as c, c.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS tome_test CASCADE")
    dbc.close()


DOC = ("# Насос НЦ-100\n\nЦентробежный насос.\n\n## Технические параметры\n\n"
       "Давление 0.7 МПа, мощность 11 kW.\n\n## Эксплуатация\n\nПроверить масло.\n")


def _ingest(client, name, content, folder="Оборуд/Насосы"):
    from tome.db import DB
    from tome.worker import run_once
    r = client.post("/v1/documents", files={"file": (name, content.encode(), "text/markdown")},
                    data={"folder_path": folder})
    run_once(DB())
    return client.get(f"/v1/jobs/{r.json()['job_id']}").json()


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_ingest_and_sections(client):
    job = _ingest(client, "nasos.md", DOC)
    assert job["status"] == "done"
    tree = client.get("/v1/folders").json()["folders"]
    fid = [f["id"] for f in tree if f["name"] == "Насосы"][0]
    docs = client.get(f"/v1/folders/{fid}/documents").json()["documents"]
    assert docs and docs[0]["section_count"] == 3


def test_search_and_section_edit(client):
    res = client.get("/v1/search?q=давление&mode=bm25").json()["results"]
    assert res
    sid = res[0]["id"]
    sec = client.get(f"/v1/sections/{sid}").json()
    pr = client.patch(f"/v1/sections/{sid}", json={"content": "Давление 0.9 МПа.", "rev": sec["rev"]})
    assert pr.status_code == 200
    # conflict
    cf = client.patch(f"/v1/sections/{sid}", json={"content": "x", "rev": sec["rev"]})
    assert cf.status_code == 409


def test_insert_delete_section(client):
    tree = client.get("/v1/folders").json()["folders"]
    fid = [f["id"] for f in tree if f["name"] == "Насосы"][0]
    did = client.get(f"/v1/folders/{fid}/documents").json()["documents"][0]["id"]
    before = len(client.get(f"/v1/documents/{did}/sections?depth=6").json()["sections"])
    r = client.post(f"/v1/documents/{did}/sections",
                    json={"heading": "Безопасность", "content": "Носить СИЗ.", "level": 2})
    sid = r.json()["section_id"]
    after = len(client.get(f"/v1/documents/{did}/sections?depth=6").json()["sections"])
    assert after == before + 1
    client.delete(f"/v1/sections/{sid}")
    assert len(client.get(f"/v1/documents/{did}/sections?depth=6").json()["sections"]) == before


def test_conflict_on_reimport_with_manual_edit(client):
    # a document with a manual edit → re-import of different content = pending conflict
    job = _ingest(client, "conf.md", "# A\n\nтекст один.\n", folder="Оборуд/Конфликт")
    did = job["document_id"]
    secs = client.get(f"/v1/documents/{did}/sections?depth=6").json()["sections"]
    sec = client.get(f"/v1/sections/{secs[0]['id']}").json()
    client.patch(f"/v1/sections/{secs[0]['id']}", json={"content": "ручная правка", "rev": sec["rev"]})
    job2 = _ingest(client, "conf.md", "# A\n\nтекст ДВА изменён.\n", folder="Оборуд/Конфликт")
    assert job2["stage"] == "conflict_pending"
    cf = client.get(f"/v1/documents/{did}/conflict").json()
    assert cf["conflict"] is True
    client.post(f"/v1/documents/{did}/conflict/resolve", json={"action": "keep_current"})
    assert client.get(f"/v1/documents/{did}/conflict").json()["conflict"] is False


def test_versions_and_atlas(client):
    tree = client.get("/v1/folders").json()["folders"]
    fid = [f["id"] for f in tree if f["name"] == "Насосы"][0]
    did = client.get(f"/v1/folders/{fid}/documents").json()["documents"][0]["id"]
    vers = client.get(f"/v1/documents/{did}/versions").json()["versions"]
    assert vers
    atlas = client.get("/v1/atlas").json()["markdown"]
    assert "Atlas" in atlas


def test_unchanged_reimport_skips(client):
    j1 = _ingest(client, "same.md", "# Z\n\nстабильный текст.\n", folder="Оборуд/Стаб")
    j2 = _ingest(client, "same.md", "# Z\n\nстабильный текст.\n", folder="Оборуд/Стаб")
    assert j2["stage"] == "unchanged"
