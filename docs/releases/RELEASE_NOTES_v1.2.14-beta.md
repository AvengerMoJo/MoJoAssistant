# Release Notes — v1.2.14-beta

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

### Parallel tool call runaway fix (`parallel_tool_calls=false` + dedup)

Gemma 4 exhibited a generation bug where it batched dozens of **identical** tool calls in a
single response instead of one. Observed: 88 bash_exec calls in iteration 1, 161 in iteration 2,
all with the same `git clone` command. The first call succeeded; the other 87 failed because the
destination already existed, flooding the context with errors and causing the model to spiral.

**Root cause:** The OpenAI spec allows models to return multiple tool calls per response for
genuine parallel work. Local models like Gemma 4 can misuse this to generate runaway batches.

**Fix — two layers:**

1. **`parallel_tool_calls: false`** added to every OpenAI-format payload in `UnifiedLLMClient._build_payload`
   when tools are present. Instructs compliant backends (OpenRouter, GPT-4, Claude API) to issue
   one tool call per response.

2. **Dedup + cap in `_execute_tool_calls`** as a defensive backstop for local models that ignore
   the flag. Identical `(name, args)` pairs in the same response are collapsed to one execution.
   Total calls per turn are also hard-capped at 10.

**Side effects tested:** Qwen 3.5 and Gemma 4 both behaved correctly after the fix — no
regressions on sequential tool use. Qwen already issued one call at a time; Gemma's batching
was eliminated.

**Guidance for model authors:** If your role needs genuinely parallel tool calls (e.g. two
independent searches at once), the dedup will not interfere as long as the calls have different
arguments. The cap (10) is high enough that no legitimate task should hit it.

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

---

## Post-session fixes (same day)

### Double push notification per task completion

Every task completion fired **two** push notifications. Root cause: two separate writes to
`EventLog` per broadcast event.

- `SSENotifier.broadcast()` already writes to `EventLog` (always has).
- The push notification fix (`_broadcast` → `event_log.append`) added a **second** write on top.

`scheduler.core._broadcast` was also accumulating duplicate scheduler daemon threads across
`daemon_restart` calls — two live threads meant two broadcasts per event at the scheduler level,
which doubled again on the EventLog write.

**Fix:** Changed `_broadcast` to write to `EventLog` only in the fallback path (no SSE notifier).
When SSE notifier is wired it owns the EventLog write. Full backend restart required to clear
stale daemon threads; `daemon_restart` alone did not reliably stop the old thread.

**Validated:** 1 notification per task completion after clean restart.

### FINAL_ANSWER fallback completion recovery

Agents that completed their work but forgot to write `<FINAL_ANSWER>` tags were silently going
to `waiting_for_input` instead of completing. The budget extension HITL ("grant more iterations?")
was being triggered even when the agent had nothing left to do.

**Fix:** After the iteration loop exits without a tagged answer, auto-extract the last assistant
response if all conditions hold:
- Last turn had no tool calls (model was writing, not acting)
- Response > 150 chars
- No in-progress patterns ("let me continue", "I'll now", "next I will", etc.)

Provenance stored in metrics: `completion_mode: "auto_extracted"`, `auto_extracted_final_answer: true`.
A proper forced-finalization phase on the last iteration is planned for v1.2.15.

### Scheduler `list` / `detail` separation

`scheduler(action='list')` was calling `task.to_dict()` — dumping full config, result, metrics,
and iteration_log for every task. Too heavy for discovery use.

`list` now returns compact summary rows: `id`, `status`, `type`, `priority`, `role_id`, `goal`
(truncated to 120 chars), timestamps, `pending_question`, `success`, `completion_mode`.
Full detail (config, result, iteration_log) is only returned by `action='get', task_id=...`.
