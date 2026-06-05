"""The OCR fallback (render+vision per poor page) must run pages CONCURRENTLY, bounded by
PAGE_CONCURRENCY — otherwise a 600-page garbled scan takes ~600x a single ~10s vision
call (well over an hour). The structure stage is already parallel; this guards the same
for the extract OCR repair loop."""
import time

import pytest

from tome.config import Config
from tome.extract import registry
from tome.extract.base import ExtractResult, Page

pytestmark = pytest.mark.unit


class _SlowVision:
    name = "vision_llm"

    def read_page_image(self, png: bytes) -> str:
        time.sleep(0.2)                       # simulate a network vision call
        return ("Технические данные укупорочного агрегата фирмы КРОНЕС приведены ниже; "
                "соблюдайте указания по технике безопасности при эксплуатации.")


def _garbled_pages(n: int):
    g = "Tex³ÇñecÉÇe ÷a³³õe BaÅ³õe yÉaÆa³Çû OÆ³aÉoêÊe³Çe Mo³ÍaÅ ÷eêo³ÍaÅ "
    g = g * 4                                 # >120 non-space chars so the garble gate fires
    pages = []
    for i in range(n):
        p = Page(number=i + 1, text=g, char_count=len(g))
        p.figures = []
        pages.append(p)
    return pages


def test_ocr_fallback_runs_pages_in_parallel(monkeypatch):
    n = 8
    result = ExtractResult(pages=_garbled_pages(n), metadata={}, extractor="tika")
    monkeypatch.setattr(registry, "get_extractor", lambda name, cfg=None: _SlowVision())
    monkeypatch.setattr(registry.pdfutil, "page_count", lambda b: n)
    monkeypatch.setattr(registry.pdfutil, "render_page_png", lambda b, i: b"\x89PNG")

    cfg = Config()
    cfg.page_concurrency = 8

    t0 = time.monotonic()
    out = registry._repair_poor_pages(result, b"%PDF-fake", "vision_llm", cfg)
    elapsed = time.monotonic() - t0

    # all garbled pages recovered to clean text
    assert all("Технические данные" in p.text for p in out.pages)
    # 8 pages x 0.2s serially = 1.6s; parallel (conc=8) must be well under that
    assert elapsed < 0.8, f"OCR fallback not parallel: {elapsed:.2f}s for {n} pages"


def test_ocr_fallback_serial_when_concurrency_one(monkeypatch):
    result = ExtractResult(pages=_garbled_pages(3), metadata={}, extractor="tika")
    monkeypatch.setattr(registry, "get_extractor", lambda name, cfg=None: _SlowVision())
    monkeypatch.setattr(registry.pdfutil, "page_count", lambda b: 3)
    monkeypatch.setattr(registry.pdfutil, "render_page_png", lambda b, i: b"\x89PNG")
    cfg = Config()
    cfg.page_concurrency = 1
    out = registry._repair_poor_pages(result, b"%PDF-fake", "vision_llm", cfg)
    assert all("Технические данные" in p.text for p in out.pages)
