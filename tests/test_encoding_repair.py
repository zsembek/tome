"""Single-byte-codepage mojibake: a PDF text layer where CP1251 (Russian) bytes were
decoded as Latin-1. The result is almost entirely accented-Latin letters with few/no
symbol glyphs, so the first garbled-detector missed it. This class is recoverable
DETERMINISTICALLY (re-encode latin-1 -> decode cp1251) — no OCR needed."""
import pytest

from tome.extract.base import repair_encoding, text_looks_garbled

pytestmark = pytest.mark.unit

# Real Russian built from code points (ASCII-safe source), then mangled the exact way a
# CP1251 text layer mis-decoded as Latin-1 would be.
_RU = ("Если на кулачке "
       "появились призн"
       "аки износа. ") * 4
_MOJIBAKE = _RU.encode("cp1251").decode("latin-1")


def test_cp1251_mojibake_is_detected_as_garbled():
    assert text_looks_garbled(_MOJIBAKE) is True


def test_repair_encoding_recovers_russian():
    fixed = repair_encoding(_MOJIBAKE)
    assert fixed is not None
    assert "Если" in fixed          # "Если"
    assert "кулачке" in fixed   # "кулачке"
    assert text_looks_garbled(fixed) is False           # recovered text is clean


def test_repair_encoding_leaves_clean_text_alone():
    for good in ("This is a perfectly clean English sentence about pumps and seals. " * 3,
                 "Die Maschine läuft über die Förderbänder für höhere Qualität. " * 3,
                 "Настоящая "  # real Cyrillic
                 "инструкция. " * 3):
        assert repair_encoding(good) is None


def test_repair_encoding_handles_empty():
    assert repair_encoding("") is None
    assert repair_encoding(None) is None


def test_repair_fixes_giant_single_line_mixed_with_ascii():
    """The real failure mode: an extractor emits the whole page as ONE line mixing
    CP1251-mojibake words with ASCII (codes, company names). Token-based repair must fix
    the mojibake words and leave ASCII (incl. accented French) untouched."""
    moji = " ".join(w.encode("cp1251").decode("latin-1")
                     for w in ["РУКОВОДСТВО", "ОПЕРАТОРА", "Номер", "Заказа", "ПНЕВМАТИЧЕСКАЯ"])
    giant = (f"1 SIDEL Manuel Opérateur Version 03 {moji} SIDEL: A873088I RG Brands "
             f"SBO 20 Universal {moji} {moji}")   # one line, no newlines

    fixed = repair_encoding(giant)
    assert fixed is not None
    assert "РУКОВОДСТВО ОПЕРАТОРА" in fixed
    assert "ПНЕВМАТИЧЕСКАЯ" in fixed
    assert "SIDEL" in fixed and "A873088I" in fixed and "RG Brands" in fixed   # ASCII intact
    assert "Opérateur" in fixed                  # genuinely-accented French NOT corrupted


def test_repair_does_not_corrupt_accented_western_text():
    fr = "Manuel Opérateur — Sidel Conveying — Rue du Commerce — déréglage des éléments."
    de = "Die Maschine läuft über die Förderbänder für höhere Qualität."
    assert repair_encoding(fr) is None
    assert repair_encoding(de) is None


def test_repair_fixes_mixed_page_keeps_clean_lines():
    """A real-world mixed page: a CP1251-mojibake header line next to clean ASCII, then a
    clean real-Cyrillic body line and a clean English line. Only the broken line changes."""
    header = ("РУКОВОДСТВО ОПЕРАТОРА".encode("cp1251").decode("latin-1")
              + " SIDEL A873088I RG Brands")
    clean_cyr = "Пневматическая конвейерная установка работает эффективно и надёжно."
    clean_en = "Sidel Group CONVEYING DIVISION Reichstett France contact details here."
    text = header + "\n" + clean_cyr + "\n" + clean_en

    fixed = repair_encoding(text)
    assert fixed is not None
    lines = fixed.split("\n")
    assert "РУКОВОДСТВО ОПЕРАТОРА" in lines[0]   # mojibake header repaired
    assert "SIDEL" in lines[0] and "RG Brands" in lines[0]   # ASCII on that line preserved
    assert lines[1] == clean_cyr                 # already-correct Cyrillic untouched
    assert lines[2] == clean_en                  # clean English untouched
