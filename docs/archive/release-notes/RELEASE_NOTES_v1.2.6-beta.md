# Release Notes — v1.2.6-beta

## Theme: Safety Foundation — Know What Your Agent Is Allowed To Do

Every layer MoJoAssistant builds on requires the agent to be trustworthy. This
release answers the question: *what stops an agent from doing something it
shouldn't?* The answer is an inline policy enforcement pipeline that runs before
every tool call, a data boundary system that keeps sensitive tasks off external
APIs, and a visibility layer so every violation is auditable in real time.

This release also ships the MCP infrastructure work deferred from v1.2.5:
MCP server lifecycle management, two-layer config, eager connection, and
urgency-driven attention routing.

---

## 1. Policy Enforcement Pipeline (`app/scheduler/policy/`)

A pluggable, ordered checker pipeline runs inline before every tool call in
`AgenticExecutor`. The first checker that blocks wins — no tool call is made,
a `policy_violation` event is emitted, and the violation is logged.

### Checkers (in default order)

| Checker | What it blocks |
|---------|---------------|
| `StaticPolicyChecker` | Tools in `denied_tools`; tools not in `allowed_tools` |
| `ContentAwarePolicyChecker` | Tool names matching patterns in `policy_patterns.json` |
| `DataBoundaryChecker` | MCP tools when `allow_external_mcp: false`; resource tiers outside `allowed_tiers` |
| `ContextAwarePolicyChecker` | All tools once `violation_total` exceeds `max_violations_before_halt` |

Configure in a role's `policy` block:

```json
"policy": {
  "checkers": ["static", "content", "data_boundary", "context"],
  "denied_tools": ["bash_exec"],
  "context_rules": { "max_violations_before_halt": 5 }
}
```

### `local_only` shorthand

A one-liner flag that expands to strict data boundary defaults:

```json
"local_only": true
```

Equivalent to:
```json
"data_boundary": {
  "allow_external_mcp": false,
  "allowed_tiers": ["free"]
}
```

Explicit `data_boundary` values always take precedence over `local_only` defaults.

### Policy violation observability

Every blocked tool call emits a `policy_violation` event to the EventLog:
- Routed to ntfy push (phone/desktop notification)
- Visible on the monitoring dashboard
- Includes: `task_id`, `role_id`, `tool_name`, `checker`, `reason`

---

## 2. Data Boundary Enforcement

Role-level `data_boundary` config controls what a task is allowed to touch:

```json
"data_boundary": {
  "allow_external_mcp": false,
  "allowed_tiers": ["free", "free_api"]
}
```

- `allow_external_mcp: false` — blocks all non-local MCP tool calls
- `allowed_tiers` — blocks LLM resource calls to tiers not in the list

`DataBoundaryChecker` enforces these rules inline, before execution, not after.
A task marked `local_only: true` will never make an external API call or use an
external MCP tool — the executor refuses before the call is made.

---

## 3. EventLog Cross-Thread Write Fix

**Root cause:** `asyncio.Lock` binds to the event loop that first acquires it
(Python 3.10+ `_LoopBoundMixin`). The MCP server's main loop bound it; the
scheduler daemon's background thread used a different loop, raising a
`RuntimeError` that was silently caught — meaning policy violation events were
written to memory but never persisted to disk.

**Fix:** Class-level `threading.Lock` (created at module import time, independent
of any event loop) used for all `append`/`purge_before` operations. A
process-level singleton for the default EventLog path ensures all writes go to
the same instance; custom-path instances (used in tests) bypass the singleton
for test isolation.

---

## 4. MCP Server Infrastructure (v1.2.5)

### MCPServerManager (`app/mcp/agents/mcp_server_manager.py`)

MCP servers are now first-class managed components with a lifecycle:

```
scheduler_add_task(type="mcp_server", config={
  "action": "start" | "stop" | "restart" | "status",
  "server_id": "playwright"
})
```

All running MCP servers appear in the agent lifecycle hub alongside scheduled
tasks.

### Two-layer `mcp_servers.json`

```
config/mcp_servers.json          ← system defaults (tracked by git)
~/.memory/config/mcp_servers.json ← personal overlay (not tracked)
```

Personal config merges over system defaults. Add personal MCP servers without
touching the repo.

### Eager connection at startup

MCP servers connect at scheduler startup rather than lazily on first tool call.
Connection errors are logged immediately — no silent failures on first agent run.

Race condition fixes: connect lock prevents concurrent connect attempts; stale
flag resets on reconnect; `wait_for` timeout prevents indefinite hangs.

### tmux-mcp-rs integration

tmux terminal tools (`tmux__list-sessions`, `tmux__new-session`, etc.) registered
at startup via `tmux-mcp-rs`. Agents can create and manage tmux sessions directly.

Default operating model:
- tmux is the shared virtual terminal backend, analogous to Playwright as the shared virtual browser backend
- operators and agents should normally see the same tmux server state
- isolation happens via dedicated tmux sessions/windows/panes, not a hidden private socket by default

---

## 5. Urgency + Importance → Attention Routing

Tasks now carry `urgency` (0–5) and `importance` (0–5) fields. A
`urgency × importance` matrix drives the attention level routed to the HITL
inbox and ntfy push:

```json
"urgency": 4,
"importance": 5
```

High-urgency + high-importance tasks surface at attention level 4–5 (immediate
ntfy notification). Low-urgency background tasks stay at level 1–2 (dashboard
only).

---

## 6. Monitoring Dashboard (`/dashboard`)

A read-only browser dashboard at `http://localhost:{port}/dashboard`:

- Live EventLog feed (SSE, auto-updates)
- Scheduler task list with status
- Agent lifecycle hub (running tasks + MCP servers)
- Policy violation log

No configuration required — available on any running MoJoAssistant instance.
Protected by the same API key as the MCP endpoint.

---

## 7. ResourcePoolLLMInterface Hardening

The dreaming pipeline LLM adapter now uses the `ResourceManager` stack
(previously used the legacy `llm_config.json` path). This eliminates the
split-brain risk where the dreaming LLM could silently use a stale model.

`except Exception` broad catches removed: transport errors (`TimeoutError`,
`ConnectionError`, `OSError`) caught by name; unexpected errors propagate
naturally without swallowing.

---

## 8. Test Coverage

| Suite | Tests | Coverage |
|-------|-------|----------|
| `tests/unit/test_policy_checkers.py` | 32 | All 4 checkers, PolicyMonitor pipeline, `local_only` shorthand |
| `tests/integration/test_scheduler*.py` | Fixed | `@pytest.mark.asyncio` + correct API names |

---

## Upgrade Notes

### Enable policy enforcement on a role

Add a `policy` block to any role JSON:

```json
"policy": {
  "checkers": ["static", "data_boundary"],
  "denied_tools": ["bash_exec"]
}
```

Or use `local_only: true` to lock a role to free-tier local resources only.

### Personal MCP server config

Copy any personal MCP server entries to `~/.memory/config/mcp_servers.json`.
System config (`config/mcp_servers.json`) is now tracked by git — personal
overrides belong in the personal layer.

### Task urgency and importance

Add to any task for attention routing:
```json
"urgency": 3,
"importance": 4
```

Omitting these fields defaults to level 1 routing (dashboard only).

---

## What's Next (v1.2.7)

- Non-atomic stop/reconnect in MCPServerManager — rollback on failed reconnect
- Inbox-subscribing PolicyAgent (separate process) — cross-agent proactive
  blocking with reasoning; target v1.3.x
