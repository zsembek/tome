"""S4: MCP ingestion parity — ready Markdown AND files-with-processing, into a tree."""
import base64

import pytest

pytestmark = pytest.mark.integration


def test_mcp_ingest_markdown_into_tree(db_fresh):
    import mcp_server.server as srv
    srv._db = db_fresh
    try:
        r = srv.ingest_markdown(content="# Turbine\n\nSpins at 3000 rpm.\n",
                                title="Turbine", folder_path="Eng/Turbines")
        assert r["document_id"]
        doc = srv.get_document(document_id=r["document_id"])
        assert "3000 rpm" in doc["markdown"]
        # folder tree was created
        folders = {f["path"] for f in srv.list_folders()}
        assert any(p.endswith("turbines") for p in folders)
    finally:
        srv._db = None


def test_mcp_ingest_file_runs_pipeline(db_fresh):
    import mcp_server.server as srv
    srv._db = db_fresh
    try:
        raw = b"# Valve\n\nGate valve DN50.\n"
        r = srv.ingest_file(filename="valve.md",
                            content_base64=base64.b64encode(raw).decode(),
                            folder_path="Eng/Valves")
        assert r["document_id"]
        doc = srv.get_document(document_id=r["document_id"])
        assert "Gate valve" in doc["markdown"]
    finally:
        srv._db = None
