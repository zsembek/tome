"""Structural editing: sections (insert/delete/move/split/merge),
documents, folders, revisions. Everything is atomic, with rebuilding of
order/breadcrumb and tsv reindexing. Works on top of DB."""
from __future__ import annotations

import logging

from tome.config import get_config
from tome.db import DB, ConflictError
from tome.pipeline.split import slugify

log = logging.getLogger(__name__)


# ───────────────────────── helpers ─────────────────────────
def _fts():
    return get_config().fts_config


def _resequence(cur, doc_id: int, hints: dict[int, float] | None = None):
    """Rebuilds order_index (pre-order DFS over parent_id) and breadcrumb.
    hints: {section_id: float position} for inserting between existing ones."""
    hints = hints or {}
    cur.execute("""SELECT id, parent_id, order_index, level, heading
                   FROM sections WHERE document_id=%s""", (doc_id,))
    rows = cur.fetchall()
    if not rows:
        return
    by_id = {r["id"]: r for r in rows}
    children: dict[int | None, list] = {}
    for r in rows:
        children.setdefault(r["parent_id"], []).append(r)

    ordered: list[dict] = []

    def pos(r):
        return hints.get(r["id"], float(r["order_index"]))

    def walk(parent):
        for r in sorted(children.get(parent, []), key=pos):
            ordered.append(r)
            walk(r["id"])
    walk(None)

    # offset trick to avoid UNIQUE(document_id, order_index) collisions
    cur.execute("UPDATE sections SET order_index = order_index - 1000000 WHERE document_id=%s",
                (doc_id,))
    for i, r in enumerate(ordered):
        crumb = _breadcrumb(r, by_id)
        cur.execute("UPDATE sections SET order_index=%s, breadcrumb=%s WHERE id=%s",
                    (i, crumb, r["id"]))
    cur.execute("UPDATE documents SET section_count=%s, updated_at=NOW() WHERE id=%s",
                (len(ordered), doc_id))


def _breadcrumb(row, by_id) -> str:
    chain, cur = [], row
    guard = 0
    while cur is not None and guard < 50:
        chain.append(cur["heading"])
        cur = by_id.get(cur["parent_id"])
        guard += 1
    return " > ".join(reversed(chain))


def _reindex_section(cur, section_id: int, content: str, language: str):
    cur.execute("""UPDATE sections SET tsv=to_tsvector(%s::regconfig,%s) WHERE id=%s""",
                (_fts(), content, section_id))
    # rebuild the section's retrieval chunks
    cur.execute("DELETE FROM retrieval_chunks WHERE section_id=%s", (section_id,))
    from tome.pipeline.chunk import chunk_section
    cfg = get_config()
    cur.execute("SELECT document_id FROM sections WHERE id=%s", (section_id,))
    doc_id = cur.fetchone()["document_id"]
    for ch in chunk_section(0, content, chunk_tokens=cfg.chunk_tokens, overlap=cfg.chunk_overlap):
        cur.execute("""INSERT INTO retrieval_chunks (section_id, document_id, ordinal, text, token_count)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (section_id, doc_id, ch.ordinal, ch.text, ch.token_count))


def _record_rev(cur, section_id: int, content: str, author: str, source: str):
    cur.execute("SELECT rev FROM sections WHERE id=%s", (section_id,))
    rev = cur.fetchone()["rev"]
    cur.execute("""INSERT INTO section_revisions (section_id, rev, content, author, source)
                   VALUES (%s,%s,%s,%s,%s)""", (section_id, rev, content, author, source))


# ───────────────────────── section ops ─────────────────────────
def get_section_by_heading(db: DB, doc_id: int, heading: str) -> dict | None:
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id, level, heading, breadcrumb, rev FROM sections
                       WHERE document_id=%s AND lower(heading)=lower(%s)
                       ORDER BY order_index LIMIT 1""", (doc_id, heading))
        return cur.fetchone()


