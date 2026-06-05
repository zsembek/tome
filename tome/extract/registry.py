"""Extractor registry + routing (primary -> quality check -> fallback)."""
from __future__ import annotations

import logging

from tome.config import Config, get_config
from tome.extract.base import (ExtractResult, Page, page_is_poor, repair_encoding,
                               strip_control_chars, text_has_residual_garble,
                               text_looks_garbled)
from tome.extract import pdfutil

log = logging.getLogger(__name__)

# top-10 names -> lazy imports (cloud/heavy adapters pull in packages/keys
# only when actually used; the registry lists every option).
_BUILDERS = {
    "tika":         ("tome.extract.tika", "TikaExtractor"),
    "docling":      ("tome.extract.docling", "DoclingExtractor"),
    "marker":       ("tome.extract.marker", "MarkerExtractor"),
    "azure_di":     ("tome.extract.azure_di", "AzureDIExtractor"),
    "aws_textract": ("tome.extract.aws_textract", "AWSTextractExtractor"),
    "google_docai": ("tome.extract.google_docai", "GoogleDocAIExtractor"),
    "mistral_ocr":  ("tome.extract.mistral_ocr", "MistralOCRExtractor"),
    "unstructured": ("tome.extract.unstructured", "UnstructuredExtractor"),
    "llamaparse":   ("tome.extract.llamaparse", "LlamaParseExtractor"),
    "vision_llm":   ("tome.extract.vision_llm", "VisionLLMExtractor"),
    "passthrough":  ("tome.extract.passthrough", "PassthroughExtractor"),
}

AVAILABLE_EXTRACTORS = [k for k in _BUILDERS if k != "passthrough"]

# Truth-in-advertising: which adapters are exercised here vs. implemented-but-unverified
# against the live third-party service. "experimental" adapters work in principle but
# have not been validated end-to-end in this repo.
VERIFIED_EXTRACTORS = {"tika", "docling", "vision_llm", "azure_di", "passthrough"}
EXPERIMENTAL_EXTRACTORS = {"marker", "aws_textract", "google_docai",
                           "mistral_ocr", "unstructured", "llamaparse"}

# Optional pip package each adapter needs (None = covered by core deps).
_REQUIRES = {
    "tika": None, "passthrough": None, "vision_llm": None,
    "mistral_ocr": None, "unstructured": None, "llamaparse": None,
    "docling": "docling", "marker": "marker-pdf",
    "azure_di": "azure-ai-documentintelligence", "aws_textract": "boto3",
    "google_docai": "google-cloud-documentai",
}
_cache: dict[str, object] = {}


def extractor_status(name: str) -> str:
    if name in VERIFIED_EXTRACTORS:
        return "verified"
    if name in EXPERIMENTAL_EXTRACTORS:
        return "experimental"
    return "unknown"


def list_extractors() -> list[dict]:
    """Catalog of extractors with verification status and optional pip requirement."""
    return [{"name": n, "status": extractor_status(n), "requires": _REQUIRES.get(n)}
            for n in _BUILDERS]


def get_extractor(name: str, cfg: Config | None = None):
    cfg = cfg or get_config()
    if name in _cache:
        return _cache[name]
    if name not in _BUILDERS:
        raise ValueError(f"Unknown extractor: {name}. Available: {sorted(_BUILDERS)}")
    mod, cls = _BUILDERS[name]
    import importlib
    impl = getattr(importlib.import_module(mod), cls)(cfg)
    _cache[name] = impl
    return impl


