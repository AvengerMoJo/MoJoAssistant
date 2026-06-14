# Release Notes — v1.2.4-beta

## Theme: Trust Layer — Know Exactly What Your Agent Did

Capability is table stakes. The differentiator is trust. When a user can open
an audit log and see exactly what crossed their local boundary — task by task,
tool by tool — that's a guarantee no cloud-first agent can make by design.

This release makes MoJoAssistant *auditable*: every external call logged, every
agent behavior enforceable, and every interaction remembered.

---

## 1. §21 Enforcement — Role ID Required

### MCP layer rejection
`scheduler(action="add", type="assistant")` now rejects tasks that:
- Have no `role_id` → error with `role_list` hint
- Use inline `system_prompt` → error with `role_create` hint

This closes the footgun where a carelessly-constructed task ran with no
personality, no tool policy, and no audit identity.

### Executor deprecation warnings
Tasks that bypass the MCP layer (e.g. `scheduler_config.json` direct entries,
internal queue adds) still execute but log `DEPRECATION` warnings for:
- Missing `role_id` on any assistant task
- Inline `system_prompt` present without a role

Both warnings name the future behavior (hard rejection) so migration is visible
in logs before it becomes breaking.

### `behavior_rules.exhausts_tools_before_asking`
New role-level rule enforced in `AgenticExecutor`. When active, `ask_user` is
rejected with a helpful error + tool list hint if the agent hasn't called any
other tool first. Fixes the Rebecca pattern of opening with a question before
checking memory or searching the web.

Rebecca's role (`~/.memory/roles/rebecca.json`) has this rule enabled.

---

## 2. Audit Trail — Every External Boundary Crossing Logged

### `~/.memory/audit_log.jsonl`
Every LLM call to a non-local resource (`tier != "free"`) is appended to an
append-only JSONL log. Each record contains:

```json
{
  "ts": "2026-03-22T22:41:07Z",
  "task_id": "rebecca_autoresearch_001",
  "role_id": "rebecca",
  "resource_id": "openrouter_free",
  "resource_type": "api",
  "tier": "free_api",
  "model": "mistral-7b",
  "tokens_in": 1840,
  "tokens_out": 312,
  "tokens_total": 2152
}
```

Content is **never** logged — metadata only. The log is never purged.
Path respects the `MEMORY_PATH` environment variable.

### `audit_get` MCP tool
```
audit_get(task_id?)  →  records + token totals + tier breakdown
```
Filter by `task_id` to see what a specific task touched. Omit for recent history.

### Audit summary in `get_context(orientation)`
The orientation response now includes an `audit_summary` block showing the count
of recent external calls, tier breakdown, and total tokens — so an LLM client
sees at a glance whether the system has been making external calls.

---

## 3. Multi-Source Dreaming — Inbox + Sessions

The `DreamingPipeline` is source-agnostic: it takes text → produces structured
archival memory. This release feeds two new sources through the same pipeline.

### Directory structure
```
~/.memory/dreams/
  conversations/   ← existing chat text
  inbox/           ← nightly resolved HITL interactions  (new)
  sessions/        ← completed agent task sessions       (new)
```

### Inbox distillation (`app/dreaming/inbox_distillation.py`)
After each nightly dreaming pass, the previous day's EventLog is scanned for
resolved HITL interactions — tasks that asked the user a question and later
completed. These pairs are serialized as readable text and fed through the
pipeline as `inbox/inbox_YYYY-MM-DD`.

Over time this builds institutional knowledge: "Ahman always needs subnet
clarification on home network tasks" becomes a pattern the dreaming LLM can
surface.

**Trigger:** `distill_inbox: true` in dreaming task config (enabled in the
default nightly task). Also available on-demand: `dream(action="distill_inbox")`.

### Session compaction (`app/dreaming/session_compactor.py`)
After every completed assistant task, the session log is serialized (smart
truncation of tool payloads, system prompt stripped) and fed through the
pipeline as `sessions/session_<task_id>`.

This replaces the naive `[role] content` serializer in
`_schedule_dreaming_for_agentic_task`. Sessions with fewer than 8 messages are
skipped (trivial tasks produce noise, not knowledge).

---

## 4. Stale Inbox Fix

`task_waiting_for_input` events are now silently dropped from the attention
inbox when the referenced task is no longer `WAITING_FOR_INPUT`. Completed or
failed tasks no longer produce phantom blocking items after server restart.

---

## 5. Design Documentation

- `docs/architecture/DREAMING_SOURCES.md` — multi-source dreaming design

---

## What Moves to v1.2.5

Items that were in the v1.2.4 scope description but not implemented this cycle:

| Item | Reason deferred |
|------|-----------------|
| Urgency + importance → attention routing | Requires task model changes; scope grew |
| Config doctor NineChapter score validation | Low urgency, no production pain |
| Config tool coverage for `mcp_servers.json` | Minor UX gap, manual edit works fine |
| `llm_config.json` → `resource_pool.json` migration | Safe to defer; agentic path unaffected |

---

## Upgrade Notes

### New role field
Add to any role that should exhaust tools before asking:
```json
"behavior_rules": {
  "exhausts_tools_before_asking": true
}
```

### Audit log
Appears automatically at `~/.memory/audit_log.jsonl` on first non-free LLM call.
No configuration needed.

### Nightly dreaming
Add `"distill_inbox": true` to the dreaming task config in `scheduler_config.json`
to enable nightly inbox distillation (not tracked by git — update manually).

### MEMORY_PATH
`audit_log.py` and `session_compactor.py` now respect the `MEMORY_PATH`
environment variable. If you run MoJo with a custom memory root, no changes needed.
