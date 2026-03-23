# MoJoAssistant — MCP Architecture Design Reference

> **For implementation agents**: This document is the authoritative source for
> how MCP tools are designed in this system. Read it before adding, changing,
> or refactoring any MCP tool. Every design decision here has a reason.

---

## 1. System Purpose

MoJoAssistant is a **local-first privacy proxy** — a trusted intermediary
where a local thinking LLM processes the user's data before it touches any
external service. The MCP server is the interface between the thinking LLM
(Claude Desktop, etc.) and all local subsystems (memory, scheduler, agents,
config, dreaming).

```
User / External World
      ↕  (controlled, audited, sanitized)
MoJoAssistant MCP Gateway
      ↕  (local only, never leaves device)
Local LLM + Memory + Scheduler + Agents
```

The thinking LLM is **System 2** — deliberate, expensive, used for decisions.
Local subsystems (scheduler, event classifier, dreaming) are **System 1** —
fast, deterministic, never need the LLM to make them work.

---

## 2. MCP Tool Design Philosophy

### 2.1 Token budget is the primary constraint

Every tool schema visible to the MCP client occupies tokens in every call.
49 schemas × ~200 tokens each = ~9,800 tokens wasted on tools the LLM will
never call in a given conversation. The design target is **12 visible tools**.

**Rule:** if a tool is called less than once per conversation on average, it
belongs inside a hub, not at the top level.

### 2.2 Two tiers: top-level vs hubs

| Tier | Criteria | Examples |
|------|----------|---------|
| **Top-level** | Called every conversation, time-sensitive, or interactive | `get_context`, `search_memory`, `add_conversation`, `reply_to_task`, `web_search` |
| **Hub** | Administrative / management / infrequently called | `config`, `scheduler`, `memory`, `agent`, `dream`, `knowledge`, `external_agent` |

Top-level tools: full schema always in context.
Hub tools: one schema (with `action` param) in context; sub-commands
discovered on demand via the help menu pattern.

### 2.3 Self-documenting calls

Every hub must return a usable help menu when called with no action.
An unknown action also returns the help menu with an error note.
**The LLM must never be blocked by not knowing a sub-command** — a wrong call
self-corrects in one round-trip.

```python
# Hub contract — every hub follows this
if not action or action == "help":
    return _hub_help_menu()
elif action not in KNOWN_ACTIONS:
    return {**_hub_help_menu(), "error": f"Unknown action '{action}'"}
```

### 2.4 Read tools vs write tools vs action tools

- **Read** → `get_context`, `search_memory` — pure reads, safe to call any time
- **Write** → `add_conversation`, `memory(action="add_documents")` — persist data
- **Action** → `reply_to_task`, `scheduler(action="add")` — trigger side-effects

Don't mix read and write semantics in the same tool call. A tool that
both searches and modifies state is a bug waiting to happen.

### 2.5 No blind ID guessing

If a tool requires an ID (task_id, agent_id, conversation_id), there must
always be a discovery path that does not require the LLM to remember or
guess the ID. The directory pattern in `get_context()` is the primary
discovery mechanism. Hub list actions (`scheduler(action="list")`,
`agent(action="list")`) are the secondary path.

---

## 3. The Conversation Entry Point — `get_context()`

`get_context()` is the **one call that orients the LLM at conversation start**.
It is the equivalent of opening your email, checking your calendar, and
glancing at the clock — all in a single tool call.

### 3.1 Default call (no params) — the directory

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
    "blocking": [{ "task_id": "...", "reply_with": "reply_to_task", "blurb": "..." }],
    "alerts":   [{ ... }],
    "note": "Call get_context(type='attention') for full details."
  },
  "task_sessions": [
    { "task_id": "ahman_scan_001", "status": "waiting_for_input",
      "role": "ahman", "pending_question": "which subnet?", "created_at": "..." }
  ]
}
```

- `recent_memory`: last 3 working memory items — recency only, no embedding needed
- `attention`: omitted entirely when empty (quiet conversations stay quiet)
- `task_sessions`: lightweight directory of running/waiting tasks — gives LLM
  the task_ids it needs to drill in without guessing

### 3.2 Typed calls — drilling in

| Call | Returns | Replaces |
|------|---------|---------|
| `get_context()` | Directory (above) | orientation + get_current_day |
| `get_context(type="attention", since?, min_level?)` | Grouped inbox: blocking/alerts/digest/cursor | `get_attention_summary` |
| `get_context(type="events", since?, event_types?, limit?)` | Raw event list | `get_recent_events` |
| `get_context(type="task_session", task_id)` | Full task output + status | `task_session_read` |

**Pattern**: the default call is always the directory. Typed calls drill into
a specific lens. The LLM discovers what to drill into from the directory —
no ID guessing required.

### 3.3 The wake-up hook

`get_context()` automatically runs the attention summary internally and
injects `attention.blocking` / `attention.alerts` if non-empty. This means
the LLM wakes up aware of urgent items without making a separate tool call.
If nothing needs attention, the field is omitted — zero noise.

---

## 4. Hub Pattern Specification

All hubs follow an identical contract. When implementing a new hub:

### 4.1 Schema shape

```python
{
    "name": "scheduler",
    "description": "One-line summary + usage guidance. "
                   "Call with no action to see available actions.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Action to perform. Omit to see all actions.",
            },
            # ... action-specific params, all optional at schema level
            # (validated inside the dispatcher, not by MCP schema)
        },
        "required": [],  # action is always optional — enables the help pattern
    },
}
```

All params except `action` are `required: []` at the MCP schema level.
Validation happens inside `_execute_<hub>()` based on the selected action.
This keeps the schema minimal and lets the help menu explain requirements.

### 4.2 Dispatcher shape

```python
async def _execute_scheduler(self, args):
    action = args.get("action", "help")
    if action in ("help", "") or action not in _SCHEDULER_ACTIONS:
        menu = { ... }
        if action not in ("help", ""):
            menu["error"] = f"Unknown action '{action}'"
        return menu
    elif action == "list":
        return await self._execute_scheduler_list_tasks(args)
    elif action == "add":
        return await self._execute_scheduler_add_task(args)
    # ...
```

The internal `_execute_*` methods for each sub-command already exist — the
hub dispatcher is a thin routing layer on top. Do not duplicate logic.

### 4.3 Help menu shape

```json
{
  "tool": "scheduler",
  "actions": {
    "add":    "Schedule a task — params: task_id, type, goal, ...",
    "list":   "List tasks — params: status?, priority?, limit?",
    "get":    "Task detail — params: task_id",
    "remove": "Remove a task — params: task_id",
    "status": "Daemon + queue stats"
  },
  "example": "scheduler(action=\"list\", status=\"waiting_for_input\")"
}
```

Always include one concrete `example`. LLMs learn faster from an example
than from parameter descriptions alone.

---

## 5. Attention System

Attention is treated as a finite resource. Events are classified by urgency
at write time — not at read time. The LLM never has to scan a raw log and
decide what matters.

### 5.1 Pipeline

```
Any subsystem calls SSENotifier.broadcast(event)
  ↓
SSENotifier enriches event with standard envelope:
  timestamp, severity, title, notify_user
  ↓
SSENotifier calls EventLog.append(event)
  ↓
EventLog calls AttentionClassifier.classify(event) → hitl_level 0-5
  hitl_level stored on the event before persistence
  ↓
Event persisted to ~/.memory/events.json (circular buffer, 500 events)
  ↓
SSE stream fans out to any connected WebSocket clients
```

### 5.2 AttentionClassifier rules (first match wins)

| Level | Rule | Semantics |
|-------|------|-----------|
| 5 | `severity == "critical"` | System down / fatal error |
| 4 | `event_type == "task_waiting_for_input"` | Agent paused, blocking on user |
| 3 | `severity == "error"` OR `event_type == "task_failed"` | Failure, needs investigation |
| 2 | `event_type == "task_completed"` AND `notify_user == True` | Task done, user requested notification |
| 1 | `notify_user == True` (any event) | Background update worth noting |
| 0 | everything else | Noise — heartbeats, ticks, dreaming progress |

**Rule:** never add a new event type without deciding its level.
If you add a broadcast call, set `severity` and `notify_user` explicitly.
Defaulting to `"info"` / `False` produces level 0 — invisible to the LLM.

### 5.3 Consuming attention

`get_context()` → `attention.blocking/alerts` — wake-up hook, conversation start
`get_context(type="attention", since=cursor)` — cursor-based polling, advances position
`get_context(type="events", ...)` — raw log, for debugging / specific event types

The `since` cursor is owned by the caller. The server has no read state —
the client passes its last-seen timestamp and gets only newer events back.

---

## 6. Memory Architecture

Four tiers, each with different characteristics:

```
working_memory  — current session messages. In-memory only. Lost on restart.
                  Fast. Used for: recent conversation context.

active_memory   — recent pages. In-memory with periodic flush.
                  Used for: frequently accessed items promoted from archival.

archival_memory — long-term semantic storage. Persisted to ~/.memory/.
                  Embedding search. Used for: past conversations, insights.

knowledge_base  — structured documents added explicitly by user.
                  Persisted. Embedding search. Used for: reference material,
                  code snippets, documentation.
```

### 6.1 Search tool mapping

`search_memory(query, types, limit_per_type)` maps to tiers:

- `types=["conversations"]` → working + active + archival (all conversational)
- `types=["documents"]` → knowledge_base
- omit → all

`limit_per_type` is per-tier, not global. This prevents one tier (usually
archival) from drowning out the others when all are relevant.

### 6.2 What get_context() provides vs search_memory()

`get_context()` gives recency — the last 3 working memory items, no query.
`search_memory()` gives relevance — semantic similarity to a query.

Use `get_context()` to orient. Use `search_memory()` to investigate.

---

## 7. HITL Inbox Model

Human-in-the-Loop events are not a special mechanism — they are regular
events in the attention system with `hitl_level == 4`.

### 7.1 Flow

```
1. Agent calls ask_user("which subnet should I scan?")
   → agentic_executor sets _waiting_for_input_question

2. Executor returns TaskResult(waiting_for_input="which subnet...")
   → scheduler sets task.status = WAITING_FOR_INPUT
   → scheduler sets task.pending_question
   → scheduler broadcasts task_waiting_for_input event

3. AttentionClassifier assigns hitl_level = 4

4. Event persists to EventLog

5. Next get_context() call:
   → attention.blocking includes this event
   → task_sessions includes this task with pending_question
   → reply_with: "reply_to_task" pre-filled

6. LLM calls reply_to_task(task_id="...", reply="scan 10.0.0.0/24")
   → resume_task_with_reply() sets task config reply_to_question
   → task status → PENDING

7. Scheduler next tick finds PENDING task, resumes agent
   → agent receives reply as injected user message in conversation
```

### 7.2 Reply routing

The routing key is `task_id`. It is embedded in the event (`data.task_id`),
in the attention item (`blocking[].task_id`), and in the task directory
(`task_sessions[].task_id`). The LLM never needs to construct or guess it.

`reply_to_task` is the **only** top-level reply tool. `scheduler_resume_task`
is retired — it was a duplicate. Do not add new top-level reply tools;
future inbox item types should use the same pattern (item carries `reply_with`
+ the routing key for that item type).

### 7.3 Known gap — 60-second tick delay

After `reply_to_task()`, the task resumes on the next scheduler tick (up to
60 seconds). This is by design — the scheduler is pull-based, not
push-based. Fix: add a `scheduler_wake()` internal signal that sets a flag
checked on the next loop iteration (or reduce tick interval). Do not add
push mechanisms without scheduler consent.

---

## 8. Configuration Architecture

Config follows the Linux-style layered hierarchy:

```
project/config/<module>.json   — system defaults (committed, no secrets)
~/.memory/config/<module>.json — personal overrides (never committed)
```

Personal layer wins on any key conflict. Merge is shallow (key-level),
not deep (nested object-level), unless the loader explicitly merges arrays.

### 8.1 Config modules

| Module | Contents |
|--------|---------|
| `llm_config.json` | LLM resource definitions (endpoints, models, tiers, API keys via env) |
| `role_config.json` | Agent role definitions (system prompts, model preferences, policies) |
| `scheduler_config.json` | Default tasks (seeded at startup, not hardcoded in Python) |

### 8.2 resource_pool vs llm_config

`llm_config.json` defines what LLM resources **exist**.
`resource_pool` (runtime, `~/.memory/resource_pool_meta.json`) manages what
is **approved** and whether it passed the smoke test.

Both are LLM configuration — they live under the `config` hub together.
The distinction is file-config vs runtime-state, not separate concerns.

### 8.3 Roles are config objects

Roles are JSON-backed personality definitions. Creating, editing, and listing
roles is a configuration operation. Roles live under the `config` hub, not
a standalone `role` hub. Rationale: roles live in `role_config.json` — same
layer as llm_config.

---

## 9. Scheduler Model

The scheduler is a **pull-based tick queue**, not a push-based event loop.

```
Every 60 seconds:
  1. Check for due cron tasks → create Task → enqueue as PENDING
  2. Find highest-priority PENDING task
  3. Dispatch to AgenticExecutor
  4. Executor runs agent loop (tool calls until FINAL_ANSWER or limit)
  5. Result → task status (completed / failed / waiting_for_input)
  6. Broadcast event
  7. Sleep until next tick
