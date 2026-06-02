"""Atlas stage: delta rebuild of a folder node from DB FACTS via the LLM.

The DB is the source of truth; the LLM merely renders the facts into readable Markdown."""
from __future__ import annotations

import logging

from tome.config import Config
from tome.llm import get_llm
from tome.prompts import load_prompt

log = logging.getLogger(__name__)


def build_folder_node(folder_name: str, folder_desc: str,
                      docs: list[dict], cfg: Config, target_lang: str) -> str:
    """docs: [{title, summary, section_count}]. Returns an Atlas Markdown node."""
    facts = [f"Folder: {folder_name}"]
    if folder_desc:
        facts.append(f"Description: {folder_desc}")
    facts.append("Documents:")
    for d in docs:
        facts.append(f"- {d['title']} :: {d.get('summary','')} :: sections {d.get('section_count',0)}")
    system = load_prompt("atlas", TARGET_LANG=target_lang, FOLDER_FACTS="\n".join(facts))
    try:
        res = get_llm(cfg).chat(system=system, user="Generate the Atlas node.",
                                model=cfg.llm_atlas_model, max_tokens=2000)
        return res.text.strip()
    except Exception as exc:
        log.warning("atlas LLM failed: %s — deterministic fallback", exc)
        return _fallback_node(folder_name, folder_desc, docs)


def build_index(folders: list[dict]) -> str:
    """Deterministic Atlas index (no LLM): ALL folders indented by nesting depth
    (by the number of ltree-path segments) + document counts."""
    lines = ["# Knowledge base Atlas", ""]
    for f in folders:
        depth = max(0, f.get("path", "").count(".")) if f.get("path") else 0
        indent = "  " * depth
        bullet = "##" if depth == 0 else "-"
        lines.append(f"{indent}{bullet} {f['name']} — _documents: {f.get('document_count', 0)}_")
        if f.get("description"):
            lines.append(f"{indent}  {f['description']}")
    return "\n".join(lines).strip() + "\n"


def _fallback_node(name: str, desc: str, docs: list[dict]) -> str:
    out = [f"## {name}"]
    if desc:
        out.append(desc)
    for d in docs:
        out.append(f"- **{d['title']}** — {d.get('summary','')} ({d.get('section_count',0)} sections)")
    return "\n".join(out).strip() + "\n"
