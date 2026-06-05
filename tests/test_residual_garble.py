"""Residual permutation-garble detection (post-deterministic-repair).

A broken PDF can carry TWO corrupted text layers at once: a CP1251-as-Latin1 body
(deterministically repairable) and a custom-font PERMUTATION cipher for headers/titles
(`³`=`н`, mixed Cyrillic+Latin, symbol glyphs) that only OCR can recover. After the body
auto-repairs, the page looks ~95% clean, so the whole-page `text_looks_garbled` check no
longer fires and the still-garbled headers slip through into the output.

`text_has_residual_garble` catches that leftover so the page is routed to render+OCR.
Crucially it must NOT fire on legitimate multi-language text (Spanish/German/Polish
accents like México, Repräsentanz, SPÓLKA) — that was the real-world false positive."""
import pytest

from tome.extract.base import _is_garble_token, text_has_residual_garble

pytestmark = pytest.mark.unit


def test_permutation_tokens_are_garble():
    # symbol glyph (³), mixed Cyrillic+Latin, uppercase-accent mid-word, high accent density
    for t in ["Tex³ÇñecÉÇe", "÷a³³õe", "BaÅ³õe", "yÉaÆa³Çû", "жіcНpyЙрЗы",
              "OÆ³aÉoêÊe³Çe", "ÀeÆoìac³ocÍø"]:
        assert _is_garble_token(t) is True, t


def test_legit_multilingual_words_are_not_garble():
    # Spanish / German / Polish / French — a stray accent or an all-caps accented word
    for t in ["México", "Repräsentanz", "SPÓLKA", "Opérateur", "Düsseldorf",
              "naïve", "KRONES", "PET", "gelb", "Инструкция", "эксплуатации"]:
        assert _is_garble_token(t) is False, t


def test_hyphenated_mixed_script_compound_is_not_garble():
    # a legit product name joining a Cyrillic part and a Latin part is NOT garble
    for t in ["КРОНЕС-Checkmat", "PET/стекло", "Rivolta-смазка"]:
        assert _is_garble_token(t) is False, t


def test_page_with_garbled_headers_flags_residual():
    # clean repaired body + a permutation header line repeated (running header)
    body = ("Эта инструкция по эксплуатации должна способствовать правильному и "
            "безопасному режиму работы машины. Поэтому выполняйте следующие указания "
            "по технике безопасности при обслуживании укупорочного агрегата фирмы. ")
    garbled_header = "Tex³ÇñecÉÇe ÷a³³õe BaÅ³õe yÉaÆa³Çû OÆ³aÉoêÊe³Çe "
    assert text_has_residual_garble(garbled_header + body) is True


def test_clean_multilingual_page_does_not_flag():
    # a real address/contacts page: Russian + Spanish + German + Polish, all legitimate
    text = ("Представительство фирмы КРОНЕС в странах СНГ и Европы. "
            "KRONES AG, Repräsentanz México, SPÓLKA z o.o., Düsseldorf, "
            "адреса представительств приведены ниже для связи с сервисной службой. " * 2)
    assert text_has_residual_garble(text) is False


def test_clean_russian_body_does_not_flag():
    text = ("Агрегат укупорки винтовой пробкой фирмы КРОНЕС рассчитан, оснащён и "
            "оборудован для надёжной и безопасной эксплуатации в составе линии розлива. " * 2)
    assert text_has_residual_garble(text) is False


def test_short_text_is_ignored():
    # below min_chars: don't risk a false trigger on a tiny snippet
    assert text_has_residual_garble("Tex³ÇñecÉÇe ÷a³³õe") is False


def test_predominantly_permutation_page_flags():
    # the worst case: almost every token is the permutation cipher (like D-04-00020)
    text = ("жіcНpyЙрЗЗ Mo³ÍaÅ ÷eêo³ÍaÅ yÉyìopoñ³õx ÂoÊoÁoÉ èPOHEC "
            "ВaÅ³õe yÉaÆa³Çû OÆ³aÉoêÊe³Çe Tex³ÇñecÉÇe ÷a³³õe ÀeÆoìac³ocÍø "
            "ÌpÇ³ðÇì oy³ÉðÇo³ÇpoÁa³Çû íÉyìopÉa cocÍoûóaû ЗЖ Cocy÷ ") * 2
    assert text_has_residual_garble(text) is True
