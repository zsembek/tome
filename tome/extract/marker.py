"""Marker extractor (Datalab) — fast PDF->Markdown. Lazy import of `marker`."""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from tome.config import Config
from tome.extract.base import ExtractResult, Page

log = logging.getLogger(__name__)


class MarkerExtractor:
    name = "marker"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._conv = None

    def _converter(self):
        if self._conv is None:
            try:
                from marker.converters.pdf import PdfConverter
                from marker.models import create_model_dict
            except ImportError as e:
                raise RuntimeError("marker is not installed: pip install marker-pdf") from e
            self._conv = PdfConverter(artifact_dict=create_model_dict())
        return self._conv

    def supports(self, mime: str, filename: str) -> bool:
        return filename.lower().endswith(".pdf")

    def extract(self, file_bytes: bytes, *, mime: str, filename: str, ocr_lang: str) -> ExtractResult:
        from marker.output import text_from_rendered
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_bytes); tmp_path = tmp.name
        try:
            rendered = self._converter()(tmp_path)
            md, _, _ = text_from_rendered(rendered)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        return ExtractResult(pages=[Page(number=1, text=md.strip(), char_count=len(md))],
                             metadata={}, extractor=self.name)
