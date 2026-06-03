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
        self.cfg = cfg
        self.url = cfg.tika_url.rstrip("/")

    def supports(self, mime: str, filename: str) -> bool:
        return True  # Tika is universal

    def extract(self, file_bytes: bytes, *, mime: str, filename: str, ocr_lang: str) -> ExtractResult:
        is_pdf = (mime == "application/pdf") or filename.lower().endswith(".pdf")
        if is_pdf:
            try:
                return self._extract_pdf(file_bytes, mime, filename, ocr_lang)
            except Exception as exc:
                log.warning("per-page PDF extraction failed (%s) — falling back to Tika blob", exc)
        return self._extract_blob(file_bytes, mime, filename, ocr_lang)

    def _figs(self, file_bytes: bytes, i: int) -> list[Figure]:
        try:
            return [Figure(fig_id=f"p{i+1}_{j}", page_number=i + 1, bbox=bb)
                    for j, bb in enumerate(pdfutil.list_figures(file_bytes, i))]
        except Exception:
            return []

    def _extract_pdf(self, file_bytes: bytes, mime: str, filename: str, ocr_lang: str) -> ExtractResult:
        """TRUE per-page extraction: each PDF page → its own Page with its own text
        (from the text layer) and its own figures. Pages without a text layer (scanned)
        are returned empty so the poor-page repair OCRs each page individually."""
        ptexts = pdfutil.page_texts(file_bytes)
        n = len(ptexts)
        total = sum(len(t.strip()) for t in ptexts)
        has_text_layer = n > 0 and total >= max(200, 20 * n)
        if has_text_layer:
            pages = [Page(number=i + 1, text=ptexts[i].strip(), figures=self._figs(file_bytes, i),
                          char_count=len(ptexts[i].strip())) for i in range(n)]
            return ExtractResult(pages=pages, metadata=pdfutil.pdf_metadata(file_bytes),
                                 extractor=self.name)
        # scanned PDF (no usable text layer)
        if self.cfg.extract_scanned or self.cfg.extract_fallback:
            # per-page empty pages → the vision/cloud fallback OCRs each page on its own
            pages = [Page(number=i + 1, text="", figures=self._figs(file_bytes, i), char_count=0)
                     for i in range(n)]
            return ExtractResult(pages=pages, metadata=pdfutil.pdf_metadata(file_bytes),
                                 extractor=self.name)
        # no fallback configured → use Tika's whole-document OCR so we never return nothing
        res = self._extract_blob(file_bytes, mime, filename, ocr_lang)
        if res.pages and n:
            res.pages[0].figures = self._figs(file_bytes, 0)
        return res

    def _extract_blob(self, file_bytes: bytes, mime: str, filename: str, ocr_lang: str) -> ExtractResult:
        """Single-call Tika extraction (universal formats + scanned-PDF OCR)."""
        headers = {
            "Accept": "application/json",
            "X-Tika-OCRLanguage": ocr_lang,
            "Content-Type": mime or "application/octet-stream",
        }
        with httpx.Client(timeout=300) as client:
            r = client.put(f"{self.url}/rmeta/text", content=file_bytes, headers=headers)
            r.raise_for_status()
            blocks = r.json()
        metadata = blocks[0] if blocks else {}
        full_text = "\n\n".join(b.get("X-TIKA:content", "") or "" for b in blocks).strip()
        return ExtractResult(
            pages=[Page(number=1, text=full_text, char_count=len(full_text))],
            metadata={"title": metadata.get("dc:title") or metadata.get("title", ""),
                      "author": metadata.get("dc:creator") or metadata.get("Author", ""),
                      "content_type": metadata.get("Content-Type", mime)},
            extractor=self.name)
