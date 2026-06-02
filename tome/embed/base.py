"""Embedder contract."""
from __future__ import annotations

from typing import Protocol


class Embedder(Protocol):
    model_id: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for a batch of texts."""
        ...
