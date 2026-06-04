"""LocalStore must surface an unwritable object-store directory loudly at startup.
A non-writable /app/_store (e.g. a stale root-owned Docker volume under a non-root
container) silently dropped every original/figure, which only surfaced much later as
"no stored original to reprocess from". Now it sets .writable and logs an ERROR."""
import logging

import pytest

from tome.config import Config
from tome.storage import LocalStore

pytestmark = pytest.mark.unit


def test_writable_dir_is_marked_writable(tmp_path):
    cfg = Config()
    cfg.storage_dir = str(tmp_path)
    s = LocalStore(cfg)
    assert s.writable is True
    assert s.put("sources/x/y.bin", b"data") == "sources/x/y.bin"
    assert s.get("sources/x/y.bin") == b"data"


def test_unwritable_dir_is_flagged_and_logs_error(tmp_path, monkeypatch, caplog):
    cfg = Config()
    cfg.storage_dir = str(tmp_path)

    # simulate a non-writable store directory (root-owned volume under non-root user)
    import tome.storage as storage

    def _boom(*a, **k):
        raise PermissionError("Errno 13: Permission denied")
    monkeypatch.setattr(storage.Path, "write_bytes", _boom)

    with caplog.at_level(logging.ERROR):
        s = LocalStore(cfg)
    assert s.writable is False
    assert any("not writable" in r.message.lower() or "permission" in r.message.lower()
               for r in caplog.records)


# ── STORAGE_DIR inline-comment leak (docker-compose env_file) ────────────────
# `.env` lines like `STORAGE_DIR=    # note` can be passed through verbatim by
# docker-compose's env_file parser, so STORAGE_DIR arrives as "# note ...". That
# made the store land in a junk, non-shared, non-persistent path inside the
# container. The store must treat a leaked inline comment as "unset".
def test_strip_inline_comment_helper():
    from tome.storage import _strip_inline_comment
    assert _strip_inline_comment("# empty -> <package>/_store ; or a path") == ""
    assert _strip_inline_comment("/var/lib/tome   # production path") == "/var/lib/tome"
    assert _strip_inline_comment("/var/lib/tome") == "/var/lib/tome"
    assert _strip_inline_comment("") == ""
    # a '#' embedded inside a token (no leading whitespace) is part of the path
    assert _strip_inline_comment("/data#1") == "/data#1"


def test_leaked_comment_storage_dir_falls_back_to_package_store(monkeypatch, tmp_path):
    # STORAGE_DIR carrying a leaked comment must NOT become the store root
    monkeypatch.setenv("STORAGE_DIR", "# empty -> <package>/_store ; or an absolute path")
    from tome.storage import LocalStore
    s = LocalStore(Config())
    assert s.root.name == "_store"          # fell back to <package>/_store
    assert "#" not in str(s.root)


def test_leaked_comment_with_real_path_uses_the_path(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_DIR", f"{tmp_path}   # the real store")
    from tome.storage import LocalStore
    s = LocalStore(Config())
    assert s.root.resolve() == tmp_path.resolve()


# ── S3 backend without boto3 must fail with a clear, actionable error ────────
def test_s3store_without_boto3_raises_actionable_error(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def _no_boto3(name, *a, **k):
        if name == "boto3" or name.startswith("boto3."):
            raise ModuleNotFoundError("No module named 'boto3'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_boto3)
    from tome.storage import S3Store
    with pytest.raises(RuntimeError) as ei:
        S3Store(Config())
    msg = str(ei.value).lower()
    assert "boto3" in msg and ("s3_use" in msg or "extra" in msg or "install" in msg)
