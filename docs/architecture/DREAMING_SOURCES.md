# Dreaming Sources — Multi-Source Memory Consolidation

## Design Principle

The `DreamingPipeline` (A→B→C→D) is source-agnostic — it takes raw text and
produces structured archival memory. This means any structured event source in
MoJo can be serialized to text and fed through the same pipeline.

Three sources feed dreaming:

```
conversations/   ← raw chat text (current)
inbox/           ← resolved HITL interactions from the event log (new)
sessions/        ← completed task session logs (new)
```

All three call `DreamingPipeline.process_conversation()` with a prefixed
`conversation_id`. The `JsonFileBackend` stores by `{storage_path}/{conversation_id}/`
so the prefix naturally creates subdirectories:

```
~/.memory/dreams/
  conversations/chat_001/archive_v1.json       ← existing
  inbox/inbox_2026-03-22/archive_v1.json       ← nightly inbox distillation
  sessions/session_popo_admin_001/archive_v1.json  ← post-task compaction
```

No backend changes required. The directory structure falls out for free.

---

## Source 1: Conversations (existing)

**Trigger:** On-demand via `dream(action="process")` or nightly automatic task.

**Input:** Raw conversation text passed directly as `conversation_text`.

**conversation_id prefix:** `conversations/` (migration: new conversations get
the prefix; existing archives remain at their original paths).

---

## Source 2: Inbox Distillation (new — `app/dreaming/inbox_distillation.py`)

**Trigger:** Nightly, after the conversation dreaming pass. Runs on previous
day's EventLog slice.

**What it captures:** Every resolved HITL interaction — a task that asked the
user a question (`task_waiting_for_input`) and later completed (`task_completed`
or `task_failed`). These are structured knowledge: role, problem, context,
resolution, outcome.

**Serialization:**
Paired events are rendered as readable text:

```
=== Resolved Interaction: ahman_scan_001 ===
Role: ahman
Question asked: which subnet should I scan?
User replied: scan 10.0.0.0/24
Outcome: task_completed
Completed at: 2026-03-22T04:15:00
```

Multiple pairs for the day are concatenated into one document, fed as a single
`process_conversation()` call with `conversation_id = "inbox/inbox_YYYY-MM-DD"`.

**conversation_id:** `inbox/inbox_2026-03-22`

**Implementation:** `app/dreaming/inbox_distillation.py`
- `build_inbox_text(date, event_log) -> Optional[str]` — serialize the day's pairs
- `run_inbox_distillation(date, event_log, pipeline)` — serialize + call pipeline

**Wiring:** New `dream(action="distill_inbox", date?)` MCP tool action +
automatic nightly trigger alongside existing dreaming task.

---

## Source 3: Session Compaction (new — `app/dreaming/session_compactor.py`)

**Trigger:** After every `task_completed` or `task_failed` event in the
scheduler, if the session log exceeds a minimum size (default: > 20 messages).

**What it captures:** The full reasoning trace of a completed agent task —
tool calls, intermediate reasoning, final answer, errors. For long coding agent
or research tasks this can be 500K+ characters raw.

**Serialization:**
Session messages flattened to readable text, skipping system prompt and raw
tool payloads (too noisy), keeping assistant reasoning and tool summaries:

```
=== Task Session: popo_kingsum_admin_flutter_plan_001 ===
Role: popo | Status: failed | Iterations: 3
Goal: Create a plan.md for the admin Flutter web app...

[Iteration 1 — tool: opencode_get_messages]
Result: retrieved session context (32 messages)

[Iteration 2 — assistant reasoning]
I've reviewed the existing Flutter docs. The admin app needs...

[Iteration 3 — assistant]
Created KingSum2E/docs/FLUTTER_ADMIN_APP.md (785 lines)...

Error: Agent did not produce a final answer
```

Fed as a single `process_conversation()` call with
`conversation_id = "sessions/session_<task_id>"`.

**`get_context(type="task_session")` integration:**
After compaction, `_execute_task_session_read` checks for a compacted archive
first. If found, returns the compressed summary (C clusters) by default.
`full=true` still returns the raw session log.

**conversation_id:** `sessions/session_popo_kingsum_admin_flutter_plan_001`

**Implementation:** `app/dreaming/session_compactor.py`
- `build_session_text(task_id, session_path) -> Optional[str]` — serialize session
- `compact_session(task_id, session_path, pipeline)` — serialize + call pipeline

**Wiring:** Called from `app/scheduler/core.py` on task completion (background,
non-blocking). Min-size gate prevents noise from trivial 2-iteration tasks.

---

## What Changes

| File | Change |
|------|--------|
| `app/dreaming/inbox_distillation.py` | New — inbox serializer + pipeline caller |
| `app/dreaming/session_compactor.py` | New — session serializer + pipeline caller |
| `app/scheduler/core.py` | Trigger `compact_session()` on task completion |
| `app/mcp/core/tools.py` | Add `dream(action="distill_inbox")`, update `task_session` read |

## What Does NOT Change

- `DreamingPipeline` — no changes to the pipeline itself
- `JsonFileBackend` — no changes to storage
- Existing conversation archives — not migrated, remain at original paths
- Existing `dream(action="process")` — unchanged behavior
