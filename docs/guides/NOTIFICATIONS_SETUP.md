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
desktop apps. MoJoAssistant POSTs to a topic URL; your ntfy client receives it.

#### Option A — Quick test (no account)

Public topics require no signup but are unprotected — anyone who knows
the topic name can publish or subscribe.

1. Pick a random topic name, e.g. `mojoassistant-abc123`
2. Open https://ntfy.sh/mojoassistant-abc123 in your browser **or** install
   the [ntfy app](https://ntfy.sh/#subscribe) and subscribe to that topic
3. Set the endpoint in config — no `auth_var` needed:

```json
{
  "id": "ntfy_push",
  "type": "ntfy",
  "enabled": true,
  "endpoint": "https://ntfy.sh/mojoassistant-abc123",
  "filter": { "min_severity": "warning", "notify_user_only": true }
}
```

#### Option B — With account (recommended for production)

Protected topics require a token to publish, so only you can send to them.

1. Create a free account at [ntfy.sh](https://ntfy.sh)
2. Go to **Account → Access Tokens → Create token** → copy the token
3. Add it to your `.env`:
   ```
   NTFY_TOKEN=tk_yourtokenhere
   ```
4. Install the ntfy app on your phone (Android/iOS) **or** open
   https://ntfy.sh in a browser
5. In the app: tap **Subscribe** → enter your topic name → tap Subscribe
   - The app will now receive pushes for that topic
6. Set the config — `auth_var` tells MoJoAssistant which env var holds the token:

```json
{
  "id": "ntfy_push",
  "type": "ntfy",
  "enabled": true,
  "endpoint": "https://ntfy.sh/YOUR_TOPIC_NAME",
  "auth_var": "NTFY_TOKEN",
  "filter": {
    "min_severity": "warning",
    "notify_user_only": true,
    "event_types": ["task_failed", "task_completed", "system_notification"]
  }
}
```

> **Important**: subscribing in the app is what makes notifications appear on
> your device. MoJoAssistant only *publishes* — the ntfy app or browser tab
> is what *receives* them. If you haven't subscribed to the topic in the app,
> nothing will appear even if delivery succeeds.

#### Self-hosted ntfy

If you run your own ntfy server, just swap the domain:
```json
"endpoint": "https://ntfy.your-domain.com/your-topic"
```

#### Priority mapping (optional)

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

**No notification on phone even though delivery succeeded:**
- You must **subscribe to the topic in the ntfy app** before notifications appear.
  MoJoAssistant only publishes — the app is what receives. Open the ntfy app,
  tap Subscribe, and enter your exact topic name.

**Notifications not arriving at all:**
- Check `.memory/cursors/{id}.json` — if the cursor is already at the current
  time, the adapter has processed all events and found nothing matching the filter.
- Check server logs for `[push/ntfy_push]` lines — look for `dispatched` or errors.
- Temporarily set `min_severity: info` and `notify_user_only: false` in the filter
  to confirm the pipeline works with low-severity events, then tighten the filter.
- Verify `enabled: true` in `config/notifications_config.json` (not `.example`).
- Run `get_recent_events(limit=10)` to confirm events are being recorded at all.

**ntfy returns 401:**
- Missing or wrong token. Set `NTFY_TOKEN` in `.env` and make sure `auth_var`
  matches. Or remove `auth_var` entirely for public (unauthenticated) topics.

**ntfy returns 403:**
- Topic name is reserved by another user, or the server requires auth.
  Use a different topic name, or add auth credentials.

**Adapter not loading (no `[push/ntfy_push]` lines in logs):**
- Unknown `type` value: must match a key in `_ADAPTER_REGISTRY` in `manager.py`.
- Import error in adapter file: check server startup logs for the full traceback.
- `enabled` is `false` or missing in config.
