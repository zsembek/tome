"""Ingestion must not crash on a STALE folder_id.

The web UI sends the currently-selected folder id with an upload. If that folder was
deleted in the meantime (or the client holds stale state), the id no longer exists in
`folders`, and inserting `documents.folder_id=<stale>` violates the FK constraint —
failing the whole job and retrying forever. `_resolve_folder_id` must validate the id
and gracefully fall back (to folder_path, else root/None) instead."""
import pytest

from tome.pipeline.run import _resolve_folder_id

pytestmark = pytest.mark.unit


class _FakeDB:
    def __init__(self, existing_ids, ensure_result=99):
        self.existing = set(existing_ids)
        self.ensure_calls = []
        self._ensure_result = ensure_result

    def folder_exists(self, ws, fid):
        return fid in self.existing

    def ensure_folder_path(self, ws, path):
        self.ensure_calls.append(path)
        return self._ensure_result


def test_valid_folder_id_is_used_as_is():
    db = _FakeDB({5})
    assert _resolve_folder_id(db, 1, 5, None, False, None) == 5
    assert db.ensure_calls == []


def test_stale_folder_id_falls_back_to_root_when_no_path():
    db = _FakeDB({3})           # folder 1 does NOT exist
    assert _resolve_folder_id(db, 1, 1, None, False, None) is None


def test_stale_folder_id_falls_back_to_folder_path():
    db = _FakeDB({3})
    assert _resolve_folder_id(db, 1, 1, "manuals/krones", False, None) == 99
    assert db.ensure_calls == ["manuals/krones"]


def test_no_folder_id_uses_folder_path():
    db = _FakeDB(set())
    assert _resolve_folder_id(db, 1, None, "a/b", False, None) == 99
    assert db.ensure_calls == ["a/b"]


def test_auto_file_uses_suggested_path_when_nothing_else():
    db = _FakeDB(set())
    assert _resolve_folder_id(db, 1, None, None, True, "vendor/x") == 99
    assert db.ensure_calls == ["vendor/x"]


def test_nothing_specified_is_root():
    db = _FakeDB(set())
    assert _resolve_folder_id(db, 1, None, None, False, None) is None
    assert db.ensure_calls == []
