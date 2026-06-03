"""Contract: the public docs carry the agreed positioning (structure-first, non-RAG,
Markdown-canonical) and the 'Tome vs. assembling a stack' framing."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8").lower()


def test_readme_positioning():
    r = _read("README.md")
    for phrase in ("structure-first", "markdown", "self-hosted", "mcp"):
        assert phrase in r, f"README is missing positioning phrase: {phrase}"


def test_product_has_stack_comparison_and_positioning():
    p = _read("PRODUCT.md")
    assert "structure-first" in p or "rag-optional" in p
    # 'one product vs. assembling Docling + Letta + a vector DB'
    assert "docling" in p and "letta" in p, "PRODUCT.md should compare Tome to a hand-assembled stack"
