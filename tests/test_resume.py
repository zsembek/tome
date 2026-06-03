"""Resumable ingestion: a large document that fails mid-way must resume from the last
completed page on retry (not restart from page 1) and end up complete."""
import pytest

pytestmark = pytest.mark.integration


def _make_pdf(n: int) -> bytes:
    import fitz
    doc = fitz.open()
    for i in range(n):
        page = doc.new_page()
        page.insert_text((72, 72),
                         f"Page {i+1} content about unit {i+1}, with enough words here to form a real text layer.")
    data = doc.tobytes()
    doc.close()
    return data


def test_ingestion_resumes_from_checkpoint(db_fresh, monkeypatch):
    from tome.config import Config
    from tome.pipeline.run import ingest

    cfg = Config()
    cfg.extract_primary = "tika"          # digital-PDF path uses PyMuPDF (no Tika server)
    cfg.extract_fallback = ""
    cfg.embed_enabled = False; cfg.graph_enabled = False; cfg.structure_enabled = False

    ws = db_fresh.default_workspace()
    pdf = _make_pdf(4)
    job = db_fresh.create_job(ws, {"filename": "book.pdf"})

    # make page 3 fail exactly once → pages 1–2 get checkpointed, then the job errors
    real_save = db_fresh.save_page_result
    state = {"failed": False}

    def flaky(job_id, page_number, content, assets, faith):
        if page_number == 3 and not state["failed"]:
            state["failed"] = True
            raise RuntimeError("simulated crash at page 3")
        return real_save(job_id, page_number, content, assets, faith)

    monkeypatch.setattr(db_fresh, "save_page_result", flaky)

    with pytest.raises(RuntimeError):
        ingest(db_fresh, workspace_id=ws, file_bytes=pdf, filename="book.pdf",
               mime="application/pdf", job_id=job, cfg=cfg)

    # pages 1 and 2 are checkpointed (work not lost)
    ckpts = db_fresh.get_page_results(job)
    assert set(ckpts) >= {1, 2}, f"expected pages 1,2 checkpointed, got {sorted(ckpts)}"

    # retry the SAME job — must resume (process only pages 3,4) and complete fully
    did = ingest(db_fresh, workspace_id=ws, file_bytes=pdf, filename="book.pdf",
                 mime="application/pdf", job_id=job, cfg=cfg)
    content = "\n".join(p["content"] for p in db_fresh.get_document_parts(did, None)).lower()
    for i in range(1, 5):
        assert f"unit {i}" in content, f"page {i} missing after resume"

    # checkpoints cleared once the document is stored
    assert db_fresh.get_page_results(job) == {}
    # the original is now linked (source_object_key persisted)
    assert db_fresh.get_document(did)["source_object_key"]
