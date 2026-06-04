"""Normalized extraction output — shared across ALL providers."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Figure:
    """An illustration on a page (for later PNG extraction + vision)."""
    fig_id: str
    page_number: int          # 1-based within the document
    bbox: list[float] | None = None   # [x0,y0,x1,y1] in PDF points, if available
    caption: str | None = None


@dataclass
class Page:
    number: int               # 1-based
    text: str                 # markdown or plain text
    figures: list[Figure] = field(default_factory=list)
    confidence: float | None = None    # OCR confidence (if available)
    language: str | None = None
    char_count: int = 0


@dataclass
class ExtractResult:
    pages: list[Page]
    metadata: dict = field(default_factory=dict)
    extractor: str = ""

    @property
    def total_chars(self) -> int:
        return sum(len(p.text) for p in self.pages)


class Extractor(Protocol):
    name: str
    def supports(self, mime: str, filename: str) -> bool: ...
    def extract(self, file_bytes: bytes, *, mime: str, filename: str, ocr_lang: str) -> ExtractResult: ...


def text_looks_garbled(text: str, *, min_chars: int = 120,
                       symbol_ratio: float = 0.04, accent_ratio: float = 0.55) -> bool:
    """Detect mojibake from a broken PDF text layer. Two common classes:
      1) a missing/wrong ToUnicode CMap -> glyph codes reinterpreted as Latin-1, with
         Latin-1 symbol glyphs (U+00A0..U+00BF, superscripts/fractions) scattered as
         "letters" — caught by symbol-glyph density.
      2) a single-byte codepage (e.g. CP1251 Russian) mis-decoded as Latin-1 -> almost
         every char becomes an accented-Latin letter (U+00C0..U+024F), often with no
         symbol glyphs at all — caught by overwhelming accented-Latin density.
    Genuine prose -- even heavily-accented German/French -- has only a few percent
    accented letters and virtually no Latin-1 symbol glyphs, so neither signal fires.
    Returns True when the page's text layer should not be trusted."""
    chars = [c for c in (text or "") if not c.isspace()]
    if len(chars) < min_chars:
        return False
    n = len(chars)
    symbols = sum(1 for c in chars if 0x00A0 <= ord(c) <= 0x00BF)
    accents = sum(1 for c in chars if 0x00C0 <= ord(c) <= 0x024F)
    if symbols / n >= symbol_ratio:          # class 1: symbol glyphs as text
        return True
    if accents / n >= accent_ratio:          # class 2: a whole codepage mis-decoded
        return True
    # class 3: a custom-font CMap PERMUTATION reinterpreted as ASCII letters + brackets
    # (glyphs render as real Cyrillic but the text layer is a substitution cipher). Tells:
    # brackets/backslash used as letters, and lowercase->UPPERCASE transitions mid-word.
    # A false positive here is harmless: it only re-routes the page through render+OCR.
    bracketish = sum(1 for c in chars if c in "[]{}\\|<>^~`")
    if bracketish / n >= 0.04:
        return True
    midcaps = sum(1 for a, b in zip(chars, chars[1:])
                  if a.isalpha() and a.islower() and ord(a) < 0x250
                  and b.isalpha() and b.isupper() and ord(b) < 0x250)
    if midcaps / n >= 0.06:
        return True
    return False


def _cyrillic_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if 0x0400 <= ord(c) <= 0x04FF) / len(letters)


_WS_SPLIT = re.compile(r"(\s+)")


def _repair_codepage_token(tok: str) -> str:
    """Re-decode ONE whitespace-delimited token if it is single-byte-codepage Cyrillic
    mis-decoded as Latin-1. Token granularity is robust to ANY line structure (a giant
    single line or many short lines) and SAFE: a token is only re-decoded when it is
    dominated by accented-Latin letters (real ASCII words like 'SIDEL' and genuinely
    accented words like French 'Opérateur' have a low ratio and are left untouched)."""
    letters = [c for c in tok if c.isalpha()]
    if len(letters) < 2:
        return tok
    hi = sum(1 for c in letters if 0x00C0 <= ord(c) <= 0x00FF)
    if hi / len(letters) < 0.6:        # not a mojibake token
        return tok
    for codec in ("cp1251", "koi8-r"):
        try:
            cand = tok.encode("latin-1", "ignore").decode(codec, "ignore")
        except Exception:
            continue
        if _cyrillic_ratio(cand) >= 0.6:   # confidently became Cyrillic
            return cand
    return tok


def repair_encoding(text: str) -> str | None:
    """Deterministically repair single-byte-codepage Cyrillic that was mis-decoded as
    Latin-1 (a common broken PDF text layer) -- no OCR/LLM. Works TOKEN BY TOKEN (so it is
    independent of how the extractor lays out lines) and only rewrites tokens dominated by
    accented-Latin, leaving clean ASCII and genuinely-accented Western words intact.
    Returns the repaired text, or None when nothing needed repair."""
    if not text:
        return None
    parts = _WS_SPLIT.split(text)
    changed = False
    for i, p in enumerate(parts):
        if p and not p.isspace():
            fixed = _repair_codepage_token(p)
            if fixed != p:
                parts[i] = fixed
                changed = True
    return "".join(parts) if changed else None


def page_is_poor(page: Page, *, min_chars: int = 80) -> bool:
    """Heuristic for a "poor" page -> needs a fallback (vision/cloud)."""
    txt = (page.text or "").strip()
    if len(txt) < min_chars and page.figures:
        return True
    if page.confidence is not None and page.confidence < 0.5:
        return True
    if text_looks_garbled(txt):
        return True
    return False
