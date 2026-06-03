"""WI-2.2: webhook HMAC signing + SSRF protection, and worker delivery behavior."""
import pytest

from tome.webhooks import is_safe_webhook_url, sign_webhook

pytestmark = pytest.mark.unit


def test_sign_webhook_deterministic():
    s1 = sign_webhook(b'{"a":1}', "secret")
    s2 = sign_webhook(b'{"a":1}', "secret")
    assert s1 == s2 and s1.startswith("sha256=")
    assert sign_webhook(b'{"a":1}', "other") != s1
    assert sign_webhook(b"x", "") is None          # no secret -> unsigned


def test_ssrf_blocks_private_and_metadata():
    for bad in ("http://127.0.0.1/h", "http://10.0.0.5/h", "http://192.168.1.1/h",
                "http://169.254.169.254/latest/meta-data", "http://[::1]/h",
                "file:///etc/passwd", "ftp://host/x", "http://0.0.0.0/h"):
        assert not is_safe_webhook_url(bad), f"should block {bad}"


def test_ssrf_allows_public_and_allowlist():
    assert is_safe_webhook_url("http://8.8.8.8/hook")          # public numeric IP
    assert is_safe_webhook_url("https://example.com/h", allow_hosts={"example.com"})


def test_process_outbox_signs_and_blocks_ssrf(monkeypatch, tmp_store):
    import tome.worker as w

    posted = []

    class FakeResp:
        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, content=None, headers=None, **k):
            posted.append({"url": url, "content": content, "headers": headers})
            return FakeResp()

    monkeypatch.setattr(w.httpx, "Client", FakeClient)

    marks = {}

    class FakeDB:
        def next_outbox(self, limit=50):
            return [
                {"id": 1, "aggregate": "webhook", "op": "deliver", "attempts": 0,
                 "payload": {"url": "http://8.8.8.8/hook", "event": "document.ready",
                             "body": {"x": 1}, "secret": "s3cr3t"}},
                {"id": 2, "aggregate": "webhook", "op": "deliver", "attempts": 0,
                 "payload": {"url": "http://127.0.0.1/hook", "event": "e", "body": {}, "secret": "s"}},
            ]

        def mark_outbox(self, oid, status):
            marks[oid] = status

    n = w.process_outbox(FakeDB())
    assert len(posted) == 1 and posted[0]["url"] == "http://8.8.8.8/hook"
    assert posted[0]["headers"].get("X-Tome-Signature", "").startswith("sha256=")
    assert marks.get(1) == "done"
    assert marks.get(2) == "failed"     # SSRF target blocked, never delivered
    assert n == 1
