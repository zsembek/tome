#!/usr/bin/env python3
"""Tome agent-memory hook for Claude Code (or any agent runtime).

Give your agent automatic long-term memory in Tome with zero code changes:
  • on every tool use  → POST /v1/memory/observe  (a cheap working-tier note)
  • at the end of a turn → POST /v1/memory/consolidate (distil into durable memory)

The script reads the hook event JSON on stdin (Claude Code's hook contract) and
talks to the Tome gateway over HTTP. It has no third-party dependencies.

Configure (e.g. in ~/.claude/settings.json):

  {
    "hooks": {
      "PostToolUse": [{ "hooks": [
        { "type": "command", "command": "python /path/to/claude_code_memory.py" } ]}],
      "Stop":        [{ "hooks": [
        { "type": "command", "command": "python /path/to/claude_code_memory.py" } ]}]
    }
  }

Environment:
  TOME_URL       gateway base URL          (default http://localhost:8080)
  TOME_TOKEN     bearer token / api key    (omit only in TOME_OPEN mode)
  TOME_AGENT_ID  memory namespace          (default "claude-code")
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

TIMEOUT = 5


def _post(path: str, body: dict) -> None:
    base = os.environ.get("TOME_URL", "http://localhost:8080").rstrip("/")
    headers = {"Content-Type": "application/json",
               "X-Agent-Id": os.environ.get("TOME_AGENT_ID", "claude-code")}
    token = os.environ.get("TOME_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=json.dumps(body).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        urllib.request.urlopen(req, timeout=TIMEOUT).read()
    except Exception as exc:  # never block the agent on a memory hiccup
        print(f"tome memory hook: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    raw = sys.stdin.read() if not sys.stdin.isatty() else "{}"
    try:
        event = json.loads(raw or "{}")
    except Exception:
        event = {}
    name = event.get("hook_event_name") or os.environ.get("CLAUDE_HOOK_EVENT", "")
    session = str(event.get("session_id", "") or "")

    if name == "Stop":
        _post("/v1/memory/consolidate", {"session_id": session})
        return 0

    tool = event.get("tool_name") or name or "event"
    payload = event.get("prompt") or event.get("tool_input") or ""
    note = payload if isinstance(payload, str) else json.dumps(payload)
    _post("/v1/memory/observe", {"content": f"{tool}: {note[:800]}", "session_id": session})
    return 0


if __name__ == "__main__":
    sys.exit(main())
