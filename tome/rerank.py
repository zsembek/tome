"""Pluggable reranker for hybrid search. Applied after RRF fusion.

Providers: cohere | bge (local cross-encoder) | none. Without a reranker,
results are returned as is (by RRF score)."""
from __future__ import annotations

import logging

from tome.config import Config, get_config

log = logging.getLogger(__name__)
_reranker = None
_NONE = object()


def get_reranker(cfg: Config | None = None):
    global _reranker
    if _reranker is not None:
        return None if _reranker is _NONE else _reranker
    cfg = cfg or get_config()
    name = getattr(cfg, "reranker", "") or ""
    if not name or name == "none":
        _reranker = _NONE
        return None
    try:
        if name.startswith("cohere"):
            _reranker = _CohereReranker(cfg)
        else:
            _reranker = _BGEReranker(name)
    except Exception as exc:
        log.warning("reranker %s unavailable (%s) — running without reranking", name, exc)
        _reranker = _NONE
        return None
    return _reranker


class _BGEReranker:
    def __init__(self, model: str):
        from sentence_transformers import CrossEncoder
        self.m = CrossEncoder(model if "/" in model else "BAAI/bge-reranker-v2-m3")

    def rerank(self, query: str, docs: list[str]) -> list[float]:
        return [float(s) for s in self.m.predict([(query, d) for d in docs])]


class _CohereReranker:
    def __init__(self, cfg: Config):
        import cohere
        self.client = cohere.Client(api_key=getattr(cfg, "cohere_api_key", ""))
        self.model = "rerank-multilingual-v3.0"

    def rerank(self, query: str, docs: list[str]) -> list[float]:
        r = self.client.rerank(model=self.model, query=query, documents=docs)
        scores = [0.0] * len(docs)
        for res in r.results:
            scores[res.index] = res.relevance_score
        return scores
