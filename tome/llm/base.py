"""LLM provider contract. All adapters conform to it."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ChatResult:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    finish_reason: str | None = None
    raw: dict = field(default_factory=dict)


class LLMProvider(Protocol):
    """Unified interface for chat and vision. Implemented by adapters."""

    def chat(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 4000,
        temperature: float = 0.2,
        json: bool = False,
    ) -> ChatResult: ...

    def vision(
        self,
        *,
        system: str,
        prompt: str,
        image_bytes: bytes,
        image_mime: str,
        model: str,
        max_tokens: int = 2000,
    ) -> ChatResult: ...
