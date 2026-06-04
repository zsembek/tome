"""Normalized extraction output — shared across ALL providers."""
from __future__ import annotations

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


def _repair_codepage_line(line: str) -> str | None:
    """Re-decode ONE line of single-byte-codepage Cyrillic mis-decoded as Latin-1.
    Returns the repaired line, or None when no confident repair applies. Works at line
    granularity so a mixed page (garbled header + clean ASCII + real Cyrillic body) keeps
    its clean lines intact and only the broken lines are fixed."""
    letters = [c for c in line if c.isalpha()]
    if len(letters) < 6:
        return None
    # cheap gate: only bother with lines dominated by Latin-1 high letters (potential mojibake)
    hi = sum(1 for c in letters if 0x00C0 <= ord(c) <= 0x00FF)
    if hi / len(letters) < 0.30:
        return None
    threshold = _cyrillic_ratio(line) + 0.30   # require a large, confident Cyrillic gain
    best, best_ratio = None, threshold
    for codec in ("cp1251", "koi8-r"):
        try:
            cand = line.encode("latin-1", "ignore").decode(codec, "ignore")
        except Exception:
            continue
        r = _cyrillic_ratio(cand)
        if r > best_ratio:
            best, best_ratio = cand, r
    return best


def repair_encoding(text: str) -> str | None:
    """Deterministically repair single-byte-codepage Cyrillic that was mis-decoded as
    Latin-1 (a common broken PDF text layer) -- no OCR/LLM. Repairs LINE BY LINE so a
    mixed page (garbled header alongside clean ASCII / already-correct Cyrillic) is
    handled safely: only the broken lines change. Returns the repaired text, or None when
    nothing needed repair."""
    if not text:
        return None
    out, changed = [], False
    for line in text.split("\n"):
        cand = _repair_codepage_line(line)
        if cand is not None and cand != line:
            out.append(cand); changed = True
        else:
            out.append(line)
    return "\n".join(out) if changed else None


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
