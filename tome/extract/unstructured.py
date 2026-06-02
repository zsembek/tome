"""Unstructured extractor — partitions a document into elements.
Via the Unstructured API (httpx). Elements -> markdown by type."""
from __future__ import annotations

import logging

import httpx

from tome.config import Config
from tome.extract.base import ExtractResult, Page

log = logging.getLogger(__name__)


class UnstructuredExtractor:
    name = "unstructured"

    def __init__(self, cfg: Config):
        if not cfg.unstructured_api_key:
            raise RuntimeError("unstructured: UNSTRUCTURED_API_KEY not set")
        self.key = cfg.unstructured_api_key
        self.url = cfg.unstructured_api_url

    def supports(self, mime: str, filename: str) -> bool:
        return True

    def extract(self, file_bytes: bytes, *, mime: str, filename: str, ocr_lang: str) -> ExtractResult:
        with httpx.Client(timeout=300) as c:
            r = c.post(self.url, headers={"unstructured-api-key": self.key, "accept": "application/json"},
                       files={"files": (filename, file_bytes, mime or "application/octet-stream")},
                       data={"strategy": "hi_res", "languages": ocr_lang.replace("+", ",")})
            r.raise_for_status()
            elements = r.json()
        # group elements by page_number, convert types to markdown
        by_page: dict[int, list[str]] = {}
        for el in elements:
            meta = el.get("metadata", {})
            pg = meta.get("page_number", 1)
            text = el.get("text", "") or ""
            typ = el.get("type", "")
            if typ == "Title":
                text = f"## {text}"
            elif typ == "ListItem":
                text = f"- {text}"
            by_page.setdefault(pg, []).append(text)
        pages = [Page(number=pg, text="\n\n".join(parts).strip(),
                      char_count=sum(len(p) for p in parts))
                 for pg, parts in sorted(by_page.items())]
        if not pages:
            pages = [Page(number=1, text="", char_count=0)]
        return ExtractResult(pages=pages, metadata={}, extractor=self.name)
