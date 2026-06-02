"""Mistral OCR extractor — modern OCR->Markdown via the Mistral API (httpx)."""
from __future__ import annotations

import base64
import logging

import httpx

from tome.config import Config
from tome.extract.base import ExtractResult, Page

log = logging.getLogger(__name__)


class MistralOCRExtractor:
    name = "mistral_ocr"

    def __init__(self, cfg: Config):
        if not cfg.mistral_api_key:
            raise RuntimeError("mistral_ocr: MISTRAL_API_KEY not set")
        self.key = cfg.mistral_api_key

    def supports(self, mime: str, filename: str) -> bool:
        return filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".tiff"))

    def extract(self, file_bytes: bytes, *, mime: str, filename: str, ocr_lang: str) -> ExtractResult:
        b64 = base64.b64encode(file_bytes).decode("ascii")
        is_pdf = filename.lower().endswith(".pdf")
        doc = ({"type": "document_url", "document_url": f"data:application/pdf;base64,{b64}"}
               if is_pdf else
               {"type": "image_url", "image_url": f"data:{mime};base64,{b64}"})
        with httpx.Client(timeout=300) as c:
            r = c.post("https://api.mistral.ai/v1/ocr",
                       headers={"Authorization": f"Bearer {self.key}"},
                       json={"model": "mistral-ocr-latest", "document": doc})
            r.raise_for_status()
            data = r.json()
        pages = []
        for i, p in enumerate(data.get("pages", []), start=1):
            md = p.get("markdown", "") or ""
            pages.append(Page(number=i, text=md.strip(), char_count=len(md)))
        if not pages:
            pages = [Page(number=1, text="", char_count=0)]
        return ExtractResult(pages=pages, metadata={}, extractor=self.name)
