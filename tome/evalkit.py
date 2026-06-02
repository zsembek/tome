"""Tome eval harness: proving quality with numbers, not claims.

Metrics:
  * faithfulness % — corpus-wide aggregate of extraction completeness (from ingestion_jobs);
  * retrieval recall@k / precision@k — over a golden set of "query → relevant sections".

Golden set (JSON):
[
  {"query": "pump pressure", "relevant_doc_titles": ["Pump NTs-100 manual"]},
  {"query": "...", "relevant_section_headings": ["2.2 Commissioning"]}
]
Relevance is matched by title/heading containment (with no hard binding to id)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from tome.config import get_config
from tome.db import DB
from tome.embed import get_embedder
from tome.store import hybrid_search

log = logging.getLogger("tome.eval")


def corpus_faithfulness(db: DB) -> dict:
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT count(*) n, AVG(faithfulness_score) avg, MIN(faithfulness_score) mn
                       FROM documents WHERE faithfulness_score IS NOT NULL""")
        r = cur.fetchone()
        cur.execute("""SELECT count(*) low FROM documents
                       WHERE faithfulness_score < %s""", (get_config().faithfulness_min,))
        low = cur.fetchone()["low"]
    return {"documents_scored": r["n"], "avg_faithfulness": round(float(r["avg"] or 0), 3),
            "min_faithfulness": round(float(r["mn"] or 0), 3), "below_threshold": low}


def retrieval_metrics(db: DB, golden: list[dict], ws: int, k: int = 10,
                      mode: str = "hybrid") -> dict:
    cfg = get_config()
    embedder = get_embedder(cfg) if mode in ("hybrid", "vector") else None
    recalls, precisions = [], []
    per_query = []
    for case in golden:
        q = case["query"]
        qemb = None
        if embedder:
            try:
                qemb = embedder.embed([q])[0]
            except Exception:
                qemb = None
        res = hybrid_search(db, workspace_id=ws, query=q, query_embedding=qemb,
                            top_k=k, mode=mode)
        rel_titles = [t.lower() for t in case.get("relevant_doc_titles", [])]
        rel_heads = [h.lower() for h in case.get("relevant_section_headings", [])]
        hits = 0
        for r in res:
            dt = (r.get("doc_title") or "").lower()
            hd = (r.get("heading") or "").lower()
            if any(t in dt for t in rel_titles) or any(h in hd for h in rel_heads):
                hits += 1
        total_rel = max(1, len(rel_titles) + len(rel_heads))
        recall = min(1.0, hits / total_rel)
        precision = hits / max(1, len(res))
        recalls.append(recall); precisions.append(precision)
        per_query.append({"query": q, "hits": hits, "returned": len(res),
                          "recall": round(recall, 3), "precision": round(precision, 3)})
    n = max(1, len(golden))
    return {"queries": len(golden), "mode": mode, "k": k,
            "recall_at_k": round(sum(recalls) / n, 3),
            "precision_at_k": round(sum(precisions) / n, 3),
            "per_query": per_query}


def run_eval(db: DB, golden_path: str | None, ws: int) -> dict:
    out = {"faithfulness": corpus_faithfulness(db)}
    if golden_path and Path(golden_path).exists():
        golden = json.loads(Path(golden_path).read_text(encoding="utf-8"))
        out["retrieval"] = retrieval_metrics(db, golden, ws)
    return out
