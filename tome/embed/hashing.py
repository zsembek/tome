"""Deterministic, dependency-free embedder (hashed bag-of-tokens).

Zero model download, fully offline. Captures lexical overlap (shared tokens →
closer vectors), so vector search is meaningful enough for tests/CI and as an
ultra-light fallback. For real semantic quality use `fastembed`/`openai`/`local`."""
from __future__ import annotations

import hashlib
import math

from tome.config import Config


class HashEmbedder:
    def __init__(self, cfg: Config):
        self.dim = int(getattr(cfg, "embed_dim", 0) or 256)
        self.model_id = f"hash-{self.dim}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in (t or "").lower().split():
                h = int(hashlib.sha256(tok.encode("utf-8")).hexdigest(), 16)
                v[h % self.dim] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out
