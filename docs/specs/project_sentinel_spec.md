# Spec: Project Checklist + Project Sentinel

**Date:** 2026-09-21
**Status:** Implemented
**Scope:** `app/scheduler/models.py` (`Task.project_id`), new `app/scheduler/project_tracker.py`,
new role `project_sentinel`, new scheduler task `project_sentinel_nightly`,
new dashboard page `/dashboard/projects`

## Problem

Quality Monitor (`docs/specs/quality_monitor_spec.md`) watches individual
scheduler `Task`s — bounded, one-shot deliverables closed by their own
"Done when:" clause. It has no concept of *ongoing, multi-feature* work:
a dashboard feature, a module rewrite, an integration effort that lands
across many separate tasks and PRs over days or weeks, with no single
"Done when:" that closes the whole thing.

Surfaced directly by the user while reviewing what Paul (the product PM
role) has actually shipped: individual dispatches to Paul were easy to
audit one at a time, but there was no single place tracking "is this
*project* actually done, including everything it implied" — and no
mechanism analogous to Quality Monitor's live verification (checking a
PR/file actually exists, not trusting a self-reported status) at that
larger scope.

## Desired Outcome

1. A **Project** entity — a persistent checklist of feature/bug/update
   items, each with its own status, independent of the Task model but
   linkable to it (`Task.project_id`, and a `ChecklistItem.task_ids`
   list on the other side).
2. A **dashboard page** (`/dashboard/projects`) rendering every tracked
   project and its checklist, so project status is visible the same way
   `/dashboard/workforce` and `/dashboard/tasks` already are.
3. A new autonomous role, **`project_sentinel`**, that runs nightly and
   does for projects what Quality Monitor does for tasks: verify each
   checklist item's claimed status against observable evidence (linked
   task reports, `git`/`gh` state) rather than trusting the label. Unlike
   Quality Monitor it is LLM-driven (the comparison of "goal vs. reality"
   requires judgment Quality Monitor's deterministic checks don't), so it
   runs as a normal scheduled role dispatch, not inline in the ticker.
4. Every gap found is escalated via `dispatch_subtask` to **Paul**, who
   owns the product judgment of whether to restart the item, branch it
   differently, or replan — `project_sentinel` never edits a checklist
   or a repo itself.

## Design Decisions (confirmed with user)

- **Data source for "project" state:** a new standalone tracked entity
  (`~/.memory/projects/<id>.json`), not parsed out of spec docs or pulled
  from Linear. Explicit and simple; works for anything regardless of
  whether it has a formal spec.
- **Task/Project unification:** `Task` gained an optional `project_id`
  field rather than building a second, parallel tracking system. Any
  task can roll up into a project by carrying that id; a task with none
  is exactly the bounded, one-shot kind Quality Monitor already handles.
  The judgment of *whether* a given piece of work should become a
  project (vs. staying a plain task) is made by whichever role/agent
  creates it — this layer is deliberately just storage, no auto-classify
  heuristics baked in, matching Quality Monitor's "stay dumb" philosophy.
- **Build approach:** direct core-engine implementation (same precedent
  as Quality Monitor), not a spec-first dispatch to Paul — this *is* the
  tooling Paul's own work gets checked against, so it was built the same
  way Quality Monitor was.
- **Escalation trigger (v1):** any gap found, every run — no throttling
  or dedup yet. Quality Monitor shipped the same way and only grew
  dedup (`_qm_escalated_at` stamps) after the real alert-storm incident
  showed the actual volume; `project_sentinel` will follow the same path
  if/when it proves necessary rather than guessing at limits up front.

## What `project_sentinel` Is Not

- Not a replacement for Quality Monitor — Task-level liveness/completion
  checking is unchanged, still deterministic, still every ~5 minutes,
  still inline in `Scheduler._ticker_loop`.
- Not a remediation engine — it finds and reports gaps; Paul decides and
  acts.
- Not local-only like Security Sentinel — it legitimately needs `git`/
  `gh` against real remotes to verify claims, and `dispatch_subtask` to
  escalate, so it carries the `exec` and `orchestration` capabilities
  Security Sentinel deliberately doesn't have.

## Implementation

- `app/scheduler/models.py` — `Task.project_id: Optional[str] = None`,
  serialized/deserialized like `parent_task_id`, defaults preserve
  backward compatibility with every existing task record.
- `app/scheduler/project_tracker.py` — `Project` / `ChecklistItem`
  dataclasses, one JSON file per project under `~/.memory/projects/`,
  atomic write + readback verification (BRIDLE: no silent partial
  writes on structured state). `create_project`, `add_item`,
  `update_item_status`, `list_projects`, `load_project`.
- `~/.memory/roles/project_sentinel.json` — role definition, modeled on
  `security_sentinel.json`'s shape (nine-chapter dimensions, purpose,
  system_prompt, behavior_rules), `capabilities: [knowledge, file, exec,
  orchestration]`.
- `~/.memory/scheduler_tasks.json` — `project_sentinel_nightly`, cron
  `0 4 * * *` (between `dreaming_nightly_offpeak_default` at 3am and
  `paul_community_daily` at 7am), `available_tools` includes
  `dispatch_subtask`.
- `app/dashboard/router.py` — `/dashboard/projects` route, new CSS for
  item/project status badges (`s-todo`, `s-in_progress`, `s-done`,
  `s-blocked`, `s-active`, `s-archived`) and `.project-card` layout, nav
  link added between Workforce and Library.

## Tests

- `tests/unit/test_project_tracker.py` — 16 tests: create/load/list,
  add-item validation, update-status persistence and task_id
  accumulation, plus `Task.project_id` round-trip and backward-compat
  defaulting.
- `tests/unit/test_dashboard_projects.py` — 5 tests: empty state,
  populated project/items rendering, multiple projects, HTML-escaping,
  auth requirement.

## Acceptance Criteria

- [x] `Task.project_id` field added, serializes/deserializes correctly,
      all 31 existing live scheduler tasks still parse after the change.
- [x] `project_tracker.py` create/add/update/list all covered by tests,
      atomic write with readback verification implemented.
- [x] `/dashboard/projects` renders live (verified against the running
      `mojoassistant.service` after restart — empty state confirmed,
      other dashboard pages unaffected).
- [x] `project_sentinel` role registered under `~/.memory/roles/`,
      discoverable via the existing directory-glob mechanism (no
      separate registry to update).
- [x] `project_sentinel_nightly` cron task registered, parses cleanly
      against `Task.from_dict`, does not collide with existing cron
      cadences.
- [ ] First real nightly run (next fire: 2026-09-22 04:00) — not yet
      observed live since no projects are tracked yet. Will show
      "nothing to report" correctly per its own behavior rules until a
      real project is created.
