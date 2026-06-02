"""Garbage collection (GC) for DB ↔ object store consistency.

Reconciles objects in the store against what the DB considers live
(assets.object_key + revision snapshots document_versions.snapshot_object_key).
Finds:
  • orphans — objects in the store with no references in the DB (can be deleted);
  • missing — DB references to objects that are absent (reported, not deleted).

Defaults to a dry run (report only). apply=True — actually delete the orphans.
"""
from __future__ import annotations

import logging

from tome.db import DB
from tome.storage import get_store

log = logging.getLogger("tome.gc")


def live_keys(db: DB) -> set[str]:
    keys: set[str] = set()
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT object_key FROM assets WHERE object_key <> ''")
        keys |= {r["object_key"] for r in cur.fetchall()}
        cur.execute("SELECT snapshot_object_key FROM document_versions WHERE snapshot_object_key <> ''")
        keys |= {r["snapshot_object_key"] for r in cur.fetchall()}
    return keys


def collect(db: DB, *, apply: bool = False) -> dict:
    store = get_store()
    live = live_keys(db)
    in_store = set(store.list_keys(""))

    orphans = sorted(in_store - live)
    missing = sorted(live - in_store)

    deleted = 0
    if apply:
        for key in orphans:
            try:
                store.delete(key)
                deleted += 1
            except Exception as exc:
                log.warning("failed to delete %s: %s", key, exc)

    return {
        "store_objects": len(in_store),
        "live_refs": len(live),
        "orphans": orphans,
        "orphans_deleted": deleted if apply else 0,
        "missing": missing,
        "dry_run": not apply,
    }
