"""Vision-LLM extractor: render a PDF page to an image -> read it with a vision model.

Often more accurate than Tesseract on chaotic layouts. Works both as a fallback and
as a standalone OCR for scanned documents. No cloud DI — LLM only."""
from __future__ import annotations

import logging

from tome.config import Config
from tome.extract.base import ExtractResult, Page
from tome.extract import pdfutil
from tome.llm import get_llm

log = logging.getLogger(__name__)

_OCR_SYSTEM = (
    "You are an OCR+layout engine. The image is a page of a document. Extract ALL "
    "visible text as Markdown, preserving the structure (headings, lists, tables) and "
    "reproducing numbers/units/codes VERBATIM. Do not describe the image or add "
    "comments — output only the page content. If the page is empty, output an empty string."
)


class VisionLLMExtractor:
    name = "vision_llm"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.llm = get_llm(cfg)

    def supports(self, mime: str, filename: str) -> bool:
        return (mime == "application/pdf") or filename.lower().endswith(
            (".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"))

    def extract(self, file_bytes: bytes, *, mime: str, filename: str, ocr_lang: str) -> ExtractResult:
        is_pdf = (mime == "application/pdf") or filename.lower().endswith(".pdf")
        pages: list[Page] = []
        if is_pdf:
            n = pdfutil.page_count(file_bytes)
            for i in range(n):
                png = pdfutil.render_page_png(file_bytes, i)
                txt = self._read(png)
                pages.append(Page(number=i + 1, text=txt, char_count=len(txt)))
        else:
            txt = self._read(file_bytes)
            pages.append(Page(number=1, text=txt, char_count=len(txt)))
        return ExtractResult(pages=pages, metadata={}, extractor=self.name)

    def read_page_image(self, png_bytes: bytes) -> str:
        """Public method — read a single page image (for fallback)."""
        return self._read(png_bytes)

    def _read(self, png_bytes: bytes) -> str:
        res = self.llm.vision(
            system=_OCR_SYSTEM, prompt="Extract the text from this page.",
            image_bytes=png_bytes, image_mime="image/png",
            model=self.cfg.llm_vision_model,
            max_tokens=self.cfg.llm_max_completion_tokens,
        )
        return res.text
