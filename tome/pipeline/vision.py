"""Vision stage: classify an image → describe it (if informative)."""
from __future__ import annotations

import json
import logging

from tome.config import Config
from tome.llm import get_llm
from tome.prompts import load_prompt

log = logging.getLogger(__name__)

_SKIP = {"logo", "decor"}


def classify_and_describe(png_bytes: bytes, cfg: Config, target_lang: str) -> dict:
    """Classify AND (if informative) describe an image in a SINGLE vision call.
    Returns {fig_class, informative, description}. Merging the old two-call
    classify-then-describe into one halves the vision round-trips per figure."""
    llm = get_llm(cfg)
    try:
        res = llm.vision(system=load_prompt("vision_combined", TARGET_LANG=target_lang),
                         prompt="Analyze this figure.", image_bytes=png_bytes,
                         image_mime="image/png", model=cfg.llm_vision_model,
                         max_tokens=cfg.llm_max_completion_tokens)
        data = json.loads(_extract_json(res.text))
    except Exception as exc:
        log.debug("vision analyze failed: %s — treating as non-informative", exc)
        return {"fig_class": "schematic", "informative": False, "description": ""}

    fig_class = data.get("fig_class") or data.get("class") or "schematic"
    informative = bool(data.get("informative", True))
    description = (data.get("description") or "").strip()
    if fig_class in _SKIP or not informative or not description:
        return {"fig_class": fig_class, "informative": False, "description": ""}
    return {"fig_class": fig_class, "informative": True, "description": description}


def _extract_json(text: str) -> str:
    s, e = text.find("{"), text.rfind("}")
    return text[s:e + 1] if s >= 0 and e > s else "{}"
