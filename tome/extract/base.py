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


def page_is_poor(page: Page, *, min_chars: int = 80) -> bool:
    """Heuristic for a "poor" page -> needs a fallback (vision/cloud)."""
    txt = (page.text or "").strip()
    if len(txt) < min_chars and page.figures:
        return True
    if page.confidence is not None and page.confidence < 0.5:
        return True
    return False
