# Release Notes v1.2.1-beta — Planned

## Theme: Attention Layer — Proactive Situational Awareness

Completes the Human-in-the-Loop story from v1.2.0 by giving the MCP client LLM
a single, fast, token-optimised tool to check what needs attention, and wires it
into the natural conversation start so the LLM never wakes up blind.

---

## Feature 1: AttentionClassifier + `get_attention_summary`

### Problem

The v1.2.0 `ask_user` / `reply_to_task` HITL flow works, but the LLM has no
proactive way to discover tasks in `waiting_for_input` state. Questions from
Ahman or Rebecca go unnoticed until the user asks explicitly. The same gap
exists for task failures, completions, and 3rd-party agent results.

### Design

**Layer 1 — AttentionClassifier (deterministic, no LLM):**

Runs inside `EventLog.append()` before the event is persisted.
Adds `hitl_level: 0–5` to every event. First match wins.

| Level | Rule | Example |
|-------|------|---------|
| 5 | `severity == "critical"` | Server crash, fatal error |
| 4 | `event_type == "task_waiting_for_input"` | Ahman asking a question |
| 3 | `severity == "error"` or `event_type == "task_failed"` | Task failed permanently |
| 2 | `event_type == "task_completed"` + `notify_user == true` | Ahman finished a scan |
| 1 | any `notify_user == true` | Background update worth noting |
| 0 | everything else | Heartbeats, scheduler ticks, dreaming noise |

**Layer 2 — `get_attention_summary` MCP tool:**

Token-compact grouped summary of unread events since a caller-owned cursor.

```
get_attention_summary(
    since: str | None     — ISO-8601 cursor (omit for last 24h)
    min_level: int = 1    — ignore level-0 noise (default)
)
```

Response:
```json
{
  "blocking": [
    {
      "id": "u_882a", "level": 4, "from": "ahman",
      "blurb": "Waiting: which subnet should I scan?",
      "reply_with": "reply_to_task", "task_id": "ahman_scan_001",
      "created_at": "2026-03-19T09:14:00"
    }
  ],
  "alerts": [
    {"id": "u_441c", "level": 3, "from": "scheduler",
     "blurb": "dreaming_nightly failed — no GPU resources"}
  ],
  "digest": [
    {"id": "u_119f", "level": 2, "from": "rebecca",
     "blurb": "Weekly summary draft ready for review"}
  ],
  "digest_count": 1,
  "noise_count": 47,
  "cursor": "2026-03-19T09:14:00"
}
```

- `blocking` — level 4–5, requires immediate action; includes `reply_with` + args
- `alerts` — level 3, errors needing attention
- `digest` — level 1–2, FYI (capped at 10 items)
- `noise_count` — suppressed level-0 events
- `cursor` — pass back as `since` on next call

### Files to Create/Change

- **New**: `app/mcp/adapters/attention_classifier.py` — `AttentionClassifier.classify(event) -> int`
- **`app/mcp/adapters/event_log.py`** — call classifier in `append()`, store `hitl_level`
- **`app/mcp/core/tools.py`** — register + implement `get_attention_summary`

---

## Feature 2: Wake-up Hook in `get_memory_context`

### Problem

`get_attention_summary` exists but the LLM still has to remember to call it.
At conversation start, the LLM calls `get_memory_context` to orient itself —
this is the natural injection point for situational awareness.

### Design

When `get_memory_context` is called, if there are any `blocking` or `alerts`
items in the attention summary, append them to the returned context automatically.

```json
{
  "memory": "...",
  "attention": {
    "blocking": [...],
    "alerts": [...],
    "note": "Call get_attention_summary for full details or to advance cursor."
  }
}
```

If nothing needs attention (`blocking` and `alerts` both empty), the field is
omitted entirely — no noise added to clean conversations.

### Behaviour guidance for LLM (in tool description)

- If `attention.blocking` is non-empty: surface to user before anything else.
  Each item includes `reply_with` so the LLM knows exactly how to act.
- If `attention.alerts` is non-empty: mention in passing, ask if user wants
  to investigate.
- If `attention` field is absent: everything is quiet, proceed normally.

### Files to Change

- **`app/mcp/core/tools.py`** — `_execute_get_memory_context()`: call
  `_execute_get_attention_summary()` internally, inject into response if non-empty

---

## Implementation Order

1. `app/mcp/adapters/attention_classifier.py` — AttentionClassifier
2. `app/mcp/adapters/event_log.py` — wire classifier into `append()`
3. `app/mcp/core/tools.py` — `get_attention_summary` tool
4. `app/mcp/core/tools.py` — wake-up hook in `get_memory_context`
5. Fix `scheduler_list_tasks` status enum to include `waiting_for_input`

---

## Verification

```bash
# 1. Schedule a task with ask_user, let it reach waiting_for_input
scheduler_add_task(task_id="inbox_test", available_tools=["ask_user"], ...)

# 2. Cold-start a new conversation — get_memory_context should surface it
get_memory_context()
# → attention.blocking: [{level:4, blurb:"Waiting: ...", reply_with:"reply_to_task"}]

# 3. Standalone check
get_attention_summary()
# → same result

# 4. Reply and check again
reply_to_task(task_id="inbox_test", reply="yes")
get_attention_summary(since=<previous_cursor>)
# → blocking: [] (cleared), digest: [{level:2, blurb:"inbox_test completed"}]
```
