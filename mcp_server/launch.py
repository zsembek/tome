"""Fail-closed launcher for the HTTP MCP (via mcpo).

Network exposure (0.0.0.0) is allowed ONLY when an MCPO_API_KEY is set or
TOME_OPEN=true. Otherwise the server binds to localhost so the write/edit tools
are not reachable from the network without authentication."""
from __future__ import annotations

import logging
import os

log = logging.getLogger("tome.mcp.launch")


def resolve_mcp_bind(env: dict) -> tuple[str, bool]:
    """Return (host, exposed). exposed=True means bound to 0.0.0.0 (network-reachable)."""
    has_key = bool((env.get("MCPO_API_KEY") or "").strip())
    open_mode = (env.get("TOME_OPEN", "false") or "").lower() in ("1", "true", "yes", "on")
    if has_key or open_mode:
        return ("0.0.0.0", True)
    return ("127.0.0.1", False)


def build_argv(env: dict, port: str = "8765") -> tuple[list[str], bool]:
    host, exposed = resolve_mcp_bind(env)
    argv = ["mcpo", "--host", host, "--port", str(port)]
    key = (env.get("MCPO_API_KEY") or "").strip()
    if key:
        argv += ["--api-key", key]
    argv += ["--", "python", "-m", "mcp_server.server"]
    return argv, exposed


def main():
    logging.basicConfig(level=logging.INFO)
    port = os.environ.get("MCP_PORT", "8765")
    argv, exposed = build_argv(os.environ, port)
    if not exposed:
        log.warning("MCP is bound to 127.0.0.1 (fail-closed). Set MCPO_API_KEY to expose "
                    "it on the network, or TOME_OPEN=true for trusted/localhost use.")
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    main()
