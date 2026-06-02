"""Tome MCP server (FastMCP). Read + write/edit tools over the same repositories
as the REST API. Works over stdio (Claude Desktop / Cursor) and over HTTP via mcpo."""
from __future__ import annotations

import logging
import sys
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from tome.config import get_config
from tome.db import DB, ConflictError
from tome.embed import get_embedder
from tome.store import hybrid_search
from tome.storage import get_store
from tome import edit as ed

log = logging.getLogger("tome.mcp")
mcp = FastMCP("tome")
_db: DB | None = None


def db() -> DB:
    global _db
    if _db is None:
        _db = DB()
    return _db


def ws() -> int:
    return db().default_workspace()


# ─────────── READ ───────────
@mcp.tool()
def get_atlas(scope: Annotated[str, Field(description="'index' or 'folder:<id>'")] = "index") -> str:
    """STEP 0. The knowledge map — read this first to orient yourself in the base."""
    return db().get_atlas(ws(), scope) or "(Atlas is empty — the base has no content yet)"


@mcp.tool()
def list_folders() -> list[dict]:
    """STEP 1. The folder tree of the knowledge base (id, path, name, description, doc_count)."""
    return db().folder_tree(ws())


@mcp.tool()
def list_documents(folder_id: Annotated[int, Field(description="folder id from list_folders")]) -> list[dict]:
    """STEP 2. Documents inside a folder."""
    return db().list_documents(folder_id)


@mcp.tool()
def list_sections(
    document_id: int,
    max_depth: Annotated[int, Field(ge=1, le=6)] = 2,
    parent_section_id: int | None = None,
) -> list[dict]:
    """STEP 3. The document's table of contents (without body text)."""
    return db().list_sections(document_id, max_depth, parent_section_id)


@mcp.tool()
def get_section(section_id: int, include_subsections: bool = True) -> dict:
    """STEP 4. Section text (with subsections by default)."""
    d = db()
    row = d.get_section(section_id)
    if not row:
        return {"error": "section not found"}
    if not include_subsections:
        md = f"{'#'*row['level']} {row['heading']}\n\n{row['content']}"
    else:
        tree = d.get_section_subtree(section_id)
        md = "\n\n".join(f"{'#'*r['level']} {r['heading']}\n\n{r['content']}".rstrip() for r in tree)
    return {"section_id": section_id, "heading": row["heading"], "rev": row["rev"], "markdown": md}


@mcp.tool()
def get_document(document_id: int, parts: list[int] | None = None) -> dict:
    """Read a document whole or by parts. For pinpoint lookups, prefer sections."""
    d = db()
    meta = d.get_document(document_id)
    if not meta:
        return {"error": "document not found"}
    rows = d.get_document_parts(document_id, parts)
    return {"document_id": document_id, "title": meta["title"],
            "markdown": "\n\n".join(r["content"] for r in rows)}


@mcp.tool()
def get_section_by_heading(document_id: int, heading: str, include_subsections: bool = True) -> dict:
    """Find a section by its exact heading and return its content (with suggestions)."""
    row = ed.get_section_by_heading(db(), document_id, heading)
    if not row:
        return {"error": "not found", "did_you_mean": ed.similar_headings(db(), document_id, heading)}
    return get_section(row["id"], include_subsections)


@mcp.tool()
def get_figure(document_id: int) -> list[dict]:
    """List a document's images (assets) with keys for /v1/assets/<key>."""
    return [{"id": a["id"], "kind": a["kind"], "fig_class": a.get("fig_class"),
             "url": f"/v1/assets/{a['object_key']}"} for a in db().list_assets(document_id)]


@mcp.tool()
def search(query: str, mode: str = "hybrid", top_k: int = 10) -> list[dict]:
    """Hybrid search (bm25|vector|hybrid) across the whole base. Returns sections."""
    cfg = get_config()
    qemb = None
    if mode in ("hybrid", "vector"):
        emb = get_embedder(cfg)
        if emb:
            try:
                qemb = emb.embed([query])[0]
            except Exception:
                pass
    return hybrid_search(db(), workspace_id=ws(), query=query,
                         query_embedding=qemb, top_k=top_k, mode=mode)


