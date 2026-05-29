# Release Notes v1.1.8-beta

## Theme: Unified LLM Infrastructure + Role-Driven Agentic System

This release delivers two major feature groups that make the agentic system
production-ready: a consolidated LLM infrastructure that eliminates auth
inconsistencies, and a complete role/personality system for autonomous agents.

---

## What's New

### 1. UnifiedLLMClient — Single LLM Call Path

**The problem:** Five separate code paths for LLM HTTP calls, each with its own
key resolution logic. A key set in one place would silently not apply in another,
causing mysterious 400/401 failures that were hard to trace.

**The fix:** All LLM calls now route through a single `UnifiedLLMClient` class
(`app/llm/unified_client.py`) with one consistent key resolution order:

```
1. key_var / api_key_env environment variable
2. Inline api_key in resource config
3. Merged config lookup (runtime override wins over codebase defaults)
4. Provider env fallback (OPENROUTER_API_KEY, LMSTUDIO_API_KEY, etc.)
```

Files consolidated: `agentic_executor.py`, `api_llm_interface.py`,
`llm_interface.py`, `resource_pool.py`.

---

### 2. Config-Driven Scheduler Tasks + Persistent Event Log

**Config-driven default tasks** (`config/scheduler_config.json`):
Default tasks (e.g. nightly dreaming) are now defined in JSON, not hardcoded
in Python. Add, remove, or reschedule default tasks without a code change.

**Persistent event log** (`~/.memory/events.json`):
Every SSE event is now written to a circular buffer (500 events). Non-WebSocket
clients can poll `get_recent_events` to catch task failures, config changes,
and system notifications.

**Standard SSE envelope** — all events now include:
```json
{ "event_type": "...", "severity": "info|warning|error", "notify_user": false,
  "title": "...", "timestamp": "ISO-8601", "data": {} }
```

New event types: `config_changed`, `resource_event`, `system_notification`,
`scheduler_tick`.

New MCP tool: `get_recent_events(since, types, limit)` — poll for missed events.

---

### 3. LLM Config Fully Generic + Dynamic Model Detection

- `config/llm_config.json` supports nested sub-accounts (one provider key,
  multiple personas), `key_var` env variable resolution, and Google provider.
- Local LMStudio/Ollama servers auto-expand into per-model resource entries
  via `/v1/models` probe at startup (`dynamic_discovery: true`).
- `resolve_llm_resource()` now searches both `api_models` and `local_models`.
- `llm_list_available_models` MCP tool uses the merged layered config.

---

### 4. Nine Chapter Role / Personality System

Agents can now have a full personality, purpose, and behavioural spec via a
structured interview process inspired by character design.

- `role_design_start` / `role_design_answer` — guided Nine Chapter interview
  (Values, Purpose, Emotional Response, Thinking Style, Communication, etc.)
- `role_create` — save a completed role to `~/.memory/roles/{id}.json`
- `role_list` / `role_get` — browse and load roles
- Roles are bound to agentic tasks via `config.role_id` — the role's system
  prompt and `model_preference` are injected at execution time

---

### 5. Agentic Tool Calling — Fixed and Production-Ready

Several bugs prevented tool-using agentic tasks from working:

| Bug | Fix |
|-----|-----|
| `ToolDefinition` missing `parameters` JSON schema → 400 from LMStudio | Added `parameters` field + `to_openai_function()` method |
| `bash_exec` whitelist of ~15 commands blocked `arp`, `ip`, `nmap`, etc. | Flipped to **blacklist** — all read/observe commands allowed; only destructive commands blocked (`rm`, `dd`, `sudo`, `chmod`, `kill`, etc.) |
| `consecutive_errors` loaded from disk on startup → all resources UNREACHABLE | Reset `consecutive_errors` to 0 on server start; stale errors from previous session no longer block resources |
| `acquire()` not filtering UNREACHABLE resources | Added `_compute_status()` check before returning a resource |
| Thinking models (Qwen3.5) return response in `reasoning_content` not `content` | Added fallback to `reasoning_content` in response text extraction |
| Role `model_preference` typo → silent 400 with no pointer to config | Diagnosed; drives Feature 4 (Config Doctor) in v1.3.0 |

---

### 6. `scheduler_list_agent_tools` MCP Tool

MCP clients can now discover available agent tools before scheduling a task:

```
scheduler_list_agent_tools() → list of tools with name, description,
                                danger_level, requires_auth
```

Updated `client_system_prompt.md` with task type decision table, tool
discovery pattern, and correct agentic task example.

---

### 7. Dreaming Pipeline Fix

`_execute_dreaming` was reading `D_archive["path"]` but the pipeline returns
`D_archive["storage_location"]` — causing every post-task dreaming
consolidation to fail silently with `KeyError: 'path'`. Fixed.

---

## Validated End-to-End

**Ahman network topology scan** — role-bound agentic task with `bash_exec`:
- Loaded Ahman personality and model preference
- Searched memory for prior context (`memory_search`)
- Ran `ip neigh`, `ping` across multiple iterations
- Identified real devices on `192.168.2.x` network
- Flagged anomalies (duplicate MAC, failed ARP entries, repeater latency)
- Produced structured `FINAL_ANSWER` in 10 iterations / 182 seconds

---

## Key Files Added

| File | Purpose |
|------|---------|
| `app/llm/unified_client.py` | Single LLM HTTP call class |
| `app/roles/role_manager.py` | Load / save roles |
| `app/roles/role_designer.py` | Nine Chapter interview engine |
| `config/llm_config.json` | LLM resource definitions (gitignored) |
| `config/client_system_prompt.md` | MCP client onboarding prompt |
| `config/planning_prompts.json` | Agentic workflow prompt library |
| `docs/nine_chapter_human_simulation.md` | Role design methodology |
| `docs/releases/RELEASE_NOTES_v1.2.0-planned.md` | v1.3.0 roadmap |

## Key Files Updated

| File | Change |
|------|--------|
| `app/scheduler/agentic_executor.py` | UnifiedLLMClient, tool defs, role loading |
| `app/scheduler/dynamic_tool_registry.py` | parameters schema, blacklist, to_openai_function() |
| `app/scheduler/resource_pool.py` | acquire() fix, startup error reset, UnifiedLLMClient key resolution |
| `app/scheduler/executor.py` | Dreaming path fix (storage_location) |
| `app/config/config_loader.py` | resolve_llm_resource() searches local_models |
| `app/llm/api_llm_interface.py` | UnifiedLLMClient |
| `app/llm/llm_interface.py` | UnifiedLLMClient |
| `app/mcp/core/tools.py` | scheduler_list_agent_tools, get_recent_events, config_changed events |
| `app/mcp/adapters/sse.py` | Standard envelope, new event types |

---

## Upgrade Notes

- `config/llm_config.json` is now the single source of truth for all LLM
  resources. Copy `.example` → remove `.example` suffix and fill in your keys.
- Role `model_preference` must match a model name available on the assigned
  resource. Use `llm_list_available_models` to verify.
- `bash_exec` now allows all non-destructive Linux commands. Review any
  agentic tasks that relied on the old whitelist behaviour.

---

## What's Next (v1.3.0)

See `docs/releases/RELEASE_NOTES_v1.2.0-planned.md`:

1. **Role Policy Monitor** — runtime tool permission enforcement
2. **Human-in-the-Loop Inbox** — `ask_user` tool + `WAITING_FOR_INPUT` status
3. **Extensible Tool Executor** — add tools via JSON config (shell, python, MCP proxy)
4. **Configuration Doctor** — validate all runtime config before tasks run
