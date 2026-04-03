# Release Notes — v1.2.9-beta

## Bug Fixes

### `available_tools` category names not expanded (critical)

When a task specified `available_tools: ["browser", "memory", "file"]` as a runtime override,
the executor used those strings as-is instead of expanding them through the tool catalog.
This meant the LLM received an empty `tool_defs` list and could not call any tools.

**Root cause:** The role-based path (`_resolve_tools_from_role`) correctly expanded category
names → tool names via `tool_catalog.json`. The task override path bypassed this expansion
entirely.

**Fix:** `available_tools` overrides now go through `_resolve_tools_from_role`. Category names
like `"browser"` resolve to `browser_navigate`, `browser_snapshot`, `browser_click`, etc.

### Task completion push notifications never fired

`_broadcast()` in the scheduler only sent events to the SSE notifier (web dashboard). The
push adapter manager (ntfy) reads from the `EventLog`, which was never written to by the
scheduler — so no push notification ever fired on task completion, failure, or waiting-for-input.

**Fix:** `_broadcast()` now appends every event to the `EventLog` after SSE dispatch. The
`event_log` instance is passed through from `ToolRegistry` → `Scheduler.__init__`.

### `get_context` blocking inbox showed stale historical tasks

The attention inbox accumulated every past `task_waiting_for_input` event with `hitl_level ≥ 4`
regardless of whether the task was still waiting. Caused blocking[] to grow unboundedly with
resolved/deleted tasks.

**Fixes:**
- Task not found in scheduler (removed/purged) → drop, not show
- Exception during status check → drop (assume resolved)
- No `task_id` on event → drop (unverifiable)
- Non-waiting events at `hitl_level ≥ 4` demoted to `alerts[]` — blocking[] is now exclusively
  for tasks actively waiting for user input right now
- Deduplicate blocking[] by `task_id`, keeping only the newest event per waiting task

---

## Features

### Budget extension mechanism

Agents can now request more iterations instead of being forced to truncate mid-task.

When nearing the iteration limit, the agent sees two options:
- **Option A** — Task complete → produce `<FINAL_ANSWER>`
- **Option B** — Not done → write `BUDGET_EXTENSION_REQUEST: Need N more iterations. Done: [...]. Remaining: [...]`

System grants automatically (capped at 20 per extension). Detection works both via plain-text
in the assistant response and via `ask_user` tool call. Tool stripping on budget warning removed.

### `pinned_resource` — pin a task to a specific LLM resource

Tasks can now be pinned to a specific resource ID, bypassing tier-based selection entirely.

```
scheduler add ... pinned_resource="lmstudio__google_gemma_4_26b_a4b"
```

Enables side-by-side model comparison. Validated: Gemma 4 (3 iterations, 35s) vs Qwen 3.5
(7 iterations, 55s) on the same task — both completed cleanly with FINAL_ANSWER.

### `agentic_capable` flags set on local models

`lmstudio_qwen35b` and `lmstudio__google_gemma_4_26b_a4b` marked `agentic_capable: true`.
Previously `false` or `null` which could cause the executor to skip them for agentic tasks.

---

## Changes

### MCP call timeout 60s → 300s

Browser automation against SPAs (e.g. Portainer) regularly exceeded 60s during page navigation
and JavaScript rendering. Raised to 300 seconds.

### Role: Bao — Autonomous agent mode

Added **Autonomous agent mode** section to Bao's system prompt, overriding the
"asks clarifying questions first" personality for scheduled tasks:
- Attempt first — take a snapshot, try a selector, adapt on failure
- Do NOT ask permission before using browser tools
- Only use `ask_user` for genuine blockers
- All `browser_*` tool names listed directly in the prompt

**Result:** Bao completed a Portainer ntfy deployment in 24 real tool-call iterations with
zero `ask_user` confirmation loops.

---

## Infrastructure

### Self-hosted ntfy on MoJoAI (192.168.2.248)

- Deployed as Docker stack `ntfy` via Portainer on MoJoAI
- Port `2586:80`, volumes `ntfy-cache` + `ntfy-etc`
- URL: `http://192.168.2.248:2586`
- cloudflared tunnel updated: `ntfy.eclipsogate.org` → `http://127.0.0.1:2586`

Replaces dependency on public `ntfy.sh`. Next: update `notifications_config.json` + wire
Apprise as unified notification layer.

---

## Known Issues / Next Steps

- **Zombie task watchdog** — tasks stuck `running` for N hours should be auto-detected and
  marked failed. Currently requires manual cleanup.
- **FINAL_ANSWER discipline** — agents occasionally complete work but exhaust iterations
  without writing `<FINAL_ANSWER>`, causing no notification and `final_answer: null`.
- **Apprise integration** — wire Apprise as Python notification layer over self-hosted ntfy
  for unified multi-channel support.
- **notifications_config.json** — update ntfy endpoint from `ntfy.sh` to self-hosted instance.
