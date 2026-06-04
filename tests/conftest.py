"""Shared pytest fixtures + test environment.

Unit/contract tests need no DB and no network (fakes + tmp object store).
Integration tests use a throwaway `tome_test` schema and are skipped unless
TOME_TEST_DSN is set."""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DSN = os.environ.get("TOME_TEST_DSN")

# Route the app/integration suite to a throwaway schema when a test DB is given.
if DSN:
    os.environ["POSTGRES_DSN"] = DSN
    os.environ.setdefault("TOME_SCHEMA", "tome_test")
    os.environ.setdefault("EMBED_ENABLED", "false")
    os.environ.setdefault("EXTRACT_PRIMARY", "passthrough")
    os.environ.setdefault("EXTRACT_FALLBACK", "")
    os.environ.setdefault("RUN_INPROCESS_WORKER", "false")
    # Disable the global in-process rate limiter for the suite: its state is module-level
    # and survives the per-test schema drop, so hundreds of requests across the suite would
    # otherwise trip 429 on late tests. The dedicated rate-limit test installs its own.
    os.environ["RATE_LIMIT_PER_MIN"] = "0"
    os.environ.setdefault("STRUCTURE_SMART", "true")
    os.environ["STRUCTURE_ENABLED"] = "false"   # no LLM restructuring in tests (fast, offline)
    os.environ.setdefault("TOME_OPEN", "true")
    # Hard-neutralize any real LLM/cloud credentials that a local tome/.env would
    # otherwise leak into the test process. Tests must be offline, deterministic, and
    # free — the pipeline degrades gracefully to raw text when no LLM is reachable.
    os.environ["LLM_PROVIDER"] = "openai"
    os.environ["OPENAI_API_KEY"] = "test-no-network"
    # Point at a closed local port and use a 1s timeout + no retries so any accidental
    # LLM call fails almost immediately. The pipeline degrades gracefully to raw text —
    # keeping the suite fast, offline and deterministic.
    os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:9/v1"
    os.environ["LLM_TIMEOUT"] = "1"
    os.environ["LLM_MAX_RETRIES"] = "0"
    for _k in ("AZURE_OPENAI_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_DI_KEY",
               "AZURE_DI_ENDPOINT", "ANTHROPIC_API_KEY", "COHERE_API_KEY",
               "MISTRAL_API_KEY", "LLAMAPARSE_API_KEY"):
        os.environ[_k] = ""

from tome.llm.base import ChatResult  # noqa: E402  (after sys.path setup)


class FakeLLM:
    """Deterministic in-memory LLM provider (no network). Conforms to LLMProvider."""

    def chat(self, *, system, user, model, max_tokens=4000, temperature=0.2, json=False) -> ChatResult:
        return ChatResult(text=user, tokens_in=len(user) // 4, tokens_out=len(user) // 4,
                          finish_reason="stop")

    def vision(self, *, system, prompt, image_bytes, image_mime, model, max_tokens=2000) -> ChatResult:
        return ChatResult(text="Figure: a schematic diagram.", tokens_in=1, tokens_out=5,
                          finish_reason="stop")


class FakeEmbedder:
    """Deterministic embedder (sha256-derived); no model download, fully offline."""

    model_id = "fake-embed"
    dim = 8

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            out.append([b / 255.0 for b in h[: self.dim]])
        return out


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    """A LocalStore rooted in a tmp dir (resets the config/store singletons)."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "store"))
    import tome.config as cfgmod
    import tome.storage as st
    cfgmod._cfg = None
    st._store = None
    store = st.get_store()
    try:
        yield store
    finally:
        cfgmod._cfg = None
        st._store = None


@pytest.fixture
def sample_markdown() -> str:
    return ("# Pump NTs-100\n\nCentrifugal pump.\n\n"
            "## Specifications\n\nPressure 0.7 MPa, power 11 kW, flow 36000 L/h.\n\n"
            "## Operation\n\nCheck the oil level.\n")


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    import fitz  # PyMuPDF (core dependency)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Pump NTs-100  Pressure 0.7 MPa  Power 11 kW")
    data = doc.tobytes()
    doc.close()
    return data


def _drop_test_schema():
    from tome.db import DB
    db = DB()
    try:
        with db.pool.connection() as c, c.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS tome_test CASCADE")
    finally:
        db.close()


@pytest.fixture
def db_fresh():
    """A DB on a freshly-created throwaway `tome_test` schema (integration).

    Use for direct repository/module tests that don't need the HTTP app."""
    if not DSN:
        pytest.skip("TOME_TEST_DSN is not set")
    from tome.config import Config
    from tome.db import DB
    db = DB(Config())
    with db.pool.connection() as c, c.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS tome_test CASCADE")
    db.init_schema()
    try:
        yield db
    finally:
        try:
            with db.pool.connection() as c, c.cursor() as cur:
                cur.execute("DROP SCHEMA IF EXISTS tome_test CASCADE")
        finally:
            db.close()


@pytest.fixture
def api_client():
    """FastAPI TestClient against a throwaway tome_test schema. Integration only."""
    if not DSN:
        pytest.skip("TOME_TEST_DSN is not set")
    from fastapi.testclient import TestClient
    import api.main as m
    _drop_test_schema()
    with TestClient(m.app) as c:
        yield c
    _drop_test_schema()


def ingest_via_client(client, name: str, content: str, folder: str | None = None) -> dict:
    """Helper: upload markdown, run one worker pass, return the finished job."""
    from tome.db import DB
    from tome.worker import run_once
    data = {"folder_path": folder} if folder else {"auto_file": "true"}
    r = client.post("/v1/documents",
                    files={"file": (name, content.encode("utf-8"), "text/markdown")},
                    data=data)
    body = r.json()
    assert "job_id" in body, f"upload failed: HTTP {r.status_code} -> {str(body)[:300]}"
    run_once(DB())
    return client.get(f"/v1/jobs/{body['job_id']}").json()


@pytest.fixture(autouse=True)
def _reset_global_config():
    """Isolation: some tests rebuild the cached config singleton under TOME_OPEN=false
    (secure mode). Reset it after every test so the next test gets a fresh config from the
    (monkeypatch-reverted) env — otherwise secure mode leaks and later uploads 401."""
    yield
    try:
        import tome.config as cfgmod
        cfgmod._cfg = None
    except Exception:
        pass
    try:
        import api.deps as deps
        deps._scope_cache.clear()
    except Exception:
        pass


@pytest.fixture
def ingest(api_client):
    """Fixture form of ingest_via_client bound to the integration api_client."""
    def _do(name: str, content: str, folder: str | None = None) -> dict:
        return ingest_via_client(api_client, name, content, folder)
    return _do
