"""Retrieval-chunking stage: section content → chunks of ~N tokens with overlap,
SEPARATE from sections. For embeddings/semantic search."""
from __future__ import annotations

from dataclasses import dataclass

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:  # tiktoken unavailable — rough word-based estimate
    _ENC = None


@dataclass
class Chunk:
    section_order_index: int
    ordinal: int
    text: str
    token_count: int


def _tokens(text: str) -> list[int] | list[str]:
    if _ENC:
        return _ENC.encode(text)
    return text.split()


def _detok(tokens, a: int, b: int) -> str:
    if _ENC:
        return _ENC.decode(tokens[a:b])
    return " ".join(tokens[a:b])


def chunk_section(section_order_index: int, text: str, *, chunk_tokens: int = 512,
                  overlap: int = 64) -> list[Chunk]:
    text = (text or "").strip()
    if not text:
        return []
    toks = _tokens(text)
    n = len(toks)
    if n <= chunk_tokens:
        return [Chunk(section_order_index, 0, text, n)]
    chunks: list[Chunk] = []
    start, ordinal = 0, 0
    step = max(1, chunk_tokens - overlap)
    while start < n:
        end = min(start + chunk_tokens, n)
        piece = _detok(toks, start, end).strip()
        if piece:
            chunks.append(Chunk(section_order_index, ordinal, piece, end - start))
            ordinal += 1
        if end >= n:
            break
        start += step
    return chunks
