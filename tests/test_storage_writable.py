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
