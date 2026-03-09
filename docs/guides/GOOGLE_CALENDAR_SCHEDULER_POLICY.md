# Google Calendar Scheduler Policy

This document defines how MoJoAssistant should use Google Calendar for scheduler tasks.

Policy file:
- `config/google_calendar_scheduler_policy.json`

Prerequisite setup guide:
- `docs/guides/GOOGLE_WORKSPACE_SETUP.md`

## Purpose

Separate user scheduling from assistant operations so autonomous workflows do not pollute the user's primary calendar.

## Scope Model

Two calendar scopes are defined:

1. `user`
- Default for `scheduled` tasks.
- Intended for user-facing events (meetings, reminders, deadlines).
- Default calendar: `primary`.
- Agent writes are blocked by default.

2. `ops`
- Default for `agentic`/system operations when calendar tracking is needed.
- Intended for maintenance windows, autonomous run windows, and operational markers.
- Default calendar: `mojo_assistant_ops`.
- Agent writes are allowed.

## Core Rules

- Agent writes to `primary` require explicit opt-in.
- Agent tasks should be scope-constrained (`ops` by default).
- If Google API call fails, scheduler can fall back to local persistence (`.memory/scheduler/*.json`, ICS files).

## Recommended Task Fields

For scheduler tasks that use Google Calendar, include:

- `provider`: `google_calendar`
- `calendar_scope`: `user` or `ops`
- `calendar_id`: optional override (if omitted, resolved from scope policy)
- `timezone`: optional override (default from policy)

Example:

```json
{
  "task_type": "scheduled",
  "config": {
    "provider": "google_calendar",
    "calendar_scope": "user",
    "title": "Weekly Planning",
    "details": "Review priorities and blockers"
  }
}
```

MCP example (`scheduler_add_task`) for a user-owned Google Calendar event:

```json
{
  "task_id": "gc_sched_smoke_001",
  "task_type": "scheduled",
  "priority": "high",
  "description": "Create a user calendar event via scheduler",
  "config": {
    "provider": "google_calendar",
    "task_owner": "user",
    "calendar_scope": "user",
    "title": "Scheduler Google Test",
    "details": "Created by scheduled task through google calendar provider",
    "start_time": "2026-03-07T18:30:00+08:00",
    "duration_minutes": 30
  }
}
```

Expected result fields in `scheduler_get_task(task_id)`:

- `result.metrics.provider = "google_calendar"`
- `result.metrics.event_id` (Google event id)
- `result.metrics.html_link` (Google Calendar event URL)

## Notes

- Google Calendar support depends on `gws` being installed and authenticated first.
- This policy is intentionally simple and can be expanded with allowlists (domains/calendar IDs) later.
- Keep `user` and `ops` calendars separate for audit clarity.
