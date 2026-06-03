"""WI-3.2 + WI-3.4: tiers, observe → consolidate, decay/GC eviction.

Memory tiers: working (raw observations) → episodic (session summary) →
semantic (durable facts). Consolidation uses an LLM when available and falls
back to a deterministic raw roll-up otherwise."""
import pytest

from tome import memory
from tome.llm.base import ChatResult

pytestmark = pytest.mark.integration


class _FactsLLM:
    """Fake LLM that returns a structured consolidation (summary + facts)."""

    def chat(self, *, system, user, model, max_tokens=4000, temperature=0.2, json=False):
        text = ("## Summary\n\nThe user configured the pump and set the pressure.\n\n"
                "## Key facts\n\n- The pump model is NTs-100.\n- Target pressure is 0.7 MPa.\n")
        return ChatResult(text=text, tokens_in=10, tokens_out=20, finish_reason="stop")

    def vision(self, **kw):
        return ChatResult(text="", finish_reason="stop")


def test_observe_appends_working(db_fresh):
    ws = db_fresh.default_workspace()
    memory.observe(db_fresh, ws=ws, agent_id="a1", session_id="s1", content="user opened the pump page")
    memory.observe(db_fresh, ws=ws, agent_id="a1", session_id="s1", content="user set pressure to 0.7 MPa")
    memory.observe(db_fresh, ws=ws, agent_id="a1", session_id="s1", content="user opened the pump page")  # dup
    working = memory.list_memory(db_fresh, ws=ws, agent_id="a1", tier="working")
    assert len(working) == 2, "duplicate observation should be de-duplicated"


def test_consolidate_with_llm_creates_episodic_and_facts(db_fresh):
    ws = db_fresh.default_workspace()
    memory.observe(db_fresh, ws=ws, agent_id="a1", session_id="s1", content="user opened the pump page")
    memory.observe(db_fresh, ws=ws, agent_id="a1", session_id="s1", content="user set pressure to 0.7 MPa")
    res = memory.consolidate(db_fresh, ws=ws, agent_id="a1", session_id="s1",
                             llm=_FactsLLM(), model="fake")
    assert res["episodic_id"]
    assert res["facts"] >= 2
    ep = memory.get_memory(db_fresh, ws=ws, mem_id=res["episodic_id"])
    assert ep["tier"] == "episodic"
    assert "##" in ep["content"]  # markdown summary
    # semantic facts were promoted
    sem = memory.list_memory(db_fresh, ws=ws, agent_id="a1", tier="semantic")
    assert any("NTs-100" in s["content"] for s in sem)
    # working observations for the session are consolidated (no longer surfaced as working)
    assert memory.list_memory(db_fresh, ws=ws, agent_id="a1", tier="working") == []


def test_consolidate_without_llm_falls_back_to_raw(db_fresh):
    ws = db_fresh.default_workspace()
    memory.observe(db_fresh, ws=ws, agent_id="a1", session_id="s2", content="observation alpha")
    memory.observe(db_fresh, ws=ws, agent_id="a1", session_id="s2", content="observation beta")
    res = memory.consolidate(db_fresh, ws=ws, agent_id="a1", session_id="s2", llm=None)
    assert res["episodic_id"]
    ep = memory.get_memory(db_fresh, ws=ws, mem_id=res["episodic_id"])
    assert "observation alpha" in ep["content"] and "observation beta" in ep["content"]


def test_consolidate_empty_session_is_noop(db_fresh):
    ws = db_fresh.default_workspace()
    res = memory.consolidate(db_fresh, ws=ws, agent_id="a1", session_id="nope", llm=None)
    assert res["episodic_id"] is None and res["working_consolidated"] == 0


def test_decay_evicts_stale_low_importance(db_fresh):
    ws = db_fresh.default_workspace()
    keep = memory.remember(db_fresh, ws=ws, agent_id="a1", tier="semantic",
                           content="durable important fact", importance=1.0)
    drop = memory.remember(db_fresh, ws=ws, agent_id="a1", tier="episodic",
                           content="trivial stale note", importance=0.3)
    # backdate the trivial one far into the past so decay drives it below the floor
    with db_fresh.pool.connection() as c, c.cursor() as cur:
        cur.execute("UPDATE agent_memory SET last_accessed_at = NOW() - INTERVAL '120 days', "
                    "created_at = NOW() - INTERVAL '120 days' WHERE id=%s", (drop["id"],))
    report = memory.decay_and_gc(db_fresh, ws=ws, half_life_days=30.0, min_importance=0.05)
    assert drop["id"] in report["evicted"]
    assert keep["id"] not in report["evicted"]
    assert memory.get_memory(db_fresh, ws=ws, mem_id=drop["id"]) is None
    assert memory.get_memory(db_fresh, ws=ws, mem_id=keep["id"]) is not None


def test_recall_reinforces_importance(db_fresh):
    ws = db_fresh.default_workspace()
    m = memory.remember(db_fresh, ws=ws, agent_id="a1", content="reinforce me on recall", importance=0.5)
    memory.recall(db_fresh, ws=ws, agent_id="a1", query="reinforce recall", top_k=5)
    got = memory.get_memory(db_fresh, ws=ws, mem_id=m["id"])
    assert got["access_count"] >= 1
    assert got["importance"] > 0.5  # recall reinforces
