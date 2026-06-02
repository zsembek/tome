"""Pluggable embedder layer (for hybrid search)."""
from tome.embed.registry import get_embedder

__all__ = ["get_embedder"]