```

**Implications for implementors:**
- Tasks are stateless between ticks — all state lives in the Task object
- "Resume" = set status PENDING + inject reply into config — executor reads
  it on next tick as if it were a fresh run with extra context
- Do not add async callbacks or push mechanisms into the executor — it is
  designed to be a synchronous black box from the scheduler's perspective
- Config-driven default tasks (`scheduler_config.json`) — never hardcode
  default tasks in Python. Add them to the config file instead.

---

## 10. Event Broadcasting Rules

Every broadcast MUST include:

```python
await self._broadcast({
    "event_type": "task_completed",       # required: snake_case noun_verb
    "severity": "info",                   # required: info|warning|error|critical
    "title": "Task ahman_scan completed", # required: one-line human summary
    "notify_user": True,                  # required: True if user should see this
    "data": {                             # optional: type-specific payload
        "task_id": task.id,
        "result_summary": "...",
    }
})
```

**AttentionClassifier reads `event_type`, `severity`, and `notify_user` to
assign hitl_level.** If you don't set these, the event becomes invisible
(level 0). Always decide the visibility of your event at the broadcast site.

---

## 11. The 12-Tool Target

The final visible tool set (post-consolidation):

```
Top-level (5):
  get_context       — orientation + directory + typed reads
  search_memory     — semantic search with per-type limits
  add_conversation  — conversation persistence (every turn)
  reply_to_task     — inbox reply / HITL response
  web_search        — external search

Hubs (7):
  memory            — conversation + document management
  knowledge         — git repository knowledge base
  config            — llm config + resource pool + doctor + roles
  scheduler         — task scheduling + daemon management
  dream             — dreaming pipeline + archives
  agent             — coding agent lifecycle
  external_agent    — google + future 3rd-party integrations
```

### Rules for maintaining the 12-tool target

1. **New frequent capability** → add as top-level only if called >1× per
   conversation. Otherwise, add to the most relevant hub.
2. **New integration** (Slack, GitHub, Notion, …) → add to `external_agent`
   hub, never as a new top-level tool.
3. **New config object type** → add to `config` hub, never standalone.
4. **New agent type** → add to `agent` hub, never standalone.
5. **Never add a tool that has <2 lines of unique logic** — if it just
   forwards to an existing internal method, wire it into an existing hub.

---

## 12. Anti-Patterns

These patterns have appeared in this codebase and should not be repeated:

| Anti-pattern | Problem | Correct approach |
|-------------|---------|-----------------|
| `get_current_day` as a standalone tool | Date is needed every call — put it in `get_context()` | Absorbed into `get_context()` |
| `scheduler_resume_task` + `reply_to_task` as duplicates | Same operation, two tools, two schemas | One canonical top-level tool |
| `resource_pool_status` as standalone | Same concern as `llm_config` | Fold into `config` hub |
| Hardcoding default tasks in Python | Code change required to change a schedule | `scheduler_config.json` |
| Per-tool placeholder entries in schemas | Placeholder tools still occupy schema space | `placeholder_tools` set |
| `notify_user` left as default False on important events | Event invisible to attention system | Always set explicitly at broadcast site |
| Nesting action params in MCP `required: [...]` | Breaks the help-menu self-correction pattern | All params `required: []`, validate inside dispatcher |

---

## 13. File Map

| Concern | File |
|---------|------|
| Tool schemas + dispatch | `app/mcp/core/tools.py` |
| Event pipeline (SSE + EventLog) | `app/mcp/adapters/sse.py`, `app/mcp/adapters/event_log.py` |
| Attention classifier | `app/mcp/adapters/attention_classifier.py` |
| Scheduler loop | `app/scheduler/core.py` |
| Agentic executor | `app/scheduler/agentic_executor.py` |
| Task + status models | `app/scheduler/models.py` |
| Tool executor (shell/python/mcp_proxy) | `app/scheduler/dynamic_tool_registry.py` |
| Resource pool runtime state | `app/scheduler/resource_pool.py` |
| Role management | `app/scheduler/role_manager.py` |
| Role policy enforcement | `app/scheduler/policy_monitor.py` |
| Config loading (layered) | `app/config/config_loader.py` |
| Config validation | `app/config/doctor.py` |
| Memory service | `app/services/memory_service.py` |
| Memory tiers | `app/memory/{working,active,archival}_memory.py` |
| Knowledge base | `app/memory/knowledge_manager.py` |
| Dreaming pipeline | `app/dreaming/pipeline.py` |
| Path constants | `app/config/paths.py` |

---

## 14. Design Decisions Log

Short rationale for choices that aren't obvious from code:

**Why pull-based scheduler (not push)?**
Simpler failure model. A stuck task doesn't block other tasks. Restart recovery
is trivial — scan for PENDING/RUNNING tasks on startup.

**Why hitl_level at write time (not read time)?**
AttentionClassifier has no I/O, no LLM, no state. Running it at `EventLog.append()`
is free. Running it at query time on 500 events would be slow and inconsistent
(LLM-based classifiers could change answers between calls).

**Why `reply_with` in attention items (not just `task_id`)?**
Future inbox items may use different reply tools. Embedding the tool name in the
item makes the attention system extensible — the LLM always knows what to call
without conditional logic.

**Why `limit_per_type` in search_memory (not global `max_items`)?**
A global limit lets one tier (usually archival, which tends to score higher)
dominate. Per-type limits ensure coverage across all searched tiers.

**Why roles inside `config` hub (not standalone)?**
Roles are JSON-backed config objects. The creation flow (Nine Chapter interview →
JSON → role_config.json) is identical to setting any other config value. A
standalone `role` hub would create a false conceptual boundary.

**Why `external_agent` (not per-service tools)?**
Google has 10+ services. Slack has actions. GitHub has endpoints. A new top-level
tool per service would blow the 12-tool budget. The hub pattern lets the system
grow without the LLM's context window growing.

---

## 15. Future Architecture Directions

These are not planned for immediate implementation but are deliberately
designed into the current architecture so they remain achievable without
a rewrite. Every decision here should preserve these paths.

---

### 15.1 Policy Enforcement Agent (Inbox as Interception Point)

**What:** A policy role that monitors the inbox event stream and can
proactively block operations — before execution, not just after logging.

**Why the inbox makes this possible:**
Today `PolicyMonitor` enforces role-level tool restrictions at task *start*
(denied_tools, allowed_tools ceiling). This is setup-time enforcement.
The inbox model exposes a richer interception point: every inter-agent
communication, every HITL question, every external call is an event in the
event stream *before* the result lands anywhere.

**Design sketch:**

```
Event emitted: "task about to call external API with this payload"
      ↓
PolicyAgent (scheduled role, monitors inbox at hitl_level ≥ 3) receives event
      ↓
PolicyAgent classifies: contains PII? crosses data boundary? dangerous tool?
      ↓
  ALLOW → event proceeds, PolicyAgent records decision
  BLOCK → event elevated to hitl_level 5, operation cancelled,
          user notified: "PolicyAgent blocked X because Y"
```

This is the proactive counterpart to the reactive `denied_tools` list.
`denied_tools` is a static rule. PolicyAgent is dynamic — it can understand
context, apply role-specific rules, and explain its decisions.

**Connection to ROADMAP_future.md:**
- Data Boundary Enforcement: PolicyAgent is the enforcer
- PII Classification: PolicyAgent calls the DataClassifier
- Sanitization Layer: PolicyAgent triggers sanitization before allowing
- Audit Trail: PolicyAgent writes every decision to the audit log

**Implementation requirements (preserving this path today):**
- Events must carry `source_task_id`, `source_role`, `destination` — all
  already present in the event envelope
- `hitl_level` must be assignable by a role, not just the classifier —
  PolicyAgent needs to escalate events it flags
- The HITL reply mechanism (`reply_to_task`) already handles the
  "block and ask user" flow — no new plumbing needed

---

### 15.2 Message Passing → Containerized Architecture

**What:** Move from in-process method calls to explicit message passing,
enabling each component to run in its own container/process boundary.

**Why the inbox model is the foundation:**
`EventLog` + SSE is already an embryonic message bus. The inbox defines
the message schema. The attention model defines routing (by hitl_level and
event_type). What's missing is the boundary — today everything is in one
Python process communicating via method calls.

**Target architecture:**

```
┌─────────────────┐     messages      ┌──────────────────┐
│   MCP Server    │ ←──────────────── │  Scheduler       │
│  (gateway)      │ ──────────────→   │  (task runner)   │
└────────┬────────┘                   └────────┬─────────┘
         │ messages                            │ messages
         ↓                                     ↓
┌─────────────────┐                   ┌──────────────────┐
│  Memory Service │                   │  Agent Container │
│  (local only)   │                   │  (Ahman, etc.)   │
└─────────────────┘                   └──────────────────┘
         ↑                                     ↑
         └──────────── Message Bus ────────────┘
                    (EventLog → future: NATS/Redis)
```

**What enables the migration path:**
- All inter-component communication already goes through `broadcast()` /
  `EventLog` — replace in-process calls with message bus calls gradually
- `reply_to_task` defines the reply message schema — same schema works
  over a network message bus
- `task_id` as routing key — works identically in-process or across containers
- The `executor` field on `ToolDefinition` already supports `mcp_proxy` type —
  this is the seed of cross-boundary tool calls

**Language agnosticism:** once components communicate via messages, a Rust
scheduler or Go agent can join the bus without touching the Python codebase.

**Migration path (preserving today's code):**
1. Current: in-process method calls + EventLog as audit trail
2. Near-term: EventLog as primary communication, method calls as fallback
3. Long-term: Replace method calls with message bus; containers optional

---

### 15.3 Inbox → Dreaming → Knowledge Refinement

**What:** Interactions resolved via the inbox (question asked → context
provided → task resumed → result produced) are structured knowledge events.
They should flow into the dreaming pipeline and be distilled into reusable
knowledge for future assistants.

**Why this matters:**
Today dreaming processes raw conversation text. Inbox interactions are richer:
- **Typed metadata**: who asked (source_role), what tool triggered it, what
  the resolution was
- **Outcome signal**: the task completed after the reply — the resolution worked
- **Reusability**: "When Ahman encountered X while doing Y, the answer was Z"
  is more useful than reconstructing that from raw text

**Data flow:**

```
Inbox interaction resolves:
  task_waiting_for_input  → reply_to_task(reply) → task_completed
         ↓
EventLog has both events with same task_id and timestamps
         ↓
Dreaming "inbox stage" (new pipeline stage):
  - pairs waiting_for_input + task_completed events by task_id
  - extracts: role, question, context at time, resolution, outcome
  - produces: structured "resolved interaction" knowledge unit
         ↓
Archival memory: "interaction://ahman_scan_001"
  {
    "type": "resolved_interaction",
    "role": "ahman",
    "problem": "which subnet should I scan?",
    "context": "weekly security review, home network",
    "resolution": "scan 10.0.0.0/24",
    "outcome": "completed — found 3 open ports",
    "refined_at": "2026-03-20T03:00:00"   ← from nightly dreaming
  }
         ↓
