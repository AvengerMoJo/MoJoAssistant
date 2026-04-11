# Spec: Task Report V2

## Problem

Today the scheduler writes a minimal completion artifact to:

`~/.memory/task_reports/{task_id}.json`

Current shape:

```json
{
  "task_id": "f10ba349",
  "role_id": "anna",
  "goal": "...",
  "status": "pending_review",
  "created_at": "...",
  "content": "<FINAL_ANSWER text>"
}
```

This is enough for raw persistence, but it is too weak for:

- dashboard task views
- chat-mode recall and debrief
- notifications
- dreaming / report distillation
- distinguishing a task report from a user-facing deliverable file

The current artifact mixes three different concepts:

1. session artifact
2. normalized completion report
3. deliverable file written for the user

These need to be separated.

## Mental Model

Every completed task should produce up to 3 different outputs:

### 1. Session artifact

Source of truth for execution history.

Location:

`~/.memory/task_sessions/{task_id}.json`

Purpose:

- audit trail
- debugging
- replay / resume context

### 2. Task report

Normalized completion record derived from the session and final answer.

Location:

`~/.memory/task_reports/{task_id}.json`

Purpose:

- dashboard summaries
- notifications
- knowledge ingestion
- role chat recall

### 3. Deliverable file

Optional user-facing file explicitly created by the agent.

Examples:

- `~/notes/briefing.md`
- `project/docs/analysis.md`
- `~/.memory/opencode-sandboxes/scott-briefings/source-map.md`

Purpose:

- the actual requested output document

Important:

The task report is not the same thing as the deliverable file.

## Desired Behaviour

When a scheduled agentic task finishes:

1. The full session is saved as it is today
2. A structured `task_report_v2` JSON is written
3. Any explicit user-facing output files are tracked separately under `artifacts.output_files`
4. Dashboard, notifications, and role chat consume report summaries instead of raw session dumps

## Proposed Schema

```json
{
  "schema_version": "task_report_v2",
  "task_id": "f10ba349",
  "role_id": "anna",
  "report_type": "task_completion",
  "status": "completed",
  "review_status": "pending_review",
  "created_at": "2026-04-02T15:27:55.444584",
  "completed_at": "2026-04-02T15:27:55.444584",
  "goal": "Search memory for Alex's 2026 plan and summarize it clearly.",
  "summary": "Anna found Alex's 2026 annual plan and returned a concise structured summary.",
  "completed": [
    "Searched memory for the 2026 plan",
    "Retrieved the master annual plan",
    "Summarized the main goals and structure"
  ],
  "findings": [
    "The 2026 plan centers on spiritual development, professional growth, and health",
    "It includes weekly time allocation targets and a quarterly review structure"
  ],
  "incomplete": [
    "Specific metrics were still placeholders pending Alex's input"
  ],
  "resume_hint": "Revisit the plan after Alex fills in missing metrics and timelines.",
  "final_answer": {
    "raw_text": "**Completed:** ...",
    "completion_mode": "model_final_answer",
    "auto_extracted": false,
    "validation_notes": []
  },
  "artifacts": {
    "session_file": "/home/alex/.memory/task_sessions/f10ba349.json",
    "report_file": "/home/alex/.memory/task_reports/f10ba349.json",
    "output_files": [],
    "source_files": []
  },
  "metrics": {
    "iterations": 6,
    "tool_calls": 4,
    "duration_seconds": 78.3
  },
  "provenance": {
    "interaction_mode": "scheduler_agentic_task",
    "resource_id": "lmstudio_gemma4",
    "model": "google/gemma-4-26b-a4b",
    "task_type": "assistant"
  },
  "promotion": {
    "eligible_for_knowledge": true,
    "knowledge_doc_id": null,
    "promoted_at": null
  }
}
```

## Required Fields

- `schema_version`
- `task_id`
- `status`
- `review_status`
- `created_at`
- `goal`
- `summary`
- `final_answer.raw_text`
- `final_answer.completion_mode`
- `artifacts.session_file`
- `artifacts.report_file`

## Field Semantics

### `status`

Execution outcome, not review outcome.

Suggested values:

- `completed`
- `completed_fallback`
- `blocked`
- `failed`
- `timed_out`
- `iteration_exhausted`

### `review_status`