def similar_headings(db: DB, doc_id: int, fragment: str, limit: int = 5) -> list[str]:
    esc = fragment.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT heading FROM sections WHERE document_id=%s AND heading ILIKE %s
                       ORDER BY order_index LIMIT %s""", (doc_id, f"%{esc}%", limit))
        return [r["heading"] for r in cur.fetchall()]


def insert_section(db: DB, doc_id: int, after_section_id: int | None,
                   heading: str, content: str, level: int, author: str = "user") -> int:
    with db.pool.connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT language FROM documents WHERE id=%s", (doc_id,))
            d = cur.fetchone()
            if not d:
                raise ValueError("document not found")
            lang = d["language"]
            parent_id, after_oi = None, -1
            if after_section_id:
                cur.execute("SELECT parent_id, order_index, level FROM sections WHERE id=%s",
                            (after_section_id,))
                a = cur.fetchone()
                if a:
                    after_oi = a["order_index"]
                    parent_id = after_section_id if level > a["level"] else a["parent_id"]
            cur.execute("""INSERT INTO sections (document_id, parent_id, order_index, level,
                           heading, breadcrumb, anchor_slug, content, char_count, language, tsv)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, to_tsvector(%s::regconfig,%s))
                           RETURNING id""",
                        (doc_id, parent_id, 10_000_000, level, heading, heading,
                         slugify(heading), content, len(content), lang, _fts(), content))
            sid = cur.fetchone()["id"]
            _reindex_section(cur, sid, content, lang)
            _resequence(cur, doc_id, hints={sid: after_oi + 0.5})
    return sid


def delete_section(db: DB, section_id: int):
    with db.pool.connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT document_id FROM sections WHERE id=%s", (section_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError("section not found")
            doc_id = row["document_id"]
            cur.execute("DELETE FROM sections WHERE id=%s", (section_id,))  # cascade to children
            _resequence(cur, doc_id)


def move_section(db: DB, section_id: int, new_parent_id: int | None,
                 after_section_id: int | None = None):
    with db.pool.connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT document_id, parent_id FROM sections WHERE id=%s", (section_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError("section not found")
            doc_id = row["document_id"]
            if new_parent_id == section_id:
                raise ValueError("cannot move under itself")
            cur.execute("UPDATE sections SET parent_id=%s WHERE id=%s", (new_parent_id, section_id))
            hint = None
            if after_section_id:
                cur.execute("SELECT order_index FROM sections WHERE id=%s", (after_section_id,))
                a = cur.fetchone()
                if a:
                    hint = {section_id: a["order_index"] + 0.5}
            _resequence(cur, doc_id, hints=hint)


def split_section(db: DB, section_id: int, at: int, author: str = "user") -> int:
    """Splits a section at the character offset `at`: the first part stays, the
    second becomes a new sibling section at the same level."""
    with db.pool.connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT * FROM sections WHERE id=%s", (section_id,))
            s = cur.fetchone()
            if not s:
                raise ValueError("section not found")
            content = s["content"]
            at = max(1, min(at, len(content) - 1))
            head_part, tail_part = content[:at].rstrip(), content[at:].lstrip()
            newrev = s["rev"] + 1
            cur.execute("""UPDATE sections SET content=%s, char_count=%s, rev=%s WHERE id=%s""",
                        (head_part, len(head_part), newrev, section_id))
            _record_rev(cur, section_id, head_part, author, "split")
            _reindex_section(cur, section_id, head_part, s["language"])
            new_head = (s["heading"] + " (continued)")
            cur.execute("""INSERT INTO sections (document_id, parent_id, order_index, level,
                           heading, breadcrumb, anchor_slug, content, char_count, language, tsv)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, to_tsvector(%s::regconfig,%s))
                           RETURNING id""",
                        (s["document_id"], s["parent_id"], 10_000_000, s["level"],
                         new_head, new_head, slugify(new_head), tail_part, len(tail_part),
                         s["language"], _fts(), tail_part))
            nid = cur.fetchone()["id"]
            _reindex_section(cur, nid, tail_part, s["language"])
            _resequence(cur, s["document_id"], hints={nid: s["order_index"] + 0.5})
    return nid


def merge_sections(db: DB, section_ids: list[int], author: str = "user") -> int:
    """Merges sections into the first one (by order), deleting the rest."""
    if len(section_ids) < 2:
        raise ValueError("at least 2 sections required")
    with db.pool.connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("""SELECT id, document_id, content, heading, rev, language, order_index
                           FROM sections WHERE id=ANY(%s::bigint[]) ORDER BY order_index""",
                        (section_ids,))
            secs = cur.fetchall()
            if len(secs) < 2:
                raise ValueError("sections not found")
            first = secs[0]
            merged = "\n\n".join(s["content"] for s in secs).strip()
            newrev = first["rev"] + 1
            cur.execute("UPDATE sections SET content=%s, char_count=%s, rev=%s WHERE id=%s",
                        (merged, len(merged), newrev, first["id"]))
            _record_rev(cur, first["id"], merged, author, "merge")
            _reindex_section(cur, first["id"], merged, first["language"])
            for s in secs[1:]:
                cur.execute("DELETE FROM sections WHERE id=%s", (s["id"],))
            _resequence(cur, first["document_id"])
    return first["id"]


# ───────────────────────── document ops ─────────────────────────
def update_document(db: DB, doc_id: int, *, title=None, tags=None, folder_path=None,
                    workspace_id: int | None = None):
    with db.pool.connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT workspace_id FROM documents WHERE id=%s", (doc_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError("document not found")
            ws = workspace_id or row["workspace_id"]
            sets, vals = [], []
            if title is not None:
                sets.append("title=%s"); vals.append(title)
            if tags is not None:
                sets.append("tags=%s"); vals.append(tags)
            if folder_path is not None:
                fid = db.ensure_folder_path(ws, folder_path)
                sets.append("folder_id=%s"); vals.append(fid)
            if not sets:
                return
            sets.append("updated_at=NOW()"); sets.append("rev=rev+1")
            vals.append(doc_id)
            cur.execute(f"UPDATE documents SET {', '.join(sets)} WHERE id=%s", vals)


def delete_document(db: DB, doc_id: int):
    """Cascade-deletes the document and queues assets for purge via the outbox."""
    with db.pool.connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT object_key FROM assets WHERE document_id=%s", (doc_id,))
            for r in cur.fetchall():
                db.enqueue_outbox(cur, "asset", "delete", {"key": r["object_key"]})
            cur.execute("DELETE FROM documents WHERE id=%s", (doc_id,))  # cascade


def list_versions(db: DB, doc_id: int) -> list[dict]:
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id, version_no, state, change_kind, author, faithfulness_score, created_at
                       FROM document_versions WHERE document_id=%s ORDER BY version_no DESC""",
                    (doc_id,))
        return list(cur.fetchall())


