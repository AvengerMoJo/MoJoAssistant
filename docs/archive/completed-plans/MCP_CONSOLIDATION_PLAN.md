# MCP Tool Consolidation Plan

## Problem

~49 visible MCP tools. Every tool schema occupies context-window tokens.
The thinking model sees 49 schemas on every call — most of which it will
never use in a given conversation. Management tools (remove_document,
scheduler_restart_daemon, resource_pool_revoke …) are indistinguishable
from frequent tools (add_conversation, reply_to_task) at the schema level.

## Design Principle

**Frequent tools stay top-level. Management tools live inside action hubs.**

Hubs expose a single schema with an `action` parameter.
Calling a hub with no action (or `action="help"`) returns a compact menu —
the LLM discovers sub-commands on demand rather than holding all schemas
in context permanently.

## Before → After

```
Before:  ~49 visible tools  (all schemas in context every call)
After:   12 visible tools   (hub sub-commands discovered on demand)
```

---

## Part 1 — `get_context` Unified Read Tool

**Current:** `get_context()` (orientation only) + `get_recent_events` +
`get_attention_summary` + `task_session_read` = 4 separate tools

**New:** one `get_context(type?, ...)` — same verb, different lens.

---

### Type: `"orientation"` (default — no type param needed)

```
get_context()
```

The **directory call** — tells the LLM everything it needs to know to decide
what to do next.  Includes:

1. **Temporal context** — timestamp, date, day_of_week, time
2. **Recent memory** — last 3 working memory items (recency, no query)
3. **Attention** — blocking/alerts if anything needs action (wake-up hook)
4. **Task sessions** — lightweight directory of active/interesting tasks so
   the LLM can discover task_ids before drilling in with `type="task_session"`

```json
{
  "timestamp": "2026-03-19T10:42:00",
  "date": "2026-03-19",
  "day_of_week": "Thursday",
  "time": "10:42",
  "recent_memory": [
    { "source": "working_memory", "content": "..." }
  ],
  "attention": {
    "blocking": [
      {
        "id": "u_882a", "level": 4, "from": "analyst",
        "blurb": "Waiting: which subnet should I scan?",
        "reply_with": "reply_to_task", "task_id": "ahman_scan_001",
        "created_at": "2026-03-19T09:14:00"
      }
    ],
    "alerts": [],
    "note": "Call get_context(type='attention') for full details."
  },
  "task_sessions": [
    {
      "task_id": "ahman_scan_001",
      "status": "waiting_for_input",
      "title": "Weekly Analyst security review",
      "role": "analyst",
      "pending_question": "which subnet should I scan?",
      "created_at": "2026-03-19T08:00:00"
    },
    {
      "task_id": "dreaming_nightly_20260319",
      "status": "running",
      "title": "Nightly dreaming consolidation",
      "role": null,
      "pending_question": null,
      "created_at": "2026-03-19T03:00:00"
    }
  ]
}
```

`attention` omitted when empty.
`task_sessions` shows: running, waiting_for_input, and recently-completed
tasks with `notify_user=true`. Omitted when empty.

---

### Inbox + Reply Routing — How It Works

`attention.blocking` items and `task_sessions` answer "what needs my attention
and what is the task_id?"  They are the same data viewed differently:

- `attention.blocking` → urgent, surfaces the question inline
- `task_sessions` → full directory, includes non-urgent running tasks

**Reply routing** is via `task_id` — a direct pointer, no separate routing table:

```
attention.blocking[0]:
  task_id: "ahman_scan_001"
  reply_with: "reply_to_task"   ← hub already tells LLM the exact call

LLM calls: reply_to_task(task_id="ahman_scan_001", reply="scan 10.0.0.0/24")
  ↓
scheduler.resume_task_with_reply() — sets task status PENDING, injects reply
  ↓
Scheduler next tick picks up PENDING task and resumes agent with reply as
injected user message in the conversation history
  ↓
Agent continues from where it paused
```

