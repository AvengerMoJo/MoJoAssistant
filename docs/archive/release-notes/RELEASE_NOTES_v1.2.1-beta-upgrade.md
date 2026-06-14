# Upgrade Notes: v1.1.9-beta → v1.2.1-beta

This document covers everything that changed between v1.1.9-beta and v1.2.1-beta.
It spans what were internally two releases (v1.2.0 and v1.2.1) but ships together
as a single upgrade.

---

## Breaking Changes

### MCP Tool Surface Replaced

The visible MCP tool list has been consolidated from ~49 tools to 12.
**Old tools still exist but return `{"status": "placeholder"}` — they no longer execute.**

Update your client system prompt. The new recommended prompt is in:
`docs/claude-guide/CLIENT_SYSTEM_PROMPT.md`

| Old tool | Replacement |
|----------|-------------|
| `get_memory_context` | `get_context()` |
| `get_current_day` / `get_current_time` | `get_context()` (includes timestamp) |
| `get_recent_events` | `get_context(type="events")` |
| `get_attention_summary` | `get_context(type="attention")` |
| `task_session_read` | `get_context(type="task_session", task_id="...")` |
| `scheduler_resume_task` | `reply_to_task(task_id="...", reply="...")` |
| `end_conversation`, `list_recent_conversations`, `add_documents`, etc. | `memory(action="...")` |
| `knowledge_add_repo`, `knowledge_get_file`, `knowledge_list_repos` | `knowledge(action="...")` |
| `scheduler_add_task`, `scheduler_list_tasks`, etc. | `scheduler(action="...")` |
| `dreaming_process`, `dreaming_list_archives`, etc. | `dream(action="...")` |
| `agent_list_types`, `agent_start`, `agent_stop`, etc. | `agent(action="...")` |
| `google_service` | `external_agent(action="google", ...)` |
| `config_doctor`, `resource_pool_*`, `role_*`, `llm_list_available_models` | `config(action="...")` |

### Config Files Added

Two new config files are auto-created if missing. You can customise them:

- `config/scheduler_config.json` — default recurring tasks (nightly dreaming, weekly Ahman)
- `config/notifications_config.json` — push notification adapters (ntfy, etc.)

Runtime overrides (never committed): `~/.memory/config/scheduler_config.json`

---

## What's New

### 1. Attention Layer — LLM Wakes Up Aware

**Problem:** The MCP client LLM had no proactive way to discover tasks in
`waiting_for_input` state. Ahman's questions went unnoticed until you asked manually.

**AttentionClassifier** (`app/mcp/adapters/attention_classifier.py`):
Deterministic System-1 classifier. Runs inside `EventLog.append()` at write time.
Every event gets a `hitl_level` (0–5) — no LLM, no I/O, first-match rules:

| Level | Rule |
|-------|------|
| 5 | `severity == "critical"` |
| 4 | `event_type == "task_waiting_for_input"` |
| 3 | `severity == "error"` or `event_type == "task_failed"` |
| 2 | `event_type == "task_completed"` + `notify_user == true` |
| 1 | any `notify_user == true` |
| 0 | everything else |

**Wake-up hook in `get_context()`:** If there are blocking or alert items,
they are injected into the orientation response automatically. Silent when quiet.

```json
{
  "timestamp": "2026-03-19T15:00:00",
  "attention": {
    "blocking": [
      {
        "level": 4, "from": "ahman",
        "blurb": "Waiting: which subnet should I scan?",
        "reply_with": "reply_to_task",
        "task_id": "ahman_scan_001"
      }
    ]
  },
  "task_sessions": [
    { "task_id": "ahman_scan_001", "status": "waiting_for_input", ... }
  ]
}
```

---

### 2. MCP Tool Consolidation (49 → 12)

**5 top-level tools** (frequent — always visible):

| Tool | Purpose |
|------|---------|
| `get_context(type?, …)` | Orientation + attention + events + task output |
| `search_memory(query, …)` | Semantic search across all memory tiers |
| `add_conversation(user, assistant)` | Save conversation turn |
| `reply_to_task(task_id, reply)` | HITL inbox reply |
| `web_search(query)` | Current web information |

**7 action hubs** (management — discovered on demand):

| Hub | Sub-commands |
|-----|-------------|
| `memory` | end_conversation, list_conversations, add_documents, stats, … |
| `knowledge` | add_repo, list_repos, get_file |
| `config` | get/set/modules + resource_status/approve/revoke + doctor + role_* |
| `scheduler` | add, list, get, remove, purge, status, daemon_* |
| `dream` | process, list, get, upgrade |
| `agent` | list_types, start, stop, status, list, restart, destroy, action |
| `external_agent` | google (+ future: github, slack, notion) |

Call any hub with no action to get its help menu. Unknown action → help menu + error.
LLM never needs to guess — a wrong call self-corrects.

---

### 3. Human-in-the-Loop (HITL) Inbox

**New in v1.2.0.** Agents can pause mid-task and ask the user a question.

```
Agent calls ask_user("which subnet should I scan?")
  → task status: waiting_for_input
  → get_context() surfaces it in attention.blocking
  → user sees question in Claude Desktop
  → reply_to_task(task_id="...", reply="scan 10.0.0.0/24")
  → scheduler wakes immediately (zero-latency via asyncio.Event)
  → agent resumes with reply injected
```

