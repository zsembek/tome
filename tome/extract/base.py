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
                       symbol_ratio: float = 0.04, accent_ratio: float = 0.5) -> bool:
    """Detect mojibake from a PDF whose embedded font has a missing/wrong ToUnicode CMap.
    Such extraction yields glyph codes reinterpreted as Latin-1: real text drowns in
    accented-Latin letters (U+00C0..U+024F) and Latin-1 symbol glyphs (U+00A0..U+00BF,
    superscripts/fractions/etc.). Genuine prose -- even heavily-accented German/French --
    almost never contains Latin-1 symbol glyphs, which is the reliable tell. Returns True
    when the page should be re-read by the render+OCR fallback instead of the broken text
    layer."""
    chars = [c for c in (text or "") if not c.isspace()]
    if len(chars) < min_chars:
        return False
    n = len(chars)
    symbols = sum(1 for c in chars if 0x00A0 <= ord(c) <= 0x00BF)
    accents = sum(1 for c in chars if 0x00C0 <= ord(c) <= 0x024F)
    # primary signal: a non-trivial density of Latin-1 symbol glyphs scattered as "letters"
    if symbols / n >= symbol_ratio:
        return True
    # backstop: overwhelmingly accented Latin with at least one symbol glyph (broken CMap)
    if symbols and accents / n >= accent_ratio:
        return True
    return False


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
