"""Safety: the structure LLM must NEVER run on garbled/mojibake extraction. Feeding a
broken text layer (custom-font permutation, mis-decoded codepage) to the LLM makes it
fabricate plausible-but-wrong content and write placeholders like "[unreadable]" — far
worse than honest raw text in a technical manual. Garbled pages are kept verbatim."""
import pytest

from tome.config import Config

pytestmark = pytest.mark.unit

# permutation-cipher mojibake (ASCII letters + brackets), like the SIDEL/MOJONNIER manuals
GARBLED = ("MUJLJ WXZVe R XKcRO YZJLRUJ de]Za_U ] XUeUbg]t deZYhdeZ[YZb]t ] dZefcbU` "
           "dcYXcgcW]gZqbpZ dcYWcY_] WpdcbtZapZ dc_hdUgZ`Za ]bfgeh_k]] Y`t \\U_U\\U ") * 4


def test_structure_does_not_call_llm_on_garbled(monkeypatch):
    import tome.pipeline.structure as s

    calls = []

    class _LLM:
        def chat(self, **kw):
            calls.append(kw)
            from tome.llm.base import ChatResult
            return ChatResult(text="[fabricated clean text]", tokens_in=5, tokens_out=5,
                              finish_reason="stop")
    monkeypatch.setattr(s, "get_llm", lambda cfg: _LLM())

    cfg = Config()
    cfg.structure_enabled = True             # opt back in (conftest disables it globally)
    cfg.structure_smart = True
    out, ti, to = s.structure_page(GARBLED, cfg, "ru")
    assert calls == []                       # the LLM was never invoked
    assert "fabricated" not in out           # nothing invented
    assert out == GARBLED.strip()            # raw text kept verbatim
    assert ti == 0 and to == 0


def test_structure_still_calls_llm_on_normal_noisy_text(monkeypatch):
    import tome.pipeline.structure as s

    calls = []

    class _LLM:
        def chat(self, **kw):
            calls.append(kw)
            from tome.llm.base import ChatResult
            return ChatResult(text="# Cleaned\n\nReal content.", tokens_in=5, tokens_out=5,
                              finish_reason="stop")
    monkeypatch.setattr(s, "get_llm", lambda cfg: _LLM())

    # noisy but genuine text (glued words, no headings) — must still be structured
    noisy = "pumpmaintenance\nschedule\noil\nlevel\ncheck\nevery\nshift\nrecord\nreadings"
    cfg = Config()
    cfg.structure_enabled = True             # opt back in (conftest disables it globally)
    cfg.structure_smart = True
    s.structure_page(noisy, cfg, "en")
    assert len(calls) == 1                   # LLM still runs on real (non-garbled) input