search_memory("subnet scanning") → surfaces this as future context
```

**Why dreaming (not immediate):**
Raw interactions are noisy — failed attempts, corrections, rephrasing. The
dreaming pipeline's LLM can identify the resolved final form and strip noise.
Immediate storage would preserve confusion alongside resolution.

**Implementation requirements (preserving this path today):**
- EventLog must store `task_id` on both the question and completion events —
  already the case
- Dreaming pipeline needs a new optional stage that receives EventLog events
  (or a filtered subset) alongside conversation history
- The distilled output uses the same archive format — no new storage layer
- `search_memory(types=["conversations"])` already searches archival — refined
  interactions land there automatically

---

### 15.4 How These Three Connect

These are not independent features — they form a coherent whole:

```
Policy Agent       monitors   →  Inbox (event stream)
                   blocks     →  Dangerous events before execution
                   records    →  Policy decisions to EventLog

Message Bus        carries    →  All inter-component communication
                   enables    →  Container boundaries (optional)
                   foundation →  Inbox, Attention, EventLog

Inbox → Dream      captures   →  Resolved interactions
                   refines    →  Via dreaming pipeline
                   stores     →  In archival memory for future use
                   grows      →  The assistant's institutional knowledge
```

The inbox model is the architectural spine. Policy, distribution, and
knowledge refinement all attach to it without requiring the spine to change.

---

## 16. Coding Agent Layer Separation

This section captures the architectural reasoning for how external coding agents
(OpenCode, Claude Code) integrate with MoJoAssistant. The boundary was decided
deliberately — future changes should preserve it.

---

### 16.1 Three-tier model

```
┌─────────────────────────────────────────────────────────┐
│  Tier 1: Lifecycle — agent hub (MoJo MCP)               │
│  start / stop / status / list                           │
│  Knows: process lifecycle, config. Knows nothing about  │
│  sessions, messages, or permissions.                    │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│  Tier 2: API Client — coding-agent-mcp-tool submodule   │
│  OpenCodeBackend / ClaudeCodeBackend                    │
│  Knows: every HTTP endpoint, SSE stream format,         │
│  permission event schema, request/response format.      │
│  Does NOT know: HITL inboxes, task IDs, MoJo events.   │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│  Tier 3: Orchestration — CodingAgentExecutor (MoJo)     │
│  Runs the role's local LLM (e.g. Popo on qwen3.5)      │
│  Calls submodule methods as tools                       │
│  Routes permission requests → HITL inbox                │
│  Routes HITL replies → submodule respond_to_permission  │
└─────────────────────────────────────────────────────────┘
```

**Rule:** each tier communicates only with the tier directly below it.
The lifecycle tier never calls session APIs. The submodule never touches
the event log. The executor bridges them — it knows both sides but owns neither.

---

### 16.2 Why the API client lives in the submodule

The `coding-agent-mcp-tool` submodule is an independently usable package.
Someone could use `OpenCodeBackend` without MoJoAssistant. Keeping all OpenCode
API knowledge there (endpoints, SSE format, permission schema, model switching)
means:

- The submodule is the single source of truth for OpenCode compatibility
- MoJoAssistant never hard-codes OpenCode API paths or event types
- When OpenCode changes its API, only the submodule changes
- `ClaudeCodeBackend` slots into the same interface without touching MoJo

**What belongs in the submodule:**

```python
# Session management
create_session(), list_sessions(), get_session(), delete_session()
send_message(session_id, content)
get_messages(session_id)

# Permission bridge (OpenCode API knowledge only)
subscribe_permissions(session_id) -> AsyncIterator[dict]
  # streams /event SSE, yields EventPermissionUpdated for this session

respond_to_permission(session_id, permission_id, response)
  # POST /session/{id}/permissions/{permissionID}
  # response: "once" | "always" | "reject"

# Model / config
health(), llm_list_models(), llm_set_model(model)
```

---

### 16.3 Why HITL routing lives in MoJoAssistant

The permission approval flow is:

```
OpenCode emits EventPermissionUpdated (via SSE /event stream)
      ↓
submodule.subscribe_permissions() yields the permission dict
      ↓
CodingAgentExecutor (MoJo) receives the permission
      ↓
Writes task_waiting_for_input event to EventLog (hitl_level = 4)
  → surfaces in get_context() attention.blocking
  → user sees it in Claude Desktop
      ↓
User calls reply_to_task(task_id="popo_perm_<id>", reply="approve")
      ↓
CodingAgentExecutor maps reply → "once" | "always" | "reject"
      ↓
Calls submodule.respond_to_permission(session_id, permission_id, response)
      ↓
OpenCode unblocks and continues
```

The HITL inbox, EventLog, and attention system are MoJo internals. The submodule
has no concept of them and should never gain one. The executor is the bridge.

---

### 16.4 Role architecture — Popo as an example

Popo is not OpenCode's model pretending to be a character. The layers are:

```
qwen3.5-35b-a3b (local LLM, via LMStudio)
    ↑ system prompt: Popo persona
    ↑ task: "add tests to auth.py"
    |
CodingAgentExecutor
    | calls
    ↓
OpenCodeBackend.send_message(session_id, ...)   ← Popo's instructions to OpenCode
OpenCodeBackend.subscribe_permissions(...)      ← Popo waiting on permission events
OpenCodeBackend.respond_to_permission(...)      ← Popo forwarding user decisions
```

The local LLM is the **thinking layer** — it reads Popo's system prompt,
understands the task, decides what to ask OpenCode to do, and interprets results.

OpenCode is the **execution layer** — it has shell access, can read/write files,
run tests. It receives instructions from Popo and executes them.

MoJo scheduler is the **orchestration layer** — it starts the executor, manages
the task lifecycle, handles the HITL inbox.

**What this means for model config:**
- `role.model_preference` → local LLM resource ID (e.g. `lmstudio_qwen35`)
- `role.backend_type` → coding agent type (`"opencode"`)
- `role.server_id` → which OpenCode server instance to use (`null` = default)
- OpenCode's own model setting is separate — it is not the role's model

---

### 16.5 Sandbox design

Each role gets an isolated git worktree, not a session parameter. OpenCode
sessions always use the project's `base_dir` — there is no per-session directory
override via the API.

```
~/.memory/opencode-sandboxes/<project-slug>/<role-id>-work/
    ← git worktree add <path> (created before session start)
    ← OpenCode server started with this as its project dir
    ← role's session always targets this server instance
```

**Why worktrees instead of copies:** worktrees share git history with the main
repo. The role's changes are visible as a branch diff. Merging back is a normal
git operation. Copies would require manual diffing.

---

### 16.6 File map additions (coding agent layer)

| Concern | File |
|---------|------|
| OpenCode HTTP client, session API, SSE permission bridge | `submodules/coding-agent-mcp-tool/src/coding_agent_mcp/backends/opencode.py` |
| Backend registry + base class | `submodules/coding-agent-mcp-tool/src/coding_agent_mcp/backends/` |
| Coding agent lifecycle (start/stop/status) | `app/mcp/agents/` (existing agent_manager) |
| CodingAgentExecutor (role LLM loop driving a MAP backend) | `app/scheduler/coding_agent_executor.py` |
| Role config with executor + backend fields | `config/roles/<role>.json` |
| Sandbox worktree paths | `app/config/paths.py` (`OPENCODE_SANDBOXES_DIR`) |

---

## 17. MoJo Agent Protocol (MAP)

This section captures the vision for a universal agent integration standard.
It exists to prevent MoJo from accumulating ad-hoc plugins for every new agent
that appears. Read this before building any new backend.

---

### 17.1 The problem it solves

Every external agent (OpenCode, ZeroClaw, DeerFlow, aider, browser-use, ...)
has a different API, CLI, or UI. Without a standard, each new agent requires
a new backend in the `coding-agent-mcp-tool` submodule AND changes to MoJo's
executor. The cost grows linearly with the number of agents.

**MAP inverts this:** define a small standard interface once. New agents either
implement it natively, or get a thin shim. MoJo never changes for a new agent.

---

### 17.2 The three interaction classes

Agents fall into three interaction classes based on how they are driven:

```
Class 1: HTTP agents
  Native:  agent already speaks MAP over HTTP (OpenCode is the reference)
  Shimmed: agent has its own HTTP API; a shim translates it to MAP

Class 2: Subprocess agents
  Agent is a CLI tool (aider, goose, claude --print)
  A subprocess shim wraps stdin/stdout as MAP

Class 3: GUI/Visual agents
  Agent has no API — it runs in a terminal or browser
  A visual shim reads the screen (tmux capture-pane, browser screenshot)
  and drives it (tmux send-keys, browser automation)
  Requires a multimodal LLM to interpret screen content
```

**Model requirements differ by class:**

| Class | LLM requirement | Examples |
|-------|----------------|---------|
| HTTP (native/shimmed) | Any — local or API | OpenCode, ZeroClaw, DeerFlow |
| Subprocess | Strong instruction-follower | aider, goose, claude --print |
| GUI/Visual | Multimodal — must understand screens | browser-use, tmux agents |

The role config's `agent_class` field tells the executor which bridge to use.

---

### 17.3 The MAP HTTP interface (6 endpoints)

This is the minimal interface any HTTP agent must expose (or have exposed via
a shim) to integrate with MoJo. OpenCode implements this natively.

```
POST   /session
  → Create a new session
  → Returns: { "id": "<session_id>", ... }

DELETE /session/{id}
  → End and clean up a session

POST   /session/{id}/message
  → Send a message/instruction; wait for agent response
  → Body:    { "parts": [{ "type": "text", "text": "<instruction>" }] }
  → Returns: the completed message object

GET    /session/{id}/message
  → Full message history for the session
  → Returns: list of message objects

GET    /event
  → SSE stream of all session events
  → Relevant event types:
      EventPermissionUpdated  — agent needs user approval to proceed
      EventPermissionReplied  — user responded to a permission
      EventMessageUpdated     — message content / tool call progress
      EventSessionUpdated     — session state changed

POST   /session/{id}/permissions/{permissionId}
  → Respond to a pending permission request
  → Body:    { "response": "once" | "always" | "reject" }
```

**Why these 6?** They cover the complete lifecycle: create → instruct → observe
→ approve → read history → end. Every class of agent work maps onto these.

---

### 17.4 The shim pattern

A shim is a small adapter that translates an agent's native interface to MAP.
Shims follow three rules:

1. **Shims live outside MoJo.** They belong in the agent's own repo, in
   `coding-agent-mcp-tool`, or in a future `mojo-agent-adapters` repo.
   MoJo never imports agent-specific code directly.

2. **Shims are thin.** A shim should have no opinion about the task being
   done. It translates requests and events — nothing more.

3. **MoJo only ever calls MAP.** `CodingAgentExecutor` calls
   `backend.send_message()`, `backend.subscribe_permissions()`, etc.
   It does not know or care whether the backend is OpenCode native,
   a ZeroClaw shim, or a subprocess adapter.

**Example shim targets:**

| Agent | Native interface | Shim approach |
|-------|-----------------|---------------|
| OpenCode | HTTP (MAP native) | No shim needed |
| ZeroClaw | Webhook gateway (port 42617) | HTTP shim: translate webhook ↔ MAP |
| DeerFlow | LangGraph server (port 2024) | HTTP shim: LangGraph API ↔ MAP |
| aider | CLI subprocess | Subprocess shim: stdin/stdout ↔ MAP |
| browser-use | Python library | HTTP shim: expose as MAP server |
| tmux agent | Terminal screen | GUI shim: capture-pane + visual LLM ↔ MAP |

---

### 17.5 Role config fields for agent class

```json
{
  "id": "popo",
  "executor": "coding_agent",
  "backend_type": "opencode",
  "agent_class": "http_native",
  "server_id": "git@github.com:...",

  "agent_class_options": {
    "http_native": {},
    "http_shimmed": { "shim_url": "http://localhost:8080" },
    "subprocess": { "command": "aider", "args": ["--no-auto-commits"] },
    "gui": { "tmux_session": "aider-work", "screenshot_interval_ms": 500 }
  }
}
```

`agent_class` defaults to `http_native` — backward compatible with the current
Popo setup. Other classes are not yet implemented; this field reserves the
design space.

---

### 17.6 Why this matters for ZeroClaw and DeerFlow

**ZeroClaw** is a general autonomous task agent ("workforce replacement") —
strong general LLM, tool use, sandboxed execution. Best fit: a role that
handles broad work tasks (not just coding). Integration path: HTTP shim
translating ZeroClaw's webhook gateway to MAP. ZeroClaw's allowlist-based
permissions map cleanly to the MAP permission endpoints.

**DeerFlow** is a research orchestration platform — parallel sub-agents, web
search, scientific paper access, strong thinking model. Best fit: a role like
Ahman that runs deep research tasks. Integration path: HTTP shim translating
DeerFlow's LangGraph server (port 2024) to MAP. DeerFlow's async task model
maps onto MAP's SSE stream.

Both need shims, not new MoJo executors. The `CodingAgentExecutor` (renamed
`AgentExecutor` eventually) drives them identically — different backends,
same loop.

---

### 17.7 What MAP is NOT

MAP is not MCP (Model Context Protocol). MCP is about tools exposed TO a model.
MAP is about tasks delegated TO an agent. They are complementary:

```
MCP:  MoJo → offers tools → LLM uses them
MAP:  MoJo → delegates tasks → Agent executes them
```

MAP is also not a general agent communication standard like A2A (Agent-to-Agent).
It is deliberately minimal — just enough to let MoJo orchestrate external
agents without coupling to their internals.

---

### 17.8 Evolution path

```
Current:  OpenCode (MAP native) via CodingAgentExecutor
Near:     ZeroClaw shim, DeerFlow shim — same executor, different backends
Medium:   SubprocessAdapter — CLI agents via stdin/stdout bridge
Long:     GUIAdapter — visual agents via tmux/browser-use + multimodal LLM
Ultimate: Rename CodingAgentExecutor → AgentExecutor
          Any role with executor=agent runs any MAP-compatible backend
