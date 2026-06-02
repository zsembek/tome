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
    """Returns {fig_class, informative, description}. Describes only
    informative images (to save cost)."""
    llm = get_llm(cfg)
    fig_class, informative = "schematic", True
    try:
        cl = llm.vision(system=load_prompt("classify_image"),
                        prompt="Classify.", image_bytes=png_bytes,
                        image_mime="image/png", model=cfg.llm_vision_model, max_tokens=200)
        data = json.loads(_extract_json(cl.text))
        fig_class = data.get("class", "schematic")
        informative = bool(data.get("informative", True))
    except Exception as exc:
        log.debug("classify failed: %s — treating as informative", exc)

    if fig_class in _SKIP or not informative:
        return {"fig_class": fig_class, "informative": False, "description": ""}

    desc = llm.vision(system=load_prompt("vision", TARGET_LANG=target_lang),
                      prompt="Describe this figure.", image_bytes=png_bytes,
                      image_mime="image/png", model=cfg.llm_vision_model,
                      max_tokens=cfg.llm_max_completion_tokens)
    return {"fig_class": fig_class, "informative": True, "description": desc.text.strip()}


def _extract_json(text: str) -> str:
    s, e = text.find("{"), text.rfind("}")
    return text[s:e + 1] if s >= 0 and e > s else "{}"
