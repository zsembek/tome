"""Language detection for extraction \u2014 pick the RIGHT OCR languages per document.

A scanned document in (say) German OCR'd with an `eng+rus` engine config comes out
garbled. Tome runs a primary language analysis on a text sample (LLM when available,
a deterministic Unicode-script + stop-word heuristic otherwise), then maps the detected
languages to the OCR engine's codes and re-scans with the correct set. The detected
language also drives the Postgres full-text-search configuration, so search works in the
document's real language.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

# ISO 639-1 \u2192 Tesseract (used by Tika/OCR). Extend freely.
_ISO_TO_TESS = {
    "en": "eng", "ru": "rus", "de": "deu", "fr": "fra", "es": "spa", "it": "ita",
    "pt": "por", "nl": "nld", "pl": "pol", "uk": "ukr", "tr": "tur", "cs": "ces",
    "sv": "swe", "fi": "fin", "no": "nor", "da": "dan", "ro": "ron", "hu": "hun",
    "el": "ell", "bg": "bul", "sr": "srp", "ar": "ara", "fa": "fas", "he": "heb",
    "hi": "hin", "zh": "chi_sim", "ja": "jpn", "ko": "kor", "kk": "kaz", "az": "aze",
    "vi": "vie", "th": "tha", "id": "ind",
}
# Postgres FTS regconfig per ISO code (others fall back to 'simple').
_ISO_TO_FTS = {
    "ru": "russian", "en": "english", "de": "german", "fr": "french", "es": "spanish",
    "it": "italian", "pt": "portuguese", "nl": "dutch", "sv": "swedish", "no": "norwegian",
    "da": "danish", "fi": "finnish", "hu": "hungarian", "ro": "romanian", "tr": "turkish",
}

# Tiny stop-word sets to disambiguate Latin-script languages without a heavy dependency.
_LATIN_HINTS = {
    "de": {"der", "die", "und", "das", "mit", "nicht", "ist", "ein", "f\u00fcr", "auch"},
    "fr": {"le", "la", "les", "et", "des", "une", "pour", "dans", "est", "avec"},
    "es": {"el", "la", "los", "las", "und", "que", "para", "con", "una", "por"},
    "it": {"il", "la", "che", "di", "per", "con", "una", "sono", "anche", "nel"},
    "pt": {"o", "a", "os", "que", "para", "com", "uma", "n\u00e3o", "dos", "uma"},
    "en": {"the", "and", "of", "to", "in", "is", "for", "with", "that", "this"},
}
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def detect_languages(text: str, *, cfg=None, llm=None, model: str = "", max_langs: int = 3) -> list[str]:
    """Return ISO 639-1 codes for the language(s) in `text`, most prominent first.
    Uses the LLM when one is reachable, else a deterministic heuristic."""
    text = (text or "").strip()
    if not text:
        return []
    if llm is None and cfg is not None:
        try:
            from tome.llm.registry import get_llm
            llm = get_llm(cfg)
        except Exception:
            llm = None
    if llm is not None:
        codes = _detect_with_llm(text, llm, model or (getattr(cfg, "llm_naming_model", "") if cfg else ""))
        if codes:
            return codes[:max_langs]
    return _detect_heuristic(text)[:max_langs]


def _detect_with_llm(text: str, llm, model: str) -> list[str]:
    system = ("You are a language identifier. Identify the natural language(s) of the "
              "user's text. Reply with ONLY a comma-separated list of ISO 639-1 codes "
              "(e.g. 'en' or 'de,en'), most prominent first. No prose.")
    try:
        res = llm.chat(system=system, user=text[:2000], model=model or "gpt-4o-mini", max_tokens=20)
        raw = (res.text or "").lower()
        codes = re.findall(r"[a-z]{2}", raw)
        seen, out = set(), []
        for c in codes:
            if c in _ISO_TO_TESS and c not in seen:
                seen.add(c); out.append(c)
        return out
    except Exception as exc:
        log.debug("LLM language detection failed: %s", exc)
        return []


def _detect_heuristic(text: str) -> list[str]:
    """Script-based detection + a stop-word vote for Latin languages."""
    scripts = _script_counts(text)
    if not scripts:
        return ["en"]
    out: list[str] = []
    # non-Latin scripts map (mostly) 1:1 to a language/script
    order = sorted(scripts.items(), key=lambda kv: -kv[1])
    for script, _ in order:
        if script == "cyrillic":
            out.append(_cyrillic_lang(text))
        elif script == "han":
            out.append("zh")
        elif script == "kana":
            out.append("ja")
        elif script == "hangul":
            out.append("ko")
        elif script == "arabic":
            out.append("ar")
        elif script == "hebrew":
            out.append("he")
        elif script == "devanagari":
            out.append("hi")
        elif script == "greek":
            out.append("el")
        elif script == "latin":
            out.append(_latin_lang(text))
    # dedup, keep order
    seen, res = set(), []
    for c in out:
        if c and c not in seen:
            seen.add(c); res.append(c)
    return res or ["en"]


def _script_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ch in text:
        o = ord(ch)
        if 0x0400 <= o <= 0x04FF:
            k = "cyrillic"
        elif 0x4E00 <= o <= 0x9FFF:
            k = "han"
        elif 0x3040 <= o <= 0x30FF:
            k = "kana"
        elif 0xAC00 <= o <= 0xD7A3:
            k = "hangul"
        elif 0x0600 <= o <= 0x06FF:
            k = "arabic"
        elif 0x0590 <= o <= 0x05FF:
            k = "hebrew"
        elif 0x0900 <= o <= 0x097F:
            k = "devanagari"
        elif 0x0370 <= o <= 0x03FF:
            k = "greek"
        elif (0x41 <= o <= 0x5A) or (0x61 <= o <= 0x7A) or (0x00C0 <= o <= 0x024F):
            k = "latin"
        else:
            continue
        counts[k] = counts.get(k, 0) + 1
    # ignore scripts that are negligible noise (< 5% of detected chars)
    total = sum(counts.values()) or 1
    return {k: v for k, v in counts.items() if v / total >= 0.05}


def _cyrillic_lang(text: str) -> str:
    words = {w.lower() for w in _WORD.findall(text)}
    if {"\u0457", "\u0454", "\u0491"} & set("".join(words)):
        return "uk"
    if words & {"\u0436\u04d9\u043d\u0435", "\u0431\u04b1\u043b", "\u04af\u0448\u0456\u043d"}:
        return "kk"
    return "ru"


def _latin_lang(text: str) -> str:
    words = [w.lower() for w in _WORD.findall(text)]
    if not words:
        return "en"
    wset = set(words)
    best, best_score = "en", 0
    for lang, hints in _LATIN_HINTS.items():
        score = len(wset & hints)
        if score > best_score:
            best, best_score = lang, score
    return best


def to_ocr_langs(iso_codes: list[str]) -> str:
    """Map ISO 639-1 codes \u2192 a Tesseract language string like 'eng+deu'."""
    tess = [_ISO_TO_TESS[c] for c in iso_codes if c in _ISO_TO_TESS]
    seen, out = set(), []
    for t in tess:
        if t not in seen:
            seen.add(t); out.append(t)
    return "+".join(out)


def fts_config_for(iso_code: str) -> str:
    return _ISO_TO_FTS.get((iso_code or "")[:2], "simple")
