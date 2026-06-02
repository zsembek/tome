"""Azure AI Document Intelligence extractor (prebuilt-layout → markdown).

Best quality on complex scans/tables. Optional (requires keys)."""
from __future__ import annotations

import logging

from tome.config import Config
from tome.extract.base import ExtractResult, Figure, Page

log = logging.getLogger(__name__)


class AzureDIExtractor:
    name = "azure_di"

    def __init__(self, cfg: Config):
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential
        if not cfg.azure_di_endpoint or not cfg.azure_di_key:
            raise RuntimeError("azure_di: AZURE_DI_ENDPOINT / AZURE_DI_KEY not set")
        self.client = DocumentIntelligenceClient(
            endpoint=cfg.azure_di_endpoint,
            credential=AzureKeyCredential(cfg.azure_di_key),
        )

    def supports(self, mime: str, filename: str) -> bool:
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        return ext in {"pdf", "png", "jpg", "jpeg", "tiff", "bmp", "heif", "docx", "xlsx", "pptx"}

    def extract(self, file_bytes: bytes, *, mime: str, filename: str, ocr_lang: str) -> ExtractResult:
        from azure.ai.documentintelligence.models import (
            AnalyzeDocumentRequest, DocumentContentFormat, DocumentAnalysisFeature,
        )
        poller = self.client.begin_analyze_document(
            model_id="prebuilt-layout",
            body=AnalyzeDocumentRequest(bytes_source=file_bytes),
            output_content_format=DocumentContentFormat.MARKDOWN,
            features=[DocumentAnalysisFeature.OCR_HIGH_RESOLUTION],
        )
        result = poller.result()
        md = result.content or ""
        n_pages = len(result.pages or []) or 1

        # Simple per-page split by DI PageBreak markers (if present)
        import re
        parts = re.split(r"<!--\s*PageBreak\s*-->", md)
        if len(parts) != n_pages:
            parts = [md]
        pages: list[Page] = []
        for i, ch in enumerate(parts):
            pages.append(Page(number=i + 1, text=ch.strip(), char_count=len(ch)))

        # figures with bbox (DI returns inches -> points)
        for i, fig in enumerate(getattr(result, "figures", None) or []):
            regions = getattr(fig, "bounding_regions", None) or []
            if not regions:
                continue
            reg = regions[0]
            pg = getattr(reg, "page_number", 1)
            poly = list(getattr(reg, "polygon", []) or [])
            bbox = None
            if len(poly) >= 4:
                xs, ys = poly[0::2], poly[1::2]
                bbox = [min(xs) * 72, min(ys) * 72, max(xs) * 72, max(ys) * 72]
            target = pages[pg - 1] if 0 < pg <= len(pages) else pages[0]
            cap = getattr(getattr(fig, "caption", None), "content", None)
            target.figures.append(Figure(fig_id=getattr(fig, "id", f"fig{i}"),
                                         page_number=pg, bbox=bbox, caption=cap))
        return ExtractResult(pages=pages, metadata={}, extractor=self.name)
