"""Local / offline embedders: deterministic hash embedder (zero deps) + fastembed wiring."""
import importlib.util

import pytest

from tome.config import Config

pytestmark = pytest.mark.contract


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b))   # vectors are normalized → dot == cosine


def test_hash_embedder_deterministic_and_overlap():
    from tome.embed.hashing import HashEmbedder
    e = HashEmbedder(Config())
    assert e.embed(["pump pressure flow"]) == e.embed(["pump pressure flow"])
    assert len(e.embed(["x"])[0]) == e.dim == 256
    assert e.embed([]) == []
    a = e.embed(["pump pressure flow"])[0]
    b = e.embed(["pump pressure rating"])[0]   # shares pump/pressure
    c = e.embed(["safety helmet gloves"])[0]   # disjoint
    assert _cos(a, b) > _cos(a, c)


def test_get_embedder_routes_hash():
    import tome.embed.registry as r
    r._cache.clear()
    cfg = Config(); cfg.embed_enabled = True; cfg.embed_provider = "hash"
    from tome.embed.hashing import HashEmbedder
    assert isinstance(r.get_embedder(cfg), HashEmbedder)


def test_get_embedder_disabled_returns_none():
    import tome.embed.registry as r
    cfg = Config(); cfg.embed_enabled = False
    assert r.get_embedder(cfg) is None


@pytest.mark.skipif(importlib.util.find_spec("fastembed") is None, reason="fastembed not installed")
def test_fastembed_real():
    from tome.embed.fastembed_provider import FastEmbedEmbedder
    e = FastEmbedEmbedder(Config())
    v = e.embed(["hello world"])
    assert v and e.dim > 0 and len(v[0]) == e.dim
