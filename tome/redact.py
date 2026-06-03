"""Secret redaction — keep live credentials out of stored agent memory.

`redact()` masks common credential shapes and strips explicit
``<private>…</private>`` blocks. It is conservative (only well-known token
prefixes/structures) to avoid mangling ordinary prose, and idempotent so it can
run on every write without compounding. All patterns are ASCII.
"""
from __future__ import annotations

import re

_MASK = "[redacted:{}]"

# (compiled pattern, label). Order matters: PEM blocks before generic tokens.
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----"
        r".*?-----END (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----",
        re.DOTALL), "private-key"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "openai-key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "aws-key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "github-token"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "slack-token"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"), "google-key"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"), "bearer"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}\b"), "jwt"),
]

# Explicit "do not remember this" blocks — removed entirely (content + tags).
_PRIVATE_BLOCK = re.compile(r"<private>.*?</private>", re.DOTALL | re.IGNORECASE)


def redact(text: str) -> str:
    """Return ``text`` with secrets masked and <private> blocks removed.

    Idempotent: the mask tokens contain no secret-shaped substrings, so a
    second pass is a no-op."""
    if not text:
        return text
    out = _PRIVATE_BLOCK.sub("", text)
    for pat, label in _PATTERNS:
        out = pat.sub(_MASK.format(label), out)
    return out


def has_secrets(text: str) -> bool:
    """True if ``text`` still contains a recognizable secret or private block."""
    if not text:
        return False
    if _PRIVATE_BLOCK.search(text):
        return True
    return any(pat.search(text) for pat, _ in _PATTERNS)
