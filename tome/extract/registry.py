"""Extractor registry + routing (primary -> quality check -> fallback)."""
from __future__ import annotations

import logging

from tome.config import Config, get_config
from tome.extract.base import ExtractResult, Page, page_is_poor
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
_cache: dict[str, object] = {}


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

    # repair poor pages (PDF only — rendering is available)
    is_pdf = (mime == "application/pdf") or filename.lower().endswith(".pdf")
    fb_name = cfg.extract_scanned or cfg.extract_fallback
    if is_pdf and fb_name and (not result.pages or any(page_is_poor(p) for p in result.pages)):
        result = _repair_poor_pages(result, file_bytes, fb_name, cfg)
    return result


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
            if txt and len(txt) > len(p.text):
                p.text = txt
                p.char_count = len(txt)
        except Exception as exc:
            log.warning("fallback on page %d failed: %s", p.number, exc)
    return result
