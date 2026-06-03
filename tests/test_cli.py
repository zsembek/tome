"""S8: operational CLI — demo-seed + export-all (Markdown backup)."""
import pytest

pytestmark = pytest.mark.integration


def test_demo_seed_then_export_all(tmp_path, db_fresh):
    from tome import cli
    cli.main(["demo-seed"])
    ws = db_fresh.default_workspace()
    docs = db_fresh.list_all_documents(ws)
    assert len(docs) >= 3, "demo-seed should create sample documents"

    out = tmp_path / "backup"
    cli.main(["export-all", str(out)])
    md_files = list(out.glob("*.md"))
    assert len(md_files) >= 3, "export-all should write one .md per document"
    # exported Markdown round-trips real content
    blob = "\n".join(f.read_text(encoding="utf-8") for f in md_files)
    assert "0.7 MPa" in blob and "Gate Valve DN50" in blob
