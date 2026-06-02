"""Unit tests for the new code (no DB or external APIs)."""
import sys, io, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── extractor registry: all top-10 are registered and importable ──
def test_extractor_registry_top10():
    from tome.extract.registry import _BUILDERS, AVAILABLE_EXTRACTORS
    import importlib
    expected = {"tika", "docling", "marker", "azure_di", "aws_textract",
                "google_docai", "mistral_ocr", "unstructured", "llamaparse", "vision_llm"}
    assert expected.issubset(set(_BUILDERS))
    assert len(AVAILABLE_EXTRACTORS) == 10
    for name, (mod, cls) in _BUILDERS.items():
        m = importlib.import_module(mod)
        assert hasattr(m, cls), f"{name}: class {cls} is missing"


# ── conflict: heading normalization ──
def test_conflict_norm():
    from tome.conflict import _norm
    assert _norm("  Технические   ПАРАМЕТРЫ ") == "технические параметры"


# ── export: rewriting image links ──
def test_export_img_regex():
    from tome.export import _IMG_RE
    md = "![x](/v1/assets/figures/abc/1.png) and ![y](images/2.png)"
    urls = _IMG_RE.findall(md)
    assert "/v1/assets/figures/abc/1.png" in urls and "images/2.png" in urls


# ── gc: live_keys collects from assets + snapshots (mock DB) ──
def test_gc_live_keys():
    from tome import gc
    class FakeCur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, q, *a): self._cur = "assets" if "FROM assets" in q else "versions"
        def fetchall(self):
            return ([{"object_key": "a"}, {"object_key": "b"}] if self._cur == "assets"
                    else [{"snapshot_object_key": "c"}])
    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return FakeCur()
    class FakePool:
        def connection(self): return FakeConn()
    class FakeDB: pool = FakePool()
    keys = gc.live_keys(FakeDB())
    assert keys == {"a", "b", "c"}


# ── dedup: building the report by groups (mock) ──
def test_dedup_report_shape():
    from tome import dedup
    class FakeCur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, q, *a): pass
        def fetchall(self): return [{"content_hash": "x" * 20, "ids": [1, 2, 3],
                                     "titles": ["a", "b", "c"], "n": 3}]
    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return FakeCur()
    class FakePool:
        def connection(self): return FakeConn()
    class FakeDB: pool = FakePool()
    rep = dedup.find_duplicates(FakeDB(), 1)
    assert rep["total_redundant"] == 2
    assert rep["duplicate_groups"][0]["count"] == 3


# ── ratelimit: the interval is respected ──
def test_ratelimit_throttle():
    import time
    from tome.ratelimit import throttle
    t0 = time.monotonic()
    throttle("k", 0.0); throttle("k", 0.0)   # 0 → no delay
    assert time.monotonic() - t0 < 0.1
    throttle("k2", 0.15); t1 = time.monotonic(); throttle("k2", 0.15)
    assert time.monotonic() - t1 >= 0.1      # the second call waits for the interval


# ── atlas index: indentation by nesting level ──
def test_atlas_index_indent():
    from tome.pipeline.atlas import build_index
    md = build_index([{"name": "A", "path": "a", "description": "", "document_count": 1},
                      {"name": "B", "path": "a.b", "description": "", "document_count": 2}])
    assert "## A" in md
    assert "  - B" in md   # nested folder with indentation


# ── storage: protection against path traversal (CVE class: arbitrary file read) ──
def test_localstore_path_traversal_blocked(tmp_path):
    from tome.storage import LocalStore
    from tome.config import Config
    cfg = Config()
    cfg.__dict__["storage_dir"] = str(tmp_path)
    st = LocalStore(cfg)
    st.put("ok/file.txt", b"data")
    assert st.get("ok/file.txt") == b"data"
    # any attempt to escape the root → None (get) / ValueError (put), with no reads from outside
    for evil in ["../../../../etc/passwd", "..%2f..%2fetc", "/etc/passwd",
                 "ok/../../../../etc/passwd"]:
        assert st.get(evil) is None, f"traversal not blocked: {evil}"
    import pytest
    with pytest.raises(ValueError):
        st.put("../escape.txt", b"x")


# ── identity: password hash (pbkdf2) + roles→scopes ──
def test_password_hash_and_roles():
    from tome.db import hash_password, verify_password_hash, role_scopes
    h, salt = hash_password("Secret123!")
    assert h and salt and h != "Secret123!"
    assert verify_password_hash("Secret123!", h, salt)
    assert not verify_password_hash("wrong", h, salt)
    # the same password with a different salt → different hashes
    h2, salt2 = hash_password("Secret123!")
    assert h2 != h and salt2 != salt
    assert role_scopes("admin") == {"read", "write", "admin"}
    assert role_scopes("editor") == {"read", "write"}
    assert role_scopes("viewer") == {"read"}
    assert role_scopes("nonexistent") == set()


# ── signed asset url: valid / expired / tampered / different key ──
def test_signed_asset_url(monkeypatch):
    monkeypatch.setenv("TOME_SECRET", "unit-test-secret")
    import tome.config as cfg
    cfg._cfg = None
    try:
        from tome import signing
        import re
        now = 1_000_000
        url = signing.signed_url("figures/a/1.png", ttl=600, now=now)
        exp = int(re.search(r"exp=(\d+)", url).group(1))
        sig = re.search(r"sig=([0-9a-f]+)", url).group(1)
        assert signing.verify("figures/a/1.png", exp, sig, now=now + 10)        # ok
        assert not signing.verify("figures/a/1.png", exp, sig, now=now + 700)   # expired
        assert not signing.verify("figures/a/1.png", exp, "dead", now=now + 10) # tampered
        assert not signing.verify("figures/OTHER.png", exp, sig, now=now + 10)  # different key
        assert not signing.verify("figures/a/1.png", None, None, now=now)       # no signature
    finally:
        cfg._cfg = None


# ── faithfulness: catches loss at the document level ──
def test_faithfulness_doc_level():
    from tome.pipeline.verify import verify
    raw = "Раздел 1. 0.7 МПа. Раздел 2. 11 kW. Раздел 3. 36000 л."
    full = "# Раздел 1\n0.7 МПа.\n# Раздел 2\n11 kW."   # section 3 is lost
    r = verify(raw, full, min_score=0.85)
    assert not r.passed and "36000" in r.missing_numbers
