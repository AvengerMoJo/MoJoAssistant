# Release Notes — v1.2.9-beta

## Agentic Executor — Budget Extension & Tool Fix

### Bug Fix: `available_tools` category names not expanded (critical)

When a task specified `available_tools: ["browser", "memory", "file"]` as a runtime override,
the executor used those strings as-is instead of expanding them through the tool catalog.
This meant the LLM received an empty `tool_defs` list and could not call any tools.

**Root cause:** The role-based path (`_resolve_tools_from_role`) correctly expanded category
names → tool names via `tool_catalog.json`. The task override path bypassed this expansion
entirely.

**Fix:** `available_tools` overrides now go through the same `_resolve_tools_from_role`
expansion. Category names like `"browser"` resolve to `browser_navigate`, `browser_snapshot`,
`browser_click`, etc. Explicit tool names continue to work unchanged.

### Feature: Budget extension mechanism

Agents can now request more iterations instead of being forced to truncate mid-task.

When nearing the iteration limit, the agent sees two options:
- **Option A** — Task is complete → produce `<FINAL_ANSWER>`
- **Option B** — Task not done → write `BUDGET_EXTENSION_REQUEST: Need N more iterations. Done: [...]. Remaining: [...]`

The system grants the request automatically (capped at 20 per extension). Detection works
both via plain-text in the assistant response and via `ask_user` tool call.

Previously, the near-limit prompt forced an immediate FINAL_ANSWER and stripped tools from
the LLM call — both of which caused worse outcomes. Tool stripping has been removed.

### Change: MCP call timeout 60s → 300s

Browser automation against SPAs (e.g. Portainer) regularly exceeded the 60-second timeout
during page navigation and JavaScript rendering. Raised to 300 seconds.

### Change: `push_manager` wired to Scheduler and ToolRegistry

Groundwork for push notification broadcast from the scheduler. The `PushAdapterManager`
instance is now passed through to the scheduler and tool registry.

---

## Role: Bao — Autonomous Agent Mode

Added an **Autonomous agent mode** section to Bao's system prompt.

**Problem:** Bao's personality ("asks clarifying questions first, then dives in") caused him
to burn iterations on `ask_user` calls before touching a single tool. In agentic tasks, every
`ask_user` pauses the entire task and costs a full iteration.

**Fix:** New role section explicitly overrides that behavior when running as a scheduled agent:
- Attempt first — take a snapshot, try a selector, adapt on failure
- Do NOT ask permission before using browser tools
- Do NOT ask the user to run tools on his behalf
- Only use `ask_user` for genuine blockers (missing credentials, ambiguous destructive actions)
- Listed all `browser_*` tool names directly in the prompt

**Result:** Bao completed a Portainer ntfy deployment in 24 iterations of real tool calls
(navigate → snapshot → click → type → evaluate → deploy → verify) with zero `ask_user` calls.

---

## Infrastructure: Self-hosted ntfy on MoJoAI

Self-hosted ntfy deployed as a Docker stack on MoJoAI (192.168.2.248) via Portainer.

- Stack name: `ntfy`
- Image: `binwiederhier/ntfy`
- Port: `2586:80`
- URL: `http://192.168.2.248:2586`
- Volumes: `ntfy-cache`, `ntfy-etc` (persistent)

Replaces dependency on the public `ntfy.sh` endpoint. Next step: update
`notifications_config.json` to point to the self-hosted instance and wire in Apprise
as a unified notification layer.
