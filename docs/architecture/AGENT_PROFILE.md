# Agent Profile Specification

**Version:** 1.0
**Status:** Draft
**Location:** `docs/architecture/AGENT_PROFILE.md`

---

## Purpose

Before any external agent can be connected to MoJo, it must be described using a standardised **Agent Profile**. The profile declares what the agent can do, how it communicates, and what MoJo integration work is required.

This serves three purposes:

1. **User-facing** — tells users what capabilities are available and what they need to install.
2. **Developer-facing** — defines what adapter/extension work is needed before an agent is supported.
3. **Test-driven** — each profile axis has a corresponding capability test; an agent is only considered integrated once all declared tests pass.

---

## Profile Axes

An agent profile is defined by six axes. Each axis is an enum — pick the value that best describes the agent.

### Axis 1 — Communication Protocol

How MoJo talks to the agent.

| Value | Description | Example |
|-------|-------------|---------|
| `http_rest` | HTTP REST API, JSON request/response | OpenCode |
| `stdio` | stdin/stdout, line-oriented or JSON-RPC | Claude Code CLI |
| `websocket` | WebSocket, bidirectional streaming | Some browser agents |
| `mcp` | MCP protocol over stdio or HTTP | Any MCP-compliant tool |
| `custom` | Non-standard — extension required | Proprietary agents |

---

### Axis 2 — Session Model

Whether the agent maintains state between calls, and what happens on disconnect.

| Value | Description | HITL implication |
|-------|-------------|-----------------|
| `stateless` | Each call is independent — no session | Simple — no resume needed |
| `stateful_reconnectable` | Sessions exist and survive client disconnect | Full suspend/resume supported |
| `stateful_volatile` | Sessions exist but are lost on disconnect | Must complete in one connection or restart |

---

### Axis 3 — Execution Model

How the agent returns results.

| Value | Description | MoJo handling |
|-------|-------------|--------------|
| `blocking` | Call blocks until response is ready | Run as background asyncio task |
| `async_poll` | Call returns immediately; poll for result | Polling loop required |
| `streaming` | Response streams back incrementally | Stream reader required |
| `event_driven` | Agent pushes events (SSE, webhook, WS) | Event subscriber required |

---

### Axis 4 — Permission Model

Whether the agent requests human approval before taking actions, and how.

| Value | Description | MoJo handling |
|-------|-------------|--------------|
| `none` | Agent acts freely, no permission system | No bridge needed |
| `inline_sync` | Blocks on a terminal/UI prompt | Must intercept stdin or wrap subprocess |
| `async_queue` | Permission goes to a REST queue; async response | Poll `GET /permission`, respond when ready |
| `event_push` | Permission pushed via SSE or webhook | Subscribe to event stream |

> **Note on `async_queue` + `blocking` combination (e.g. OpenCode):**
> The agent blocks the HTTP connection while waiting for permission. The permission
> simultaneously appears in a REST queue (`GET /permission`). The correct pattern is:
> run `send_message` as a background task, poll the permission queue in parallel,
> respond to the permission (`POST /permission/:id/reply`), and the blocked
> `send_message` will return automatically.

---

### Axis 5 — Input / Output Capabilities

What the agent can consume and produce.

**Input types:**

| Value | Description |
|-------|-------------|
| `text` | Natural language instructions |
| `vision` | Screenshots, images, screen content |
| `file_read` | Can read files from the filesystem |
| `file_write` | Can write files (may trigger permissions) |
| `shell` | Can execute shell/terminal commands |
| `browser` | Can control a web browser |
| `audio` | Can process audio input |

**Output types:**

| Value | Description |
|-------|-------------|
| `text` | Natural language responses |
| `code` | Generates or edits code |
| `file_mutations` | Creates/modifies files |
| `shell_output` | Returns command output |
| `structured` | Returns structured data (JSON, etc.) |
| `visual` | Returns screenshots or visual diffs |

---

### Axis 6 — HITL Translation

