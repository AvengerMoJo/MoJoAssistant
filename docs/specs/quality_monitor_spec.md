# Spec: Quality Monitor — Task Health Watchdog

**Date:** 2026-09-18
**Status:** Draft — design decisions confirmed by user, ready for execution planning
**Scope:** new role `quality_monitor`, `app/scheduler/core.py` (read-only task inspection), Discord HITL path (reuse, no changes)

## Problem

Confirmed live via a real incident (task `28eb4899`, role `paul`, 2026-09-17):
a scheduled task can self-report `success: true` and `status: completed`
while never satisfying its own stated completion condition. Paul was told
"Done when: a PR exists... acceptance criteria checked off... tests pass."
He wrote a PRD, then the scheduler's iteration-budget-exhaustion nudge
("Your main work is complete. Emit FINAL_ANSWER now.") pushed him to
close out early. Nothing caught the gap between "produced some output"
and "met the actual bar" — the task just looks like a clean success in
the task list.

More generally, task health today is only checked in two narrow places:

1. `scheduler(action="cleanup")` — kills zombies, archives stale
   failures, but is **on-demand only**; nothing calls it periodically.
2. Startup zombie recovery in `core.py` — runs **once, at daemon boot**
   (crash recovery for "daemon restarted while task was running"), not
   while the daemon keeps running.

There is no continuously-running component whose job is "is this task
actually healthy," and specifically nothing verifies a completed task's
`success: true` against its own stated Done-when condition before
trusting it.

## Desired Outcome

An always-running background role, `quality_monitor`, that:

- Polls task state on a short cadence (every few minutes, not nightly —
  distinct from `security_sentinel`'s cadence and concern).
- Classifies every non-terminal-healthy task into one of: `stuck`,
  `waiting_for_input_too_long`, `falsely_completed` (success claimed but
  its own Done-when condition is checkable and false), `genuinely_failed`.
- Takes a bounded action per classification (see Design) — auto-restart
  only for narrow, safe cases; everything else goes to the human via the
  **existing** Discord HITL path, not a new notification channel.
- Logs every decision it makes (PRE/ACT/POST, per the BRIDLE loop already
  used elsewhere in this codebase) so the monitor's own behavior is
  itself auditable — it must not become a silent, unaccountable layer.

## Non-Goals

- Not a general task-orchestration engine — it does not create new work,
  only intervenes on existing tasks that are unhealthy.
- Not a replacement for `security_sentinel` — that role stays scoped to
  security/policy audit of the EventLog; this role is scoped to task
  *completion health*, a different concern, different cadence.
- No new escalation channel — reuses the existing `ask_user` →
  `WAITING_FOR_INPUT` → `reply_to_task` → Discord adapter path exactly
  as `hitl_bridge.py` already implements it.
- Full autonomous reassignment across roles is explicitly out of scope
  per the confirmed design decision below (auto-restart is same-role-only).

## Design

**Revision note (implemented 2026-09-18):** the original draft below
sketched this as an `agent_type: "analyst"` role, mirroring
`security_sentinel`. That was changed during implementation: a watchdog
that needs an LLM to reason about stuck LLM-driven tasks could get stuck
the same way its subjects do, which defeats the point of a fault-resistant
monitor. What's actually built is **plain deterministic Python**
(`app/scheduler/quality_monitor.py`), called directly from
`Scheduler._ticker_loop` every 5 ticks (`core.py`) — no role, no LLM call,
no scheduled task of its own to watch. State/timestamp checks and direct
verification of a task's own "Done when" clause (never by re-asking the
agent that claimed success).

### Module (`app/scheduler/quality_monitor.py`)

- `classify_task(task, now, final_answer_loader, done_when_checker)` —
  pure function, no side effects. Returns a `QualityFinding` or `None`.
- `check_done_when(goal, pr_checker, file_checker)` — extracts a
  "Done when: ..." clause and verifies it directly (currently: PR-exists
  via `gh pr list`, file-exists via a direct filesystem check). Returns
  `True`/`False` when checkable, `None` when not checkable or when the
  checker itself couldn't run — `None` is never treated as `False`.
