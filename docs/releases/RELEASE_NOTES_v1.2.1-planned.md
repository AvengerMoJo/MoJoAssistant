# Release Notes v1.2.1 — Planned

## Theme: Attention Layer — Proactive Situational Awareness

Completes the Human-in-the-Loop story from v1.2.0 by giving the MCP client LLM
a single, fast, token-optimised tool to check what needs attention — without
polling across multiple tools or missing waiting tasks entirely.

---

## Feature: Attention Layer

### Problem

The v1.2.0 `ask_user` / `reply_to_task` HITL flow works, but the LLM has no
proactive way to discover tasks in `waiting_for_input` state. It only finds them
if it manually calls `scheduler_get_task` or `scheduler_list_tasks`. In practice,
questions from Ahman or Rebecca go unnoticed until the user asks explicitly.

The same gap exists for task failures, completions, and future 3rd-party agent
results — the LLM sees them only if it happens to poll.

### Design

Two-layer approach: a **deterministic classifier** that enriches every event with
a `hitl_level` at write time, and a **compact summary tool** the LLM can call
to get situational awareness in one shot.

---

### Layer 1 — AttentionClassifier (System-1, no LLM)

Runs inside `EventLog.append()` before the event is persisted.
Adds `hitl_level: 0–5` to every event based on deterministic rules.

| Level | Rule | Example |
|-------|------|---------|
| 5 | `severity == "critical"` | Server crash, fatal error |
| 4 | `event_type == "task_waiting_for_input"` | Ahman asking a question |
| 3 | `severity == "error"` or `event_type == "task_failed"` | Nightly dreaming failed |
| 2 | `event_type == "task_completed"` and `notify_user == true` | Ahman finished a scan |
| 1 | any `notify_user == true` | Background update worth noting |
| 0 | everything else | Heartbeats, scheduler ticks, dreaming noise |

Rules are evaluated top-down (first match wins). Custom overrides can be added
per `event_type` in a config block for future extensibility.

---

### Layer 2 — `get_attention_summary` MCP Tool

Returns a token-compact grouped summary of unread events since the caller's last
cursor. The LLM can call this at conversation start to get situational awareness.

**Tool schema:**
```
get_attention_summary(
    since: str | None     — ISO-8601 cursor (omit for last 24h)
    min_level: int = 1    — ignore level-0 noise (default)
)
```

**Response schema:**
```json
{
  "blocking": [
    {
      "id": "u_882a",
      "level": 4,
      "from": "ahman",
      "blurb": "Waiting: which subnet should I scan?",
      "reply_with": "reply_to_task",
      "task_id": "ahman_scan_001",
      "created_at": "2026-03-19T09:14:00"
    }
  ],
  "alerts": [
    {
      "id": "u_441c",
      "level": 3,
      "from": "scheduler",
      "blurb": "dreaming_nightly failed — no GPU resources available",
      "created_at": "2026-03-19T03:04:00"
    }
  ],
  "digest": [
    {
      "id": "u_119f",
      "level": 2,
      "from": "rebecca",
      "blurb": "Weekly summary draft ready for review",
      "created_at": "2026-03-19T08:00:00"
    }
  ],
  "digest_count": 1,
  "noise_count": 47,
  "cursor": "2026-03-19T09:14:00",
  "since": "2026-03-18T09:14:00"
}
```

- `blocking` — level 4–5, requires immediate action
- `alerts` — level 3, errors needing attention
- `digest` — level 1–2, FYI updates (capped at 10 items)
- `noise_count` — count of level-0 events suppressed
- `cursor` — advance this on next call to avoid re-reading

**LLM behaviour guidance** (in tool description):
- Check `blocking` first — if non-empty, surface to user before anything else
- Each blocking item includes `reply_with` + args so the LLM knows exactly
  how to act without guessing
- Pass the returned `cursor` back as `since` on the next call

---

### Files to Create/Change

- **New**: `app/mcp/adapters/attention_classifier.py`
  - `AttentionClassifier.classify(event) -> int` (0–5)
  - Deterministic rule chain, no external deps
- **`app/mcp/adapters/event_log.py`**
  - Call `AttentionClassifier.classify()` inside `append()`
  - Store `hitl_level` on every persisted event
- **`app/mcp/core/tools.py`**
  - Register `get_attention_summary` tool
  - `_execute_get_attention_summary()`: reads EventLog, groups by level,
    builds compact response

---

### What is NOT in v1.2.1

- `get_memory_context` auto-injection ("wake-up hook") — v1.3.0
- Per-source routing rules (opencode results → level 1 by default) — v1.3.0
- Infrastructure routing (Ceph/ZFS log sinks, terminal interrupts) — future
- Inbox read-state per-client (cursor is caller-owned, no server-side tracking)

---

### Verification

```bash
# 1. Schedule a task with ask_user
scheduler_add_task(task_id="inbox_test", ..., available_tools=["ask_user"])

# 2. Once task is waiting_for_input:
get_attention_summary()
# → blocking: [{level:4, from:"scheduler", blurb:"Waiting: ...", reply_with:"reply_to_task"}]

# 3. Reply and check again:
reply_to_task(task_id="inbox_test", reply="yes")
get_attention_summary()
# → blocking: [] (cleared), digest: [{level:2, blurb:"inbox_test completed"}]
```
