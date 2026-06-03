"""Adapter for OpenAI-compatible APIs: OpenAI, Azure OpenAI, x.AI (Grok),
Ollama, vLLM and any server exposing /v1/chat/completions.

Handles the differences: Azure (deployment-based, api-version), reasoning models
(max_completion_tokens instead of max_tokens, no temperature)."""
from __future__ import annotations

import base64
import logging
import time

import httpx
from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AzureOpenAI,
    BadRequestError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from tome.config import Config
from tome.llm.base import ChatResult

log = logging.getLogger(__name__)

_RETRYABLE = (
    RateLimitError, APIConnectionError, APITimeoutError, InternalServerError,
    httpx.ConnectError, httpx.ReadError, httpx.ReadTimeout, httpx.RemoteProtocolError,
    ConnectionError,
)


def _param_unsupported(exc: APIError, param: str) -> bool:
    if not isinstance(exc, BadRequestError):
        return False
    body = getattr(exc, "body", None) or {}
    err = body.get("error", {}) if isinstance(body, dict) else {}
    return err.get("code") == "unsupported_parameter" and err.get("param") == param


class OpenAICompatProvider:
    """provider ∈ {openai, azure_openai, xai, ollama, vllm, openai_compatible}."""

    def __init__(self, cfg: Config, provider: str):
        self.cfg = cfg
        self.provider = provider
        # client-level timeout; disable the SDK's own retries — we manage retries
        # ourselves (bounded) so a hung endpoint can't stall ingestion for minutes.
        timeout = max(1.0, float(getattr(cfg, "llm_timeout_sec", 60.0)))
        if provider == "azure_openai":
            self.client = AzureOpenAI(
                azure_endpoint=cfg.azure_openai_endpoint,
                api_key=cfg.azure_openai_key,
                api_version=cfg.azure_openai_api_version,
                timeout=timeout, max_retries=0,
            )
        else:
            base_url = cfg.openai_base_url or _default_base(provider)
            self.client = OpenAI(
                api_key=cfg.openai_api_key or "sk-noauth",
                base_url=base_url or None,
                timeout=timeout, max_retries=0,
            )

    def _retry(self, fn):
        """Bounded retry with capped backoff (cfg.llm_max_retries extra attempts)."""
        attempts = max(1, int(getattr(self.cfg, "llm_max_retries", 2)) + 1)
        delay = 1.0
        for i in range(attempts):
            try:
                return fn()
            except _RETRYABLE:
                if i >= attempts - 1:
                    raise
                time.sleep(min(delay, 8.0)); delay *= 2

    # ── chat ──
    def chat(self, *, system, user, model, max_tokens=4000, temperature=0.2, json=False) -> ChatResult:
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        return self._retry(lambda: self._complete(model, msgs, max_tokens, temperature, json))

    def vision(self, *, system, prompt, image_bytes, image_mime, model, max_tokens=2000) -> ChatResult:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{image_mime};base64,{b64}"
        msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]},
        ]
        return self._retry(lambda: self._complete(model, msgs, max_tokens, 0.2, False))

    def _complete(self, model, messages, max_tokens, temperature, json) -> ChatResult:
        # per-provider rate limit (from settings) — shared across all threads
        from tome.ratelimit import throttle
        throttle(self.provider, self.cfg.provider_min_interval_sec)
        kwargs: dict = {"model": model, "messages": messages,
                        "max_completion_tokens": max_tokens}
        if json:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except APIError as exc:
            if _param_unsupported(exc, "max_completion_tokens"):
                kwargs.pop("max_completion_tokens", None)
                kwargs["max_tokens"] = min(max_tokens, 8192)
                kwargs["temperature"] = temperature
                resp = self.client.chat.completions.create(**kwargs)
            else:
                raise
        choice = resp.choices[0]
        usage = getattr(resp, "usage", None)
        return ChatResult(
            text=(choice.message.content or "").strip(),
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            finish_reason=getattr(choice, "finish_reason", None),
        )


def _default_base(provider: str) -> str:
    return {
        "xai": "https://api.x.ai/v1",
        "ollama": "http://localhost:11434/v1",
        "vllm": "http://localhost:8000/v1",
    }.get(provider, "")
