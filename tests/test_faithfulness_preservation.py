"""Content-preservation guarantee: LLM structuring must never drop a document's
content. If the model over-summarizes (or judges a noisy page as empty), the pipeline
keeps the raw extracted text — so an 84-page book never collapses into a 7-page summary.
"""
import pytest

from tome.llm.base import ChatResult

pytestmark = pytest.mark.integration


class _Summarizer:
    """A misbehaving LLM that summarizes everything into one short line."""

    def chat(self, *, system, user, model, max_tokens=4000, temperature=0.2, json=False):
        return ChatResult(text="# Summary\n\nThe document is about machinery.",
                          tokens_in=len(user) // 4, tokens_out=8, finish_reason="stop")

    def vision(self, **kw):
        return ChatResult(text="", finish_reason="stop")


def test_structuring_never_drops_content(db_fresh):
    import tome.llm.registry as reg
    from tome.config import Config
    from tome.pipeline.run import ingest

    reg._cache["openai"] = _Summarizer()              # force the summarizing LLM
    try:
        cfg = Config()
        cfg.llm_provider = "openai"
        cfg.structure_enabled = True                  # exercise the LLM path
        cfg.structure_smart = False                   # always call the LLM (no skip)
        cfg.extract_primary = "passthrough"; cfg.extract_fallback = ""
        cfg.embed_enabled = False; cfg.graph_enabled = False

        body = "# Manual\n\n" + "\n\n".join(
            f"## Unit {i}\n\nUnit {i} operates at {i*10} bar; valve V{i} and pump P{i} require service."
            for i in range(40))
        did = ingest(db_fresh, workspace_id=db_fresh.default_workspace(),
                     file_bytes=body.encode("utf-8"), filename="book.md",
                     mime="text/markdown", title_override="Book", cfg=cfg)

        content = "\n".join(p["content"] for p in db_fresh.get_document_parts(did, None))
        # the LLM "summarized" to ~40 chars, but the full content must be preserved
        assert "Unit 39" in content and "Unit 20" in content and "valve V39" in content
        assert len(content) > 0.5 * len(body), "content was lost to summarization"
    finally:
        reg._cache.pop("openai", None)