def extract_document(file_bytes: bytes, *, mime: str, filename: str,
                     cfg: Config | None = None) -> ExtractResult:
    """Main entry point: picks an extractor by file type and repairs "poor"
    pages with a fallback (vision-LLM / cloud DI) if one is configured."""
    cfg = cfg or get_config()
    ocr_lang = cfg.extract_ocr_lang

    # text formats -> passthrough, no OCR
    pt = get_extractor("passthrough", cfg)
    if pt.supports(mime, filename):
        return pt.extract(file_bytes, mime=mime, filename=filename, ocr_lang=ocr_lang)

    is_pdf_early = (mime == "application/pdf") or filename.lower().endswith(".pdf")
    primary_name = cfg.extract_primary
    try:
        primary = get_extractor(primary_name, cfg)
        # split large PDFs to fit provider limits and stitch back with page offset
        if is_pdf_early and _too_big(file_bytes, cfg):
            result = _extract_large_pdf(primary, file_bytes, mime, filename, ocr_lang, cfg)
        else:
            result = primary.extract(file_bytes, mime=mime, filename=filename, ocr_lang=ocr_lang)
    except Exception as exc:
        log.warning("primary extractor %s failed: %s — trying fallback", primary_name, exc)
        result = ExtractResult(pages=[], metadata={}, extractor=primary_name)

    # Cheap deterministic repair: a CP1251/KOI8-R text layer mis-decoded as Latin-1 is
    # fixed by re-decoding (no OCR/LLM), LINE BY LINE — so it also fixes MIXED pages
    # (garbled header + clean ASCII/Cyrillic body) without disturbing the clean lines.
    # Run unconditionally (repair_encoding returns None when nothing needs fixing); runs
    # first so language detection sees clean text. Pages still garbled afterwards
    # (custom-font CMap permutation) fall through to the render+OCR repair below.
    for p in result.pages:
        if not p.text:
            continue
        # strip NUL/C0 control bytes (broken PDFs contain them) — PostgreSQL rejects NUL
        sanitized = strip_control_chars(p.text)
        if sanitized != p.text:
            p.text = sanitized
            p.char_count = len(sanitized)
        fixed = repair_encoding(p.text)
        if fixed and fixed != p.text:
            log.info("repaired mis-decoded text layer (page %s) via codepage re-decode", p.number)
            p.text = fixed
            p.char_count = len(fixed)

    # AI language pre-analysis: detect the document's real language(s) and, if the OCR
    # ran with the wrong languages, re-scan with the correct set. Never breaks extraction.
    if cfg.extract_auto_lang and result.pages:
        try:
            result, ocr_lang = _apply_auto_language(result, primary, file_bytes, mime,
                                                    filename, ocr_lang, cfg, is_pdf_early)
        except Exception as exc:
            log.debug("auto-language analysis skipped: %s", exc)

    # repair poor pages (PDF only — rendering is available)
    is_pdf = (mime == "application/pdf") or filename.lower().endswith(".pdf")
    fb_name = cfg.extract_scanned or cfg.extract_fallback
    if is_pdf and fb_name and (not result.pages or any(page_is_poor(p) for p in result.pages)):
        result = _repair_poor_pages(result, file_bytes, fb_name, cfg)

    # FINAL pass on EVERY page, regardless of which path produced the text (primary
    # extract, codepage repair, language re-scan, or OCR fallback): (1) repair mis-decoded
    # CP1251/KOI8-R again — the auto-language re-scan can replace pages with a fresh RAW
    # (still-garbled) extraction AFTER the early repair, and downstream structuring must
    # see clean text to add headings; (2) strip NUL/C0 control bytes PostgreSQL rejects.
    for p in result.pages:
        if not p.text:
            continue
        fixed = repair_encoding(p.text)
        if fixed and fixed != p.text:
            p.text = fixed
        p.text = strip_control_chars(p.text)
        p.char_count = len(p.text)
    return result


def _apply_auto_language(result: ExtractResult, primary, file_bytes: bytes, mime: str,
                         filename: str, ocr_lang: str, cfg: Config, is_pdf: bool):
    """Detect the sample's language(s); if they aren't covered by the current OCR
    language set, re-scan once with the corrected set and keep the better result.
    Always records the detected primary language in result.metadata['language']."""
    from tome.lang import detect_languages, to_ocr_langs
    sample = ""
    for p in result.pages:
        sample += (p.text or "") + "\n"
        if len(sample) >= cfg.extract_lang_sample_chars:
            break
    sample = sample.strip()
    if not sample:
        return result, ocr_lang
    detected = detect_languages(sample, cfg=cfg)
    if detected:
        result.metadata["language"] = detected[0]
    needed = set(filter(None, to_ocr_langs(detected).split("+")))
    current = set(filter(None, ocr_lang.split("+")))
    # only re-OCR scanned PDFs whose detected language isn't already covered
    if is_pdf and needed and not needed <= current:
        merged = "+".join(sorted(current | needed))
        log.info("auto-language: detected %s — re-scanning OCR with '%s'", detected, merged)
        re_res = (_extract_large_pdf(primary, file_bytes, mime, filename, merged, cfg)
                  if _too_big(file_bytes, cfg)
                  else primary.extract(file_bytes, mime=mime, filename=filename, ocr_lang=merged))
        # keep the re-scan only if it didn't lose content
        if re_res.pages and re_res.total_chars >= result.total_chars * 0.9:
            re_res.metadata.setdefault("language", result.metadata.get("language", ""))
            d2 = detect_languages("\n".join(p.text or "" for p in re_res.pages)[:cfg.extract_lang_sample_chars], cfg=cfg)
            if d2:
                re_res.metadata["language"] = d2[0]
            result, ocr_lang = re_res, merged
    for p in result.pages:
        if not p.language:
            p.language = result.metadata.get("language", "")
    return result, ocr_lang