The scheduler agent does not "watch" for replies — it passively finds the
PENDING task on the next tick.  This is intentional: the scheduler is a
pull-based queue, not a push-based event listener.

**Known gap:** up to 60-second tick delay between reply and resume.
Acceptable for v1.x; a future `scheduler_wake` signal or tick reduction
can fix it without changing the inbox design.

**`reply_to_task` stays top-level** — it is a direct action on a known task_id,
time-sensitive (user is waiting), and called frequently enough to warrant
immediate access.  `scheduler_resume_task` is the same operation and will
be **retired** — `reply_to_task` is the canonical name.

---

### Type: `"attention"` — cursor-based attention polling

```
get_context(type="attention", since="2026-03-19T09:00:00", min_level=1)
```

Replaces standalone `get_attention_summary`.
Returns full grouped summary: blocking / alerts / digest / noise_count / cursor.
Use `since` cursor to advance position and avoid re-reading old items.

---

### Type: `"events"` — raw event log

```
get_context(type="events", since="...", event_types=["task_failed"], limit=50, include_data=false)
```

Replaces `get_recent_events`.
Returns raw event list with envelope fields (event_type, severity,
hitl_level, title, notify_user, timestamp).

---

### Type: `"task_session"` — full task output

```
get_context(type="task_session", task_id="ahman_scan_001")
```

Replaces `task_session_read`.
Returns full streamed output of the task, current status, and
`pending_question` if status is `waiting_for_input`.

LLM discovers `task_id` values from `get_context()` → `task_sessions` directory
before drilling in here.  No blind guessing of IDs required.

---

### Files
- `app/mcp/core/tools.py` — expand `get_context` schema with `type` + type-specific
  params; update `_execute_get_context` to dispatch on `type`
- Internal `_execute_get_attention_summary`, `_execute_get_recent_events`,
  `_execute_task_session_read` remain as private methods, called via type dispatch
- `app/scheduler/core.py` — `_build_task_sessions_directory()` helper returning
  lightweight task list for the orientation response

---

## Part 2 — `memory` Hub

Wraps infrequent memory management operations.

```
memory()                                     → help menu
memory(action="end_conversation")            → archive current topic
memory(action="list_conversations", limit=10)→ recent conversations
memory(action="remove_conversation", id="…") → delete one
memory(action="remove_conversations", count=3)→ bulk delete
memory(action="add_documents", documents=[…])→ add to knowledge base
memory(action="list_documents", limit=10)   → recent documents
memory(action="remove_document", id="…")    → delete document
memory(action="stats")                      → memory tier statistics
memory(action="toggle_multi_model", enabled=true) → embedding mode
```

**Retired into hub:** `end_conversation`, `list_recent_conversations`,
`remove_conversation_message`, `remove_recent_conversations`,
`add_documents`, `list_recent_documents`, `remove_document`,
`get_memory_stats`, `toggle_multi_model`

### Files
- `app/mcp/core/tools.py` — new `memory` schema + `_execute_memory` dispatcher

---

## Part 3 — `knowledge` Hub

Git repository knowledge base management.

```
knowledge()                                           → help menu
knowledge(action="add_repo", name, url, ssh_key_path) → register repo
knowledge(action="list_repos")                        → list registered repos
knowledge(action="get_file", repo, path, git_hash?)   → read file from repo
```

**Retired into hub:** `knowledge_add_repo`, `knowledge_list_repos`,
`knowledge_get_file`

### Files
- `app/mcp/core/tools.py` — new `knowledge` schema + `_execute_knowledge`

---

## Part 4 — `config` Hub (Expanded)

Current `config` manages llm_config / role_config / scheduler_config JSON files.
Expand it to absorb resource pool runtime state, config validation, model
discovery, and role management.

