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