def _too_big(pdf_bytes: bytes, cfg: Config) -> bool:
    try:
        return pdfutil.page_count(pdf_bytes) > cfg.extract_max_pages
    except Exception:
        return False


def _extract_large_pdf(extractor, pdf_bytes: bytes, mime: str, filename: str,
                       ocr_lang: str, cfg: Config) -> ExtractResult:
    """Splits a large PDF into chunks of <= extract_max_pages, extracts each, and
    stitches the pages back together with continuous numbering."""
    parts = pdfutil.split_pdf(pdf_bytes, cfg.extract_max_pages)
    all_pages, meta, name = [], {}, extractor.name
    for start, end, chunk in parts:
        r = extractor.extract(chunk, mime=mime, filename=filename, ocr_lang=ocr_lang)
        meta = meta or r.metadata
        for p in r.pages:
            p.number = start + (p.number - 1)   # continuous page number
            for f in p.figures:
                f.page_number = p.number
            all_pages.append(p)
    log.info("large PDF: %d pages in %d chunks", len(all_pages), len(parts))
    return ExtractResult(pages=all_pages, metadata=meta, extractor=name)


def _repair_poor_pages(result: ExtractResult, pdf_bytes: bytes, fb_name: str,
                       cfg: Config) -> ExtractResult:
    try:
        fb = get_extractor(fb_name, cfg)
    except Exception as exc:
        log.warning("fallback %s unavailable: %s", fb_name, exc)
        return result

    n = pdfutil.page_count(pdf_bytes)
    if not result.pages:
        result.pages = [Page(number=i + 1, text="", char_count=0) for i in range(n)]

    for p in result.pages:
        if not page_is_poor(p):
            continue
        idx0 = p.number - 1
        try:
            if fb_name == "vision_llm":
                png = pdfutil.render_page_png(pdf_bytes, idx0)
                txt = fb.read_page_image(png)
            else:
                # cloud DI on a single-page fragment
                sub = pdfutil.split_pdf(pdf_bytes, 1)
                target = next((b for s, e, b in sub if s == p.number), None)
                txt = ""
                if target is not None:
                    r = fb.extract(target, mime="application/pdf", filename="page.pdf",
                                   ocr_lang=cfg.extract_ocr_lang)
                    txt = "\n\n".join(pg.text for pg in r.pages)
            # a garbled (broken-CMap) page has many junk chars, so don't gate on length —
            # replace whenever the OCR result is itself clean; otherwise keep the longer text.
            # `was_residual` covers a page whose body already repaired but still carries a
            # permutation-cipher header (whole-page text_looks_garbled is False there): we
            # still want the clean OCR, but guard against swapping a mostly-clean body for a
            # much shorter OCR read (keep >=50% of the length).
            was_garbled = text_looks_garbled(p.text)
            was_residual = text_has_residual_garble(p.text)
            ocr_clean = bool(txt) and not text_looks_garbled(txt) and not text_has_residual_garble(txt)
            if ocr_clean and (was_garbled or len(txt) > len(p.text)
                              or (was_residual and len(txt) >= len(p.text) * 0.5)):
                p.text = txt
                p.char_count = len(txt)
        except Exception as exc:
            log.warning("fallback on page %d failed: %s", p.number, exc)
    return result