- `apply_action(queue, task, finding, now)` — restart (same-role
  continuation, capped) or escalate (existing Discord HITL path via a
  `WAITING_FOR_INPUT` alert task) — exactly one action per finding.
- `run_quality_check(queue, now, final_answer_loader, done_when_checker)`
  — top-level entry point; iterates all tasks, skips its own
  restarts/alerts (`created_by == "quality_monitor"`), returns every
  finding for the caller to log (including the empty-list "all healthy"
  case).

### Scheduling

Not a cron task — `core.py`'s own tick loop calls `run_quality_check`
every 5 ticks (`tick_count % 5 == 0`), which is ~5 minutes at the default
60s `tick_interval`, matching the confirmed cadence. This keeps the
monitor inside the same trusted process as the scheduler itself rather
than as another dispatched task that could itself go stuck or get skipped
by the very queue it's meant to watch.

### Classification logic

For each task not in a healthy terminal state:

| State | Check | 
|---|---|
| `stuck` | `status == "running"` and no state change for longer than the task's own `max_duration_seconds` (already a per-role field, see Paul's role config) |
| `waiting_for_input_too_long` | `status == "waiting_for_input"` past a threshold (default: 24h — a human review cadence, not urgent-alarm cadence) |
| `falsely_completed` | `status == "completed"`, `success == true`, but the goal contains a mechanically-checkable "Done when" clause (file exists / PR exists / branch exists / tests pass) that is independently false when checked directly (not by re-asking the agent) |
| `genuinely_failed` | `status == "failed"` with a real error and exhausted retries |

### Action policy (per confirmed design decisions)

- `falsely_completed` or `stuck` **with a clear, same-role continuation**
  (e.g. "you wrote the plan, now dispatch the implementation" — Paul's
  exact case) → auto re-dispatch as a continuation task, same `role_id`,
  goal explicitly states what was already done and what's still missing.
  Capped at 2 restarts (see behavior_rules above).
- `waiting_for_input_too_long`, `genuinely_failed`, or anything ambiguous
  (unclear what "done" would even look like, or restart cap exhausted)
  → escalate via `ask_user` on the existing Discord HITL path. Never
  silently drop it, never auto-retry past the cap.
- Healthy tasks → no action, logged as such (matches `security_sentinel`'s
  "write a digest even when nothing is found" discipline).

### Files affected (as implemented)

- `app/scheduler/quality_monitor.py` (new — classification + action logic)
- `app/scheduler/core.py` (`_ticker_loop`) — periodic call, non-fatal on
  exception (logged as warning, never crashes the scheduler tick)
- `tests/unit/test_quality_monitor.py` (23 tests, all passing; includes
  a direct replay of the task-28eb4899 incident using its real goal text)
- No role file, no scheduler API changes — deliberately, per the revision
  note above.

## Acceptance Criteria

- [x] A re-run against task `28eb4899`'s actual goal text correctly
      classifies it as `falsely_completed` and generates a same-role
      continuation task (`TestClassifyTask::test_falsely_completed_replays_paul_incident`,
      `TestRunQualityCheck::test_end_to_end_falsely_completed_creates_continuation`).
- [x] A genuinely-failed task and a stuck task each correctly classify and
      route to escalation in a test harness — no live network/gh/git
      calls in unit tests (every checker is injected).
- [x] Restart cap (2) is enforced and verified — cap-exhausted escalates
      instead of retrying again (`test_restart_cap_exhausted_escalates_instead`).
- [x] The monitor's own decisions are logged (`Scheduler._log`, distinct
      per-finding messages), separate from the task acted on.
- [x] Running the monitor with zero unhealthy tasks produces an explicit
      "all tasks healthy" debug log, not silence.
- [ ] Live end-to-end verification: let the deployed scheduler run a full
      5-tick cycle against real task state and confirm the log line
      actually appears — not yet observed live, only unit-tested.

## Delivery

Implemented directly on `wip_managed_e2e` (the branch already checked out
locally) rather than a fresh `wip_quality_monitor` branch — this is core
scheduler engine work the user asked to finish natively, not something to
route through the agent workforce or a separate PR cycle. Committing and
pushing is a separate step from writing the code; ask before either.
