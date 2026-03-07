# Google Calendar Scheduler Policy

This document defines how MoJoAssistant should use Google Calendar for scheduler tasks.

Policy file:
- `config/google_calendar_scheduler_policy.json`

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

## Notes

- This policy is intentionally simple and can be expanded with allowlists (domains/calendar IDs) later.
- Keep `user` and `ops` calendars separate for audit clarity.
