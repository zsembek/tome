"""Smoke tests for the shared test harness (fixtures must behave deterministically)."""
import pytest

from tome.llm.base import ChatResult

pytestmark = pytest.mark.unit


def test_fake_llm_chat_is_deterministic(fake_llm):
    r1 = fake_llm.chat(system="s", user="hello 0.7 MPa", model="m")
    r2 = fake_llm.chat(system="s", user="hello 0.7 MPa", model="m")
    assert isinstance(r1, ChatResult)
    assert r1.text == r2.text == "hello 0.7 MPa"
    assert r1.finish_reason == "stop"


def test_fake_llm_vision_returns_text(fake_llm):
    r = fake_llm.vision(system="s", prompt="p", image_bytes=b"x", image_mime="image/png", model="m")
    assert isinstance(r, ChatResult) and r.text


def test_fake_embedder_deterministic_and_sized(fake_embedder):
    v1 = fake_embedder.embed(["a", "b"])
    v2 = fake_embedder.embed(["a", "b"])
    assert v1 == v2
    assert len(v1) == 2 and len(v1[0]) == fake_embedder.dim == 8
    assert fake_embedder.embed([]) == []


def test_tmp_store_roundtrip_and_traversal_blocked(tmp_store):
    tmp_store.put("ok/file.txt", b"data")
    assert tmp_store.get("ok/file.txt") == b"data"
    assert str(tmp_store.root).endswith("store")
    for evil in ["../../../../etc/passwd", "/etc/passwd", "ok/../../../x"]:
        assert tmp_store.get(evil) is None, f"traversal not blocked: {evil}"


def test_sample_fixtures(sample_markdown, sample_pdf_bytes):
    assert sample_markdown.startswith("# Pump")
    assert sample_pdf_bytes[:4] == b"%PDF"
