"""AWS Textract extractor — forms/tables/handwritten text. Lazy boto3.
For PDFs: render pages to PNG (PyMuPDF) and send detect_document_text per page."""
from __future__ import annotations

import logging

from tome.config import Config
from tome.extract.base import ExtractResult, Page
from tome.extract import pdfutil

log = logging.getLogger(__name__)


class AWSTextractExtractor:
    name = "aws_textract"

    def __init__(self, cfg: Config):
        try:
            import boto3
        except ImportError as e:
            raise RuntimeError("aws_textract: pip install boto3") from e
        self.client = boto3.client("textract", region_name=cfg.aws_region)

    def supports(self, mime: str, filename: str) -> bool:
        return filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".tiff"))

    def _ocr_image(self, png: bytes) -> str:
        resp = self.client.detect_document_text(Document={"Bytes": png})
        lines = [b["Text"] for b in resp.get("Blocks", []) if b["BlockType"] == "LINE"]
        return "\n".join(lines)

    def extract(self, file_bytes: bytes, *, mime: str, filename: str, ocr_lang: str) -> ExtractResult:
        if filename.lower().endswith(".pdf"):
            n = pdfutil.page_count(file_bytes)
            pages = []
            for i in range(n):
                png = pdfutil.render_page_png(file_bytes, i)
                txt = self._ocr_image(png)
                pages.append(Page(number=i + 1, text=txt, char_count=len(txt)))
        else:
            txt = self._ocr_image(file_bytes)
            pages = [Page(number=1, text=txt, char_count=len(txt))]
        return ExtractResult(pages=pages, metadata={}, extractor=self.name)
