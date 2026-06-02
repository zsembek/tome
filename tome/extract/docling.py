"""Docling extractor (IBM) — the best OSS doc->Markdown: layout, tables, formulas,
reading order. Lazy import of the `docling` package."""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from tome.config import Config
from tome.extract.base import ExtractResult, Page
from tome.extract import pdfutil

log = logging.getLogger(__name__)


class DoclingExtractor:
    name = "docling"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._conv = None

    def _converter(self):
        if self._conv is None:
            try:
                from docling.document_converter import DocumentConverter
            except ImportError as e:
                raise RuntimeError(
                    "docling is not installed. Install it with: pip install docling") from e
            self._conv = DocumentConverter()
        return self._conv

    def supports(self, mime: str, filename: str) -> bool:
        return filename.lower().endswith(
            (".pdf", ".docx", ".pptx", ".xlsx", ".html", ".md", ".png", ".jpg", ".jpeg", ".tiff"))

    def extract(self, file_bytes: bytes, *, mime: str, filename: str, ocr_lang: str) -> ExtractResult:
        suffix = Path(filename).suffix or ".pdf"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            result = self._converter().convert(tmp_path)
            md = result.document.export_to_markdown()
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        # single logical page (the pipeline splits by headings itself); PDF figures — by bbox
        pages: list[Page] = []
        is_pdf = filename.lower().endswith(".pdf")
        if is_pdf:
            try:
                n = pdfutil.page_count(file_bytes)
            except Exception:
                n = 1
            chunks = md.split("\f") if "\f" in md else [md]
            if len(chunks) != n:
                chunks = [md]
            from tome.extract.base import Figure
            for i, ch in enumerate(chunks):
                figs = [Figure(fig_id=f"p{i+1}_{j}", page_number=i + 1, bbox=bb)
                        for j, bb in enumerate(pdfutil.list_figures(file_bytes, i))]
                pages.append(Page(number=i + 1, text=ch.strip(), figures=figs, char_count=len(ch)))
        else:
            pages.append(Page(number=1, text=md.strip(), char_count=len(md)))
        return ExtractResult(pages=pages, metadata={}, extractor=self.name)