Human / downstream workflow state for the report artifact.

Suggested values:

- `pending_review`
- `reviewed`
- `promoted`
- `archived`

### `summary`

One short executive summary for:

- dashboard list rows
- notifications
- role-chat recall results

This should not be a copy of the full `FINAL_ANSWER`.

### `completed`, `findings`, `incomplete`

Structured extraction from the `FINAL_ANSWER` contract:

- `**Completed:**`
- `**Findings:**`
- `**Incomplete:**`

If the final answer is unstructured, runtime may synthesize these fields.

### `resume_hint`

Useful continuation note for:

- retrying blocked tasks
- follow-up agent work
- future role memory / dreaming

### `final_answer.completion_mode`

How the final answer was obtained.

Suggested values:

- `model_final_answer`
- `auto_extracted_last_response`
- `runtime_synthesized_fallback`

This is critical for debugging reliability issues.

### `artifacts.output_files`

Explicit user-facing files created by the agent via file tools.

This field solves the current ambiguity:

- session/report artifacts are always runtime-managed
- deliverable files are optional and task-specific

### `promotion`

Tracks whether the report has been elevated into long-term knowledge.

This keeps reviewable task output separate from stable knowledge-base content.

## Serialization Rules

### Rule 1: Never treat the report itself as the deliverable file

`task_report_v2` is a normalized completion record.

If the user asked for a markdown report, analysis file, or briefing document, that path
must appear in `artifacts.output_files`.

### Rule 2: Preserve raw final answer

Even when fields are parsed into structured sections, keep:

`final_answer.raw_text`

This preserves auditability and allows future parsers to improve.

### Rule 3: Mark fallback provenance explicitly

If the model forgot `<FINAL_ANSWER>` tags and the runtime recovered the response,
the report must say so via:

- `status: completed_fallback` or similar
- `final_answer.completion_mode`
- `final_answer.auto_extracted`

### Rule 4: Keep sessions and reports separate

- session = full execution trail
- report = normalized result

Do not embed the full session inside the report.

## Derived Views

The report should support at least 3 views.

### 1. Summary view

For scheduler list, notifications, and quick recall.

Fields:

- `task_id`
- `role_id`
- `status`
- `summary`
- `created_at`
- `completed_at`

### 2. Detail view

For dashboard task inspection.

Fields:

- summary view
- `goal`
- `completed`
- `findings`
- `incomplete`
- `resume_hint`
- `metrics`
- `artifacts`

### 3. Dreaming / ingestion view

For knowledge extraction.

Fields:

- `goal`
- `summary`
- `completed`
- `findings`
- `incomplete`
- `resume_hint`
- `final_answer.raw_text`

This is distinct from the full session transcript handled by the session-memory flow.

## Migration Plan

### Phase 1

Update the completion artifact writer in
[agentic_executor.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/agentic_executor.py#L1101)
to write both:

- legacy fields for compatibility
- new `task_report_v2` fields

### Phase 2

Update dashboard and role chat consumers to prefer:

- `summary`
- `completed`
- `findings`
- `incomplete`

instead of reading raw `content` only.

### Phase 3

Track explicit output files from file-writing tools and store them in:

`artifacts.output_files`

### Phase 4

Once all readers are migrated, remove dependence on the legacy top-level `content` field.

## Success Criteria

1. A completed task always produces a normalized report artifact with `schema_version`
2. Dashboard task list can use `summary` without loading the full session
3. Notifications can send a compact, readable result using report data
4. Role chat can search prior reports without relying on raw unstructured blobs
5. Tasks that wrote explicit user deliverables can point to them via `artifacts.output_files`
6. Fallback completions are visibly distinguishable from clean `FINAL_ANSWER` completions

## Out of Scope

- redesign of task session format
- retroactive migration of all old reports
- automatic creation of user deliverable files for every task
- knowledge-promotion workflow details beyond the report metadata hooks

## Relationship to Existing Specs

- [task_session_memory_v1.2.15.md](/home/alex/Development/Personal/MoJoAssistant/docs/specs/task_session_memory_v1.2.15.md)
  governs how full task sessions become long-term memory
- this spec governs the normalized task-completion artifact written at task finish

They complement each other:

- task session memory = conversational / execution memory
- task report v2 = structured completion record