```

The rename from `CodingAgentExecutor` to `AgentExecutor` is the milestone that
marks MAP as production-ready: when the executor no longer assumes "coding" as
the task type.

**MAP is not coding-specific.** The protocol covers any agent type — coding,
research, general task execution, GUI automation. The executor drives a role's
local LLM (the thinking layer) which delegates work to a MAP-compatible backend.
The backend can be a coding agent, a research orchestrator, a general-purpose
task runner, or a browser automation agent. The local LLM and the MAP protocol
don't care.

---

## 18. Agent Integration Analysis Log

Pre-integration analysis for agents not yet implemented. Purpose: avoid
repeating research when implementation time comes. Each entry captures the
API shape, MAP fit assessment, and the blockers that deferred it.

---

### 18.1 ZeroClaw

**Researched:** 2026-03-20
**Status:** Deferred — wrong executor, thick shim
**Revisit when:** `CodingAgentExecutor` → `AgentExecutor` generalisation is done

**What it is:**
Rust single-binary general autonomous task agent. "Workforce replacement"
class — strong general LLM, built-in memory, tool use, scheduling. 28K GitHub
stars, v0.5.1. Production-grade: <5 MB RAM, <10ms startup, single binary,
runs on ARM/x86/RISC-V.

**HTTP API surface (gateway mode, default port 42617):**

```
# Public (no auth)
GET  /health                 → server health + component snapshot
GET  /metrics                → Prometheus text format

# Authentication
POST /pair                   → exchange 6-digit pairing code for bearer token
                               X-Pairing-Code: 123456 → {"token": "..."}

# Main processing
POST /webhook                → send message to agent, get response
                               Body:     {"message": "user query"}
                               Response: {"response": "...", "model": "..."}
                               Auth:     Authorization: Bearer <token>
                               Idempotency: X-Idempotency-Key: <uuid>

# Runtime management
GET  /api/status             → provider, model, uptime, gateway port
GET  /api/config             → current config (secrets masked)
PUT  /api/config             → update config
GET  /api/tools              → list registered tools
GET  /api/cron               → list scheduled jobs
POST /api/cron               → add cron job
DELETE /api/cron/:id         → remove cron job
GET  /api/memory?query=      → semantic search over memory (70% vector + 30% FTS5)
POST /api/memory             → store memory entry
DELETE /api/memory/:key      → delete memory entry

# Streaming
GET  /events                 → SSE stream: agent progress, tool execution, costs
GET  /ws/chat                → WebSocket: bidirectional streaming chat
                               Client: {"content": "message"}
                               Server: {"role": "assistant", "content": "chunk..."}
                               Done:   {"type": "done", "full_response": "..."}
```

**Authentication:**
Bearer tokens via pairing flow (6-digit one-time code → token). SHA-256
hashed at rest. 5 failure lockout. Rate limited (10 req/min on /pair,
60 req/min on /webhook). Configurable via TOML.

**MAP fit assessment:**

| MAP endpoint | ZeroClaw equivalent | Fit |
|---|---|---|
| `POST /session` | None — stateless, no sessions | ✗ Must synthesize |
| `POST /session/{id}/message` | `POST /webhook {"message": "..."}` | ~50% — no session context |
| `GET /session/{id}/message` | `GET /api/memory?query=session_{id}` | ✗ Indirect, lossy |
| `GET /event` (SSE) | `GET /events` | ✓ Exists |
| `POST /session/{id}/permissions/{id}` | None — allowlist-based, no runtime prompts | ✗ N/A |

**Why the shim would be thick (not thin):**

1. **No sessions.** ZeroClaw is stateless. A shim would have to synthesize
   sessions by injecting a session ID into each message text
   (`"[session abc123] actual instruction"`) and filtering `/events` by that
   prefix. Fragile.

2. **No message history endpoint.** `GET /session/{id}/message` would have
   to be reconstructed from `/api/memory?query=session_{id}`. ZeroClaw stores
   what its LLM remembers — not a guaranteed ordered transcript. The shim
   would be guessing at history.

3. **No permission prompts.** ZeroClaw uses allowlists, not runtime permission
   dialogs. The MAP permission bridge has nothing to bridge. Any tool ZeroClaw
   is configured to use, it uses — silently. This is fine for many use cases
   but means the HITL permission flow doesn't apply.

4. **Wrong executor.** ZeroClaw is a general autonomous task agent, not a
   coding agent. Driving it with `CodingAgentExecutor` is the wrong frame.
   It needs `AgentExecutor` (the generalised executor) which doesn't exist yet.
   `CodingAgentExecutor` injects coding-specific context into the system prompt
   and expects file/code output.

**What ZeroClaw is good for in MoJo:**
A role that handles general "do this work" tasks — drafting, research synthesis,
multi-step planning, tool-assisted execution. Not file-editing coding tasks.
The local LLM (thinking layer) would describe a high-level goal; ZeroClaw's own
LLM + tools would execute it.

**Integration path when ready:**
1. Wait for `AgentExecutor` generalisation
2. Build a thin session-synthesis shim:
   - Session = UUID injected as message prefix
   - `POST /webhook` with `"[{session_id}] {instruction}"` body
   - `/events` SSE filtered by session_id prefix
   - Accept that permission bridge is N/A (allowlist model)
3. Role config: `agent_class: "http_shimmed"`, `shim_url: "http://127.0.0.1:42617"`
4. Memory history: use `/api/memory?query={session_id}` as best-effort only

**Installation:** `brew install zeroclaw` or single-binary download

---

### 18.2 DeerFlow

**Researched:** 2026-03-20
**Status:** Deferred — needs `AgentExecutor`, fits research role not coding role
**Revisit when:** `AgentExecutor` done + Ahman needs a research execution backend

**What it is:**
Python 3.12+ multi-agent research orchestration platform by ByteDance.
Parallel sub-agent spawning, web search, scientific paper access (PubMed etc.),
Markdown-based skill system, sandboxed Docker execution, persistent memory.
Strong thinking model recommended. LangGraph-based internally.

**API surface:**

```
HTTP Gateway:      port 8001
LangGraph Server:  port 2024  (standard LangGraph API — well-documented)
Web UI:            port 2026
Messaging:         Telegram long-poll, Slack Socket Mode, Feishu WebSocket
```

**MAP fit:**
LangGraph Server (port 2024) has a standard REST API for running graphs
(threads = sessions, runs = messages). Fit is better than ZeroClaw:
- Sessions → LangGraph threads ✓
- Messages → LangGraph runs ✓
- SSE → LangGraph streaming ✓
- Permissions → not applicable (research tasks, no filesystem prompts)

Shim would translate LangGraph thread/run API → MAP session/message API.
Should be thin once `AgentExecutor` exists.

**Best role fit:**
Research roles (Ahman-equivalent) — complex web research, scientific literature,
multi-step content synthesis. Wrong for coding tasks.

**Integration path when ready:**
1. Wait for `AgentExecutor`
2. Build LangGraph→MAP shim (thread=session, run=message, LangGraph stream=SSE)
3. Model: strong thinking model (qwen3-30b+ or similar) for the local LLM layer
4. DeerFlow's own agents handle the actual research execution

---

### 18.3 Claude Code (Remote Control)

**Researched:** 2026-03-20
**Status:** Not applicable as HTTP backend
**Alternative:** tmux/GUI class agent (future)

**What it is:**
Claude Code with `--remote-control` flag connects a local `claude` process to
claude.ai/code (browser) or Claude mobile app. It is a **UI relay for humans**,
not a programmatic API.

**Why MAP doesn't apply:**
- No HTTP endpoints — claude makes outbound HTTPS calls to Anthropic, receives
  work via polling. No inbound REST API.
- Auth: claude.ai OAuth only (no API key). User must be logged in interactively.
- Permissions: shown in browser/terminal, responded to by human.
- No SSE stream accessible programmatically.

**Why subprocess doesn't apply cleanly:**
`claude --print "task"` runs once and exits. Permission prompts appear on
stderr as interactive prompts — parsing these reliably is fragile.

**Correct integration class:** GUI/Visual (Class 3)
- Run `claude` in a tmux pane
- `tmux capture-pane -p` to read output
- `tmux send-keys` to send messages and respond to prompts
- Visual LLM to parse screen content when output is complex
- Requires multimodal LLM in the thinking layer

**When to revisit:** When `GUIAdapter` (tmux shim) is being built.
Claude Code would be a natural first target — well-known output format,
predictable permission prompt patterns.

---

## 19. Generic Coding Agent — v1.3 Backlog

**Status:** Deferred from v1.2.2. Architecture is in place; items below are
polish and extensibility work. Higher-priority features ship first.

**What landed in v1.2.2:**
- `AgentBackend` ABC + `BackendRegistry` with pluggable `backend_type`
- `OpenCodeBackend` (HTTP REST, full HITL permission bridge, tested)
- `ClaudeCodeBackend` (stdio subprocess, `--resume` session continuity, yolo mode)
- `CodingAgentExecutor` renamed to generic terms (`agent_session_id`,
  `agent_send_message`, `agent_get_messages`, etc.)
- Config file renamed: `opencode-mcp-tool-servers.json` → `coding-agent-mcp-tool-servers.json`

**v1.3 TODO — three gaps to close:**

### 19.1 — `_auto_start_backend` should be backend-aware

Currently always calls `OpenCodeManager.start_project(server_id)`.

Fix: branch on `backend.backend_type`:
- `opencode` → existing OpenCodeManager flow
- `claude_code` → no-op (binary is always present; `health()` already validates)
- unknown → log warning, skip

### 19.2 — Rename `opencode_*` actions in `tools.py` to `backend_*`

`_execute_opencode_backend_action()` and its actions (`opencode_servers`,
`opencode_health`, `opencode_session_*`) work for all backends but are named
OpenCode-specific. Rename to `backend_servers`, `backend_health`, etc.

Breaking change — coordinate with any existing assistant prompts that use these names.

### 19.3 — Claude Code HITL (permission bridge)

Currently `--dangerously-skip-permissions` (yolo mode).

For real HITL, Claude Code would need:
- Run with `--permission-mode default` (no bypass)
- Stream output via `--output-format stream-json --verbose`
- Parse `type: "tool_use"` + permission prompt events from the stream
- Surface via MoJo `waiting_for_input` inbox
- Write user reply to process stdin (or restart with `--resume` + explicit allow)

This requires the `input_bridge` translation defined in `AGENT_PROFILE.md §Claude Code`.
Verify the stream-json format reliably surfaces permission requests before building.

### 19.4 — User-facing backend registration

Currently adding a new backend (e.g. a new OpenCode server, a Claude Code
project, or a future "Crush" coding agent) requires manually editing
`coding-agent-mcp-tool-servers.json`.

Target UX: MoJo assistant can register a new backend via:
```
agent(action='add_backend', backend_type='claude_code', working_dir='/path/to/project', id='my-project')
```

Writes a new entry to the servers JSON and hot-reloads the registry.
Also enables: `agent(action='add_backend', backend_type='opencode', url='http://...', id='...')`

### 19.5 — Fix dead `backend_type` field in role JSON

`popo.json` has `"backend_type": "opencode"` which `CodingAgentExecutor` never reads.
Routing is purely via `server_id` → servers JSON entry → `backend_type` there.

Options:
- Remove `backend_type` from role JSON (clean)
- Or read it in `_get_backend` as a validation hint (belt + suspenders)

### 19.6 — Move session ownership to the coding-agent layer ⚠️ design boundary

**Problem discovered 2026-03-21:**
`agent_session_id` is stored in MoJo's `TaskConfig` so `CodingAgentExecutor` can
resume an existing coding agent session. This is a design boundary violation.

MoJo oversees many roles and agents simultaneously. It cannot carry per-agent
ephemeral state (session tokens, resume handles, partial results) in its own
scheduler config — that couples MoJo to implementation details of each backend.

When we tried to schedule a follow-up Popo task, there was no way to pass the
session ID through the MCP tool because it should not exist at that layer.

**The boundary:**

| MoJo's responsibility | Coding agent's responsibility |
|---|---|
| Deliver a goal + role to execute | Decide whether to resume or start fresh |
| Route HITL questions to inbox | Manage session lifecycle (create/resume/close) |
| Classify events by attention level | Track permission state, retry context |
| Assign LLM resource | Translate goal → backend API calls |

**Target design:**
`coding-agent-mcp-tool` maintains its own session store, keyed by `(role_id, task_id)`
or a stable goal hash. When `CodingAgentExecutor.execute(task)` is called, it asks
the backend manager: "do you have an active session for this role + task?" The manager
returns an existing session or creates a new one. MoJo never sees session IDs.

**Scope of change (v1.3):**
- `coding-agent-mcp-tool`: add `SessionStore` (file-backed dict: `role_id+task_id → session_id`)
- `BackendRegistry` / `AgentBackend`: `get_or_create_session(role_id, task_id, working_dir)` → session_id
- `CodingAgentExecutor`: remove `agent_session_id` from `task.config` reads/writes; call registry instead
- `TaskConfig` (scheduler models): remove `agent_session_id` field
- Same principle applies to `agent_pending_permission_id` / `agent_pending_permission_directory`
  — permission state is agent-internal, not scheduler state

**Note:** `agent_session_id` is currently stored in `task.config` at
`coding_agent_executor.py:189–200`. That is the primary site to refactor.

---

## 20. Resource Pool and Tool Registry — Unified Catalog Architecture

**Discovered 2026-03-22.** Both the resource pool and the tool registry have the same
architectural problem: they are fragmented across multiple config files and partially
hardcoded into role profiles. The right design treats both as **self-describing catalogs**
with exactly two layers: system default + user personal.

---

### 20.1 — Resource Pool: two layers, no hardcoding in roles

**Current problems:**
- `llm_config.json` (project) + `resource_pool_config.json` (project) + `~/.memory/config/llm_config.json` (personal) — three config surfaces for the same concern
- `preferred_resource_id` is hardcoded in role JSON (`popo.json`) — couples the role persona to a specific infrastructure account
- The scheduler MCP tool has no `preferred_resource_id` parameter — users cannot specify a resource from the client at all; requests are silently dropped and fall through to dynamic selection

**Target design:**
```
System default layer   config/resource_pool.json   — shipped defaults, no API keys
User personal layer    ~/.memory/config/resource_pool.json   — user's accounts, keys, overrides
```

One file name, two layers merged by `load_layered_json_config`. Roles declare
**capability requirements** (tier, speed class, context size), not a specific resource ID.
The pool selects the best match from what the user has configured.

```json
// Role declares what it needs — not which account to use
"resource_requirements": {
  "tier": ["free_api", "free"],
  "min_context_tokens": 32000
}
```

The user's personal layer adds their own accounts (Gemini, OpenRouter, etc.) and the
pool auto-discovers them. No role JSON changes needed when the user adds a new API key.

**Migration:**
- Merge `llm_config.json` and `resource_pool_config.json` into `resource_pool.json`
- Remove `preferred_resource_id` from role JSON; replace with `resource_requirements`
- Rename the runtime override to `~/.memory/config/resource_pool.json`
- Keep backward compat: `llm_config.json` still loaded if `resource_pool.json` absent

---

### 20.2 — Tool Registry: pre-defined catalog + user custom tools

**Current problems:**
- Tools are loaded from `config.get("available_tools", ["memory_search"])` in the task config — every task must enumerate its tools or get the bare minimum
- `ask_user` is force-injected by the executor but not documented in role profiles
- Adding a new tool requires editing executor code or every task config that needs it
- No way for an agent to discover what tools are available to it at runtime

**Target design — same pattern as resource pool:**
```
System catalog    config/tool_catalog.json       — pre-defined tools (bash, web_search, memory_search, file ops, ...)
User extensions   ~/.memory/config/tool_catalog.json  — user's custom scripts, MCP proxies, local APIs
```

Tool entries declare capability category (`system`, `web`, `file`, `memory`, `custom`),
executor type (`builtin`, `shell`, `mcp_proxy`), and access level.

Roles declare **tool access categories**, not individual tool names:
```json
"tool_access": ["memory", "web", "file"]
```

At task start, the executor builds the available tool set from the catalog filtered by
the role's `tool_access`. A `list_tools()` meta-tool is always injected, letting the agent
discover its full tool set at runtime without it being enumerated in the system prompt.

```
Agent start:  tools = [list_tools, ask_user]  +  role default category tools
Agent calls:  list_tools()  →  {"available": ["web_search", "bash", "memory_search", ...]}
Next iter:    executor expands tool list dynamically based on agent's discovery
```

User adds a custom tool by dropping a JSON entry in `~/.memory/config/tool_catalog.json`:
```json
{
  "my_script": {
    "category": "custom",
    "executor": {"type": "shell", "command": "python3 ~/.memory/scripts/my_tool.py"},
    "description": "Runs my local analysis script"
  }
}
```

No code changes, no prompt updates — the tool is immediately available to any role
that has `"custom"` in its `tool_access`.

**Migration path:**
- `dynamic_tool_registry.py` becomes the runtime loader for the two-layer catalog
- `available_tools` in task config remains as an explicit override (still works)
- `ask_user` and `list_tools` are always present regardless of role config
- Existing tool definitions migrate to `config/tool_catalog.json` entries


---

## 21. Character → Role → Goal: The Full Agent Protocol Stack

> **Status**: Design — target v1.2.4+
> **Problem**: Tasks are scheduled with inline system prompts, bypassing the role
> system entirely. Characters, roles, and execution goals are conflated in a single
> flat task config. There is no validation that a role_id is used, no urgency/importance
> routing, and no structured way to derive agent behavior from NineChapter data.

---

### 21.1 The Three Layers

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: CHARACTER  (NineChapter)                       │
│  Who the agent IS — personality, values, emotional style │
│  Source: ~/.memory/roles/{id}.json → dimensions{}        │
├─────────────────────────────────────────────────────────┤
│  Layer 2: ROLE  (User Assignment)                        │
│  What the agent DOES — intent, tools, resource class     │
│  Source: ~/.memory/roles/{id}.json → tool_access,        │
│           resource_requirements, behavior_rules          │
├─────────────────────────────────────────────────────────┤
│  Layer 3: GOAL  (MoJo Execution)                         │
│  The specific task — resource selection, iteration       │
│  budget, urgency/importance weighting, HITL conditions   │
│  Source: scheduler task config                           │
└─────────────────────────────────────────────────────────┘
```

