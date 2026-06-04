"""Ingestion speed optimizations: parallel per-page structuring (Tier 1),
single-call vision (Tier 2), and smarter LLM-skip / optional escalation (Tier 3)."""
import time

import pytest

from tome.config import Config
from tome.pipeline.structure import looks_clean

pytestmark = pytest.mark.unit


# ── Tier 3: smart-skip ──────────────────────────────────────────────
def test_clean_prose_without_headings_skips_llm():
    # a clean digital-PDF paragraph (no markdown heading) should NOT need the LLM
    prose = ("This section describes the routine maintenance of the centrifugal pump. "
             "Check the oil level before every shift and record the readings in the log. "
             "Replace the seals according to the maintenance schedule provided by the maker.")
    assert looks_clean(prose) is True


def test_noisy_text_still_needs_llm():
    assert looks_clean("wo\nrd\nby\nwo\nrd\nbr\nok\nen") is False


def test_heading_doc_still_clean():
    assert looks_clean("# Title\n\nA sufficiently long and clean paragraph of body text here.") is True


# ── Tier 2: single-call vision ──────────────────────────────────────
class _CountingLLM:
    def __init__(self):
        self.vision_calls = 0

    def vision(self, **kw):
        self.vision_calls += 1
        from tome.llm.base import ChatResult
        return ChatResult(text='{"informative": true, "fig_class": "diagram", '
                               '"description": "A flow diagram of the process."}',
                          tokens_in=10, tokens_out=10, finish_reason="stop")


def test_vision_uses_a_single_call(monkeypatch):
    import tome.pipeline.vision as v
    llm = _CountingLLM()
    monkeypatch.setattr(v, "get_llm", lambda cfg: llm)
    out = v.classify_and_describe(b"\x89PNG fake", Config(), "en")
    assert llm.vision_calls == 1                      # one round-trip, not two
    assert out["informative"] is True
    assert "diagram" in (out["fig_class"] or "")
    assert "flow diagram" in out["description"].lower()


def test_vision_skips_logo_without_describe_call(monkeypatch):
    import tome.pipeline.vision as v

    class _Logo(_CountingLLM):
        def vision(self, **kw):
            self.vision_calls += 1
            from tome.llm.base import ChatResult
            return ChatResult(text='{"informative": false, "fig_class": "logo", "description": ""}',
                              tokens_in=5, tokens_out=2, finish_reason="stop")
    llm = _Logo()
    monkeypatch.setattr(v, "get_llm", lambda cfg: llm)
    out = v.classify_and_describe(b"img", Config(), "en")
    assert llm.vision_calls == 1
    assert out["informative"] is False
    assert out["description"] == ""


# ── Tier 1: parallel per-page processing ────────────────────────────
def test_page_concurrency_config_default():
    assert Config().page_concurrency == 4


def test_map_concurrent_preserves_order_and_runs_in_parallel():
    """The per-page concurrency primitive: results are ordered by input index, and N
    slow tasks finish in ~1 task-time (not N×) when concurrency covers them."""
    from tome.pipeline.run import _map_concurrent

    def slow(x):
        time.sleep(0.3)
        return x * 2

    t0 = time.monotonic()
    out = _map_concurrent(list(range(6)), slow, concurrency=6)
    elapsed = time.monotonic() - t0

    assert out == [0, 2, 4, 6, 8, 10]      # ordered, regardless of completion order
    assert elapsed < 1.2                   # parallel: ~0.3s, not 6×0.3=1.8s


def test_map_concurrent_serial_when_concurrency_one():
    from tome.pipeline.run import _map_concurrent
    assert _map_concurrent([1, 2, 3], lambda x: x + 1, concurrency=1) == [2, 3, 4]
