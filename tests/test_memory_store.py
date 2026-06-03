"""WI-3.1: agent_memory store — remember / recall / list / get / forget.

Memory content is canonical Markdown, lives in its own table (no Atlas / folder
pollution), and is retrievable by BM25. WI-3.4 supersession + visibility scoping
are exercised here too."""
import json

import pytest

from tome import memory

pytestmark = pytest.mark.integration


def test_remember_then_recall_markdown(db_fresh):
    ws = db_fresh.default_workspace()
    memory.remember(db_fresh, ws=ws, agent_id="a1",
                    content="## Pump NTs-100\n\nRuns at **0.7 MPa**, 11 kW.",
                    title="pump facts", tier="semantic")
    hits = memory.recall(db_fresh, ws=ws, agent_id="a1", query="pump pressure", top_k=5)
    assert hits, "recall returned nothing"
    top = hits[0]
    # canonical markdown round-trips (headings/bold preserved), not a JSON blob
    assert "0.7 MPa" in top["content"] and "##" in top["content"]
    with pytest.raises(Exception):
        json.loads(top["content"])


def test_get_and_list_and_forget_audits(db_fresh):
    ws = db_fresh.default_workspace()
    m = memory.remember(db_fresh, ws=ws, agent_id="a1", content="remember me", title="t")
    got = memory.get_memory(db_fresh, ws=ws, mem_id=m["id"])
    assert got and got["content"] == "remember me"
    lst = memory.list_memory(db_fresh, ws=ws, agent_id="a1")
    assert any(x["id"] == m["id"] for x in lst)
    assert memory.forget(db_fresh, ws=ws, mem_id=m["id"], reason="test") is True
    assert memory.get_memory(db_fresh, ws=ws, mem_id=m["id"]) is None
    # forget is audited
    with db_fresh.pool.connection() as c, c.cursor() as cur:
        cur.execute("SELECT count(*) n FROM memory_audit WHERE action='forget' AND memory_id=%s", (m["id"],))
        assert cur.fetchone()["n"] == 1


def test_memory_not_in_kb_atlas_or_folder_tree(db_fresh):
    ws = db_fresh.default_workspace()
    memory.remember(db_fresh, ws=ws, agent_id="a1", content="secret memory content xyzzy")
    # memory must not leak into the document KB surfaces
    assert db_fresh.folder_tree(ws) == [] or all("xyzzy" not in (f.get("name") or "")
                                                  for f in db_fresh.folder_tree(ws))
    with db_fresh.pool.connection() as c, c.cursor() as cur:
        cur.execute("SELECT count(*) n FROM documents WHERE workspace_id=%s", (ws,))
        assert cur.fetchone()["n"] == 0
        cur.execute("SELECT count(*) n FROM sections")
        assert cur.fetchone()["n"] == 0


def test_supersede_on_same_key(db_fresh):
    ws = db_fresh.default_workspace()
    old = memory.remember(db_fresh, ws=ws, agent_id="a1", mkey="user.name",
                          content="The user's name is Alex.")
    new = memory.remember(db_fresh, ws=ws, agent_id="a1", mkey="user.name",
                          content="The user's name is Alexandra.")
    hits = memory.recall(db_fresh, ws=ws, agent_id="a1", query="user name", top_k=10)
    contents = " ".join(h["content"] for h in hits)
    assert "Alexandra" in contents and "is Alex." not in contents
    # the old row is marked superseded (kept for audit, hidden from recall)
    with db_fresh.pool.connection() as c, c.cursor() as cur:
        cur.execute("SELECT superseded_by FROM agent_memory WHERE id=%s", (old["id"],))
        assert cur.fetchone()["superseded_by"] == new["id"]


def test_scope_isolated_vs_shared(db_fresh):
    ws = db_fresh.default_workspace()
    memory.remember(db_fresh, ws=ws, agent_id="a1", scope="agent", content="private to a1 only")
    memory.remember(db_fresh, ws=ws, agent_id="a1", scope="shared", content="shared with everyone")
    # a2 sees the shared one but NOT a1's private memory
    a2 = memory.recall(db_fresh, ws=ws, agent_id="a2", query="private shared everyone only", top_k=10)
    blob2 = " ".join(h["content"] for h in a2)
    assert "shared with everyone" in blob2
    assert "private to a1 only" not in blob2
    # a1 sees both
    a1 = memory.recall(db_fresh, ws=ws, agent_id="a1", query="private shared everyone only", top_k=10)
    blob1 = " ".join(h["content"] for h in a1)
    assert "private to a1 only" in blob1 and "shared with everyone" in blob1


def test_remember_redacts_secrets(db_fresh):
    ws = db_fresh.default_workspace()
    m = memory.remember(db_fresh, ws=ws, agent_id="a1",
                        content="api key sk-abcdEFGH1234567890ijklMNOP do not store")
    got = memory.get_memory(db_fresh, ws=ws, mem_id=m["id"])
    assert "sk-abcdEFGH1234567890ijklMNOP" not in got["content"]
    assert "do not store" in got["content"]