What MoJo must build to surface agent events to the user inbox.

| Value | Description | Build effort |
|-------|-------------|-------------|
| `native` | Agent uses MoJo's own HITL API directly | None |
| `permission_bridge` | Translate agent permissions → MoJo inbox events | Medium — pattern established (see OpenCode) |
| `input_bridge` | Agent needs user text input mid-task | Low — use `waiting_for_input` |
| `visual_bridge` | Agent produces/requires visual content | High — needs vision model integration |
| `custom_bridge` | Non-standard translation needed | High — extension required |

---

## Install Tier

Based on the six axes, every agent is assigned an **install tier** that tells users and developers what is required to use it.

| Tier | Name | Meaning | User experience |
|------|------|---------|----------------|
| **0** | `auto` | Fully supported. Standard adapter exists, all capabilities verified. | One-click install |
| **1** | `semi_auto` | Mostly supported. Needs minor manual config (e.g. start a local server). | Install + configure |
| **2** | `extension_required` | Core adapter exists but one or more capability bridges are missing or unverified. | Install extension first |
| **3** | `known_unsupported` | Agent type is known but no adapter exists yet. | Cannot install — contribution welcome |
| **4** | `unknown` | Not yet profiled. | Must profile before installing |

---

## Known Agent Profiles

### OpenCode

```yaml
agent_type: opencode
version: ">=0.3"
protocol: http_rest
session_model: stateful_reconnectable
execution_model: blocking
permission_model: async_queue
input_capabilities: [text, file_read, file_write, shell]
output_capabilities: [text, code, file_mutations, shell_output]
hitl_translation: permission_bridge
install_tier: 1  # semi_auto — requires local OpenCode server running
notes: >
  send_message blocks the HTTP connection while awaiting permission.
  Permission simultaneously appears in GET /permission queue.
  Sessions survive client disconnect and can be rejoined.
  SSE (permission.asked) is unreliable — use polling as primary detection.
```

**Verified capabilities (OpenCode, 2026-03):**

| Capability | Test | Result |
|-----------|------|--------|
| CAP-1-1 Create session | `test_cap_1_1` | PASS |
| CAP-1-2 Session persists across clients | `test_cap_1_2` | PASS |
| CAP-2-1 send_message blocks until complete | `test_cap_2_1` | PASS |
| CAP-2-2 send_message safe as background task | `test_cap_2_2` | PASS |
| CAP-2-3 get_messages reflects completed turn | `test_cap_2_3` | PASS |
| CAP-3-1 Permission detected via polling | `test_cap_3_1` | PASS |
| CAP-3-2 Permission detected via SSE | `test_cap_3_2` | **UNRELIABLE** — use polling |
| CAP-3-3 respond_to_permission unblocks send | `test_cap_3_3` | PASS |
| CAP-4-1 Cancel send + respond completes action | `test_cap_4_1` | PASS |
| CAP-4-2 New message after suspend/resume | `test_cap_4_2` | PASS |
| CAP-5-1 Two concurrent sessions | `test_cap_5_1` | PASS |
| CAP-6-1 Health check | `test_cap_6_1` | PASS |
| CAP-6-2 Empty permission list when none | `test_cap_6_2` | PASS |
| CAP-6-3 Stale permission ID handled gracefully | `test_cap_6_3` | PASS |

---

### Claude Code (CLI)

```yaml
agent_type: claude_code
version: ">=1.0"
protocol: stdio
session_model: stateful_volatile
execution_model: streaming
permission_model: inline_sync
input_capabilities: [text, file_read, file_write, shell, mcp]
output_capabilities: [text, code, file_mutations, shell_output]
hitl_translation: input_bridge
install_tier: 1  # semi_auto — requires claude CLI installed + authenticated
notes: >
  Runs as a subprocess. Permissions are requested inline via stdout.
  Sessions are process-bound — if the process dies, session is lost.
  Must intercept stdout to detect permission prompts.
  Streaming output requires incremental reader.
```