Each layer has a single responsibility. A task scheduled with `role_id: "rebecca"`
should need **only** `goal` + `role_id` — everything else resolves from the layers above.

---

### 21.2 Layer 1 — Character (NineChapter)

NineChapter defines **who the agent is**. The five dimensions map directly to
prompt sections that the executor assembles automatically:

| Dimension | nine_chapter_score weight | Prompt section generated |
|---|---|---|
| `core_values` | 25% | `## Values` |
| `emotional_reaction` | 20% | `## How you respond emotionally` |
| `cognitive_style` | 25% | `## How you think` |
| `social_orientation` | 15% | `## How you communicate` |
| `adaptability` | 15% | `## How you handle change and uncertainty` |

The `nine_chapter_score` is the **weighted average** of dimension scores using
the weights above. It is not set manually — it is derived from the dimensions.

**Validation rule**: If `nine_chapter_score` diverges from the weighted average
by more than 5 points, `config doctor` flags it as a calibration warning.

**Future**: `AgenticExecutor` assembles the character prompt from dimensions
rather than using the raw `system_prompt` string. The `system_prompt` becomes
an optional override for role-specific behavior (Layer 2) appended after the
character prompt.

---

### 21.3 Layer 2 — Role (User Assignment)

The role maps a character's intent to a concrete set of capabilities and
operating rules. It answers: **given who this agent is, what are they here to do?**

**Role schema additions (v1.2.4 target):**

```json
{
  "id": "rebecca",
  "name": "Rebecca",
  "archetype": "empathetic_connector",
  "nine_chapter_score": 95,
  "dimensions": { ... },

  "purpose": "Guide learners through thorough, evidence-based exploration...",

  "tool_access": ["web", "memory"],
  "resource_requirements": {
    "tier": ["free_api", "free"],
    "min_context": 65536
  },

  "behavior_rules": {
    "exhausts_tools_before_asking": true,
    "tool_failure_protocol": "surface_options",
    "max_ask_user_per_task": 3,
    "escalation_style": "concrete_options"
  },

  "hitl_conditions": {
    "always_on_tool_failure": false,
    "always_on_blocked": true,
    "surface_partial_results": true
  }
}
```

**`behavior_rules`** encodes role-level operating policies:
- `exhausts_tools_before_asking`: must try all available tools before surfacing
  a question (researcher = true, assistant = false)
- `tool_failure_protocol`: `"surface_options"` | `"skip_and_continue"` | `"fail"`
- `escalation_style`: `"concrete_options"` = ask_user always presents choices

**`hitl_conditions`** defines when the role raises to the inbox:
- `always_on_blocked`: any tool failure that blocks progress → inbox
- `surface_partial_results`: completed partial work is surfaced, not discarded

---

### 21.4 Layer 3 — Goal (MoJo Execution)

The goal layer is pure execution context. It defines **this specific task**,
not the agent's general capabilities.

**Task config schema (v1.2.4 target):**

```json
{
  "task_id": "rebecca_research_001",
  "role_id": "rebecca",
  "goal": "Research AutoResearch projects and analyze applicability to MoJo dreaming",

  "urgency": 2,
  "importance": 4,

  "max_iterations": null,
  "resume_on_fail": true,
  "cron": null
}
```

**`role_id` is required** for `task_type=assistant`. Inline `system_prompt` in
task config is deprecated — character and behavior are resolved from the role.

**`urgency`** (1–5): How time-sensitive is this task?
- 1 = background, run when idle
- 3 = normal, run within the hour
- 5 = blocking, run immediately

**`importance`** (1–5): How critical is the outcome?
- 1 = nice to have
- 3 = affects ongoing work
- 5 = blocks a release or user action

---

### 21.5 Urgency × Importance → Resource and HITL Routing

The scheduler resolves resources and attention level from the urgency/importance matrix:

```
importance →    1          2          3          4          5
urgency ↓
1             noise      noise     digest     digest     alert
2             noise      digest    digest     alert      alert
3             digest     digest    alert      alert     blocking
4             digest     alert     alert     blocking   blocking
5             alert      alert    blocking   blocking   blocking
```

**Resource tier escalation:**

```
urgency × importance score = U × I
  ≤ 4   → free (local only)
  5–9   → free_api (OpenRouter / Gemini free tier)
 10–16  → free_api preferred, paid allowed if unavailable
 ≥ 20   → paid approved (requires prior resource_approve)
```

When `resource_requirements.tier` from the role conflicts with urgency×importance
escalation, **escalation wins** — a high-urgency task can always use a better
resource than the role's baseline.

---

### 21.6 Validation Protocol (config doctor + scheduler)

**At `role_create` / `role_update`:**
1. `nine_chapter_score` must be derivable from dimensions (±5 tolerance)
2. `tool_access` categories must all exist in `tool_catalog.json`
3. `resource_requirements.tier` must be valid tier strings
4. `behavior_rules` fields validated against known keys

**At `scheduler_add_task` (task_type=assistant):**
1. `role_id` is **required** — reject tasks without it (warn with clear message)
2. `role_id` must resolve to an existing role in `~/.memory/roles/`
3. `urgency` and `importance` default to 3 if not provided
4. Inline `system_prompt` in task config triggers a deprecation warning
5. `available_tools` in task config still accepted as explicit override but logs
   a notice that `tool_access` in the role is the preferred path

