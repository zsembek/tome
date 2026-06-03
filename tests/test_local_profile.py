"""WI-3.0c: the local / air-gapped profile bakes fastembed into the image so
offline embeddings work without a manual rebuild."""
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parent.parent


def test_dockerfile_supports_extras_build_arg():
    df = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG TOME_EXTRAS" in df, "Dockerfile must expose a TOME_EXTRAS build arg"
    assert "TOME_EXTRAS" in df and ".[$TOME_EXTRAS]" in df, "extras must be conditionally installed"


def test_local_overlay_wires_fastembed():
    overlay = (ROOT / "docker-compose.local.yml").read_text(encoding="utf-8")
    assert "TOME_EXTRAS" in overlay and "fastembed" in overlay, \
        "local overlay must build the image with the fastembed extra"
