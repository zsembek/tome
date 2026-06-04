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
