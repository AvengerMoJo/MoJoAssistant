# Claude Code Manager

Manages Claude Code CLI subprocess lifecycle within MoJoAssistant.

## What It Does

- Starts/stops/restarts Claude Code CLI as a persistent subprocess
- Tracks PID and process health
- Persists session state across MoJoAssistant restarts

## What It Does NOT Do

- Expose coding tools (read_file, edit, grep) — those are in the external MCP tool project
- Clone repositories or manage SSH keys — Claude Code handles its own workspace
- Manage multiple models/providers — delegates to Claude Code CLI

## How to Enable

```bash
# In .env
ENABLE_CLAUDE_CODE=true

# Optional: specify claude binary path (auto-detected from PATH by default)
CLAUDE_BIN=/path/to/claude
```

Requires the Claude Code CLI to be installed and authenticated.

## MCP Tools (unified agent tools)

All Claude Code lifecycle operations use the unified `agent_*` tools with `agent_type: "claude_code"`.

| Tool | Parameters | Description |
|------|------------|-------------|
| `agent_start` | `agent_type: "claude_code"`, `identifier: "<session_id>"`, `params: {working_dir: "...", model: "..."}` | Start a session |
| `agent_stop` | `agent_type: "claude_code"`, `identifier: "<session_id>"` | Stop a running session |
| `agent_status` | `agent_type: "claude_code"`, `identifier: "<session_id>"` | Check session status (PID, alive, model) |
| `agent_list` | `agent_type: "claude_code"` | List all sessions |
| `agent_restart` | `agent_type: "claude_code"`, `identifier: "<session_id>"` | Restart a session with same config |

## Architecture

```
MoJoAssistant (this code)
  └── Claude Code Manager
        └── Process lifecycle only (start/stop/restart/health)
              └── claude subprocess (PID tracked)

External MCP Tool Project (separate repo)
  └── Coding tools (read_file, edit, grep, etc.)
        └── Routes to Claude Code subprocess
```

## State

Session state is persisted at `~/.memory/claude-code-state.json`.

## Extending BaseAgentManager

Claude Code Manager extends `BaseAgentManager` (defined in `app/mcp/agents/base.py`), the same ABC that OpenCode Manager uses. This ensures all agent managers share a consistent lifecycle interface.
