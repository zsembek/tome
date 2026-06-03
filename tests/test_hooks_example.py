"""WI-3.5: the auto-capture hook example is valid and calls the right endpoints."""
import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

HOOK = Path(__file__).resolve().parent.parent / "examples" / "hooks" / "claude_code_memory.py"


def _load(monkeypatch, stdin_text: str):
    """Load the hook module fresh with a fake stdin and a capturing urlopen."""
    import io
    import sys
    import urllib.request
    spec = importlib.util.spec_from_file_location("tome_hook_example", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    calls = []

    class _Resp:
        def read(self):
            return b""

    def _fake_urlopen(req, timeout=0):
        calls.append((req.full_url, req.data))
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    return mod, calls


def test_hook_file_exists_and_parses():
    assert HOOK.exists()
    src = HOOK.read_text(encoding="utf-8")
    assert "/v1/memory/observe" in src and "/v1/memory/consolidate" in src
    compile(src, str(HOOK), "exec")  # syntactically valid


def test_post_tool_use_observes(monkeypatch):
    mod, calls = _load(monkeypatch, '{"hook_event_name":"PostToolUse",'
                                    '"tool_name":"Read","session_id":"s1"}')
    mod.main()
    assert calls and calls[0][0].endswith("/v1/memory/observe")


def test_stop_consolidates(monkeypatch):
    mod, calls = _load(monkeypatch, '{"hook_event_name":"Stop","session_id":"s1"}')
    mod.main()
    assert calls and calls[0][0].endswith("/v1/memory/consolidate")
