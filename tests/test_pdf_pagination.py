"""A multi-page PDF must be extracted PAGE BY PAGE (own text + own figures per page),
not collapsed into one blob — so an 84-page book stays 84 pages through the pipeline."""
import pytest

pytestmark = pytest.mark.unit


def _make_pdf(pages_text: list[str]) -> bytes:
    import fitz
    doc = fitz.open()
    for t in pages_text:
        page = doc.new_page()
        page.insert_text((72, 72), t)
    data = doc.tobytes()
    doc.close()
    return data


def test_pdf_extracted_page_by_page():
    from tome.config import Config
    from tome.extract.tika import TikaExtractor
    pdf = _make_pdf([
        "Page one about centrifugal pumps and pressure 0.7 MPa, enough text here to count as a layer.",
        "Page two about gate valves DN50 and flow rate, with plenty of words to exceed the threshold.",
        "Page three covering safety guidelines and PPE gloves and lockout, sufficiently long content too.",
    ])
    res = TikaExtractor(Config()).extract(pdf, mime="application/pdf", filename="manual.pdf", ocr_lang="eng")
    assert len(res.pages) == 3, f"expected 3 pages, got {len(res.pages)}"
    assert "centrifugal pumps" in res.pages[0].text.lower()
    assert "gate valves" in res.pages[1].text.lower()
    assert "safety guidelines" in res.pages[2].text.lower()
    # each page numbered correctly (so the pipeline structures/OCRs them individually)
    assert [p.number for p in res.pages] == [1, 2, 3]


def test_pdf_pages_carry_their_own_figures(monkeypatch):
    # figures must be detected per page, not only on page 1
    from tome.config import Config
    from tome.extract import tika as tika_mod
    pdf = _make_pdf(["Long enough text layer for page one " * 4,
                     "Long enough text layer for page two " * 4])
    monkeypatch.setattr(tika_mod.pdfutil, "list_figures",
                        lambda b, i, **k: [[10.0, 10.0, 90.0, 90.0]] if i == 1 else [])
    res = TikaExtractor_extract(Config(), pdf)
    assert res.pages[0].figures == [] and len(res.pages[1].figures) == 1
    assert res.pages[1].figures[0].page_number == 2


def TikaExtractor_extract(cfg, pdf):
    from tome.extract.tika import TikaExtractor
    return TikaExtractor(cfg).extract(pdf, mime="application/pdf", filename="m.pdf", ocr_lang="eng")
