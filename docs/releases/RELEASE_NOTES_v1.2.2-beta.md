# Release Notes — v1.2.2-beta

## Theme: Generic Coding Agent + Per-Source Attention

Two major features land in this release: a production-ready coding agent integration
that works with any backend (OpenCode, Claude Code, and future agents), and per-source
attention routing so different task types surface at the right noise level.

A key architectural correction was also made mid-release: session and permission state
moved out of MoJo's scheduler and into the coding-agent layer where they belong.

---

## 1. Generic Coding Agent Integration

### CodingAgentExecutor
A new executor type (`executor: "coding_agent"` in role JSON) that drives an external
coding agent via a local LLM acting as the role's persona. The LLM orchestrates the
agent — breaking goals into steps, sending instructions, reading results, and iterating
— while MoJo handles HITL routing, resource selection, and session lifecycle.

### Pluggable backend: OpenCode + Claude Code
`coding-agent-mcp-tool` submodule now ships two backends behind a common `AgentBackend` ABC:

- **`OpenCodeBackend`** — HTTP REST, full permission bridge, session management
- **`ClaudeCodeBackend`** — stdio subprocess, `--output-format json`, `--resume` for session continuity, yolo mode (`--dangerously-skip-permissions`) with HITL bridge planned for v1.3

New backends register by adding a class to `BACKEND_CLASSES` — no executor changes needed.

Config file renamed: `opencode-mcp-tool-servers.json` → `coding-agent-mcp-tool-servers.json` (v1.0 backward-compat preserved).

### HITL permission bridge
When OpenCode requests a file write, shell command, or other permission, the executor:
1. Detects it via `list_permissions()` polling (background task + 3s interval)
2. Pauses the LLM loop
3. Surfaces the request to the user via `waiting_for_input`
4. Resumes with the user's allow/deny reply on the next task execution

### Session ownership moved to coding-agent layer (§19.6)
Previously `agent_session_id` and `agent_pending_permission_id` were stored in MoJo's
`TaskConfig` — a design boundary violation. MoJo oversees many roles simultaneously;
it cannot carry per-agent ephemeral state.

`BackendRegistry` now owns a `SessionStore` (file-backed, `$MEMORY_PATH/coding-agent-sessions.json`):
- Key: `role_id::server_id` — one persistent session per role per project
- `get_or_create_session(role_id, server_id)` — resumes automatically, no session ID in task config
- `set/pop_pending_permission(role_id, server_id)` — permission state fully agent-internal

**Scheduling a follow-up task for Popo now just needs `goal` + `role_id`.** The session
resumes automatically from the store.

### Generic naming
All `opencode_*` names renamed to agent-agnostic equivalents:
- Task config: `opencode_session_id` → (removed from config entirely)
- Executor tools: `opencode_send_message` → `agent_send_message`, `opencode_get_messages` → `agent_get_messages`
- MCP tool actions: `opencode_servers/health/session_*` → `backend_servers/health/session_*`
  (old `opencode_*` names still accepted as backward-compat aliases)

### Backend-aware auto-start (§19.1)
`_auto_start_backend` now branches on `backend_type`:
- `opencode` → OpenCodeManager launch flow (unchanged)
- `claude_code` → no-op (binary always present; `health()` validates working dir)
- unknown → warning + None (no silent failure)

---

## 2. Per-Source Attention Routing

`AttentionClassifier` extended with config-driven per-source rules
(`config/notifications_config.json` → `source_rules`):

```json
{
  "source_rules": {
    "dreaming": { "max_level": 1 },
    "agent":    { "min_level": 2 }
  }
}
```

- `max_level` caps noisy sources (dreaming failures stay quiet)
- `min_level` floors important sources (agent events always surface)
- Source matched on `event.task_type`
- `AttentionClassifier.reload_rules()` hot-reloads from disk

---

## 3. Other Improvements

- **`ask_user` universal HITL escape hatch** — injected into every agentic task regardless of `available_tools`. Any agent can surface a blocker without being told to in its prompt.
- **`add_conversation` latency fix** — embedding generation moved to background task; tool returns immediately
- **MEMORY_PATH hardcoded path fixes** — all `~/.memory` references now honour the `MEMORY_PATH` env var
- **Notification config example** — `task_waiting_for_input`, `task_started`, `task_cancelled` added to example config
- **`external_agent` MCP tool** — `server_id`, `session_id`, `content` params added to schema

---

## 4. Architecture Documents

- **§17** — MoJo Agent Protocol (MAP)
- **§18** — Agent integration analysis (ZeroClaw, DeerFlow, Claude Code)
- **§19** — Generic coding agent v1.3 backlog (5 TODOs including §19.6 session ownership)
- **§20** — Resource pool + tool registry catalog architecture (target for v1.2.3)

---

## 5. Tests

36 smoke tests, all passing (`tests/unit/test_v1_2_2_smoke.py`):
- 14 `AttentionClassifier` per-source routing tests
- 3 agent hub normalisation tests
- 5 scheduler hub normalisation tests
- 3 `CodingAgentExecutor` routing tests
- 2 `CodingAgentExecutor` send/permission polling tests
- 6 `SessionStore` unit tests
- 3 `BackendRegistry` session management tests

---

## 6. Breaking Changes

- `coding-agent-mcp-tool-servers.json` is the new config filename (was `opencode-mcp-tool-servers.json`). Old filename still read for backward compat.
- `task.config["agent_session_id"]` is no longer written or read. Sessions are managed by `BackendRegistry.SessionStore`. Any external tooling that set `agent_session_id` in task config should stop — it has no effect.
- `external_agent` MCP tool actions renamed from `opencode_*` to `backend_*`. Old names still work.

---

## What's Next — v1.2.3

Resource pool unification + tool registry catalog:
- Single `resource_pool.json` (two layers: system default + `~/.memory/config/`)
- Roles declare `resource_requirements`, not a hardcoded `preferred_resource_id`
- `tool_catalog.json` with system pre-defined + user custom tools
- `list_tools()` meta-tool — agents discover available tools at runtime
- No more `available_tools` enumeration in every task config
