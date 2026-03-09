# Google Workspace Setup

This guide prepares MoJoAssistant to use Google Workspace features through the external `gws` CLI.

Use this before:
- `google_service` MCP calls
- scheduler tasks with `provider: "google_calendar"`

## Prerequisites

- `gcloud` installed and working
- `gws` installed and available in `PATH`
- a Google account with access to the target calendar/workspace data

## Step 1: Install and authenticate `gcloud`

Install Google Cloud SDK:
- https://cloud.google.com/sdk/docs/install

Authenticate application-default credentials:

```bash
gcloud auth application-default login
```

## Step 2: Install and authenticate `gws`

Install `gws` using the method you prefer, then confirm it is in `PATH`:

```bash
gws --help
```

Authenticate:

```bash
gws auth login
```

If you want the broader Google Workspace surface used in MoJoAssistant, enable at least:
- `calendar`
- `drive`
- `sheets`
- `gmail`
- `docs`
- `people`

## Step 3: Verify access

Verify the account and calendar access:

```bash
gws calendar calendars list
```

If this fails, fix `gcloud`/`gws` authentication before testing MoJoAssistant.

## Step 4: Test through MoJoAssistant

Example `google_service` call:

```json
{
  "service": "calendar",
  "resource": "events",
  "method": "list",
  "params": {
    "calendarId": "primary",
    "maxResults": 10,
    "singleEvents": true,
    "orderBy": "startTime"
  }
}
```

Example scheduler task:

```json
{
  "task_id": "gc_sched_smoke_live",
  "task_type": "scheduled",
  "priority": "high",
  "description": "Create a user calendar event via scheduler",
  "config": {
    "provider": "google_calendar",
    "task_owner": "user",
    "calendar_scope": "user",
    "title": "MoJo Scheduler Test",
    "details": "Created by scheduled task through google calendar provider",
    "start_time": "2026-03-09T18:30:00+08:00",
    "duration_minutes": 30
  }
}
```

Expected result fields from `scheduler_get_task(task_id)`:
- `result.metrics.provider = "google_calendar"`
- `result.metrics.event_id`
- `result.metrics.html_link`

## Notes

- MoJoAssistant does not replace `gws`; it delegates Google Workspace operations to it.
- If Google Calendar calls fail, scheduler may fall back to local persistence depending on task/provider path.
- Keep user calendar and ops calendar separated. See:
  - `docs/guides/GOOGLE_CALENDAR_SCHEDULER_POLICY.md`
