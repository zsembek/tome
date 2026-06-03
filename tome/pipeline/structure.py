"""Structure stage: raw page text → clean Markdown via LLM.

Smart mode: for already-clean pages (little OCR noise, single language, has structure)
the heavy LLM can be skipped. But the result always passes Verify (faithfulness)."""
from __future__ import annotations

import logging
import re

from tome.config import Config
from tome.llm import get_llm
from tome.prompts import load_prompt

log = logging.getLogger(__name__)

_FIGURE_RE = re.compile(r"\[\[FIGURE_\d+\]\]")
# Signs of "noise": long runs glued together without spaces, lots of single line breaks,
# alphabets mixed within a single word, etc.
_NOISE_HINT = re.compile(r"[A-Za-z\u0410-\u042f\u0430-\u044f]{2,}[0-9]{2,}|[-\uffff]")


def looks_clean(text: str) -> bool:
    """Rough heuristic: whether to skip the LLM (smart mode)."""
    if not text.strip():
        return True
    has_headings = bool(re.search(r"^#{1,6}\s", text, re.MULTILINE))
    short_line_ratio = _short_line_ratio(text)
    noisy = bool(_NOISE_HINT.search(text))
    return has_headings and short_line_ratio < 0.25 and not noisy


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
