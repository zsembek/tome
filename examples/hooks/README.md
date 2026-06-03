# Auto-capture: give your agent memory in Tome

`claude_code_memory.py` is a dependency-free hook that wires an agent's activity
into Tome's [agent memory](../../README.md#-agent-memory-markdown-native):

- **PostToolUse** → `POST /v1/memory/observe` — logs a cheap working-tier note.
- **Stop** → `POST /v1/memory/consolidate` — distils the session's observations
  into one episodic summary and promotes durable facts to semantic memory.

Memories are plain Markdown, scoped per agent (`X-Agent-Id`), and secrets are
redacted before anything is stored.

## Setup (Claude Code)

1. Pick a token (a session token, or an API key with `write` scope):

   ```bash
   export TOME_URL=http://localhost:8080
   export TOME_TOKEN=tome_xxx            # omit only when TOME_OPEN=true
   export TOME_AGENT_ID=claude-code      # your memory namespace
   ```

2. Register the hook in `~/.claude/settings.json`:

   ```json
   {
     "hooks": {
       "PostToolUse": [{ "hooks": [
         { "type": "command", "command": "python /abs/path/to/claude_code_memory.py" } ]}],
       "Stop":        [{ "hooks": [
         { "type": "command", "command": "python /abs/path/to/claude_code_memory.py" } ]}]
     }
   }
   ```

That's it — the agent now remembers across sessions. Recall it any time with the
`recall` MCP tool or `GET /v1/memory/recall?q=…`.

## Other runtimes

Any agent can do the same with two HTTP calls: `observe` during work and
`consolidate` at the end. See [`claude_code_memory.py`](./claude_code_memory.py)
for the minimal contract.
