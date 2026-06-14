# Release Notes v1.2.1-beta

## Theme: Attention Layer + MCP Consolidation

Two major improvements: the MCP client LLM now wakes up aware (not blind), and the
tool surface drops from ~49 visible schemas to 12.

---

## Feature 1: Attention Layer

**Problem:** v1.2.0 HITL worked but the LLM had no proactive way to discover waiting
tasks. Ahman's questions went unnoticed until the user asked manually.

### AttentionClassifier (`app/mcp/adapters/attention_classifier.py`)

Deterministic System-1 classifier — no LLM, no I/O. Runs inside `EventLog.append()`
at write time. Every event gets a `hitl_level` (0–5). First match wins:

| Level | Rule |
|-------|------|
| 5 | `severity == "critical"` |
| 4 | `event_type == "task_waiting_for_input"` |
| 3 | `severity == "error"` or `event_type == "task_failed"` |
| 2 | `event_type == "task_completed"` + `notify_user == true` |
| 1 | any `notify_user == true` |
| 0 | everything else |

### EventLog (`app/mcp/adapters/event_log.py`)

Persistent circular buffer (500 events) at `~/.memory/events.json`. Calls
AttentionClassifier in `append()` before persisting. Every SSE event flows
through EventLog automatically.

### Wake-up Hook in `get_context()`

`get_context()` (the conversation-start orientation call) now injects `attention`
into its response whenever `blocking` or `alerts` are non-empty. Silent when
everything is quiet — no noise added to clean conversations.

```json
{
  "timestamp": "...",
  "attention": {
    "blocking": [
      {
        "id": "u_882a", "level": 4, "from": "ahman",
        "blurb": "Waiting: which subnet should I scan?",
        "reply_with": "reply_to_task", "task_id": "ahman_scan_001"
      }
    ],
    "note": "Call get_context(type='attention') for full details."
  },
  "task_sessions": [
    {
      "task_id": "ahman_scan_001",
      "status": "waiting_for_input",
      "pending_question": "which subnet should I scan?"
    }
  ]
}
```

---

## Feature 2: MCP Tool Consolidation (49 → 12)

**Problem:** ~49 visible tool schemas in every LLM context window. Management tools
(remove_document, scheduler_restart_daemon) indistinguishable from frequent tools
(add_conversation, reply_to_task).

**Design:** Frequent tools stay top-level. Management tools live inside action hubs.
Call a hub with no action → compact help menu. Unknown action → help menu + error note.
LLM never needs to guess.

### 12 Visible Tools

| # | Tool | Type |
|---|------|------|
| 1 | `get_context(type?, …)` | top-level — orientation + attention + events + task_session |
| 2 | `search_memory(query, …)` | top-level — semantic search across all memory tiers |
| 3 | `add_conversation(user, assistant)` | top-level — call each turn |
| 4 | `reply_to_task(task_id, reply)` | top-level — HITL inbox reply |
| 5 | `web_search(query)` | top-level |
| 6 | `memory(action, …)` | hub — 9 memory management actions |
| 7 | `knowledge(action, …)` | hub — 3 git repo actions |
| 8 | `config(action, …)` | hub — file config + resource pool + doctor + roles |
| 9 | `scheduler(action, …)` | hub — 10 scheduler actions |
| 10 | `dream(action, …)` | hub — 4 dreaming actions |
| 11 | `agent(action, …)` | hub — 8 agent lifecycle actions |
| 12 | `external_agent(action, …)` | hub — Google + future 3rd-party |

### `get_context` Type System

One tool, four lenses:

```
get_context()                                    → orientation (default)
get_context(type="attention", since="...", min_level=1) → grouped inbox
get_context(type="events", event_types=[...])   → raw event log
get_context(type="task_session", task_id="...")  → full task output
```

`task_sessions` directory included in orientation so LLMs discover task_ids
before needing to drill in.

### Retired Tools (now placeholder_tools)

`get_memory_context`, `get_current_day`, `get_current_time`, `get_recent_events`,
`get_attention_summary`, `task_session_read`, `scheduler_resume_task`,
`get_memory_stats`, `end_conversation`, `toggle_multi_model`,
`list_recent_conversations`, `remove_conversation_message`,
`remove_recent_conversations`, `add_documents`, `list_recent_documents`,
`remove_document`, `knowledge_add_repo`, `knowledge_get_file`,
`knowledge_list_repos`, all `agent_*`, all `scheduler_*`, all `dreaming_*`,
`config_doctor`, `llm_list_available_models`, all `resource_pool_*`,
all `role_*`, `google_service`

---

## Feature 3: Scheduler Improvements

### Zero-latency wake signal

Replaced 60-second sleep polling with `asyncio.Event`. When `reply_to_task()` or
`add_task()` fires, the scheduler wakes immediately instead of waiting up to 60s.

### Config-driven default tasks (`config/scheduler_config.json`)

Default recurring tasks defined in JSON — no code change needed to add, modify,
or disable a default task. Runtime overrides at `~/.memory/config/scheduler_config.json`.

```json
{
  "default_tasks": [
    {
      "id": "dreaming_nightly_offpeak_default",
      "type": "dreaming",
      "cron": "0 3 * * *",
      "priority": "low",
      "enabled": true
    }
  ]
}
```

---

## Feature 4: SSE Event Envelope

All SSE events now carry a standard envelope:

```json
{
  "event_type": "task_completed",
  "timestamp": "ISO-8601",
  "severity": "info",
  "title": "Short one-line summary",
  "notify_user": false,
  "hitl_level": 0,
  "data": { "...type-specific..." }
}
```

`notify_user` auto-set when `severity` is `warning` or above.

---

## Architecture Documents Added

- `docs/architecture/MCP_DESIGN.md` — authoritative design reference for implementation agents
- `docs/claude-guide/CLIENT_SYSTEM_PROMPT.md` — recommended client system prompt for 12-tool architecture
- `docs/releases/ROADMAP_future.md` — three future architecture directions (Policy Agent, Message Passing, Inbox→Dream)

---

## Files Changed

| File | Change |
|------|--------|
| `app/mcp/adapters/attention_classifier.py` | NEW — deterministic hitl_level classifier |
| `app/mcp/adapters/event_log.py` | EventLog + AttentionClassifier wired in |
| `app/mcp/adapters/sse.py` | Standard event envelope |
| `app/mcp/core/tools.py` | 12-tool surface, hub dispatchers, get_context, search_memory |
| `app/scheduler/core.py` | Wake signal, config-driven task seeding |
| `config/scheduler_config.json` | NEW — default task definitions |
| `config/scheduler_config.json.example` | NEW — committed template |