---

### 4. Role Policy Monitor

**New in v1.2.0.** Runtime enforcement of per-role tool permissions.

- `denied_tools` — tools the role can never call
- `allowed_tools` — whitelist (deny all others)
- `require_confirmation_for` — pause before executing specific tools
- Violations blocked at execution time, not just config time

Roles defined in `config/role_config.json`. Create via `config(action="role_design_start")`.

---

### 5. Configuration Doctor

**New in v1.2.0.** Pre-flight validation of your entire config before runtime failures.

```
config(action="doctor")
```

Checks: LLM providers reachable, API keys present, roles valid, scheduler config
consistent, embedding models available. Returns a structured report with warnings
and blocking errors.

---

### 6. Extensible Tool Executor

**New in v1.2.0.** Agents can now call three tool types:

| Type | What it runs |
|------|-------------|
| `shell` | Sandboxed shell command |
| `python` | Sandboxed Python snippet |
| `mcp_proxy` | Any MoJoAssistant MCP tool |

Tools defined in `config/dynamic_tools.json`. Safety policy in `config/safety_policy.json`.

---

### 7. Agentic Smoke Test

**New in v1.2.0.** Validates tool-calling fidelity of the configured LLM before use.

```
config(action="resource_smoke_test", resource_id="lmstudio")
```

Sends a structured JSON task to the LLM and verifies it can follow tool-use
instructions correctly. Prevents silent failures where a model accepts requests
but ignores tool schemas.

---

### 8. Push Notifications (ntfy)

**New in v1.2.0.** Independent push adapter system. Events flow through SSE → EventLog
→ push adapters. Each adapter is an independent channel — disabling one has zero
effect on others.

Configure in `config/notifications_config.json`:

```json
{
  "adapters": [
    {
      "id": "ntfy_home",
      "type": "ntfy",
      "enabled": true,
      "topic": "your-topic",
      "server": "https://ntfy.sh",
      "min_level": 2
    }
  ]
}
```

---

### 9. Scheduler Improvements

- **Zero-latency wake signal** — `asyncio.Event` replaces 60-second sleep poll.
  Tasks resume within milliseconds of `reply_to_task()` being called.
- **Config-driven default tasks** — `config/scheduler_config.json` defines recurring
  tasks. No code change needed to add/modify/disable defaults.
- **Task sessions directory** — `get_context()` orientation response includes a
  lightweight list of running and waiting tasks so LLMs discover task_ids immediately.

---

### 10. Standard SSE Event Envelope

All events now carry a consistent structure:

```json
{
  "event_type": "task_completed",
  "timestamp": "ISO-8601",
  "severity": "info",
  "title": "Short summary",
  "notify_user": false,
  "hitl_level": 0,
  "data": { "...type-specific fields..." }
}
```

---

### 11. Docker + CI (v1.1.9)

- GitHub Actions: smoke test on every push, Docker build + ghcr.io publish
- Production and dev/test Docker images (CPU + AMD ROCm variants)
- Portainer-compatible compose files with named volumes
- `MEMORY_PATH` env var honoured consistently across all components

---

## MCP Surface Smoke Test

New test suite covering all 12 tools — happy paths + expected errors:

```bash
source venv/bin/activate
python -m pytest tests/integration/test_mcp_surface_smoke.py -v
# 93 passed
```

Run this before every release.

---

## Upgrade Steps

1. Pull latest `main`
2. `pip install -r requirements-runtime.txt` (no new deps for this release)
3. Copy `config/scheduler_config.json.example` → `config/scheduler_config.json` if not present
4. Copy `config/notifications_config.json.example` → `config/notifications_config.json` if not present
5. Update your MCP client system prompt — see `docs/claude-guide/CLIENT_SYSTEM_PROMPT.md`
6. Restart MCP server
7. Verify: `get_context()` returns orientation with timestamp

---

## Files Added / Changed

| File | Change |
|------|--------|
| `app/mcp/adapters/attention_classifier.py` | NEW |
| `app/mcp/adapters/event_log.py` | AttentionClassifier wired into append() |
| `app/mcp/adapters/sse.py` | Standard event envelope |
| `app/mcp/adapters/push/` | NEW — push adapter system (ntfy + manager) |
| `app/mcp/core/tools.py` | 12-tool surface, all hub dispatchers |
| `app/scheduler/core.py` | Wake signal, config-driven seeding |
| `app/scheduler/agentic_executor.py` | HITL ask_user, tool executor |
| `app/scheduler/policy_monitor.py` | NEW — role policy enforcement |
| `app/scheduler/agentic_smoke_test.py` | NEW |
| `app/config/doctor.py` | NEW — config validation |
| `app/roles/role_manager.py` | Role schema + Nine Chapter system |
| `config/scheduler_config.json.example` | NEW |
| `config/notifications_config.json.example` | NEW |
| `config/safety_policy.json` | NEW |
| `tests/integration/test_mcp_surface_smoke.py` | NEW — 93 cases |
| `.github/workflows/smoke-test.yml` | CI: smoke test + Docker build |
| `docs/architecture/MCP_DESIGN.md` | NEW — authoritative design reference |
| `docs/claude-guide/CLIENT_SYSTEM_PROMPT.md` | NEW — recommended client prompt |
| `docs/releases/ROADMAP_future.md` | NEW — future release directions |
