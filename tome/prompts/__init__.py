"""Loading system prompts from files (version-controlled, no hardcoding)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=32)
def _read(name: str) -> str:
    return (_DIR / f"{name}.txt").read_text(encoding="utf-8")


def load_prompt(name: str, **vars) -> str:
    """Reads prompts/<name>.txt and substitutes {VARS}."""
    text = _read(name)
    for k, v in vars.items():
        text = text.replace("{" + k + "}", str(v))
    return text