**Verified capabilities:** _Not yet tested — profile is preliminary._

---

### Screen / Visual Agent (hypothetical)

```yaml
agent_type: visual_screen_agent
protocol: http_rest  # or websocket
session_model: stateful_reconnectable
execution_model: async_poll
permission_model: none
input_capabilities: [text, vision]
output_capabilities: [text, visual, structured]
hitl_translation: visual_bridge
install_tier: 2  # extension_required — visual_bridge not yet built
notes: >
  Requires a vision-capable LLM to transcribe screenshots.
  MoJo must render screenshots in the inbox for user review.
  No permission system — agent acts freely; HITL is for user review of actions.
```

**Verified capabilities:** _Not yet profiled._

---

## Adding a New Agent

To integrate a new agent type, follow these steps:

### Step 1 — Write the profile YAML

Copy the template below and fill in all six axes. Add it to the **Known Agent Profiles** section above.

```yaml
agent_type: <name>
version: "<version range>"
protocol: <http_rest|stdio|websocket|mcp|custom>
session_model: <stateless|stateful_reconnectable|stateful_volatile>
execution_model: <blocking|async_poll|streaming|event_driven>
permission_model: <none|inline_sync|async_queue|event_push>
input_capabilities: [<list>]
output_capabilities: [<list>]
hitl_translation: <native|permission_bridge|input_bridge|visual_bridge|custom_bridge>
install_tier: <0-4>
notes: >
  <Any known quirks, API gotchas, or integration notes>
```

### Step 2 — Run the capability test plan

The capability tests live in:
```
submodules/coding-agent-mcp-tool/tests/test_hitl_capability_plan.py
```

For agents with a different backend, create a parallel test file:
```
tests/test_hitl_capability_plan_<agent_type>.py
```

Run all capability tests and record the results in the **Verified capabilities** table.

### Step 3 — Identify gaps

Any test that FAILs or is SKIPPED is a gap. For each gap, either:

- **Accept the limitation** — mark as known, design around it.
- **Build a bridge** — write the adapter code needed to fill the gap.
- **Upgrade the install tier** — if the gap is too large for auto-install.

### Step 4 — Build the MoJo adapter

Based on the profile, implement the appropriate components:

| HITL Translation | What to build |
|-----------------|--------------|
| `permission_bridge` | Background permission poller + `respond_to_permission` on HITL reply |
| `input_bridge` | Intercept agent stdout for prompts; surface via `waiting_for_input` |
| `visual_bridge` | Screenshot capture + vision model transcription + visual inbox renderer |
| `custom_bridge` | Custom event mapping between agent events and MoJo inbox |

### Step 5 — Wire into the AgentRegistry

Add the new manager class to `app/mcp/agents/registry.py` and gate it behind an env var:

```python
if os.getenv("ENABLE_MY_AGENT", "false").lower() in ("true", "1", "yes"):
    from app.mcp.my_agent.manager import MyAgentManager
    self._managers["my_agent"] = MyAgentManager(logger=logger)
```

---

## HITL Flow Reference

The standard HITL flow for any agent with `permission_bridge`:

```
Task starts
│
├── [background] send_message → BLOCKS (held by agent while processing)
│
├── [background] permission poller (GET /permission or SSE every 3s)
│       │
│       └── permission detected
│               │
│               ├── [auto-approve path]  respond_to_permission("once")
│               │       └── send_message unblocks → result returned → task continues
│               │
│               └── [HITL path]  save session_id + perm_id
│                       task → waiting_for_input → user inbox
│                       │
│                       user replies → respond_to_permission
│                       task resumes → send new message to same session
│                       session rejoined → LLM continues from current state
│
└── send_message returns → LLM processes result → continues or finishes
```

Key properties verified for OpenCode (must verify for each new agent):
- `send_message` stays blocked while permission is pending ✓
- Session survives client disconnect ✓
- `respond_to_permission` completes the action server-side ✓
- New message to same session works after suspend/resume ✓
