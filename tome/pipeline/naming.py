"""Name stage: title/summary/tags/entities/suggested_folder via the LLM (JSON)."""
from __future__ import annotations

import json
import logging

from tome.config import Config
from tome.llm import get_llm
from tome.prompts import load_prompt

log = logging.getLogger(__name__)


def derive_metadata(text: str, cfg: Config, target_lang: str,
                    existing_folders: list[str], filename: str) -> dict:
    head = text[:4000]
    system = load_prompt("name", TARGET_LANG=target_lang,
                         EXISTING_FOLDERS="\n".join(existing_folders[:200]) or "(empty)")
    llm = get_llm(cfg)
    try:
        res = llm.chat(system=system, user=head, model=cfg.llm_naming_model,
                       max_tokens=1000, json=True)
        data = json.loads(_extract_json(res.text))
    except Exception as exc:
        log.warning("naming failed: %s — falling back to the filename", exc)
        data = {}
    base = filename.rsplit(".", 1)[0] if "." in filename else filename
    return {
        "title": data.get("title") or base,
        "summary": data.get("summary", ""),
        "tags": data.get("tags", []) or [],
        "entities": data.get("entities", []) or [],
        "suggested_folder_path": data.get("suggested_folder_path") or None,
        "language": data.get("language", ""),
    }


def _extract_json(text: str) -> str:
    s, e = text.find("{"), text.rfind("}")
    return text[s:e + 1] if s >= 0 and e > s else "{}"
