# Release Notes — v1.2.7-beta

## Theme: Security Depth — Behavioral Monitoring, Role Chat, and Agentic Delegation

v1.2.7 extends the safety foundation from v1.2.6 in two directions: wider threat
coverage (behavioral security patterns + a self-running security sentinel), and
deeper agent capability (sub-task dispatch, role chat persistence, dashboard UX
polish). Every new feature ships with unit tests; the full suite is green at
342 passing / 2 skipped.

---

## 1. Behavioral Security Patterns (`config/behavioral_patterns.json`)

`ContentAwarePolicyChecker` now loads a second pattern file covering active
threat categories beyond API key leaks:

| Category | Examples |
|----------|---------|
| Credential paths | `.ssh/id_rsa`, `.aws/credentials`, `.kube/config`, `.netrc`, GPG key store |
| C2 / reverse shells | `/dev/tcp/`, `nc -e /bin/sh`, Python/Perl socket reverse shells, `socat EXEC:bash`, `mkfifo` pipe shells |
| Data exfiltration | Large base64 payloads, `curl --data` to external URLs, `scp`/`rsync` outbound transfers |
| Privilege escalation | `chmod` SUID/SGID bit, `crontab -e`, `LD_PRELOAD=` injection |

23 new patterns across 4 categories. Any match blocks the tool call with a
`policy_violation` event regardless of whether the severity tag is `block` or
`warn`.

### Pattern override

Personal patterns live at `~/.memory/config/behavioral_patterns.json`. Later
files overwrite earlier ones by pattern name — add patterns or raise/lower
severity without touching the repo.

### Pattern load order

1. `config/policy_patterns.json` — secrets / PII (system)
2. `config/behavioral_patterns.json` — behavioral threats (system, new)
3. `~/.memory/config/policy_patterns.json` — personal policy overlay
4. `~/.memory/config/behavioral_patterns.json` — personal behavioral overlay

---

## 2. Security Sentinel Role (`~/.memory/roles/security_sentinel.json`)

A scheduled background role that audits the EventLog nightly and writes a
structured security digest to memory.

```json
{
  "local_only": true,
  "schedule_cron": "0 3 * * *",
  "model_preference": "lmstudio",
  "tool_access": ["memory", "file"]
}
```

The sentinel runs at 03:00 every night, reads the EventLog for policy
violations and baseline deviations, and writes a digest under the memory key
`security/digest_YYYY-MM-DD`. No external API calls — fully `local_only`.

Registered in `config/scheduler_config.json` as `security_sentinel_nightly`
(`tier_preference: "free"`, type `assistant`).

---

## 3. MCPServerManager Stop/Restart Hardening

`MCPServerManager.stop_server()` and `restart_server()` now guarantee a clean
state even when peers or reconnects fail:

- **Stop**: if any sibling server fails to stop, the manager retries the
  failed siblings up to 2 times, then returns a `partial` status listing which
  servers are still running.
- **Restart**: stop errors cause the restart to abort early (target server is
  never left in a half-started state); reconnect errors surface as a `partial`
  warning rather than an unhandled exception.
- Already-disconnected servers on stop return `ok` (idempotent).

---

## 4. Sub-Agent Dispatch (`dispatch_subtask`)

Scheduler tasks can now spawn child tasks using the `dispatch_subtask` tool:

```json
{
  "tool": "dispatch_subtask",
  "args": {
    "task_type": "assistant",
    "role_id": "researcher",
    "description": "Summarise latest policy violations",
    "depth": 1
  }
}
```

- `depth` is incremented from parent to child (max 3 by default).
- Depth-limit blocks delegation loops: a task at depth 3 cannot dispatch
  further.
- Tasks without a live scheduler instance return a graceful error, not a crash.

---

## 5. Role Chat Interface — Dashboard (`/dashboard/chat`)

Persistent conversation UI for any MoJoAssistant role, accessible from the
monitoring dashboard.

### Features

- Chat history stored at `~/.memory/roles/{role_id}/chat_history/{session_id}.json`
- Session sidebar: all previous sessions listed, newest first
- **+ New Chat** button now correctly opens a blank session (fixed: previously
  it loaded the most recent session instead of creating a new one)
- First message auto-creates the session ID; subsequent messages append to it
- Memory tools available inline: `memory_search`, `memory_write`,
  `read_file`, `list_files`
- Think-token stripping (`<think>…</think>`) applied before display

### Session management API (`dialog` tool, `sessions` / `history` actions)

```json
{ "action": "sessions", "role_id": "researcher" }
{ "action": "history",  "role_id": "researcher", "session_id": "abc123" }
```

---

## 6. Test Coverage

| File | Tests | What's covered |
|------|-------|----------------|
| `tests/unit/test_v1_2_7_features.py` | 39 | `dispatch_subtask` depth + error paths, `dialog` tool actions, `RoleChatSession` load/save/history/search, `MCPServerManager` stop/restart rollback, `list_chat_sessions` |
| `tests/unit/test_dreaming_parsing.py` | Updated | Chunker/synthesizer graceful fallback (was: fail-fast RuntimeError) |
| Various integration tests | Fixed | `@pytest.mark.asyncio` added; `asyncio.run()` replaces deprecated `get_event_loop()` |

**Suite totals: 342 passed, 2 skipped, 0 failures.**

---

## Upgrade Notes

### Enable behavioral pattern scanning

No action required — `ContentAwarePolicyChecker` loads
`config/behavioral_patterns.json` automatically when `content_check: true`
(the default).

To add custom patterns without touching the repo:

```bash
mkdir -p ~/.memory/config
# create ~/.memory/config/behavioral_patterns.json with your patterns
```

### Enable the Security Sentinel

1. Copy `~/.memory/roles/security_sentinel.json` to your memory directory
   (already done on fresh installs).
2. The nightly cron entry is in `config/scheduler_config.json` — it will be
   picked up on next scheduler restart.

### Sub-task dispatch depth

The default max depth is 3. Override per-role:

```json
"dispatch": { "max_depth": 5 }
```

---

## What's Next (v1.3.x)

- Inbox-subscribing PolicyAgent — cross-agent proactive blocking with reasoning
- Agent learning loop — sentinel findings feed back into role policy updates
- Hybrid memory search — BM25 + embedding reranking for research roles
