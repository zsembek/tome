"""DB-boundary guard: per-page checkpoints with NUL/control bytes must not blow up the
PostgreSQL write (broken PDFs produce them)."""
import pytest

pytestmark = pytest.mark.integration


def test_save_page_result_strips_nul(db_fresh):
    db = db_fresh
    ws = db.default_workspace()
    jid = db.create_job(ws, {"filename": "x.pdf"})
    db.save_page_result(jid, 1, "a\x00b\x01c\td\ne", [], 0.9)   # NUL + C0 + tab/newline
    pr = db.get_page_results(jid)
    content = pr[1]["content"]
    assert "\x00" not in content and "\x01" not in content
    assert "a" in content and "e" in content and "\t" in content and "\n" in content
