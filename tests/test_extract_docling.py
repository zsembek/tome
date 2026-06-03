"""Docling first-class: the adapter passes Docling's faithful Markdown
(GFM tables, reading order) through to the pipeline. Mocked so it runs without
the heavy `docling` package; a gated real-PDF test runs when it is installed."""
import importlib.util

import pytest

from tome.config import Config
from tome.extract.docling import DoclingExtractor

pytestmark = pytest.mark.contract

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_docling_exports_gfm_table_markdown(monkeypatch):
    ex = DoclingExtractor(Config())
    table_md = "# Spec\n\n| Param | Value |\n| --- | --- |\n| Pressure | 0.7 MPa |\n"

    class FakeDoc:
        def export_to_markdown(self):
            return table_md

    class FakeRes:
        document = FakeDoc()

    class FakeConv:
        def convert(self, path):
            return FakeRes()

    monkeypatch.setattr(ex, "_converter", lambda: FakeConv())
    r = ex.extract(b"docx-bytes", mime=_DOCX, filename="spec.docx", ocr_lang="eng")
    md = r.pages[0].text
    assert "| Param | Value |" in md and "| Pressure | 0.7 MPa |" in md
    assert r.extractor == "docling"


@pytest.mark.skipif(importlib.util.find_spec("docling") is None, reason="docling not installed")
def test_docling_real_pdf(sample_pdf_bytes):
    ex = DoclingExtractor(Config())
    r = ex.extract(sample_pdf_bytes, mime="application/pdf", filename="s.pdf", ocr_lang="eng")
    assert r.pages
    assert any(("Pump" in p.text) or ("MPa" in p.text) for p in r.pages)
