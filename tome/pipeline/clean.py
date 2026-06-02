"""Cleans markdown of extractor housekeeping noise (PageHeader/Footer/Break),
simple HTML tables → markdown pipe, complex ones kept as HTML.

Ported and generalized from the proven scripts/md_clean.py."""
from __future__ import annotations

import re
from html.parser import HTMLParser

_PAGE_META_RE = re.compile(r"<!--\s*Page(?:Header|Footer|Number)=[^>]*?-->\s*", re.IGNORECASE)
_PAGE_BREAK_RE = re.compile(r"<!--\s*PageBreak\s*-->", re.IGNORECASE)
_TABLE_BLOCK_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.IGNORECASE | re.DOTALL)
_LEADING_ESCAPE_RE = re.compile(r"^(\s*)\\([+\-])", re.MULTILINE)
_MANY_BLANK_RE = re.compile(r"\n{3,}")


def clean(markdown: str) -> str:
    text = markdown
    text = _PAGE_META_RE.sub("", text)
    text = _PAGE_BREAK_RE.sub("\n\n", text)
    text = _TABLE_BLOCK_RE.sub(_table_replacer, text)
    text = _LEADING_ESCAPE_RE.sub(r"\1\2", text)
    text = _MANY_BLANK_RE.sub("\n\n", text)
    return text.strip() + "\n"


def _table_replacer(m: "re.Match[str]") -> str:
    md = _html_table_to_md(m.group(0))
    return ("\n\n" + md + "\n\n") if md is not None else ("\n\n" + m.group(0).strip() + "\n\n")


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.caption_parts: list[str] = []
        self.in_caption = False
        self.bail = False
        self.first_th = False

    def handle_starttag(self, tag, attrs):
        if self.bail:
            return
        d = dict(attrs)
        if tag == "caption":
            self.in_caption = True
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            if (d.get("rowspan") and d["rowspan"] != "1") or (d.get("colspan") and d["colspan"] != "1"):
                self.bail = True
                return
            self.cell = []
            if tag == "th" and self.row == [] and not self.rows:
                self.first_th = True
        elif tag == "br":
            if self.cell is not None:
                self.cell.append(" ")
        elif tag in ("strong", "b", "em", "i", "span", "p", "sub", "sup", "u", "thead", "tbody", "table"):
            pass
        else:
            self.bail = True

    def handle_endtag(self, tag):
        if self.bail:
            return
        if tag == "caption":
            self.in_caption = False
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()).replace("|", "\\|"))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.bail:
            return
        if self.in_caption:
            self.caption_parts.append(data)
        elif self.cell is not None:
            self.cell.append(data)


def _html_table_to_md(html: str) -> str | None:
    p = _TableParser()
    try:
        p.feed(html)
    except Exception:
        return None
    if p.bail or not p.rows:
        return None
    width = max(len(r) for r in p.rows)
    if width == 0:
        return None
    rows = [r + [""] * (width - len(r)) for r in p.rows]
    header = rows[0]
    body = rows[1:]
    out = []
    cap = " ".join("".join(p.caption_parts).split())
    if cap:
        out += [f"**{cap}**", ""]
    out.append("| " + " | ".join(header) + " |")
    out.append("| " + " | ".join(["---"] * width) + " |")
    for r in body:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)
