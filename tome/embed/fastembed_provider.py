"""Local embedder via fastembed (ONNX, CPU — no torch). Light and fully offline:
recommended for the zero-egress / personal profile. Optional dependency."""
from __future__ import annotations

from tome.config import Config

_DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


class FastEmbedEmbedder:
    def __init__(self, cfg: Config):
        from fastembed import TextEmbedding  # lazy import
        # fastembed needs an org/model id; fall back if an OpenAI-style name is set.
        self.model_id = cfg.embed_model if "/" in (cfg.embed_model or "") else _DEFAULT_MODEL
        self._model = TextEmbedding(model_name=self.model_id)
        self.dim = len(next(iter(self._model.embed(["probe"]))))

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return [[float(x) for x in v] for v in self._model.embed(list(texts))]
