"""High-level storage operations: atomic document write, hybrid search.
Uses the DB pool. Writing sections/parts/chunks/embeddings is a single transaction."""
from __future__ import annotations

import logging

from tome.db import DB, _regconfig

log = logging.getLogger(__name__)


def store_document_atomic(db: DB, *, workspace_id: int, folder_id: int | None,
                          meta: dict, parts: list[str], sections: list,
                          chunks_by_section: dict, embeddings_by_chunk: dict | None,
                          language: str) -> int:
    """Writes the document fully within a SINGLE transaction (or updates an existing one).
    sections — list[Section] from pipeline.split. chunks_by_section: {sec_oi: [Chunk]}.
    embeddings_by_chunk: {(sec_oi, ordinal): vector} | None.
    Returns document_id."""
    from tome.config import get_config
    rc = get_config().fts_config   # single FTS config (default 'simple')
    with db.pool.connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            # document (upsert on content_hash match — the skip is done upstream)
            cur.execute("""INSERT INTO documents
                (workspace_id, folder_id, title, summary, tags, source_filename, mime_type,
                 extractor, language, parts, section_count, total_chars, content_hash,
                 pipeline_version, faithfulness_score, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ready')
                RETURNING id""",
                (workspace_id, folder_id, meta["title"], meta.get("summary", ""),
                 meta.get("tags", []), meta.get("source_filename", ""),
                 meta.get("mime_type", ""), meta.get("extractor", ""), language,
                 len(parts), len(sections), sum(len(p) for p in parts),
                 meta.get("content_hash", ""), meta.get("pipeline_version", ""),
                 meta.get("faithfulness_score")))
            doc_id = cur.fetchone()["id"]

            # parts
            for i, content in enumerate(parts, start=1):
                cur.execute("""INSERT INTO document_parts (document_id, part_number, content, char_count)
                               VALUES (%s,%s,%s,%s)""", (doc_id, i, content, len(content)))

            # sections (parent via order_index → real id)
            oi_to_id: dict[int, int] = {}
            for s in sections:
                parent_real = oi_to_id.get(s.parent_order_index) if s.parent_order_index is not None else None
                cur.execute("""INSERT INTO sections
                    (document_id, parent_id, order_index, level, heading, breadcrumb,
                     anchor_slug, content, char_count, language, tsv)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, to_tsvector(%s::regconfig,%s))
                    RETURNING id""",
                    (doc_id, parent_real, s.order_index, s.level, s.heading, s.breadcrumb,
                     s.anchor_slug, s.content, len(s.content), language, rc, s.content))
                oi_to_id[s.order_index] = cur.fetchone()["id"]

            # retrieval chunks + embeddings (the embedding column exists only with pgvector)
            has_vec = db.has_vector() and embeddings_by_chunk is not None
            for sec_oi, chunks in chunks_by_section.items():
                sid = oi_to_id.get(sec_oi)
                if sid is None:
                    continue
                for ch in chunks:
                    if has_vec:
                        emb = embeddings_by_chunk.get((sec_oi, ch.ordinal))
                        cur.execute("""INSERT INTO retrieval_chunks
                            (section_id, document_id, ordinal, text, token_count, embed_model_id, embedding)
                            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                            (sid, doc_id, ch.ordinal, ch.text, ch.token_count,
                             meta.get("embed_model_id", ""), _vec(emb)))
                    else:
                        cur.execute("""INSERT INTO retrieval_chunks
                            (section_id, document_id, ordinal, text, token_count, embed_model_id)
                            VALUES (%s,%s,%s,%s,%s,%s)""",
                            (sid, doc_id, ch.ordinal, ch.text, ch.token_count,
                             meta.get("embed_model_id", "")))
            # document version
            cur.execute("""INSERT INTO document_versions
                (document_id, version_no, content_hash, pipeline_version, faithfulness_score, change_kind)
                VALUES (%s,1,%s,%s,%s,'import')""",
                (doc_id, meta.get("content_hash", ""), meta.get("pipeline_version", ""),
                 meta.get("faithfulness_score")))
    return doc_id


def _vec(v):
    if not v:
        return None
    return "[" + ",".join(str(x) for x in v) + "]"


def hybrid_search(db: DB, *, workspace_id: int, query: str, query_embedding: list[float] | None,
                  top_k: int = 10, mode: str = "hybrid") -> list[dict]:
    """BM25 (tsv) + ANN (pgvector) → RRF fusion. Without an embedding — BM25 only."""
    bm25 = _bm25(db, workspace_id, query, top_k * 3) if mode in ("hybrid", "bm25") else []
    ann = _ann(db, workspace_id, query_embedding, top_k * 3) if (mode in ("hybrid", "vector") and query_embedding) else []
    # for the reranker we take more candidates, then trim to top_k
    fused = _rrf(bm25, ann, top_k * 3)
    if not fused:
        return []
    ids = [sid for sid, _ in fused]
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT s.id, s.document_id, s.heading, s.breadcrumb, s.content,
                              d.title doc_title, d.folder_id
                       FROM sections s JOIN documents d ON d.id=s.document_id
                       WHERE s.id = ANY(%s::bigint[])""", (ids,))
        rows = {r["id"]: r for r in cur.fetchall()}
    out = []
    for sid, score in fused:
        if sid in rows:
            r = dict(rows[sid]); r["score"] = round(score, 4); out.append(r)

    # optional reranking
    try:
        from tome.rerank import get_reranker
        rr = get_reranker()
        if rr and out:
            docs = [(r["heading"] + "\n" + (r["content"] or ""))[:2000] for r in out]
            scores = rr.rerank(query, docs)
            for r, s in zip(out, scores):
                r["rerank_score"] = round(float(s), 4)
            out.sort(key=lambda r: -r.get("rerank_score", 0))
    except Exception as exc:
        log.debug("rerank skipped: %s", exc)
    return out[:top_k]


def _bm25(db, ws, query, limit):
    from tome.config import get_config
    fts = get_config().fts_config
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(f"""SELECT s.id, ts_rank(s.tsv, plainto_tsquery('{fts}', %s)) rank
                       FROM sections s JOIN documents d ON d.id=s.document_id
                       WHERE d.workspace_id=%s AND s.tsv @@ plainto_tsquery('{fts}', %s)
                       ORDER BY rank DESC LIMIT %s""", (query, ws, query, limit))
        return [(r["id"], float(r["rank"])) for r in cur.fetchall()]


def _ann(db, ws, qemb, limit):
    if not qemb:
        return []
    vec = _vec(qemb)
    with db.pool.connection() as conn, conn.cursor() as cur:
        try:
            cur.execute("""SELECT c.section_id id, 1-(c.embedding <=> %s::vector) sim
                           FROM retrieval_chunks c JOIN documents d ON d.id=c.document_id
                           WHERE d.workspace_id=%s AND c.embedding IS NOT NULL
                           ORDER BY c.embedding <=> %s::vector LIMIT %s""", (vec, ws, vec, limit))
            seen, out = set(), []
            for r in cur.fetchall():
                if r["id"] not in seen:
                    seen.add(r["id"]); out.append((r["id"], float(r["sim"])))
            return out
        except Exception as exc:
            log.warning("ANN unavailable (%s) — BM25 only", exc)
            return []


def _rrf(a, b, top_k, k=60):
    scores: dict[int, float] = {}
    for lst in (a, b):
        for rank, (sid, _) in enumerate(lst):
            scores[sid] = scores.get(sid, 0.0) + 1.0 / (k + rank + 1)
    ranked = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
    return ranked
