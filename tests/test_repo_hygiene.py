"""Contract: the public repo stays clean — no secrets, no stray .env, English sources.

Scans git-tracked files only (what would actually be published)."""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Patterns are split so this test file never contains a literal secret itself.
SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),                                   # AWS access key id
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),                 # private key blocks
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),                            # OpenAI-style keys
    re.compile(r"(AZURE_OPENAI_KEY|AZURE_DI_KEY|TOME_SECRET|S3_SECRET_KEY)\s*=\s*\S{16,}"),
    re.compile("Fpr" + "Nq1sAoM7"),                                    # previously-exposed key prefix
]

TEXT_EXT = {".py", ".md", ".txt", ".sql", ".yml", ".yaml", ".toml", ".ts", ".tsx",
            ".js", ".jsx", ".json", ".cfg", ".ini", ".conf", ".sh", ".example", ""}
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
# Cyrillic is allowed only in test fixtures and the example tokens inside LLM prompts.
CYRILLIC_ALLOW = ("tests/", "tome/prompts/")


def _tracked_files() -> list[Path]:
    res = subprocess.run(["git", "ls-files"], cwd=str(ROOT), capture_output=True, text=True)
    if res.returncode != 0:
        pytest.skip("not a git repository")
    return [ROOT / line for line in res.stdout.splitlines() if line.strip()]


def _is_text(p: Path) -> bool:
    return p.suffix.lower() in TEXT_EXT or p.name in ("Dockerfile", ".gitignore", ".env.example")


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def test_no_secrets_in_tracked_files():
    offenders = []
    for p in _tracked_files():
        if not _is_text(p):
            continue
        txt = _read(p)
        for pat in SECRET_PATTERNS:
            if pat.search(txt):
                offenders.append(f"{p.relative_to(ROOT)} :: {pat.pattern}")
    assert not offenders, f"possible secrets in tracked files: {offenders}"


def test_env_not_tracked_but_example_is():
    tracked = {str(p.relative_to(ROOT)).replace("\\", "/") for p in _tracked_files()}
    assert ".env" not in tracked, ".env must never be committed"
    assert ".env.example" in tracked, ".env.example should be committed"


def test_shipped_sources_are_english():
    offenders = []
    for p in _tracked_files():
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if rel.startswith(CYRILLIC_ALLOW) or not _is_text(p):
            continue
        if CYRILLIC.search(_read(p)):
            offenders.append(rel)
    assert not offenders, f"non-English text in shipped sources: {offenders}"
