"""Google Document AI extractor. Lazy google-cloud-documentai.
GOOGLE_DOCAI_PROCESSOR = projects/.../locations/.../processors/...
GOOGLE_APPLICATION_CREDENTIALS — path to the service-account json (env)."""
from __future__ import annotations

import logging

from tome.config import Config
from tome.extract.base import ExtractResult, Page

log = logging.getLogger(__name__)


class GoogleDocAIExtractor:
    name = "google_docai"

    def __init__(self, cfg: Config):
        if not cfg.google_docai_processor:
            raise RuntimeError("google_docai: GOOGLE_DOCAI_PROCESSOR not set")
        try:
            from google.cloud import documentai
        except ImportError as e:
            raise RuntimeError("google_docai: pip install google-cloud-documentai") from e
        self._documentai = documentai
        self.processor = cfg.google_docai_processor
        self.client = documentai.DocumentProcessorServiceClient()

    def supports(self, mime: str, filename: str) -> bool:
        return filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".gif"))

    def extract(self, file_bytes: bytes, *, mime: str, filename: str, ocr_lang: str) -> ExtractResult:
        di = self._documentai
        raw = di.RawDocument(content=file_bytes, mime_type=mime or "application/pdf")
        req = di.ProcessRequest(name=self.processor, raw_document=raw)
        result = self.client.process_document(request=req)
        doc = result.document
        full = doc.text or ""
        pages = []
        for i, p in enumerate(doc.pages, start=1):
            # page text from layout segments
            seg = ""
            try:
                for s in p.layout.text_anchor.text_segments:
                    seg += full[int(s.start_index):int(s.end_index)]
            except Exception:
                seg = ""
            pages.append(Page(number=i, text=seg.strip(), char_count=len(seg)))
        if not pages:
            pages = [Page(number=1, text=full.strip(), char_count=len(full))]
        return ExtractResult(pages=pages, metadata={}, extractor=self.name)
