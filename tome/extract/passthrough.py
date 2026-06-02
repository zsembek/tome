"""Passthrough for text formats: md/txt/html — no OCR, direct parsing."""
from __future__ import annotations

import re

from tome.config import Config
from tome.extract.base import ExtractResult, Page


class PassthroughExtractor:
    name = "passthrough"

    def __init__(self, cfg: Config | None = None):
        pass

    def supports(self, mime: str, filename: str) -> bool:
        return filename.lower().endswith((".md", ".markdown", ".txt", ".text", ".html", ".htm")) \
            or mime in ("text/markdown", "text/plain", "text/html")

    def extract(self, file_bytes: bytes, *, mime: str, filename: str, ocr_lang: str) -> ExtractResult:
        text = file_bytes.decode("utf-8", errors="replace")
        if filename.lower().endswith((".html", ".htm")) or mime == "text/html":
            text = _html_to_text(text)
        return ExtractResult(pages=[Page(number=1, text=text, char_count=len(text))],
                             metadata={}, extractor=self.name)


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</p>", "\n\n", html)
    text = re.sub(r"<[^>]+>", "", html)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