```
config()                                            → help menu + module list

# --- existing file config ---
config(action="get",      module="llm_config")
config(action="set",      module="llm_config", path="…", value=…)
config(action="list",     module="llm_config")
config(action="delete",   module="llm_config", path="…")
config(action="validate", module="llm_config")
config(action="modules")                            → list all config modules

# --- resource pool (runtime LLM state) ---
config(action="resource_status")                    → all resources + approval + smoke-test
config(action="resource_approve",   resource_id="…")
config(action="resource_revoke",    resource_id="…")
config(action="resource_smoke_test",resource_id="…")
config(action="llm_models",         resource_id="…") → list live models from server

# --- validation ---
config(action="doctor")                             → full config pre-flight report

# --- role management ---
config(action="role_list")
config(action="role_get",    role_id="…")
config(action="role_create", role_id, system_prompt, model_preference, …)
config(action="role_design_start")                  → Nine Chapter interview Q1
config(action="role_design_answer", session_id, answer) → next question / finish
```

**Retired into hub:** `resource_pool_status`, `resource_pool_approve`,
`resource_pool_revoke`, `resource_pool_smoke_test`, `llm_list_available_models`,
`config_doctor`, `role_list`, `role_get`, `role_create`, `role_design_start`,
`role_design_answer`

**Why roles belong here:** Roles are JSON-backed config objects. Creating/editing
a role is a configuration operation, not a runtime operation.  The role
definition lives in `role_config.json` — same layer as llm_config.

### Files
- `app/mcp/core/tools.py` — expand `config` schema + `_execute_config` dispatcher

---

## Part 5 — `scheduler` Hub

```
scheduler()                                          → help menu
scheduler(action="add",   task_id, type, goal, …)   → schedule a task
scheduler(action="list",  status?, priority?, limit?)→ list tasks
scheduler(action="get",   task_id)                  → task detail
scheduler(action="remove",task_id)                  → remove task
scheduler(action="purge", before_date?)             → bulk remove completed/failed
scheduler(action="status")                          → daemon + queue stats
scheduler(action="daemon_start")
scheduler(action="daemon_stop")
scheduler(action="daemon_restart")
scheduler(action="list_tools")                      → tools available to agents
```

**`scheduler_resume_task` is retired** — duplicate of `reply_to_task` which stays
top-level.  See inbox + reply routing design in Part 1.

**Retired into hub:** `scheduler_add_task`, `scheduler_list_tasks`,
`scheduler_get_status`, `scheduler_get_task`, `scheduler_remove_task`,
`scheduler_purge_tasks`, `scheduler_start_daemon`, `scheduler_stop_daemon`,
`scheduler_restart_daemon`, `scheduler_daemon_status`,
`scheduler_list_assistant_tools`

**Retired entirely:** `scheduler_resume_task` (use `reply_to_task` instead)

### Files
- `app/mcp/core/tools.py` — new `scheduler` schema + `_execute_scheduler`

---

## Part 6 — `dream` Hub

```
dream()                                             → help menu
dream(action="process", conversation_id, quality?)  → run dreaming pipeline
dream(action="list")                                → list archives
dream(action="get",     conversation_id, version?)  → retrieve archive
dream(action="upgrade", conversation_id, target_quality) → quality upgrade
```

**Retired into hub:** `dreaming_process`, `dreaming_list_archives`,
`dreaming_get_archive`, `dreaming_upgrade_quality`

### Files
- `app/mcp/core/tools.py` — new `dream` schema + `_execute_dream`

---

## Part 7 — `agent` Hub

```
agent()                                          → help menu
agent(action="list_types")                       → available agent types
agent(action="start",   agent_id, type, …)
agent(action="stop",    agent_id)
agent(action="status",  agent_id)
agent(action="list")                             → all running agents
agent(action="restart", agent_id)
agent(action="destroy", agent_id)
agent(action="action",  agent_id, action, params) → send action to agent
```

**Retired into hub:** `agent_list_types`, `agent_start`, `agent_stop`,
`agent_status`, `agent_list`, `agent_restart`, `agent_destroy`, `agent_action`

### Files
- `app/mcp/core/tools.py` — new `agent` schema + `_execute_agent`

---

## Part 8 — `external_agent` Hub

External services and 3rd-party integrations.  Anything that talks to an
outside API that is not search goes here.

