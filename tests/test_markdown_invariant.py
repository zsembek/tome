"""Contract: Markdown is the canonical representation.

Pure checks run everywhere; round-trip/storage checks need a DB (integration).
This locks the core invariant: content, Atlas and (later) agent memory are Markdown,
never a proprietary object model."""
import io
import json
import zipfile

import pytest


# ── pure (no DB) ──────────────────────────────────────────────────────────
def test_atlas_index_is_markdown_not_json():
    from tome.pipeline.atlas import build_index
    md = build_index([{"name": "A", "path": "a", "description": "", "document_count": 1},
                      {"name": "B", "path": "a.b", "description": "", "document_count": 2}])
    assert isinstance(md, str) and "#" in md          # markdown headings
    with pytest.raises(Exception):
        json.loads(md)                                 # not a JSON blob


def test_sections_roundtrip_preserves_markdown_tokens():
    from tome.pipeline.split import build_sections
    md = "# Title\n\nIntro 0.7 MPa.\n\n## Spec\n\n11 kW, 36000 L/h.\n"
    secs = build_sections(md)
    blob = " ".join(str(getattr(s, f, "")) for s in secs for f in ("heading", "content"))
    for token in ["Title", "Spec", "0.7 MPa", "11 kW", "36000"]:
        assert token in blob, f"lost token through section split: {token}"


# ── integration (DB) ──────────────────────────────────────────────────────
@pytest.mark.integration
def test_document_content_is_markdown(api_client, ingest, sample_markdown):
    job = ingest("doc.md", sample_markdown, folder="T/Inv")
    assert job["status"] == "done"
    content = api_client.get(f"/v1/documents/{job['document_id']}/content").json()["markdown"]
    assert "0.7 MPa" in content and "11 kW" in content
    with pytest.raises(Exception):
        json.loads(content)                            # canonical = markdown, not JSON


@pytest.mark.integration
def test_export_then_reimport_preserves_content(api_client, ingest, sample_markdown):
    job = ingest("rt.md", sample_markdown, folder="T/RT")
    did = job["document_id"]
    exp = api_client.get(f"/v1/documents/{did}/export")
    assert exp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(exp.content))
    md_names = [n for n in zf.namelist() if n.endswith(".md")]
    assert md_names, "export bundle must contain a .md file"
    md = zf.read(md_names[0]).decode("utf-8")
    for token in ["0.7 MPa", "11 kW", "36000"]:
        assert token in md
    # re-import the exported markdown → content survives the round-trip
    job2 = ingest("rt2.md", md, folder="T/RT2")
    c2 = api_client.get(f"/v1/documents/{job2['document_id']}/content").json()["markdown"]
    for token in ["0.7 MPa", "11 kW", "36000"]:
        assert token in c2


@pytest.mark.integration
@pytest.mark.xfail(reason="agent memory namespace lands in Sprint 3", strict=False)
def test_memory_namespace_is_markdown():
    # Locked contract: agent memory will be ordinary Markdown documents in the KB.
    raise AssertionError("agent memory not implemented until Sprint 3")
