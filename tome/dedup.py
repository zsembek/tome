"""Deduplication of documents by content_hash.

find_duplicates — a report of groups of identical documents (the same content
under different folders/names). dedup(apply) — keeps the oldest in each group
and deletes the rest (cascade of sections/chunks/assets + outbox cleanup of
store objects)."""
from __future__ import annotations

import logging

from tome.db import DB
from tome import edit as ed

log = logging.getLogger("tome.dedup")


def find_duplicates(db: DB, ws: int) -> dict:
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT content_hash, array_agg(id ORDER BY id) ids,
                              array_agg(title ORDER BY id) titles, count(*) n
                       FROM documents
                       WHERE workspace_id=%s AND content_hash <> ''
                       GROUP BY content_hash HAVING count(*) > 1""", (ws,))
        groups = [{"content_hash": r["content_hash"][:12], "ids": r["ids"],
                   "titles": r["titles"], "count": r["n"]} for r in cur.fetchall()]
    return {"duplicate_groups": groups,
            "total_redundant": sum(g["count"] - 1 for g in groups)}


def dedup(db: DB, ws: int) -> dict:
    rep = find_duplicates(db, ws)
    removed = []
    for g in rep["duplicate_groups"]:
        keep = g["ids"][0]            # oldest (smallest id)
        for dup_id in g["ids"][1:]:
            ed.delete_document(db, dup_id)
            removed.append({"deleted": dup_id, "kept": keep})
    return {"removed": removed, "count": len(removed)}
