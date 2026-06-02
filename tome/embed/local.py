"""Local embedder via sentence-transformers (BGE/e5). Optional dependency.

Fully offline — data never leaves the perimeter (personal mode / privacy)."""
from __future__ import annotations

from tome.config import Config


class LocalEmbedder:
    def __init__(self, cfg: Config):
        from sentence_transformers import SentenceTransformer  # lazy import
        self.model_id = cfg.embed_model or "BAAI/bge-m3"
        self._model = SentenceTransformer(self.model_id)
        self.dim = self._model.get_sentence_embedding_dimension()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vecs = self._model.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vecs]
