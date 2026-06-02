"""Split stage: markdown → sections (hierarchy by headings) + normalization +
parts ≤ N characters. Ported from the proven md_parse + size normalization."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class Section:
    order_index: int
    level: int
    heading: str
    breadcrumb: str
    content: str
    parent_order_index: int | None
    anchor_slug: str = ""


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:80] or "section"


def build_sections(full_text: str, *, max_chars: int = 8000,
                   min_chars: int = 40) -> list[Section]:
    matches = list(_HEADING_RE.finditer(full_text))
    sections: list[Section] = []
    stack: list[tuple[int, int]] = []

    if not matches:
        sections.append(Section(0, 1, "(untitled)", "(untitled)",
                                full_text.strip(), None))
    else:
        if matches[0].start() > 0:
            pre = full_text[:matches[0].start()].strip()
            if pre:
                sections.append(Section(0, 1, "(preamble)", "(preamble)", pre, None))
        for i, m in enumerate(matches):
            level = len(m.group(1))
            heading = m.group(2).strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
            content = full_text[start:end].strip()
            oi = len(sections)
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else None
            crumb = " > ".join([sections[p].heading for _, p in stack] + [heading])
            sections.append(Section(oi, level, heading, crumb, content, parent))
            stack.append((level, oi))

    sections = _normalize(sections, max_chars=max_chars, min_chars=min_chars)
    for s in sections:
        s.anchor_slug = slugify(s.heading)
    # reindex order_index after normalization
    for i, s in enumerate(sections):
        s.order_index = i
    return sections


_DUP_NOISE = {"содержимое", "описание", "оглавление", "содержание"}


def _normalize(sections: list[Section], *, max_chars: int, min_chars: int) -> list[Section]:
    """Reject empty/junk sections + split up large ones (small ones are kept for now —
    they may serve a structural role as a parent)."""
    out: list[Section] = []
    seen_noise: set[str] = set()
    for s in sections:
        h = s.heading.lower().strip()
        # empty junk duplicates of header/footer headings
        if not s.content.strip() and h in _DUP_NOISE:
            if h in seen_noise:
                continue
            seen_noise.add(h)
        # split up large sections
        if len(s.content) > max_chars:
            out.extend(_split_large(s, max_chars))
        else:
            out.append(s)
    return out


def _split_large(s: Section, max_chars: int) -> list[Section]:
    """Splits a large section's content into sub-sections by paragraph, preserving the breadcrumb."""
    paras = re.split(r"\n{2,}", s.content)
    chunks: list[str] = []
    cur = ""
    for p in paras:
        if len(cur) + len(p) + 2 > max_chars and cur:
            chunks.append(cur.strip())
            cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur.strip():
        chunks.append(cur.strip())
    if len(chunks) <= 1:
        return [s]
    result = [Section(s.order_index, s.level, s.heading, s.breadcrumb, chunks[0],
                      s.parent_order_index)]
    for i, ch in enumerate(chunks[1:], start=1):
        result.append(Section(s.order_index, min(s.level + 1, 6),
                              f"{s.heading} (pt.{i+1})",
                              f"{s.breadcrumb} (pt.{i+1})", ch, s.order_index))
    return result


def split_parts(full_md: str, max_chars: int) -> list[str]:
    """Cuts the whole document into parts ≤ max_chars at heading boundaries (for get_document)."""
    if len(full_md) <= max_chars:
        return [full_md]
    offsets = [0] + [m.start() for m in _HEADING_RE.finditer(full_md)] + [len(full_md)]
    offsets = sorted(set(offsets))
    parts, cur = [], 0
    while cur < len(full_md):
        target = cur + max_chars
        if target >= len(full_md):
            parts.append(full_md[cur:]); break
        cand = [o for o in offsets if cur < o <= target]
        cut = cand[-1] if cand else full_md.rfind("\n\n", cur, target)
        if cut <= cur:
            cut = full_md.rfind("\n", cur, target)
        if cut <= cur:
            cut = target
        parts.append(full_md[cur:cut]); cur = cut
    return parts
