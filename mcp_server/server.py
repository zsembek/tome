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
def ingest_markdown(
    content: Annotated[str, Field(description="ready GitHub-Flavored Markdown to store as-is")],
    title: str,
    folder_path: Annotated[str | None, Field(description="'A/B/C' — folder tree, created on demand")] = None,
    folder_id: int | None = None,
) -> dict:
    """Ingest READY Markdown directly — no extraction/processing. Use this when you
    already have clean Markdown and just want it filed into the knowledge base."""
    import dataclasses
    from tome.pipeline.run import ingest
    cfg = dataclasses.replace(get_config(), extract_primary="passthrough", extract_fallback="")
    fn = title if title.lower().endswith((".md", ".markdown")) else f"{title}.md"
    doc_id = ingest(db(), workspace_id=ws(), file_bytes=content.encode("utf-8"), filename=fn,
                    mime="text/markdown", folder_path=folder_path, folder_id=folder_id,
                    title_override=title, cfg=cfg)
    return {"document_id": doc_id, "title": title}


# Back-compat alias (older clients called this for markdown text).
@mcp.tool()
def ingest_document(content: str, title: str, folder_path: str | None = None) -> dict:
    """Deprecated alias of ingest_markdown (ready Markdown text)."""
    return ingest_markdown(content=content, title=title, folder_path=folder_path)


@mcp.tool()
def ingest_file(
    filename: Annotated[str, Field(description="original filename incl. extension, e.g. report.pdf")],
    content_base64: Annotated[str, Field(description="base64-encoded raw file bytes")],
    folder_path: str | None = None,
    folder_id: int | None = None,
) -> dict:
    """Ingest a FILE (PDF/DOCX/image/…) — runs the full extraction → structuring →
    faithfulness pipeline, then files it into the folder tree."""
    import base64
    import mimetypes
    from tome.pipeline.run import ingest
    try:
        data = base64.b64decode(content_base64, validate=True)
    except Exception:
        return {"error": "content_base64 is not valid base64"}
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    doc_id = ingest(db(), workspace_id=ws(), file_bytes=data, filename=filename, mime=mime,
                    folder_path=folder_path, folder_id=folder_id)
    return {"document_id": doc_id, "filename": filename}


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


# ─────────── KNOWLEDGE GRAPH ───────────
@mcp.tool()
def list_entities(query: str = "", limit: int = 50) -> list[dict]:
    """List knowledge-graph entities (key concepts, model codes, acronyms) extracted
    from the base, most-mentioned first. Optionally filter by a query substring."""
    from tome.graph import list_entities as _le
    return _le(db(), ws(), query, limit)


@mcp.tool()
def get_entity(entity_id: int) -> dict:
    """An entity's sections (where it's mentioned) and related entities (neighbors).
    Use it to pivot from a concept to the documents that discuss it."""
    from tome.graph import get_entity as _ge
    return _ge(db(), ws(), entity_id) or {"error": "entity not found"}


# ─────────── AGENT MEMORY ───────────
def _agent(agent_id: str | None) -> str:
    return (agent_id or get_config().memory_default_agent or "default").strip() or "default"


def _mem_embedding(text: str):
    cfg = get_config()
    if not cfg.memory_enabled:
        return None
    emb = get_embedder(cfg)
    if not emb:
        return None
    try:
        return emb.embed([text])[0]
    except Exception:
        return None


@mcp.tool()
def remember(content: Annotated[str, Field(description="Markdown memory to store")],
             title: str = "", tier: str = "semantic", scope: str | None = None,
             mkey: Annotated[str, Field(description="key to supersede a prior memory")] = "",
             importance: float = 1.0, agent_id: str | None = None) -> dict:
    """Store a long-term memory (Markdown). Secrets are redacted automatically.
    Set `mkey` to overwrite an outdated fact with the same key."""
    from tome import memory
    row = memory.remember(db(), ws=ws(), agent_id=_agent(agent_id), content=content,
                          title=title, tier=tier, scope=scope, mkey=mkey,
                          importance=importance, embedding=_mem_embedding(content))
    return {"id": row["id"], "tier": row["tier"], "scope": row["scope"]}


@mcp.tool()
def recall(query: str, top_k: int = 8, tier: str | None = None,
           agent_id: str | None = None) -> list[dict]:
    """Recall relevant memories (hybrid BM25 + vector). Call this before acting,
    to reuse what was learned earlier."""
    from tome import memory
    return memory.recall(db(), ws=ws(), agent_id=_agent(agent_id), query=query,
                         top_k=top_k, tier=tier, query_embedding=_mem_embedding(query))


@mcp.tool()
def list_memory(tier: str | None = None, limit: int = 100, agent_id: str | None = None) -> list[dict]:
    """List stored memories (optionally by tier: working|episodic|semantic|procedural)."""
    from tome import memory
    return memory.list_memory(db(), ws=ws(), agent_id=_agent(agent_id), tier=tier, limit=limit)


@mcp.tool()
def observe(content: Annotated[str, Field(description="a raw observation to log")],
            session_id: str = "", agent_id: str | None = None) -> dict:
    """Log a raw working-tier observation (idempotent per session). Cheap to call
    often; `consolidate` later distils these into durable memory."""
    from tome import memory
    row = memory.observe(db(), ws=ws(), agent_id=_agent(agent_id), content=content,
                         session_id=session_id)
    return {"id": row["id"], "tier": "working"}


@mcp.tool()
def consolidate(session_id: str = "", agent_id: str | None = None) -> dict:
    """Distil a session's observations into one episodic summary and promote
    durable facts to semantic memory."""
    from tome import memory
    cfg = get_config()
    llm = None
    try:
        from tome.llm.registry import get_llm
        llm = get_llm(cfg)
    except Exception:
        llm = None
    return memory.consolidate(db(), ws=ws(), agent_id=_agent(agent_id),
                              session_id=session_id, llm=llm, model=cfg.llm_atlas_model)


@mcp.tool()
def import_transcript(transcript: str, session_id: str = "", consolidate: bool = True,
                      agent_id: str | None = None) -> dict:
    """Import a conversation transcript (one turn per line) into memory: each line
    becomes an observation, then the session is consolidated into durable memory."""
    from tome import memory
    cfg = get_config()
    llm = None
    if consolidate:
        try:
            from tome.llm.registry import get_llm
            llm = get_llm(cfg)
        except Exception:
            llm = None
    return memory.import_transcript(db(), ws=ws(), agent_id=_agent(agent_id), transcript=transcript,
                                    session_id=session_id, consolidate_after=consolidate,
                                    llm=llm, model=cfg.llm_atlas_model)


@mcp.tool()
def forget(memory_id: int, agent_id: str | None = None) -> dict:
    """Delete a memory by id (audited)."""
    from tome import memory
    ok = memory.forget(db(), ws=ws(), mem_id=memory_id, author="agent")
    return {"deleted": memory_id} if ok else {"error": "memory not found"}


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
