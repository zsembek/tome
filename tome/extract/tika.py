"""Apache Tika extractor (server mode). Universal parser for 1000+ formats."""
from __future__ import annotations

import logging

import httpx

from tome.config import Config
from tome.extract.base import ExtractResult, Figure, Page
from tome.extract import pdfutil

log = logging.getLogger(__name__)


class TikaExtractor:
    name = "tika"

    def __init__(self, cfg: Config):
        self.url = cfg.tika_url.rstrip("/")

    def supports(self, mime: str, filename: str) -> bool:
        return True  # Tika is universal

    def extract(self, file_bytes: bytes, *, mime: str, filename: str, ocr_lang: str) -> ExtractResult:
        headers = {
            "Accept": "text/plain",
            "X-Tika-OCRLanguage": ocr_lang,
            "Content-Type": mime or "application/octet-stream",
        }
        # rmeta — text + metadata in one call (JSON per document/attachment)
        with httpx.Client(timeout=300) as client:
            r = client.put(f"{self.url}/rmeta/text", content=file_bytes,
                           headers={**headers, "Accept": "application/json"})
            r.raise_for_status()
            blocks = r.json()

        metadata = blocks[0] if blocks else {}
        full_text = "\n\n".join(b.get("X-TIKA:content", "") or "" for b in blocks).strip()

        # Tika doesn't reliably split text per page; for PDFs we use
        # PyMuPDF to count pages and figures, and place the text as a single "logical
        # page" per original (the pipeline later splits it by headings itself).
        is_pdf = (mime == "application/pdf") or filename.lower().endswith(".pdf")
        pages: list[Page] = []
        if is_pdf:
            try:
                n = pdfutil.page_count(file_bytes)
            except Exception:
                n = 1
            # split the text proportionally by form feed, if present
            chunks = full_text.split("\f") if "\f" in full_text else [full_text]
            if len(chunks) != n:
                chunks = [full_text]  # guess failed — single page
            for i, ch in enumerate(chunks):
                figs = [Figure(fig_id=f"p{i+1}_{j}", page_number=i + 1, bbox=bb)
                        for j, bb in enumerate(pdfutil.list_figures(file_bytes, i))]
                pages.append(Page(number=i + 1, text=ch.strip(), figures=figs,
                                  char_count=len(ch)))
        else:
            pages.append(Page(number=1, text=full_text, char_count=len(full_text)))

        return ExtractResult(pages=pages, metadata={
            "title": metadata.get("dc:title") or metadata.get("title", ""),
            "author": metadata.get("dc:creator") or metadata.get("Author", ""),
            "content_type": metadata.get("Content-Type", mime),
        }, extractor=self.name)