```
external_agent()                                      → help menu
external_agent(action="google", service, resource,
               method, params?)                       → Google API proxy
```

Future additions land here without adding new top-level tools:
- `external_agent(action="github", …)`
- `external_agent(action="slack", …)`
- `external_agent(action="notion", …)`

**Retired into hub:** `google_service`

### Files
- `app/mcp/core/tools.py` — new `external_agent` schema + `_execute_external_agent`

---

## Final Tool Map

| # | Tool | Type | Replaces / Notes |
|---|------|------|---------|
| 1 | `get_context(type?, …)` | top-level | orientation + get_recent_events + get_attention_summary + task_session_read. Default call returns **directory** (attention + task_sessions list). |
| 2 | `search_memory(query, …)` | top-level | already done |
| 3 | `add_conversation(user, assistant)` | top-level | unchanged |
| 4 | `reply_to_task(task_id, reply)` | top-level | unchanged; `scheduler_resume_task` **retired** — this is the canonical inbox reply |
| 5 | `web_search(query)` | top-level | unchanged |
| 6 | `memory(action, …)` | hub | 9 management tools |
| 7 | `knowledge(action, …)` | hub | 3 knowledge_* tools |
| 8 | `config(action, …)` | hub | existing config + resource_pool (4) + doctor + llm_models + roles (5) = +11 tools |
| 9 | `scheduler(action, …)` | hub | 11 scheduler_* tools (resume_task retired) |
| 10 | `dream(action, …)` | hub | 4 dreaming_* tools |
| 11 | `agent(action, …)` | hub | 8 agent_* tools |
| 12 | `external_agent(action, …)` | hub | google_service + future 3rd-party |

**49 active tools → 12 visible tools**

### Inbox flow at a glance

```
get_context()
  └─ attention.blocking[0]
       task_id: "ahman_scan_001"
       reply_with: "reply_to_task"     ← pre-filled hint
       blurb: "Waiting: which subnet?"
  └─ task_sessions[0]
       task_id: "ahman_scan_001"       ← same ID, can drill in

get_context(type="task_session", task_id="ahman_scan_001")
  └─ full output + pending_question    ← LLM decides if it needs more context

reply_to_task(task_id="ahman_scan_001", reply="scan 10.0.0.0/24")
  └─ task resumes on next scheduler tick
```

---

## Implementation Order

1. `get_context` — add `type` dispatch (events, attention, task_session)
2. `memory` hub
3. `knowledge` hub
4. `config` hub expansion (resource_pool + doctor + llm_models + roles)
5. `scheduler` hub
6. `dream` hub
7. `agent` hub
8. `external_agent` hub
9. Retire all replaced tool schemas + update placeholder_tools

Each step is independently testable via MCP restart.

---

## Hub Response Contract

Every hub called with no action (or `action="help"`) returns:

```json
{
  "tool": "scheduler",
  "actions": {
    "add":            "Schedule a new task — params: task_id, type, goal, ...",
    "list":           "List tasks — params: status?, priority?, limit?",
    "get":            "Get task detail — params: task_id",
    "remove":         "Remove a task — params: task_id",
    "purge":          "Bulk remove old tasks — params: before_date?",
    "status":         "Daemon + queue stats",
    "daemon_start":   "Start the scheduler daemon",
    "daemon_stop":    "Stop the scheduler daemon",
    "daemon_restart": "Restart the scheduler daemon",
    "list_tools":     "List tools available to scheduled agents",
    "resume_task":    "Resume a waiting task — params: task_id, reply"
  },
  "example": "scheduler(action=\"list\", status=\"waiting_for_input\")"
}
```

Unknown actions also return the help menu with an error note.
This means the LLM never needs to guess — a wrong call self-corrects.

---

## What Does NOT Change

- `add_conversation` — called every turn, top-level forever
- `reply_to_task` — HITL is time-sensitive, must be immediate
- `web_search` — fundamental capability
- Internal `_execute_*` private methods — hubs call them, no rewrite needed
- `AttentionClassifier`, `EventLog`, `SSENotifier` — unchanged
