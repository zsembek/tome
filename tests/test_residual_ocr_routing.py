"""A page that still has permutation-cipher garble after deterministic repair must be
routed to the render+OCR fallback, and the clean OCR result must replace it. Proven here
with a fake vision_llm extractor (no network/Azure)."""
import pytest

from tome.config import Config
from tome.extract import registry
from tome.extract.base import ExtractResult, Page

pytestmark = pytest.mark.unit


class _FakeVision:
    """Stands in for the vision_llm fallback: returns the clean page text."""
    name = "vision_llm"
    CLEAN = ("Технические данные\n\nДопустимые производственные материалы и предельные "
             "режимы эксплуатации укупорочного агрегата фирмы КРОНЕС приведены в таблице.")

    def read_page_image(self, png: bytes) -> str:
        return self.CLEAN


def test_residual_garble_page_is_ocr_recovered(monkeypatch):
    # body repaired to clean Cyrillic, but a permutation header survived
    garbled_header = "Tex³ÇñecÉÇe ÷a³³õe BaÅ³õe yÉaÆa³Çû OÆ³aÉoêÊe³Çe "
    body = ("Допустимые производственные материалы и предельные режимы эксплуатации "
            "приведены ниже. Соблюдайте указания по технике безопасности при работе. ")
    page = Page(number=1, text=garbled_header + body, char_count=len(garbled_header + body))
    page.figures = []
    result = ExtractResult(pages=[page], metadata={}, extractor="tika")

    # force the vision fallback and stub PDF rendering
    monkeypatch.setattr(registry, "get_extractor", lambda name, cfg=None: _FakeVision())
    monkeypatch.setattr(registry.pdfutil, "page_count", lambda b: 1)
    monkeypatch.setattr(registry.pdfutil, "render_page_png", lambda b, i: b"\x89PNG")

    cfg = Config()
    out = registry._repair_poor_pages(result, b"%PDF-fake", "vision_llm", cfg)

    assert "Технические данные" in out.pages[0].text   # clean header recovered
    assert "³" not in out.pages[0].text                # permutation glyph gone
