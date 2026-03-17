# Notifications Setup Guide

MoJoAssistant uses an **independent push adapter** model for notifications.
Every adapter is a separate reader of the same persistent event log — enabling
or disabling one has zero effect on any other.

---

## How It Works

```
Producers (scheduler, config changes, resource events)
    │
    ▼
SSENotifier.broadcast()
    │
    ├──► EventLog (.memory/events.json)   ← single source of truth
    │         │
    │    ┌────┴──────────────────────────────┐
    │    ↓                ↓                  ↓
    │  SSE stream     MCP polling       Push adapters
    │  /events/tasks  get_recent_       (ntfy, FCM, ...)
    │  (WebSocket)    events()
    │                 (Claude Desktop)
    │
    └──► fans out to live WebSocket subscribers in real-time
```

Each push adapter:
- Has its own **cursor** persisted in `.memory/cursors/{id}.json`
- Applies its own **filter** (severity threshold, event types, notify_user flag)
- Delivers via its own channel — no shared state with others

---

## Enabling Notifications

### 1. Copy the example config

```bash
cp config/notifications_config.json.example config/notifications_config.json
```

### 2. Edit `config/notifications_config.json`

The file has one entry per adapter. Set `"enabled": true` and fill in
channel-specific settings.

### 3. Restart the server or reload via MCP

```
config set notifications adapters[0].enabled true
```

The `_on_notifications_config_change` hook hot-reloads all adapters — no
server restart needed when changing notification config.

---

## Built-in Adapters

### ntfy (recommended first adapter)

[ntfy](https://ntfy.sh) delivers push notifications to Android, iOS, and
desktop apps. No account required for public topics.

```json
{
  "id": "ntfy_push",
  "type": "ntfy",
  "enabled": true,
  "endpoint": "https://ntfy.sh/YOUR_TOPIC_NAME",
  "filter": {
    "min_severity": "warning",
    "notify_user_only": true,
    "event_types": ["task_failed", "task_completed", "system_notification"]
  }
}
```

**Optional auth** (for protected topics):
```json
"auth_var": "NTFY_TOKEN"
```
Set `NTFY_TOKEN=your-bearer-token` in your `.env` file.

**Self-hosted ntfy:**
```json
"endpoint": "https://ntfy.your-domain.com/your-topic"
```

**Priority mapping** (optional override):
```json
"priority_map": {
  "info": "default",
  "warning": "high",
  "error": "urgent",
  "critical": "urgent"
}
```

### SSE stream (built-in, always-on)

`GET /events/tasks` — long-lived HTTP stream for browser/CLI clients.

```bash
curl -N http://localhost:8000/events/tasks
```

No configuration needed — this adapter is always active regardless of
`notifications_config.json`.

### MCP polling (built-in, always-on)

Claude Desktop and other MCP clients use `get_recent_events` to poll the
event log. No configuration needed.

```
get_recent_events(limit=20, include_data=true)
```

Use `since_timestamp` to advance your cursor and only fetch new events:
```
get_recent_events(since_timestamp="2026-03-17T04:00:00", types=["task_failed"])
```

---

## Event Types

| event_type | severity | notify_user | Description |
|---|---|---|---|
| `task_started` | info | false | Agentic/dreaming task began |
| `task_completed` | info | false | Task finished successfully |
| `task_failed` | error | **true** | Task failed permanently |
| `scheduler_tick` | info | false | Heartbeat every ~10 ticks |
| `config_changed` | info | false | Config updated via MCP tool |

### Event envelope

Every event includes:

```json
{
  "id": "uuid",
  "event_type": "task_failed",
  "timestamp": "2026-03-17T04:01:23.441Z",
  "severity": "error",
  "title": "Task ahman_weekly_security_review failed",
  "notify_user": true,
  "data": {
    "task_id": "ahman_weekly_security_review",
    "task_type": "assistant",
    "error": "..."
  }
}
```

`notify_user: true` is set automatically when `severity` is `warning`, `error`,
or `critical`. Push adapters default to filtering on `notify_user_only: true`
so only actionable events reach your phone.

---

## Cursor Persistence

Each adapter stores its read position in `.memory/cursors/{adapter_id}.json`:

```json
{ "cursor": "2026-03-17T04:01:23.441Z", "updated": "2026-03-17T04:01:25.000Z" }
```

On server restart, each adapter resumes from its last position — no duplicate
notifications, no missed events (within the 500-event window).

To reset an adapter's cursor (replay recent events):
```bash
rm .memory/cursors/ntfy_push.json
```

---

## Adding a New Push Channel

1. Create `app/mcp/adapters/push/myservice.py`:

```python
from app.mcp.adapters.push.base import PushAdapter

class MyServiceAdapter(PushAdapter):
    adapter_type = "myservice"

    async def dispatch(self, event: dict) -> None:
        title = self._format_title(event)
        body = self._format_body(event)
        # ... send via your service's API
```

2. Register it in `app/mcp/adapters/push/manager.py` `_register_builtins()`:

```python
from app.mcp.adapters.push.myservice import MyServiceAdapter
_ADAPTER_REGISTRY["myservice"] = MyServiceAdapter
```

3. Add an entry to `notifications_config.json`:

```json
{
  "id": "my_push",
  "type": "myservice",
  "enabled": true,
  "filter": { "min_severity": "warning" }
}
```

No other code changes needed.

---

## Troubleshooting

**Notifications not arriving:**
- Check `.memory/cursors/{id}.json` — if cursor is at current time, the adapter
  has already processed all events.
- Check server logs for `[push/{id}]` lines.
- Verify `enabled: true` in `notifications_config.json` (not the `.example` file).
- Run `get_recent_events(types=["task_failed"], limit=5)` to confirm events exist.

**ntfy returns 401:**
- Set `NTFY_TOKEN` env var or remove `auth_var` field for public topics.

**ntfy returns 403:**
- Topic is reserved or the server requires auth. Use a different topic name.

**Adapter not loading:**
- Unknown `type` value: check that it matches a key in `_ADAPTER_REGISTRY`.
- Import error in adapter file: check server startup logs.
