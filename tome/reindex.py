"""Reprocessing of documents from the stored original (source asset).

Needed when the LLM model/prompts/pipeline_version change: the same file yields
a better result, but the content_hash matches → a normal ingest would skip it.
Reindex forces a run from the original in the store.

only_stale=True — only documents whose pipeline_version differs from the current
one.
"""
from __future__ import annotations

import logging

from tome.config import get_config
from tome.db import DB
from tome.storage import get_store
from tome import edit as ed
from tome.pipeline.run import ingest

log = logging.getLogger("tome.reindex")


def _candidates(db: DB, ws: int, only_stale: bool) -> list[dict]:
    cur_ver = get_config().pipeline_version
    with db.pool.connection() as conn, conn.cursor() as cur:
        if only_stale:
            cur.execute("""SELECT id, folder_id, source_filename, mime_type, pipeline_version
                           FROM documents WHERE workspace_id=%s AND pipeline_version <> %s""",
                        (ws, cur_ver))
        else:
            cur.execute("""SELECT id, folder_id, source_filename, mime_type, pipeline_version
                           FROM documents WHERE workspace_id=%s""", (ws,))
        return list(cur.fetchall())


def _source_key(db: DB, doc_id: int) -> str | None:
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT object_key FROM assets
                       WHERE document_id=%s AND kind='source' LIMIT 1""", (doc_id,))
        r = cur.fetchone()
        return r["object_key"] if r else None


def reindex_all(db: DB, ws: int, *, only_stale: bool = True) -> dict:
    store = get_store()
    docs = _candidates(db, ws, only_stale)
    done, skipped, errors = [], [], []
    for d in docs:
        key = _source_key(db, d["id"])
        if not key:
            skipped.append({"id": d["id"], "reason": "no stored original"})
            continue
        data = store.get(key)
        if not data:
            skipped.append({"id": d["id"], "reason": "original missing from store"})
            continue
        fid = d["folder_id"]   # exact folder by id — no name ambiguity
        try:
            ed.delete_document(db, d["id"])
            new_id = ingest(db, workspace_id=ws, file_bytes=data,
                            filename=d["source_filename"] or "document",
                            mime=d["mime_type"] or "application/octet-stream",
                            folder_id=fid)
            done.append({"old_id": d["id"], "new_id": new_id})
        except Exception as exc:
            log.exception("reindex %s failed", d["id"])
            errors.append({"id": d["id"], "error": str(exc)[:200]})
    return {"reindexed": done, "skipped": skipped, "errors": errors,
            "counts": {"done": len(done), "skipped": len(skipped), "errors": len(errors)}}
