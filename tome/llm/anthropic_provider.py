"""Anthropic (Claude) adapter. Imported lazily — the package is optional."""
from __future__ import annotations

import base64

from tome.config import Config
from tome.llm.base import ChatResult


class AnthropicProvider:
    def __init__(self, cfg: Config):
        import anthropic  # lazy import
        self.client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)

    def chat(self, *, system, user, model, max_tokens=4000, temperature=0.2, json=False) -> ChatResult:
        msg = self.client.messages.create(
            model=model, system=system, max_tokens=max_tokens, temperature=temperature,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
        return ChatResult(text=text, tokens_in=msg.usage.input_tokens,
                          tokens_out=msg.usage.output_tokens,
                          finish_reason=msg.stop_reason)

    def vision(self, *, system, prompt, image_bytes, image_mime, model, max_tokens=2000) -> ChatResult:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        msg = self.client.messages.create(
            model=model, system=system, max_tokens=max_tokens,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": image_mime, "data": b64}},
                {"type": "text", "text": prompt},
            ]}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
        return ChatResult(text=text, tokens_in=msg.usage.input_tokens,
                          tokens_out=msg.usage.output_tokens, finish_reason=msg.stop_reason)
