"""Knowledge graph \u2014 a DERIVED index over the Markdown knowledge base.

Entities (key noun phrases, model codes, acronyms) and their co-occurrence relations
are extracted deterministically from section text \u2014 no LLM required, no graph DB. The
graph is a third retrieval signal fused into hybrid search alongside BM25 + vectors, and
it is fully rebuildable from the documents at any time (`tome graph-rebuild`).
"""
from __future__ import annotations

import logging
import re

from tome.config import get_config
from tome.db import DB

log = logging.getLogger(__name__)

# multi-word Capitalized phrase (Latin or Cyrillic), e.g. "Centrifugal Pump", "Atlas Index".
# The separator is spaces/tabs only (NOT \s) so a phrase never spans line breaks and
# absorbs the next paragraph's sentence-initial word.
_PHRASE = re.compile(r"[A-Z\u0410-\u042f\u0401][\w\u0410-\u042f\u0430-\u044f\u0451\u0401\-]*(?:[ \t]+[A-Z\u0410-\u042f\u0401][\w\u0410-\u042f\u0430-\u044f\u0451\u0401\-]*)+")
_TOKEN = re.compile(r"[A-Za-z\u0410-\u042f\u0430-\u044f\u0451\u04010-9][A-Za-z\u0410-\u042f\u0430-\u044f\u0451\u04010-9\-]*")
_STOP = {
    "the", "and", "for", "with", "this", "that", "from", "into", "are", "was", "were",
    "\u0435\u0433\u043e", "\u044d\u0442\u043e", "\u043a\u0430\u043a", "\u0434\u043b\u044f", "\u0447\u0442\u043e", "\u043f\u0440\u0438", "\u0438\u043b\u0438", "the ", "see", "note", "fig",
}


def extract_entities(text: str, *, min_len: int = 3, max_n: int = 30) -> list[tuple[str, str]]:
    """Deterministically extract (name, kind) entities from text. kind \u2208
    concept|code|acronym. Single sentence-initial words are intentionally ignored
    (too noisy); we keep multi-word phrases, alphanumeric codes, and acronyms."""
    out: dict[str, tuple[str, str]] = {}

    def add(raw: str, kind: str, floor: int):
        name = re.sub(r"\s+", " ", raw).strip(" -\u00b7\u2022\t")
        norm = name.lower()
        if len(norm) < floor or norm in _STOP or norm.isdigit():
            return
        out.setdefault(norm, (name, kind))

    text = text or ""
    for m in _PHRASE.finditer(text):
        add(m.group(0), "concept", min_len)
    for tok in _TOKEN.findall(text):
        has_d = any(c.isdigit() for c in tok)
        has_a = any(c.isalpha() for c in tok)
        if has_d and has_a:
            add(tok, "code", 2)                       # model codes: NTs-100, DN50, gpt-4o
        elif tok.isupper() and 2 <= len(tok) <= 6 and tok.isalpha():
            add(tok, "acronym", 2)                    # API, DN, ABS
    return list(out.values())[:max_n]


# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 build \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
def build_graph_for_document(db: DB, ws: int, doc_id: int) -> dict:
    """Extract entities + co-occurrence edges for one document's sections.
    Idempotent: clears this document's mentions first. Never raises (graph is an
    enhancement) \u2014 logs and returns counts."""
    cfg = get_config()
    ents_added = edges = 0
    try:
        with db.pool.connection() as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("DELETE FROM graph_mentions WHERE document_id=%s", (doc_id,))
                cur.execute("SELECT id, heading, content FROM sections WHERE document_id=%s", (doc_id,))
                sections = cur.fetchall()
                for s in sections:
                    names = extract_entities(f"{s['heading']}\n{s['content']}",
                                             min_len=cfg.graph_min_entity_len,
                                             max_n=cfg.graph_max_entities_per_section)
                    ids = []
                    for name, kind in names:
                        eid = _upsert_entity(cur, ws, name, kind)
                        cur.execute("""INSERT INTO graph_mentions (entity_id, workspace_id, document_id, section_id)
                                       VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                                    (eid, ws, doc_id, s["id"]))
                        if cur.rowcount:
                            cur.execute("UPDATE graph_entities SET mention_count=mention_count+1 WHERE id=%s", (eid,))
                            ents_added += 1
                        ids.append(eid)
                    for i in range(len(ids)):
                        for j in range(i + 1, len(ids)):
                            a, b = sorted((ids[i], ids[j]))
                            cur.execute("""INSERT INTO graph_edges (workspace_id, src_id, dst_id, weight)
                                           VALUES (%s,%s,%s,1)
                                           ON CONFLICT (workspace_id, src_id, dst_id)
                                           DO UPDATE SET weight = graph_edges.weight + 1""", (ws, a, b))
                            edges += 1
    except Exception as exc:
        log.warning("graph build failed for doc %s: %s", doc_id, exc)
    return {"mentions": ents_added, "edges": edges}


def _upsert_entity(cur, ws: int, name: str, kind: str) -> int:
    norm = name.lower()
    cur.execute("""INSERT INTO graph_entities (workspace_id, name, norm, kind)
                   VALUES (%s,%s,%s,%s)
                   ON CONFLICT (workspace_id, norm) DO UPDATE SET name=graph_entities.name
                   RETURNING id""", (ws, name, norm, kind))
    return cur.fetchone()["id"]


def rebuild_graph(db: DB, ws: int) -> dict:
    """Drop and rebuild the whole graph for a workspace from its documents."""
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM graph_edges WHERE workspace_id=%s", (ws,))
        cur.execute("DELETE FROM graph_mentions WHERE workspace_id=%s", (ws,))
        cur.execute("DELETE FROM graph_entities WHERE workspace_id=%s", (ws,))
        cur.execute("SELECT id FROM documents WHERE workspace_id=%s", (ws,))
        doc_ids = [r["id"] for r in cur.fetchall()]
    for did in doc_ids:
        build_graph_for_document(db, ws, did)
    return {"documents": len(doc_ids), "entities": count_entities(db, ws)}


def count_entities(db: DB, ws: int) -> int:
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) n FROM graph_entities WHERE workspace_id=%s", (ws,))
        return cur.fetchone()["n"]


# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 read / retrieval \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
def list_entities(db: DB, ws: int, query: str = "", limit: int = 50) -> list[dict]:
    with db.pool.connection() as conn, conn.cursor() as cur:
        if query.strip():
            cur.execute("""SELECT id, name, kind, mention_count FROM graph_entities
                           WHERE workspace_id=%s AND norm LIKE %s
                           ORDER BY mention_count DESC, name LIMIT %s""",
                        (ws, f"%{query.strip().lower()}%", limit))
        else:
            cur.execute("""SELECT id, name, kind, mention_count FROM graph_entities
                           WHERE workspace_id=%s ORDER BY mention_count DESC, name LIMIT %s""",
                        (ws, limit))
        return [dict(r) for r in cur.fetchall()]


def get_entity(db: DB, ws: int, entity_id: int) -> dict | None:
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name, kind, mention_count FROM graph_entities WHERE id=%s AND workspace_id=%s",
                    (entity_id, ws))
        ent = cur.fetchone()
        if not ent:
            return None
        cur.execute("""SELECT m.section_id, s.heading, d.id document_id, d.title doc_title
                       FROM graph_mentions m JOIN sections s ON s.id=m.section_id
                       JOIN documents d ON d.id=m.document_id
                       WHERE m.entity_id=%s LIMIT 100""", (entity_id,))
        sections = [dict(r) for r in cur.fetchall()]
        cur.execute("""SELECT e.id, e.name, e.kind,
                              CASE WHEN g.src_id=%s THEN g.dst_id ELSE g.src_id END other, g.weight
                       FROM graph_edges g
                       JOIN graph_entities e ON e.id = CASE WHEN g.src_id=%s THEN g.dst_id ELSE g.src_id END
                       WHERE g.workspace_id=%s AND (g.src_id=%s OR g.dst_id=%s)
                       ORDER BY g.weight DESC LIMIT 25""",
                    (entity_id, entity_id, ws, entity_id, entity_id))
        neighbors = [{"id": r["id"], "name": r["name"], "kind": r["kind"], "weight": r["weight"]}
                     for r in cur.fetchall()]
    return {"entity": dict(ent), "sections": sections, "neighbors": neighbors}


def graph_stream(db: DB, ws: int, query: str, limit: int = 30) -> list[tuple[int, float]]:
    """Retrieval signal: sections whose entities match the query terms.
    Returns [(section_id, score)] for RRF fusion."""
    toks = [t.lower() for t in re.findall(r"[^\W_]+", query or "") if len(t) >= 3]
    if not toks:
        return []
    likes = " OR ".join(["norm LIKE %s"] * len(toks))
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT id FROM graph_entities WHERE workspace_id=%s AND ({likes})",
                    (ws, *[f"%{t}%" for t in toks]))
        eids = [r["id"] for r in cur.fetchall()]
        if not eids:
            return []
        cur.execute("""SELECT section_id, count(*) c FROM graph_mentions
                       WHERE entity_id = ANY(%s::bigint[]) AND section_id IS NOT NULL
                       GROUP BY section_id ORDER BY c DESC LIMIT %s""", (eids, limit))
        return [(r["section_id"], float(r["c"])) for r in cur.fetchall()]