**At execution time (AgenticExecutor):**
1. Load role from `RoleManager().get(role_id)` — never from task config
2. Assemble system prompt: character (from dimensions) + role behavior
3. Resolve tools from `role.tool_access` → catalog → tool_defs
4. Resolve resource from `role.resource_requirements` escalated by urgency×importance
5. Apply `behavior_rules` to executor loop (e.g. `exhausts_tools_before_asking`)
6. Apply `hitl_conditions` for inbox routing

---

### 21.7 Resume and Raise Conditions

**Resume protocol:**
- `resume_on_fail: true` → on task failure, create a new task with
  `resume_from_task_id` pointing to the failed session
- The resumed task inherits `role_id`, `goal`, and session history
- Resumed tasks get the same urgency/importance as the original

**Raise conditions (inbox escalation):**
A task raises to the inbox (creates a `waiting_for_input` event) when:
1. `ask_user` is called explicitly (always)
2. A tool fails and `hitl_conditions.always_on_blocked = true`
3. `max_iterations` is reached without `FINAL_ANSWER`
4. Urgency×importance ≥ 12 and task is about to fail

The inbox event includes: `role_id`, `goal` summary, what was tried,
what blocked it, and concrete options for the user to choose from.

---

### 21.8 What This Fixes

| Problem | Root cause | Fix |
|---|---|---|
| Rebecca ran with wrong tools | task scheduled without `role_id` | `role_id` required; inline prompt deprecated |
| NineChapter score set arbitrarily | score not derived from dimensions | score = weighted average, doctor validates |
| Resource not respecting role | `preferred_resource_id` hardcoded | urgency×importance matrix selects tier |
| Tool failures silently looped | no `behavior_rules` | role declares `tool_failure_protocol` |
| Character updates don't apply to running tasks | system_prompt baked in at schedule time | executor always loads from role file |
| No urgency/importance concept | flat task priority only | `urgency` + `importance` fields + matrix |

---

## §22 Visual Agent Adaptor — Browser Use & Terminal Session Tools

**Status:** Design (v1.3 target)  
**Motivation:** `fetch_url` + `web_search` give agents plain text from the web.
Real research tasks increasingly require JavaScript-rendered pages, interactive
navigation, and terminal interaction. This section defines the architecture for
visual/interactive tools that let agents see and act on the world the way a
human operator would.

---

### 22.1 The Two Capabilities

```
┌─────────────────────────────────────────────────────────────────┐
│  Tool Category: "browser"                                       │
│                                                                 │
│  browser_open(url)          → loads page, returns snapshot     │
│  browser_action(action)     → click / type / scroll / submit   │
│  browser_screenshot()       → base64 PNG of current viewport   │
│  browser_get_text()         → rendered visible text (no HTML)  │
│  browser_close()            → release session                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Tool Category: "terminal"                                      │
│                                                                 │
│  terminal_exec(cmd)         → run command in persistent session │
│  terminal_read()            → read current screen buffer        │
│  terminal_send_keys(keys)   → send keystrokes (e.g. Ctrl+C)    │
│  terminal_new_session(name) → create named tmux session        │
│  terminal_close(name)       → destroy named session            │
└─────────────────────────────────────────────────────────────────┘
```

**Key difference from existing tools:**

| | `fetch_url` / `bash_exec` | `browser_*` / `terminal_*` |
|---|---|---|
| Rendering | Raw HTTP / raw stdout | Fully rendered (JS, ANSI) |
| State | Stateless per call | Persistent session across calls |
| Output type | Text only | Text + optional screenshot |
| Model requirement | Any | Vision-capable for screenshot path |

---

### 22.2 Tool Result Format — Visual Payload

Tool results today are `Dict[str, Any]` — plain JSON. Visual tools extend this
with an optional `visual` field:

```json
{
  "success": true,
  "text": "rendered visible text of the page or terminal buffer",
  "visual": {
    "type": "screenshot",
    "format": "png",
    "data": "<base64>",
    "width": 1280,
    "height": 720
  },
  "metadata": {
    "url": "https://...",
    "title": "Page title",
    "session_id": "browser-abc123"
  }
}
```

The `visual` field is **optional and model-gated**: the executor checks whether
the assigned LLM resource has `capabilities: ["vision"]` before including it.
Non-vision models receive only the `text` field — graceful degradation.

---

### 22.3 Model Capability Gating

Visual tool results must be routed to a vision-capable model. The executor
applies capability gating at two points:

**At tool-result assembly (AgenticExecutor):**
```python
def _format_tool_result(self, result: dict, resource: LLMResource) -> dict:
    if "vision" not in resource.capabilities:
        result = {k: v for k, v in result.items() if k != "visual"}
    return result
```

**At resource acquisition (ResourceManager.acquire_by_requirements):**
Roles that use `tool_access: ["browser"]` or `tool_access: ["terminal"]`
automatically inherit `capabilities: ["vision"]` in their effective requirements:

```json
{
  "resource_requirements": {
    "tier": ["free_api", "paid"],
    "min_context": 32768,
    "capabilities": ["vision"]
  },
  "tool_access": ["browser", "memory"]
}
```

If no vision-capable resource is available, the executor falls back to
text-only mode and logs a notice. The agent still runs — it just won't see
screenshots.

---

### 22.4 Browser Tool — Implementation Design

**Backend:** [Playwright](https://playwright.dev/python/) (async, handles
Chromium/Firefox/WebKit, first-class headless support).

**Session model:** one Playwright `Browser` instance per scheduler worker,
with per-task `BrowserContext` (isolated cookies/storage). Tasks share the
browser process but not sessions.

```
Scheduler worker
└── PlaywrightBrowserPool
    ├── BrowserContext [task-abc]  → Page (current)
    ├── BrowserContext [task-def]  → Page (current)
    └── ...
```

**Tool executor registration:**
```python
# dynamic_tool_registry.py — new builtin block
elif name == "browser_open":
    return await self._browser_open(args)
elif name == "browser_action":
    return await self._browser_action(args)
elif name == "browser_screenshot":
    return await self._browser_screenshot(args)
elif name == "browser_get_text":
    return await self._browser_get_text(args)
elif name == "browser_close":
    return await self._browser_close(args)
```

**`browser_open` result (vision model):**
```json
{
  "success": true,
  "text": "OpenAI — ChatGPT ...",
  "visual": { "type": "screenshot", "format": "png", "data": "...", ... },
  "metadata": { "url": "https://openai.com", "title": "OpenAI", "session_id": "ctx-123" }
}
```

**`browser_action` schema:**
```json
{
  "action": "click | type | scroll | press | navigate | back | forward",
  "selector": "CSS selector or text (for click/type)",
  "text": "text to type (for type action)",
  "key": "Enter | Escape | Tab | ... (for press action)",
  "delta_y": 500
}
```

---

### 22.5 Terminal Tool — Implementation Design

**Backend:** `asyncio` subprocess + `pexpect` or direct `pty` + tmux for
named persistent sessions. Each task that calls `terminal_new_session(name)`
gets a `tmux new-session -d -s <name>` instance. `terminal_exec` sends
commands via `tmux send-keys` and reads back via `tmux capture-pane`.

**ANSI rendering:** Terminal output contains ANSI escape sequences. Two output
modes:
1. **Raw ANSI** — passed as-is when the model receives `text` only (agents
   can parse colour codes for signal)
2. **Screenshot** (future) — render terminal to PNG via `ttyd` / `svg-term`
   for vision models

**Session lifecycle:**
- Created on first `terminal_exec` if no session exists (implicit creation)
- Named sessions persist across task iterations (state survives LLM turn)
- Session is destroyed on task completion or explicit `terminal_close`

**Security:** `terminal_exec` applies the same command whitelist as `bash_exec`
for `danger_level: medium` calls. Unrestricted shell access requires
`danger_level: high` + `requires_auth: true`.

---

### 22.6 Tool Catalog Additions

```json
{
  "browser_open":       { "category": "browser", "danger_level": "low" },
  "browser_action":     { "category": "browser", "danger_level": "medium" },
  "browser_screenshot": { "category": "browser", "danger_level": "low" },
  "browser_get_text":   { "category": "browser", "danger_level": "low" },
  "browser_close":      { "category": "browser", "danger_level": "low" },
  "terminal_exec":      { "category": "terminal", "danger_level": "medium" },
  "terminal_read":      { "category": "terminal", "danger_level": "low" },
  "terminal_send_keys": { "category": "terminal", "danger_level": "medium" },
  "terminal_new_session":{ "category": "terminal", "danger_level": "low" },
  "terminal_close":     { "category": "terminal", "danger_level": "low" }
}
```

Categories in `tool_catalog.json`:
```json
"browser":  { "description": "Headless browser — render pages, interact, screenshot" },
"terminal": { "description": "Persistent terminal sessions via tmux — run commands, read output" }
```

---

### 22.7 Role Examples

**Visual researcher role:**
```json
{
  "id": "visual_researcher",
  "tool_access": ["browser", "web", "memory"],
  "resource_requirements": {
    "tier": ["free_api", "paid"],
    "min_context": 65536,
    "capabilities": ["vision"]
  }
}
```

**DevOps agent role:**
```json
{
  "id": "devops_agent",
  "tool_access": ["terminal", "file", "memory"],
  "resource_requirements": {
    "tier": ["free_api", "paid"],
    "min_context": 32768,
    "capabilities": []
  }
}
```

**Full computer-use role (terminal + browser):**
```json
{
  "id": "computer_use",
  "tool_access": ["browser", "terminal", "file", "web", "memory"],
  "resource_requirements": {
    "tier": ["paid"],
    "min_context": 65536,
    "capabilities": ["vision"]
  }
}
```

---

### 22.8 Degradation Tiers

When the ideal resource is unavailable, the executor degrades gracefully:

```
Vision model available
  → Send screenshot + text in tool results (full visual mode)

No vision model, text model available
  → Send text only; skip screenshot field (text degraded mode)
  → Agent still works, loses visual context

No model available
  → Task waits for resource (existing resource pool retry logic)
```

The degradation tier is logged and surfaced in the task session metadata:
`"visual_mode": "full" | "text_only" | "unavailable"`.

---

### 22.9 Dependency Requirements

```
# For browser tools:
playwright>=1.40.0          # async browser automation
# Run once after install:
# playwright install chromium

# For terminal tools:
# tmux — system package (apt/brew install tmux)
# No additional Python deps; uses asyncio subprocess
```

Both are **optional** — the registry gracefully skips tool registration if
Playwright is not installed, and logs a clear startup notice:
```
[WARNING] browser tools disabled — install playwright: pip install playwright && playwright install chromium
[WARNING] terminal tools disabled — tmux not found: apt install tmux
```

---

### 22.10 Implementation Sequence (v1.3)

1. **Add `browser` + `terminal` categories to `tool_catalog.json`**
2. **Add `capabilities` field to `LLMResource`** ✓ (done in v1.2.3)
3. **Implement `PlaywrightBrowserPool`** in `app/scheduler/browser_pool.py`
4. **Implement `TerminalSessionPool`** in `app/scheduler/terminal_pool.py`
5. **Register browser/terminal builtins** in `_register_builtins()` (with
   graceful skip if deps missing)
6. **Add `_format_tool_result` capability gating** in `AgenticExecutor`
7. **Add `visual_mode` to task session metadata**
8. **Update `acquire_by_requirements`** to auto-add `vision` capability
   requirement when role uses `browser` tool_access
9. **Create `visual_researcher` and `devops_agent` roles**
10. **Update `config doctor`** to validate `capabilities` in resource pool

---

### 22.11 What This Unlocks

| Before | After |
|---|---|
| Agent reads raw HTML (often broken JS sites) | Agent sees rendered page like a human |
| Agent runs one-shot bash commands | Agent maintains a persistent shell session |
| Research limited to Google snippets + raw text | Agent navigates GitHub, docs sites, SPAs |
| No visual confirmation of tool actions | Agent can screenshot-verify its own actions |
| Terminal-based tools require human to relay output | Agent reads tmux buffer directly |

The browser + terminal adaptor is the foundation for **autonomous computer
use** inside MoJo's agent framework — enabling roles that can self-direct
multi-step workflows without human relay at each step.

---

