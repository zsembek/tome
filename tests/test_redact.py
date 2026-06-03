"""WI-3.4: secret redaction for agent memory (pure, no IO).

Memory must never persist live credentials. `redact()` masks common secret
shapes and strips explicit <private>…</private> blocks before anything is stored.
"""
import pytest

from tome.redact import has_secrets, redact

pytestmark = pytest.mark.unit


def test_redacts_openai_key():
    out = redact("token is sk-abcdEFGH1234567890ijklMNOP here")
    assert "sk-abcdEFGH1234567890ijklMNOP" not in out
    assert "[redacted" in out.lower()


def test_redacts_aws_access_key():
    out = redact("AKIAIOSFODNN7EXAMPLE in config")
    assert "AKIAIOSFODNN7EXAMPLE" not in out


def test_redacts_bearer_and_github_and_slack():
    out = redact("Authorization: Bearer abcDEF123456ghiJKL789mno")
    assert "abcDEF123456ghiJKL789mno" not in out
    out2 = redact("deploy with ghp_0123456789abcdefABCDEF0123456789abcd")
    assert "ghp_0123456789abcdefABCDEF0123456789abcd" not in out2
    out3 = redact("slack xoxb-1234567890-ABCDEFghijkl")
    assert "xoxb-1234567890-ABCDEFghijkl" not in out3


def test_strips_private_blocks_entirely():
    out = redact("keep this <private>my secret note 42</private> and this")
    assert "my secret note 42" not in out
    assert "keep this" in out and "and this" in out


def test_strips_private_key_pem():
    pem = ("-----BEGIN RSA PRIVATE KEY-----\nMIIBOwIBAAJBAKj34\n"
           "-----END RSA PRIVATE KEY-----")
    out = redact(f"here {pem} done")
    assert "MIIBOwIBAAJBAKj34" not in out
    assert "here" in out and "done" in out


def test_preserves_ordinary_markdown():
    md = "# Title\n\nThe pump runs at 0.7 MPa, 11 kW. See [doc](/x).\n"
    assert redact(md) == md  # nothing to redact -> unchanged


def test_redaction_is_idempotent():
    s = "key sk-abcdEFGH1234567890ijklMNOP and AKIAIOSFODNN7EXAMPLE"
    once = redact(s)
    assert redact(once) == once


def test_has_secrets_detects_and_clears():
    assert has_secrets("sk-abcdEFGH1234567890ijklMNOP") is True
    assert has_secrets("just a normal sentence") is False
    assert has_secrets(redact("sk-abcdEFGH1234567890ijklMNOP")) is False
