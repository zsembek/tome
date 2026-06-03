"""WI-2.4: config security self-audit + TOME_STRICT fail-fast."""
import logging

import pytest

from tome.config import Config
from tome.security import audit_config, enforce

pytestmark = pytest.mark.unit


def test_audit_flags_empty_secret_and_default_pw():
    cfg = Config()
    cfg.tome_open = False
    cfg.secret = ""
    cfg.postgres_dsn = "postgresql://postgres:postgres@host:5432/db"
    issues = audit_config(cfg)
    assert any("SECRET" in i for i in issues)
    assert any("Postgres" in i for i in issues)


def test_audit_clean_when_secret_set_and_strong_pw():
    cfg = Config()
    cfg.tome_open = True
    cfg.secret = "x" * 40
    cfg.postgres_dsn = "postgresql://user:Str0ngPass@host:5432/db"
    cfg.s3_use = False
    assert audit_config(cfg) == []


def test_strict_mode_blocks_startup():
    cfg = Config()
    cfg.tome_open = False
    cfg.secret = ""
    cfg.tome_strict = True
    cfg.postgres_dsn = "postgresql://postgres:postgres@host/db"
    with pytest.raises(RuntimeError):
        enforce(cfg, logging.getLogger("test"))


def test_non_strict_only_warns():
    cfg = Config()
    cfg.tome_open = False
    cfg.secret = ""
    cfg.tome_strict = False
    cfg.postgres_dsn = "postgresql://postgres:postgres@host/db"
    enforce(cfg, logging.getLogger("test"))   # must not raise