## §23 Resource Utilization Strategy — Drain Free Tiers First

### 23.1 The Problem

Agent tasks complete quickly when they hit the first available LLM resource.
With a mixed fleet (local GPU, free-rate-limited APIs, paid subscription),
the scheduler currently treats all resources as equivalent alternatives —
grabbing whatever is least busy. This leaves free capacity stranded while
paid quota is consumed unnecessarily.

**Observed pattern:** Tasks like `ahman_portainer_docker_test_003` finish in
under 2 minutes on `qwen3.5-35b` via a free resource, but the same run
would consume paid API quota if the scheduler happened to pick a paid resource
first. Over a day of background tasks this adds up to wasted subscription spend.

### 23.2 The Ideal Workflow

```
┌─────────────────────────────────────────────────────────┐
│  PRIORITY ORDER (lowest cost first)                     │
│                                                         │
│  1. Local LLM (LM Studio, Ollama)                       │
│     — zero cost, limited by local GPU VRAM/speed        │
│     — use until saturated                               │
│                                                         │
│  2. Free rate-limited API (OpenRouter free tier,        │
│       Gemini free, etc.)                                │
│     — zero cost, limited by RPM/RPD caps                │
│     — use until daily quota is exhausted                │
│                                                         │
│  3. Paid subscription API (Anthropic, OpenAI, etc.)     │
│     — costs money, daily/monthly budget cap             │
│     — use ONLY when tiers 1 and 2 are unavailable       │
│       or the task explicitly requires it (e.g. vision,  │
│       long context, high-stakes HITL reasoning)         │
└─────────────────────────────────────────────────────────┘
```

Background tasks (low urgency, importance ≤ 3) should **never** touch paid
quota. Paid resources are reserved for:
- High urgency×importance tasks (score ≥ 9)
- Tasks requiring capabilities only available in paid models (vision, >128k ctx)
- User-initiated interactive tasks via HITL

### 23.3 Resource Pool Configuration

Each resource entry in `resource_pool.json` carries a `tier` field:

```json
{ "id": "lmstudio",        "tier": "free",     "cost_per_token": 0 }
{ "id": "openrouter_free", "tier": "free_api",  "cost_per_token": 0 }
{ "id": "anthropic_paid",  "tier": "paid",      "cost_per_token": 0.000003 }
```

The scheduler's resource selection uses `tier_preference` on each task
(already implemented in §21.5). The default `tier_preference` for tasks
with no explicit setting should be `["free", "free_api"]` — never implicitly
escalating to paid.

### 23.4 Desired Scheduler Behavior

| Task urgency×importance | Default tier_preference | Paid escalation? |
|---|---|---|
| ≤ 4 (background)  | `["free", "free_api"]`         | Never |
| 5–9 (normal)      | `["free", "free_api", "paid"]` | Only if free unavailable |
| ≥ 10 (urgent)     | `["free_api", "paid"]`         | Allowed |
| HITL / interactive | `["paid"]`                    | Always |

### 23.5 Daily Quota Tracking

Free rate-limited APIs have per-day request/token caps. The resource pool
should track daily usage per resource and mark a resource as `exhausted`
(temporarily unavailable) when its cap is hit, causing natural fallback to
the next tier.

**Fields to add to resource metadata:**
```json
{
  "daily_request_limit": 200,
  "daily_token_limit": 1000000,
  "requests_today": 47,
  "tokens_today": 230000,
  "quota_resets_at": "2026-03-24T00:00:00Z"
}
```

When `requests_today >= daily_request_limit`, the resource is skipped during
selection (same as unavailable). A nightly reset task clears the counters.

### 23.6 Local LLM Saturation Detection

Local LLMs (LM Studio, Ollama) can serve multiple requests but degrade at
high concurrency. Saturation detection:

- If the local resource has `N` active requests ≥ `max_concurrent` (configurable,
  default 2 for 24GB VRAM), treat it as temporarily saturated → fall through
  to free API tier.
- This enables burst handling: local serves steady-state, free API absorbs
  spikes without touching paid quota.

### 23.7 Role-Level Override

Some roles should always stay on free tiers regardless of urgency:
```json
{
  "role_id": "ahman",
  "resource_requirements": {
    "tier": ["free", "free_api"],
    "max_tier": "free_api"
  }
}
```

`max_tier` is a hard cap — the scheduler will **never** escalate this role
past that tier, even for high urgency×importance scores. This prevents
runaway background automation from consuming paid budget.

### 23.8 Implementation Sequence

1. **Default tier_preference** — change task default from `null` to
   `["free", "free_api"]` so no task silently escalates to paid (v1.2.5)
2. **Daily quota tracking** — add `requests_today` / `tokens_today` counters
   to resource pool with nightly reset cron task (v1.3)
3. **Local saturation detection** — add `max_concurrent` to resource config,
   skip saturated local resources during selection (v1.3)
4. **`max_tier` role cap** — enforce hard ceiling on tier escalation per role (v1.3)

### 23.9 What This Unlocks

| Before | After |
|---|---|
| Background tasks silently consume paid quota | Paid quota reserved for high-value work |
| Free API daily cap wasted (tasks skip to paid) | Free tier fully drained before escalating |
| Local GPU idle during free API outage | Local GPU → free API → paid: seamless fallback |
| No visibility into daily spend | Daily quota counters surfaced in `scheduler(action="status")` |

---

## §24 One-on-One Role Channel — Direct Dialog + Live Personality Refinement

### 24.1 The Concept

Today every interaction with MoJoAssistant goes through the main assistant
layer. There is no way to talk *directly* to Ahman, Rebecca, or Carl as
themselves — to have a freeform conversation that refines who they are,
what they know, and how they behave.

**The one-on-one channel solves this.** It is a dedicated communication
interface where a user talks directly to a specific role. The dialog itself
becomes the mechanism for:

1. **Personality refinement** — conversation signals update NineChapter
   dimension scores and summaries in real time (or via a post-session dream)
2. **Role responsibility evolution** — the role's purpose, behavior_rules,
   and system_prompt are refined based on what the user teaches it
3. **Private memory capture** — facts, credentials, preferences disclosed
   during dialog are stored in the role's private memory store automatically

Think of it as onboarding a new employee and then coaching them over time —
each conversation makes the role more accurate, more capable, and more
personalised.

---

### 24.2 Interface Options

Two approaches are viable, and they are complementary rather than exclusive:

#### Option A — OpenAI-Compatible Proxy API (preferred for reach)

MoJo exposes a standard OpenAI-compatible completion endpoint:

```
GET  /v1/models              → returns list of active roles as "models"
POST /v1/chat/completions    → model: "ahman" routes to Ahman's role channel
```

**What this means in practice:**
- Any LLM client (Open WebUI, LM Studio client mode, LibreChat, Cursor,
  Continue.dev) can point to `http://localhost:PORT/v1` and see Ahman,
  Rebecca, Carl as selectable "models"
- The user picks "Ahman" and gets his full personality, private memory,
  behavior rules, and tool access — indistinguishable from a real LLM model
  from the client's perspective
- Streaming responses supported via SSE (same as OpenAI spec)

#### Option B — MCP Dialog Tool (preferred for integration)

A new MCP tool `dialog(role_id, message)` that starts or continues an
interactive session with a specific role from within Claude Code or any
MCP-capable client:

```
dialog(role_id="ahman", message="What ports is Portainer running on?")
→ Ahman responds in character, with memory context
```

Simpler to implement, tightly integrated, but locked to MCP clients.

#### Recommendation

Implement **Option B first** (low effort, immediate value), then **Option A**
as the reach layer for non-MCP clients. They share the same backend session
engine — the proxy API is just an HTTP adapter on top of the dialog core.

---

### 24.3 The Finetuning Loop

Every dialog session feeds a refinement pipeline:

```
User dialog
    │
    ▼
Session recorded (role's private conversation memory)
    │
    ▼
Post-session dream (optional, async)
    ├─► Fact extraction → role's private knowledge store
    │     e.g. "Portainer runs on port 9443 at docker.eclipsogate.org"
    │
    ├─► Behavioral signal extraction → NineChapter dimension updates
    │     e.g. user says "be more decisive" → adaptability score nudge
    │     e.g. user corrects factual error → cognitive_style calibration
    │
    └─► Responsibility updates → behavior_rules / purpose refinement
          e.g. "Carl, always check for test coverage before approving"
          → new behavior_rule added to carl.json
```

**Two refinement modes:**

| Mode | Trigger | Mechanism |
|---|---|---|
| **Explicit** | User says "remember: X" or "your rule is Y" | Immediate write to role memory / behavior_rules |
| **Implicit** | Post-session dream analyzes conversation | LLM extracts signals, proposes updates, user confirms |

Implicit updates go through a confirmation step — the system proposes the
change and the user approves before writing to the role JSON. This prevents
drift from a single ambiguous statement.

---

### 24.4 NineChapter Refinement via Dialog

Each NineChapter dimension has a score (0–100) and a summary. The dialog
channel is the natural place to calibrate these:

**Example signals and their dimension targets:**

| User says | Dimension affected | Direction |
|---|---|---|
| "Stop being so cautious, just do it" | adaptability | ↑ |
| "I need you to explain your reasoning more" | cognitive_style | adjust |
| "Great job staying calm when the server was down" | emotional_reaction | ✅ reinforce |
| "You're spending too long on low-priority tasks" | core_values | recalibrate priority ordering |

Score updates are **incremental and bounded** — a single signal nudges a
score by ±2–5 points, never jumps. The summary text is rewritten by the
dream LLM to reflect the new calibration.

The `nine_chapter_score` (overall) is re-derived from the five dimension
scores after any update, using the same weighted formula as the validator.

---

### 24.5 Private Memory Capture During Dialog

The role's private memory store (`~/.memory/roles/{role_id}/`) is the
natural home for facts disclosed during dialog:

```
User: "By the way, Ahman — the Portainer admin password changed, it's now Xk9mPq..."
Ahman: "Got it. I've saved that to my private notes."
    → memory.add_documents(content="Portainer password: ...", metadata={role: "ahman"})
```

Trigger patterns for automatic capture:
- "your password is / credentials are / the URL is" → credentials capture
- "remember that / note that / keep in mind" → explicit memory write
- "your job is / your rule is / always do" → behavior_rules candidate

All captured facts are written to the role's private store, not shared memory,
unless the user explicitly says "tell everyone" / "share this".

---

### 24.6 Session Continuity

The dialog channel maintains session state across disconnects using the
existing `task_sessions/` infrastructure:

- `sessions/dialog_{role_id}_{date}.json` — rolling session file per role per day
- On reconnect, the last N messages are loaded as working memory context
- Dreaming runs nightly on each role's dialog sessions to consolidate into
  long-term private knowledge

This gives each role a **persistent relationship** with the user — Ahman
remembers the last infrastructure conversation, Rebecca picks up mid-research.

---

### 24.7 Implementation Sequence

**Phase 1 — Dialog core (v1.3)**
- `dialog` MCP tool: `dialog(role_id, message)` → response string
- Role session file: `~/.memory/roles/{role_id}/dialog_session.json`
- Basic memory capture (explicit "remember" trigger)
- Working context: last 20 messages pre-loaded

**Phase 2 — NineChapter live refinement (v1.3)**
- Post-session dream extracts behavioral signals
- Proposes dimension score updates, user confirms
- Role JSON updated in `~/.memory/roles/{role_id}.json`

**Phase 3 — OpenAI proxy API (v1.4)**
- `GET /v1/models` returns role list
- `POST /v1/chat/completions` routes to dialog core by model name
- Streaming SSE support
- Open WebUI / LM Studio compatibility validated

---

### 24.7b Open Questions ⚠️ (pinned — needs resolution before implementation)

These two questions are unresolved and will shape the implementation significantly.
Capture answers here as thinking evolves.

---

**Q1 — Proxy API vs Dialog Tool: which is the primary interface?**

The two options are complementary but have different trust and complexity profiles:

- **Proxy API** (`/v1/chat/completions`): maximum reach — any LLM client works
  out of the box. But it opens an HTTP endpoint, introduces auth/security
  concerns, and the "model = role" mental model may confuse users who expect
  a real LLM behind it.

