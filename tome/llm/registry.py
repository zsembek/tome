"""Select the LLM provider based on config."""
from __future__ import annotations

from tome.config import Config, get_config
from tome.llm.base import LLMProvider

_OPENAI_COMPAT = {"openai", "azure_openai", "xai", "ollama", "vllm", "openai_compatible"}
_cache: dict[str, LLMProvider] = {}


def get_llm(cfg: Config | None = None) -> LLMProvider:
    cfg = cfg or get_config()
    provider = cfg.llm_provider
    if provider in _cache:
        return _cache[provider]
    if provider in _OPENAI_COMPAT:
        from tome.llm.openai_compatible import OpenAICompatProvider
        impl = OpenAICompatProvider(cfg, provider)
    elif provider == "anthropic":
        from tome.llm.anthropic_provider import AnthropicProvider
        impl = AnthropicProvider(cfg)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
    _cache[provider] = impl
    return impl
