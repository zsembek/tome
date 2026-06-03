"""WI-2.1: MCP fail-closed bind policy."""
import pytest

from mcp_server.launch import build_argv, resolve_mcp_bind

pytestmark = pytest.mark.unit


def test_localhost_without_key_or_open():
    assert resolve_mcp_bind({}) == ("127.0.0.1", False)
    assert resolve_mcp_bind({"MCPO_API_KEY": "   "}) == ("127.0.0.1", False)
    assert resolve_mcp_bind({"TOME_OPEN": "false"}) == ("127.0.0.1", False)


def test_exposed_with_key():
    assert resolve_mcp_bind({"MCPO_API_KEY": "secret"}) == ("0.0.0.0", True)


def test_exposed_with_open_mode():
    assert resolve_mcp_bind({"TOME_OPEN": "true"}) == ("0.0.0.0", True)


def test_build_argv_with_key():
    argv, exposed = build_argv({"MCPO_API_KEY": "k"}, port="8765")
    assert argv[:5] == ["mcpo", "--host", "0.0.0.0", "--port", "8765"]
    assert "--api-key" in argv and "k" in argv
    assert argv[-4:] == ["--", "python", "-m", "mcp_server.server"]
    assert exposed is True


def test_build_argv_localhost_no_key():
    argv, exposed = build_argv({})
    assert "127.0.0.1" in argv and "0.0.0.0" not in argv
    assert "--api-key" not in argv and exposed is False
