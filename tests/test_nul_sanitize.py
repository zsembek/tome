"""Broken PDF text layers can contain NUL (0x00) and other C0 control bytes, which
PostgreSQL text columns reject ("cannot contain NUL"). The pipeline must strip them so
ingestion never fails on such a document."""
import pytest

from tome.extract.base import strip_control_chars
from tome.pipeline.clean import clean

pytestmark = pytest.mark.unit


def test_strip_control_chars_removes_nul_and_c0_keeps_tab_newline():
    s = "a\x00b\x01c\x08d\x0be\x0cf\x1fg\x7fh\tI\nJ\rK"
    out = strip_control_chars(s)
    assert "\x00" not in out
    assert all(ord(ch) >= 0x20 or ch in "\t\n" for ch in out)
    assert "\t" in out and "\n" in out
    assert "abcdefgh" in out.replace("\t", "").replace("\n", "").replace("I", "").replace("J", "").replace("K", "")[:8]


def test_strip_handles_empty_and_none():
    assert strip_control_chars("") == ""
    assert strip_control_chars(None) is None


def test_clean_removes_nul_bytes():
    cleaned = clean("Heading\x00 with NUL\x00 and \x01 control\n\nbody\x00 text")
    assert "\x00" not in cleaned
    assert "\x01" not in cleaned
    assert "body" in cleaned and "Heading" in cleaned
