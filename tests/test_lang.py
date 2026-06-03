"""Language pre-analysis: detect the document's real language(s) and re-scan OCR
with the correct engine languages (fixes garbled multi-language scans)."""
import pytest

from tome import lang
from tome.extract.base import ExtractResult, Page

pytestmark = pytest.mark.unit


def test_detect_single_languages():
    assert lang.detect_languages("The pump operates at high pressure and flow rate.")[0] == "en"
    assert lang.detect_languages("Центробежный насос работает под высоким давлением.")[0] == "ru"
    assert lang.detect_languages("Der Motor läuft mit hoher Drehzahl und das Öl ist warm.")[0] == "de"


def test_detect_mixed_languages():
    codes = set(lang.detect_languages("The pump насос works under давление reliably."))
    assert "en" in codes and "ru" in codes


def test_to_ocr_langs_mapping():
    assert lang.to_ocr_langs(["en", "de"]) == "eng+deu"
    assert lang.to_ocr_langs(["ru"]) == "rus"
    assert lang.to_ocr_langs(["xx"]) == ""          # unknown codes dropped


def test_fts_config_for():
    assert lang.fts_config_for("ru") == "russian"
    assert lang.fts_config_for("en") == "english"
    assert lang.fts_config_for("zz") == "simple"


def test_auto_language_rescans_ocr_with_correct_langs():
    from tome.config import Config
    from tome.extract.registry import _apply_auto_language
    cfg = Config()
    cfg.llm_provider = "none"          # force the deterministic detector (no network)
    cfg.extract_auto_lang = True

    class FakePrimary:
        name = "fake"
        def __init__(self):
            self.calls = []

        def extract(self, file_bytes, *, mime, filename, ocr_lang):
            self.calls.append(ocr_lang)
            return ExtractResult(
                pages=[Page(number=1, text="Der Motor und die Pumpe laufen mit hohem Druck.",
                            char_count=47)], extractor="fake")

    fp = FakePrimary()
    initial = fp.extract(b"x", mime="application/pdf", filename="f.pdf", ocr_lang="eng+rus")
    fp.calls.clear()

    # OCR ran with eng+rus but the document is German → must re-scan adding 'deu'
    result, ocr = _apply_auto_language(initial, fp, b"x", "application/pdf", "f.pdf",
                                       "eng+rus", cfg, True)
    assert result.metadata["language"] == "de"
    assert "deu" in ocr
    assert any("deu" in c for c in fp.calls), "primary OCR was not re-invoked with German"
