"""Hybrid search: RRF fusion (pure), reranker pluggability, and the full
vector path (embeddings → HNSW → ANN) end-to-end on Postgres."""
import os

import pytest


@pytest.mark.unit
def test_rrf_fusion_prefers_common_hits():
    from tome.store import _rrf
    bm25 = [(1, 0.9), (2, 0.5), (3, 0.2)]
    ann = [(2, 0.8), (4, 0.7), (1, 0.1)]
    fused = _rrf(bm25, ann, top_k=10)
    ids = [sid for sid, _ in fused]
    # sections present in BOTH lists (1, 2) must outrank single-list ones (3, 4)
    assert set(ids[:2]) == {1, 2}


@pytest.mark.unit
def test_get_reranker_none_returns_none():
    import tome.rerank as rr
    from tome.config import Config
    rr._reranker = None
    cfg = Config(); cfg.reranker = "none"
    assert rr.get_reranker(cfg) is None


@pytest.mark.integration
def test_vector_and_hybrid_search_end_to_end():
    if not os.environ.get("TOME_TEST_DSN"):
        pytest.skip("TOME_TEST_DSN is not set")
    from tome.config import Config
    from tome.db import DB
    from tome.embed.hashing import HashEmbedder
    from tome.pipeline.run import ingest
    from tome.store import hybrid_search

    cfg = Config()
    cfg.embed_enabled = True
    cfg.embed_provider = "hash"
    cfg.extract_primary = "passthrough"
    cfg.extract_fallback = ""
    db = DB(cfg)
    with db.pool.connection() as c, c.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS tome_test CASCADE")
    db.init_schema()
    ws = db.default_workspace()
    try:
        ingest(db, workspace_id=ws, cfg=cfg, mime="text/markdown", filename="pumps.md",
               file_bytes=b"# Pumps\n\nCentrifugal pump pressure and flow rate.\n", folder_path="V/A")
        ingest(db, workspace_id=ws, cfg=cfg, mime="text/markdown", filename="safety.md",
               file_bytes=b"# Safety\n\nWear protective equipment and gloves.\n", folder_path="V/B")

        qvec = HashEmbedder(cfg).embed(["pump pressure flow"])[0]

        vec = hybrid_search(db, workspace_id=ws, query="pump pressure flow",
                            query_embedding=qvec, top_k=5, mode="vector")
        assert vec, "vector search returned nothing"
        top = vec[0]
        assert "pump" in (top["content"] or "").lower() or "Pump" in top["doc_title"]

        hyb = hybrid_search(db, workspace_id=ws, query="pump", query_embedding=qvec,
                            top_k=5, mode="hybrid")
        assert hyb

        # HNSW index was built once the embedding dimension was known
        with db.pool.connection() as c, c.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_indexes WHERE indexname='ix_chunks_embedding'")
            assert cur.fetchone() is not None, "HNSW index was not created"
    finally:
        with db.pool.connection() as c, c.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS tome_test CASCADE")
        db.close()
