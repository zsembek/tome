"""A PDF whose embedded font lacks a proper ToUnicode CMap extracts as mojibake
(e.g. Russian 'Фирма Кронес' comes out as 'OÇpêa èpo³ec'). Such a page has plenty
of text, so the old page_is_poor() missed it and the garbage shipped. We must DETECT
broken-encoding text and treat the page as poor → triggers the render+OCR fallback."""
import pytest

from tome.extract.base import Page, page_is_poor, text_looks_garbled

pytestmark = pytest.mark.unit

# Synthesised broken-CMap output: accented-Latin glyphs + Latin-1 symbol glyphs
# (0xB3 '³', 0xF7 '÷') interleaved with a few ASCII letters — exactly the class of
# mojibake the user pasted. Built from code points so the source stays pure ASCII.
_G = [0xCE, 0xC7, 0x70, 0xEA, 0x61, 0x20, 0xE8, 0x70, 0x6F, 0xB3, 0x65, 0x63, 0x20,
      0xEC, 0x6F, 0x63, 0xCD, 0x6F, 0xFB, 0xB3, 0xB3, 0x6F, 0x20, 0x70, 0x61, 0xE0,
      0x6F, 0xCD, 0x61, 0xEA, 0xCD, 0x20, 0xF7, 0x61, 0xCA, 0xF8, 0xB3, 0x65]
GARBLED = "".join(chr(c) for c in _G) * 8


def _clean_ru():
    # real Cyrillic letters (U+0410..U+044F) — zero chars in the Latin-1 suspect range
    return ("".join(chr(c) for c in range(0x0410, 0x0450)) + " ") * 4


def test_detects_broken_font_mojibake():
    assert text_looks_garbled(GARBLED) is True


def test_clean_text_is_not_flagged():
    english = "This manual describes the safe operation of the mixer unit. " * 4
    # German with real umlauts — accented letters present but no symbol glyphs
    german = "Die Maschine läuft über die Förderbänder. " * 4
    for t in (english, german, _clean_ru()):
        assert text_looks_garbled(t) is False, repr(t[:40])


def test_short_text_is_never_flagged():
    # too little to judge — don't false-positive on a tiny snippet
    assert text_looks_garbled(chr(0xB3) + chr(0xCE) + chr(0xC7)) is False


def test_page_with_garbled_text_is_poor():
    assert page_is_poor(Page(number=1, text=GARBLED, char_count=len(GARBLED))) is True


def test_page_with_clean_text_is_not_poor():
    assert page_is_poor(Page(number=1, text=_clean_ru(), char_count=80)) is False