def list_section_revisions(db: DB, section_id: int) -> list[dict]:
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT rev, author, source, created_at, left(content,200) preview
                       FROM section_revisions WHERE section_id=%s ORDER BY rev DESC""",
                    (section_id,))
        return list(cur.fetchall())


# ───────────────────────── folder ops ─────────────────────────
def rename_folder(db: DB, folder_id: int, *, name=None, description=None):
    with db.pool.connection() as conn, conn.cursor() as cur:
        sets, vals = [], []
        if name is not None:
            sets.append("name=%s"); vals.append(name)
        if description is not None:
            sets.append("description=%s"); vals.append(description)
        if not sets:
            return
        vals.append(folder_id)
        cur.execute(f"UPDATE folders SET {', '.join(sets)} WHERE id=%s", vals)


def move_folder(db: DB, folder_id: int, new_parent_id: int | None):
    """Re-parents the folder subtree via ltree."""
    with db.pool.connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT path::text, slug, workspace_id FROM folders WHERE id=%s", (folder_id,))
            f = cur.fetchone()
            if not f:
                raise ValueError("folder not found")
            old = f["path"]
            if new_parent_id:
                cur.execute("SELECT path::text FROM folders WHERE id=%s", (new_parent_id,))
                np = cur.fetchone()
                new = f"{np['path']}.{f['slug']}"
            else:
                new = f["slug"]
            if new == old:
                return
            # update path of the entire subtree
            cur.execute("""UPDATE folders SET path = (%s || subpath(path, nlevel(%s::ltree)-1))::ltree,
                           parent_id = CASE WHEN id=%s THEN %s ELSE parent_id END
                           WHERE workspace_id=%s AND path <@ %s::ltree""",
                        (new, old, folder_id, new_parent_id, f["workspace_id"], old))


def delete_folder(db: DB, folder_id: int):
    with db.pool.connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            # purge assets of the subtree's documents
            cur.execute("""SELECT a.object_key FROM assets a JOIN documents d ON d.id=a.document_id
                           WHERE d.folder_id IN (SELECT id FROM folders WHERE path <@
                             (SELECT path FROM folders WHERE id=%s))""", (folder_id,))
            for r in cur.fetchall():
                db.enqueue_outbox(cur, "asset", "delete", {"key": r["object_key"]})
            cur.execute("DELETE FROM folders WHERE id=%s", (folder_id,))  # cascade
