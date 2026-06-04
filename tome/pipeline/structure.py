"""Structure stage: raw page text → clean Markdown via LLM.

Smart mode: for already-clean pages (little OCR noise, single language, has structure)
the heavy LLM can be skipped. But the result always passes Verify (faithfulness)."""
from __future__ import annotations

import logging
import re

from tome.config import Config
from tome.extract.base import text_looks_garbled
from tome.llm import get_llm
from tome.prompts import load_prompt

log = logging.getLogger(__name__)

_FIGURE_RE = re.compile(r"\[\[FIGURE_\d+\]\]")
# Signs of "noise": long runs glued together without spaces, lots of single line breaks,
# alphabets mixed within a single word, etc.
_NOISE_HINT = re.compile(r"[A-Za-z\u0410-\u042f\u0430-\u044f]{3,}\d{3,}|\ufffd")


def looks_clean(text: str) -> bool:
    """Rough heuristic: whether to skip the LLM (smart mode).

    A page is "clean enough" to keep verbatim when it has flowing prose (few stray
    short lines) and no OCR noise. Markdown headings are a bonus, not a requirement —
    most digital-PDF pages are clean prose with no headings, and forcing every such
    page through the LLM was the dominant ingestion cost."""
    if not text.strip():
        return True
    if bool(_NOISE_HINT.search(text)):
        return False
    return _short_line_ratio(text) < 0.25


def _short_line_ratio(text: str) -> float:
    # headings/list markers are legitimately short — exclude them from the count
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    body = [l for l in lines if not l.startswith(("#", "-", "*", "|", ">"))]
    if not body:
        return 0.0
    short = sum(1 for l in body if len(l) < 25)
    return short / len(body)


def structure_page(text: str, cfg: Config, target_lang: str) -> tuple[str, int, int]:
    """Returns (markdown, tokens_in, tokens_out)."""
    if not text.strip():
        return "", 0, 0
    if not getattr(cfg, "structure_enabled", True):
        return text.strip(), 0, 0  # LLM restructuring disabled — keep raw text
    # SAFETY: never feed a broken/garbled text layer (custom-font permutation, mis-decoded
    # codepage) to the LLM — it fabricates plausible-but-wrong content and placeholders.
    # Keep the raw text verbatim; the extractor's OCR fallback is the path to recover it.
    if text_looks_garbled(text):
        log.warning("structure: garbled text layer — skipping LLM, keeping raw (no fabrication)")
        return text.strip(), 0, 0
    if cfg.structure_smart and looks_clean(text):
        return text.strip(), 0, 0  # already clean — skip the LLM
    system = load_prompt("structure", TARGET_LANG=target_lang)
    try:
        llm = get_llm(cfg)
        res = llm.chat(system=system, user=text, model=cfg.llm_structure_model,
                       max_tokens=cfg.llm_max_completion_tokens)
        return res.text.strip(), res.tokens_in, res.tokens_out
    except Exception as exc:
        # Resilience: LLM unavailable/no key — do NOT lose the extracted text,
        # return it raw (degrade gracefully rather than fail the import).
        log.warning("structure LLM unavailable (%s) — keeping raw text", exc)
        return text.strip(), 0, 0