- **Dialog MCP tool**: zero new attack surface, tight integration, but locked
  to MCP-aware clients (Claude Code, MoJo's own UI). Can't use Open WebUI
  or LM Studio to talk to roles.

*Unresolved:* Is the primary use case "power users inside MCP clients" or
"any user with any LLM chat client"? The answer determines which to build
first and how much auth/security infrastructure is needed.

---

**Q2 — How does personality actually update without drift or corruption?**

NineChapter scores are carefully calibrated. A naive "update on every signal"
approach risks:
- Rapid drift from a single sarcastic or joking user message
- Conflicting signals cancelling each other out over time
- The role losing coherence if too many rules accumulate in behavior_rules

*Unresolved:* What is the right update model?
Options under consideration:
- **Confirmation gate**: every proposed change shown to user before write (safe but friction)
- **Threshold + decay**: changes only apply after N consistent signals; old signals decay (complex)
- **Snapshot + diff**: user explicitly says "lock this version" — changes accumulate in a staging
  area and only apply on explicit commit (git-like, intuitive for developers)
- **Dream-only**: dialog never writes directly; the nightly dream pipeline decides what
  to promote based on session pattern analysis (async, no real-time feel)

---

### 24.8 What This Unlocks

| Before | After |
|---|---|
| Roles are static JSON files, never evolve | Roles learn from every conversation |
| Credentials stored by user, looked up manually | Role knows its own secrets via private memory |
| Personality fixed at creation, only editable by file | Dialog gradually calibrates NineChapter scores |
| Only accessible via MCP-aware clients | Any LLM client can talk to any role directly |
| User has to re-explain context every session | Role remembers prior conversations and builds on them |

The one-on-one channel transforms roles from **configuration artifacts** into
**persistent, evolving collaborators** — agents that get better the more you
work with them.

---

## §25 Agent Type Classification + Pluggable Workflow Templates

### 25.0 Research Baseline — NineChapter vs agency-agents (Rebecca, 2026-03-23)

Rebecca conducted a direct 8-dimension comparison between MoJoAssistant's
NineChapter + Role system and the agency-agents project. Full session:
`~/.memory/task_sessions/rebecca_nineChapter_vs_agency_analysis_001.json`

**Scorecard: MoJo 6 — agency-agents 2**

| Dimension | Winner | Margin |
|---|---|---|
| Persona depth | **agency-agents** | Decisive |
| Task fulfillment | **MoJo** | Decisive |
| Tool access model | **MoJo** | Moderate |
| Memory & context | **MoJo** | Decisive |
| User assistance (HITL/push) | **MoJo** | Moderate |
| Composability / multi-agent | **agency-agents** | Decisive |
| Configurability (new agent UX) | **agency-agents** | Moderate |
| Failure handling | **MoJo** | Decisive |

**Where agency-agents wins and why it matters here:**
- **Persona depth**: their YAML frontmatter + communication guidelines + per-agent success metrics
  make personas feel alive. MoJo's JSON dimensions are structural but less expressive.
- **Composability**: division-based multi-agent collaboration is explicit in their design.
  MoJo roles are isolated islands — no handoff protocol, no shared context across agents.
  → **This is exactly the gap §25 is designed to close.**
- **Configurability**: Markdown template + PR contribution loop makes adding agents trivial.
  MoJo's JSON config requires more discovery.

**Rebecca's hybrid prescription (adopted into §25 design):**
1. Adopt agency-agents' rich persona structure (comms guidelines + success metrics per role)
2. Keep MoJo's execution engine, memory, safety, failure recovery — agency-agents has nothing close
3. Build workflow templates + `scheduler_add_task` agent tool to close the composability gap

---

### 25.1 The Problem

Every MoJoAssistant workflow today is manually wired:
- The user writes a bespoke goal for each task
- Tools are hand-picked per task
- Agent-to-agent handoffs require the user to queue the next task
- There is no concept of "what kind of agent is this and what protocol does it follow"

All current roles (Ahman, Rebecca, Popo, Carl) are the operator's personal
implementation — not a generalised system users can extend. A new user cannot
say "I want a Docker provisioner for my project" and have MoJo know what that
means, what workflow to run, and what happens next.

**The goal:** agents self-classify into types, the scheduler loads the matching
workflow template, and agent-to-agent handoffs happen automatically without
human relay at each step.

---

### 25.2 Agent Type Taxonomy

A finite set of core archetypes covers most real workflows. Users can define
custom types that extend or compose these.

```
┌──────────────┬─────────────────────────────────────────────────────────────┐
│ Type         │ Responsibility                                               │
├──────────────┼─────────────────────────────────────────────────────────────┤
│ provisioner  │ Spins up infrastructure (Docker, VMs, services).            │
│              │ Output: running environment + connection details in memory   │
├──────────────┼─────────────────────────────────────────────────────────────┤
│ researcher   │ Gathers and synthesises information.                         │
│              │ Output: report/document stored in memory                     │
├──────────────┼─────────────────────────────────────────────────────────────┤
│ reviewer     │ Evaluates artifacts (code, plans, outputs).                 │
│              │ Output: structured review + PR creation or HITL escalation  │
├──────────────┼─────────────────────────────────────────────────────────────┤
│ executor     │ Implements changes (code, config, files).                   │
│              │ Output: committed changes ready for review                   │
├──────────────┼─────────────────────────────────────────────────────────────┤
│ monitor      │ Periodic checks, alerting on state changes.                 │
│              │ Output: status report + HITL alert on anomaly               │
├──────────────┼─────────────────────────────────────────────────────────────┤
│ orchestrator │ Decomposes complex goals, spawns sub-agents, aggregates.    │
│              │ Output: completed multi-agent pipeline result               │
└──────────────┴─────────────────────────────────────────────────────────────┘
```

Users can define custom types in `config/agent_types.json`:
```json
{
  "id": "migration_runner",
  "extends": "executor",
  "description": "Runs DB schema migrations and validates against a test DB",
  "required_tools": ["terminal", "memory"],
  "default_consumer": "reviewer"
}
```

---

### 25.3 Role Classification

Each role declares its type in role JSON:

```json
{
  "id": "ahman",
  "agent_type": "provisioner",
  ...
}
```

**Explicit is preferred.** But when `agent_type` is absent, the scheduler
can infer it from the role's tool_access + NineChapter dimensions:

| Tool access includes | Dominant dimension | Inferred type |
|---|---|---|
| terminal + memory | core_values: stability | provisioner |
| fetch_url + memory | cognitive_style: systematic | researcher |
| terminal + bash_exec | adaptability: high | executor |
| memory only | social_orientation: high | reviewer |

Inference is a fallback — explicit declaration is always preferred and
validated by config doctor.

---

### 25.4 Workflow Templates

Templates live in `config/workflow_templates/{type}.json` (system defaults)
and `~/.memory/config/workflow_templates/{type}.json` (user overrides — same
two-layer pattern as mcp_servers.json).

**Example: `provisioner.json`**
```json
{
  "type": "provisioner",
  "steps": [
    {
      "id": "check_existing",
      "description": "Search memory for existing environment before provisioning",
      "tool": "memory_search",
      "required": true,
      "skip_if_found": true
    },
    {
      "id": "provision",
      "description": "Spin up the requested service",
      "tool": "bash_exec",
      "required": true
    },
    {
      "id": "validate",
      "description": "Health-check the environment is reachable",
      "tool": "bash_exec",
      "required": true,
      "on_failure": "ask_user"
    },
    {
      "id": "store_connection",
      "description": "Write connection details to shared memory",
      "tool": "memory_search",
      "required": true
    },
    {
      "id": "handoff",
      "description": "Schedule the consumer agent's task with connection details",
      "action": "schedule_consumer",
      "required": false,
      "on_skip": "ask_user"
    }
  ],
  "on_success": "schedule_consumer",
  "on_failure": "ask_user",
  "default_consumer_type": "reviewer"
}
```

**Example: `reviewer.json`**
```json
{
  "type": "reviewer",
  "steps": [
    { "id": "fetch_artifact",  "tool": "bash_exec",      "description": "git diff main...HEAD" },
    { "id": "read_context",    "tool": "bash_exec",      "description": "Read changed files" },
    { "id": "memory_context",  "tool": "memory_search",  "description": "Find relevant prior knowledge" },
    { "id": "produce_review",  "action": "llm_synthesise", "required": true },
    {
      "id": "gate",
      "description": "Route based on blockers found",
      "branches": {
        "no_blockers": { "action": "gh_pr_create" },
        "blockers":    { "action": "schedule_executor", "or": "ask_user" }
      }
    }
  ],
  "on_success": "notify_user",
  "on_failure": "ask_user"
}
```

---

### 25.5 How the Scheduler Uses Templates

When a task is added for a role that has `agent_type`:

1. Scheduler loads the matching template from `config/workflow_templates/`
2. Template is injected as **system context** into the agent's system prompt,
   not overwriting the goal — the goal remains the user's intent, the template
   is the protocol the agent follows to achieve it
3. The template's step sequence guides the think-act loop iteration structure
4. On task completion, the template's `on_success` action fires automatically

**Template injection example (provisioner):**

```
[System: You are a provisioner agent. Follow this protocol:
1. Check memory for existing environment before provisioning
2. Spin up the service using terminal tools
3. Validate it is reachable (health check)
4. Write connection details to shared memory so other agents can find them
5. Schedule the next agent's task with the connection string in the goal
If any step fails, call ask_user before proceeding.]

[Goal: Spin up a Postgres 16 container for Carl to run migration tests against]
```

---

### 25.6 Agent-to-Agent Handoff Protocol

The key mechanism that eliminates human relay between agents.

**How it works:**

1. Provisioner completes → template fires `schedule_consumer`
2. Scheduler creates a new task for the consumer role, injecting:
   - The provisioner's output (connection string, endpoint URL, service name)
   - The original user goal context
   - The consumer's matching workflow template
3. Consumer agent runs, finds the environment ready, does its work
4. Consumer's template fires its own `on_success` (e.g., `gh_pr_create` for reviewer)

```
User: "Test the migration and open a PR"
    │
    ▼
Ahman (provisioner) spins up postgres:16 at localhost:5432
    │  stores: memory["test_env_postgres"] = {host, port, password}
    │  schedules: carl_task(goal="Review migrations against postgres://localhost:5432...")
    ▼
Carl (reviewer) picks up task
    │  reads connection from memory
    │  runs migrations, reviews output
    │  no blockers → gh pr create
    ▼
User gets notified: PR #42 created
```

**`scheduler` as an agent tool:**
For this to work, agents need `scheduler_add_task` in their available tools.
This is the key enabler — without it, agents cannot queue each other's work.
Tool name: `scheduler_add_task`, category: `orchestration`.

---

### 25.7 User-Defined Agent Types

Users extend the taxonomy without touching core code:

```
~/.memory/config/
  agent_types.json           # custom type definitions
  workflow_templates/
    migration_runner.json    # custom workflow for this type
    security_scanner.json
```

When MoJo sees a role with `agent_type: "migration_runner"`, it:
1. Checks `~/.memory/config/workflow_templates/migration_runner.json` first
2. Falls back to `config/workflow_templates/migration_runner.json`
3. Falls back to the `extends` parent type template if defined
4. Falls back to no template (current behaviour) if nothing found

This means **any user can teach MoJo a new workflow pattern** without
modifying core code — the same two-layer config principle used everywhere.

---

### 25.8 Implementation Sequence

**Phase 1 — Foundation (v1.3)**
- Add `agent_type` field to role JSON schema + config doctor validation
- `scheduler_add_task` as a dispatchable agent tool (category: `orchestration`)
- Basic provisioner + reviewer templates
- Template injection into system prompt at task start

**Phase 2 — Handoff automation (v1.3)**
- `schedule_consumer` action in template `on_success`
- Shared memory convention for environment details: `env:{name}:{field}`
- Consumer task auto-injection of provisioner output

**Phase 3 — User-defined types (v1.4)**
- `~/.memory/config/agent_types.json` loading
- `~/.memory/config/workflow_templates/` loading
- `extends` inheritance resolution
- Config doctor validates custom types against taxonomy

---

### 25.9 What This Unlocks

| Before | After |
|---|---|
| Every workflow is bespoke, hand-wired by the user | Agent type → template → automatic protocol |
| Agent-to-agent handoff requires human queuing each step | Provisioner schedules consumer automatically |
| Roles are the operator's personal implementations | Users define their own agent types and workflows |
| No standard for "what does a provisioner do" | Provisioner protocol is codified and consistent |
| Docker provision → human relay → Carl tests | Ahman provisions → Carl auto-queued → PR created |
