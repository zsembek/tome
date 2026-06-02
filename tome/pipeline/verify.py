"""Verify stage — the faithfulness guarantee. Checks the structured output against
the original extraction: content coverage, numbers/units, cleanliness.

Deterministic checks (no LLM) — cheap and objective."""
from __future__ import annotations

import re
from dataclasses import dataclass

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
_WORD_RE = re.compile(r"\w{3,}", re.UNICODE)
_CJK_RE = re.compile(r"[一-鿿]")


@dataclass
class FaithReport:
    coverage: float          # share of significant source tokens preserved in the output
    numbers_ok: bool         # all source numbers are present in the output
    missing_numbers: list[str]
    clean: bool              # no leftover noise/foreign-language tails
    score: float             # aggregate score 0..1
    passed: bool


def _tokens(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text)}


def _numbers(text: str) -> list[str]:
    return [n.replace(",", ".") for n in _NUM_RE.findall(text)]


def verify(source_text: str, output_md: str, *, min_score: float,
           target_lang: str = "auto") -> FaithReport:
    src_tok = _tokens(source_text)
    out_tok = _tokens(output_md)
    coverage = (len(src_tok & out_tok) / len(src_tok)) if src_tok else 1.0

    src_nums = _numbers(source_text)
    out_nums_set = set(_numbers(output_md))
    missing = [n for n in src_nums if n not in out_nums_set]
    # allow a small loss (page numbers/OCR artifacts)
    numbers_ok = (len(missing) / len(src_nums) < 0.05) if src_nums else True

    # cleanliness: if the target language isn't Chinese, leftover CJK = noise
    clean = True
    if target_lang not in ("auto", "zh", "zh-cn") and _CJK_RE.search(output_md):
        clean = False

    score = coverage * (1.0 if numbers_ok else 0.7) * (1.0 if clean else 0.8)
    return FaithReport(
        coverage=round(coverage, 3), numbers_ok=numbers_ok,
        missing_numbers=missing[:20], clean=clean,
        score=round(score, 3), passed=score >= min_score,
    )
