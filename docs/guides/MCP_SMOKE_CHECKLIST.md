# MCP Smoke Checklist

Use this checklist after an MCP restart or before a release candidate merge.

This is not a full automated test suite. It is a short live verification of the highest-risk MCP paths in the current release scope.

## Preconditions

- MCP server is running and authenticated
- `gws` is installed and authenticated if you want Google Calendar checks
- OpenRouter free-api keys are loaded if you want agentic free-api checks

## 1. Resource Pool Status

Check that runtime resources are visible:

- Call `resource_pool_status`
- Verify expected resources are `available`
- Verify OpenRouter free-api accounts appear if configured

Pass criteria:
- no status error
- expected resource IDs are present

## 2. Google Calendar Read Path

Check generic Google Workspace access:

Example:

```json
{
  "service": "calendar",
  "resource": "events",
  "method": "list",
  "params": {
    "calendarId": "primary",
    "maxResults": 5,
    "singleEvents": true,
    "orderBy": "startTime"
  }
}
```

Pass criteria:
- `google_service` returns `status = success`
- result contains calendar event data

## 3. Google Calendar Scheduled Task Write Path

Create a real scheduler task using Google Calendar:

```json
{
  "task_id": "gc_sched_smoke_live",
  "task_type": "scheduled",
  "priority": "high",
  "description": "Google Calendar scheduler smoke test",
  "config": {
    "provider": "google_calendar",
    "task_owner": "user",
    "calendar_scope": "user",
    "title": "MoJo Scheduler Smoke Test",
    "details": "Created by scheduler smoke checklist",
    "start_time": "2026-03-10T19:00:00+08:00",
    "duration_minutes": 15
  }
}
```

Then call `scheduler_get_task(task_id)`.

Pass criteria:
- `result.success = true`
- `result.metrics.provider = "google_calendar"`
- `result.metrics.event_id` exists
- `result.metrics.html_link` exists

## 4. Agentic Free-API Path

Run a short agentic task that forces free-api routing.

Example:

```json
{
  "task_id": "agentic_freeapi_smoke_live",
  "task_type": "agentic",
  "priority": "high",
  "description": "Free API agentic smoke test",
  "config": {
    "mode": "normal",
    "goal": "Return FINAL_ANSWER containing exactly: smoke-ok",
    "max_iterations": 3,
    "tier_preference": ["free_api"]
  }
}
```

Then call:
- `scheduler_get_task(task_id)`
- optionally `task_session_read(task_id)`

Pass criteria:
- task completes
- iteration log shows a concrete resolved model, not only `openrouter/auto`
- final answer is correct

## 5. Parallel Discovery Review Path

Run a parallel review task:

```json
{
  "task_id": "agentic_parallel_smoke_live",
  "task_type": "agentic",
  "priority": "high",
  "description": "Parallel discovery smoke test",
  "config": {
    "mode": "parallel_discovery",
    "goal": "Return FINAL_ANSWER containing exactly: alpha",
    "max_iterations": 3,
    "parallel_agents": {
      "enabled": true,
      "goal_variants": [
        "Return FINAL_ANSWER containing exactly: alpha",
        "Return FINAL_ANSWER containing exactly: beta",
        "Return FINAL_ANSWER containing exactly: gamma"
      ],
      "max_concurrent": 3,
      "review_policy": {
        "auto_decide": false
      }
    }
  }
}
```

Then call `scheduler_get_task(task_id)`.

Pass criteria:
- parent task completes
- `result.metrics.review_report` exists
- `review_report.summary` exists
- `review_report.recommendation_reason` exists
- `review_report.recommended_next_actions` exists
- `decision_required = true` unless explicitly overridden

## 6. Session Output Check

For at least one agentic task, read the session:

- Call `task_session_read(task_id)`

Pass criteria:
- session exists
- messages are readable
- final answer or failure reason is preserved

## Recommended Order

1. `resource_pool_status`
2. `google_service` calendar list
3. `scheduled` Google Calendar write
4. `agentic` free-api
5. `parallel_discovery`
6. `task_session_read`

## Notes

- If Google checks fail, verify `gcloud` and `gws` first:
  - `docs/guides/GOOGLE_WORKSPACE_SETUP.md`
- If free-api checks fail, verify resource pool env keys and OpenRouter auth.
- This checklist is intended for live MCP verification, not unit testing.
