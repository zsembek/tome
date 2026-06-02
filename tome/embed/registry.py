"""Select the embedder. Returns None if semantic search is disabled."""
from __future__ import annotations

from tome.config import Config, get_config
from tome.embed.base import Embedder

_cache: dict[str, Embedder] = {}


def get_embedder(cfg: Config | None = None) -> Embedder | None:
    cfg = cfg or get_config()
    if not cfg.embed_enabled:
        return None
    key = f"{cfg.embed_provider}:{cfg.embed_model}"
    if key in _cache:
        return _cache[key]
    provider = cfg.embed_provider
    if provider in ("openai", "azure_openai", "vllm", "ollama", "openai_compatible", "voyage", "cohere"):
        from tome.embed.openai_compatible import OpenAICompatEmbedder
        impl = OpenAICompatEmbedder(cfg)
    elif provider == "local":
        from tome.embed.local import LocalEmbedder
        impl = LocalEmbedder(cfg)
    else:
        raise ValueError(f"Unknown EMBED_PROVIDER: {provider}")
    _cache[key] = impl
    return impl
