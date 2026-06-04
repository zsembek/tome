"""Third mojibake class: a custom-font CMap PERMUTATION. The glyphs render as correct
Cyrillic in a viewer, but the extracted text layer maps each character to an arbitrary
ASCII letter / bracket (e.g. 'MUJLJ' == 'ГЛАВА', 'WXZVe' == 'НОРМЫ'). Because the bytes
are plain ASCII (no high-bit chars), the symbol/accent detectors and codepage re-decode
all miss it — it must be detected so the render+OCR fallback recovers the real text."""
import pytest

from tome.extract.base import Page, page_is_poor, repair_encoding, text_looks_garbled

pytestmark = pytest.mark.unit

# A faithful slice of a real affected document's extracted text layer (ASCII + brackets).
PERMUTED = (
    "  I MUJLJ   WXZVe R XKcRO YZJLRUJ   \n"
    "  de]Za_U ] XUeUbg]t   \n"
    "  deZYhdeZ[YZb]t ] dZefcbU`   \n"
    "  ]bfgeh_k]] Y`t \\U_U\\U decWZYZb]t eUVcg bU aZfgZ   \n"
    "  dcYXcgcW]gZqbpZ dcYWcY_] WpdcbtZapZ dc_hdUgZ`Za   \n"
) * 4


def test_permutation_mojibake_is_detected():
    assert text_looks_garbled(PERMUTED) is True


def test_permutation_page_is_poor():
    assert page_is_poor(Page(number=1, text=PERMUTED, char_count=len(PERMUTED))) is True


def test_codepage_redecode_does_not_touch_ascii_permutation():
    # repair_encoding can't fix an ASCII permutation (re-decode only changes high bytes);
    # it must return None so the page falls through to OCR rather than being "fixed" wrongly.
    assert repair_encoding(PERMUTED) is None


def test_clean_english_with_a_few_brackets_is_not_flagged():
    txt = ("See the maintenance schedule in section [3] and the parts list [4] for the "
           "centrifugal pump. Replace the seals every 200 hours of operation as required. ") * 3
    assert text_looks_garbled(txt) is False


def test_clean_text_with_acronyms_is_not_flagged():
    txt = ("The PLC controls the HMI and the SCADA system reports to the MES layer. "
           "Operators review KPIs on the dashboard during each shift handover routine. ") * 3
    assert text_looks_garbled(txt) is False