# ─────────── WRITE / EDIT ───────────
@mcp.tool()
def create_folder(path: Annotated[str, Field(description="'A/B/C' — created cascadingly")],
                  description: str = "") -> dict:
    """Create a folder / folder tree."""
    fid = db().ensure_folder_path(ws(), path)
    return {"folder_id": fid, "path": path}


@mcp.tool()
def ingest_document(
    content: Annotated[str, Field(description="document text/markdown")],
    title: str,
    folder_path: str | None = None,
) -> dict:
    """Ingest a document from text (the agent grows the base itself). Runs the pipeline."""
    from tome.pipeline.run import ingest
    data = content.encode("utf-8")
    fn = f"{title}.md"
    doc_id = ingest(db(), workspace_id=ws(), file_bytes=data, filename=fn,
                    mime="text/markdown", folder_path=folder_path)
    return {"document_id": doc_id, "title": title}


@mcp.tool()
def update_section(section_id: int, content: str, rev: int) -> dict:
    """Edit a section's text (rev is required — protects against conflicts)."""
    try:
        return db().update_section(section_id, content, rev=rev, author="agent")
    except ConflictError as e:
        return {"error": "conflict", "detail": str(e)}
    except ValueError as e:
        return {"error": str(e)}


@mcp.tool()
def insert_section(document_id: int, heading: str, content: str = "", level: int = 2,
                   after_section_id: int | None = None) -> dict:
    """Insert a new section after the given one."""
    return {"section_id": ed.insert_section(db(), document_id, after_section_id, heading, content, level, author="agent")}


@mcp.tool()
def delete_section(section_id: int) -> dict:
    """Delete a section (and its subsections)."""
    ed.delete_section(db(), section_id)
    return {"deleted": section_id}


@mcp.tool()
def move_section(section_id: int, new_parent_id: int | None = None,
                 after_section_id: int | None = None) -> dict:
    """Move / reorder a section."""
    ed.move_section(db(), section_id, new_parent_id, after_section_id)
    return {"moved": section_id}


@mcp.tool()
def split_section(section_id: int, at: int) -> dict:
    """Split a section into two at the character offset `at`."""
    return {"new_section_id": ed.split_section(db(), section_id, at, author="agent")}


@mcp.tool()
def merge_sections(section_ids: list[int]) -> dict:
    """Merge several sections into the first one."""
    return {"merged_into": ed.merge_sections(db(), section_ids, author="agent")}


@mcp.tool()
def update_document(document_id: int, title: str | None = None,
                    tags: list[str] | None = None, folder_path: str | None = None) -> dict:
    """Rename / move a document, or change its tags."""
    ed.update_document(db(), document_id, title=title, tags=tags, folder_path=folder_path, workspace_id=ws())
    return {"updated": document_id}


@mcp.tool()
def delete_document(document_id: int) -> dict:
    """Delete a document (cascade + purge images)."""
    ed.delete_document(db(), document_id)
    return {"deleted": document_id}


@mcp.tool()
def move_document(document_id: int, folder_path: str) -> dict:
    """Move a document to another folder."""
    ed.update_document(db(), document_id, folder_path=folder_path, workspace_id=ws())
    return {"moved": document_id}


@mcp.tool()
def list_versions(document_id: int) -> list[dict]:
    """A document's version history."""
    return ed.list_versions(db(), document_id)


@mcp.tool()
def export_document(document_id: int) -> dict:
    """Export a whole document as clean Markdown (no lock; for export/transfer)."""
    d = db()
    meta = d.get_document(document_id)
    if not meta:
        return {"error": "document not found"}
    rows = d.get_document_parts(document_id, None)
    return {"document_id": document_id, "title": meta["title"],
            "markdown": "\n\n".join(r["content"] for r in rows)}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    logging.basicConfig(level=logging.INFO)
    d = db()
    if not d.schema_ready():
        log.warning("schema not ready — run the gateway/migration to initialize it")
    mcp.run()


if __name__ == "__main__":
    main()
