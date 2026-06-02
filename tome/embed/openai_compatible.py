"""Embedder via an OpenAI-compatible /v1/embeddings endpoint (OpenAI, Azure, vLLM,
Ollama, as well as Voyage/Cohere behind an OpenAI-compatible proxy)."""
from __future__ import annotations

import logging

from openai import AzureOpenAI, OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from tome.config import Config

log = logging.getLogger(__name__)

# Known dimensions (fallback — determined from the first response)
_DIMS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "bge-m3": 1024,
}


class OpenAICompatEmbedder:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.model_id = cfg.embed_model
        self.dim = _DIMS.get(cfg.embed_model, 0)  # 0 → determined dynamically
        if cfg.embed_provider == "azure_openai":
            self.client = AzureOpenAI(
                azure_endpoint=cfg.azure_openai_endpoint,
                api_key=cfg.azure_openai_key,
                api_version=cfg.azure_openai_api_version,
            )
        else:
            self.client = OpenAI(
                api_key=cfg.openai_api_key or "sk-noauth",
                base_url=cfg.openai_base_url or None,
            )

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=3, min=3, max=30), reraise=True)
    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = self.client.embeddings.create(model=self.model_id, input=texts)
        vecs = [d.embedding for d in resp.data]
        if vecs and not self.dim:
            self.dim = len(vecs[0])
        return vecs
