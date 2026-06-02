"""LlamaParse extractor (LlamaIndex) — complex PDFs/tables -> Markdown.
Via the LlamaCloud API (httpx): upload -> poll -> result markdown."""
from __future__ import annotations

import logging
import time

import httpx

from tome.config import Config
from tome.extract.base import ExtractResult, Page

log = logging.getLogger(__name__)
_BASE = "https://api.cloud.llamaindex.ai/api/v1/parsing"


class LlamaParseExtractor:
    name = "llamaparse"

    def __init__(self, cfg: Config):
        if not cfg.llamaparse_api_key:
            raise RuntimeError("llamaparse: LLAMAPARSE_API_KEY not set")
        self.h = {"Authorization": f"Bearer {cfg.llamaparse_api_key}"}

    def supports(self, mime: str, filename: str) -> bool:
        return filename.lower().endswith((".pdf", ".docx", ".pptx", ".xlsx", ".html"))

    def extract(self, file_bytes: bytes, *, mime: str, filename: str, ocr_lang: str) -> ExtractResult:
        with httpx.Client(timeout=600) as c:
            up = c.post(f"{_BASE}/upload", headers=self.h,
                        files={"file": (filename, file_bytes, mime or "application/octet-stream")},
                        data={"result_type": "markdown"})
            up.raise_for_status()
            jid = up.json()["id"]
            for _ in range(120):
                st = c.get(f"{_BASE}/job/{jid}", headers=self.h).json()
                if st.get("status") == "SUCCESS":
                    break
                if st.get("status") == "ERROR":
                    raise RuntimeError(f"llamaparse job error: {st}")
                time.sleep(3)
            res = c.get(f"{_BASE}/job/{jid}/result/markdown", headers=self.h).json()
        pages_data = res.get("pages", [])
        if pages_data:
            pages = [Page(number=i + 1, text=(p.get("md", "") or "").strip(),
                          char_count=len(p.get("md", "") or ""))
                     for i, p in enumerate(pages_data)]
        else:
            md = res.get("markdown", "") or ""
            pages = [Page(number=1, text=md.strip(), char_count=len(md))]
        return ExtractResult(pages=pages, metadata={}, extractor=self.name)
