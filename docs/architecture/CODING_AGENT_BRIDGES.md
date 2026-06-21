# Coding Agent Bridges & Skills

> 3rd-party coding agent integration in MoJoAssistant — analysis of existing routes, the decision matrix, and the bridge + skills implementation plan.

**Status:** Implemented on `wip_coding_agent_skill_bridge`; current worktree also adds
CubeSandbox-backed isolation for OpenCode sessions.
**Owner:** repo maintainer
**Last reviewed:** 2026-06-20

---

## Context

The question this document answers:

> Should 3rd-party coding agents (OpenCode, Claude Code) be reached via the existing MCP `external_agent` hub, or should an assistant like Popo call the sandbox opencode / claude directly? Does the 3rd party agent need *another* model to work, or do we build a bridge / skill that operates it directly?

The answer determines the production path for delegating coding work to specialized external agents (file edits, shell, tests, code review) from within MoJoAssistant's role-based scheduler.

---

## The two existing routes

### Route A — `external_agent` MCP hub

**Location:** `app/mcp/core/tools.py:6513`

The `external_agent` tool is a dispatcher with three sub-flavors, all defined in the same file:

| Sub-action | File:line | Purpose |
|---|---|---|
| `ask_user` / `check_reply` | `app/mcp/core/tools.py:6562` + `app/scheduler/hitl_bridge.py` | Inject a question into the HITL inbox and poll for a reply |
| `run_task` | `app/mcp/core/tools.py:6576` | Spawn a headless Claude Code subprocess, with MoJo injected as its MCP server (config generated at `app/mcp/core/tools.py:6685`) |
| `backend_*` | `app/mcp/core/tools.py:6702` | Thin pass-through to `coding-agent-mcp-tool` submodule backends (OpenCode / Claude Code HTTP APIs at `submodules/coding-agent-mcp-tool/src/coding_agent_mcp/backends/`) |

**Properties:** no memory, no persona, no iteration budget, no role binding. Pure protocol gateway. Backends are referenced by `backend_type` (`opencode.py:29`, `claude_code.py:42`).

### Route B — Assistant-style (Popo) calling the backend

**Location:** `app/scheduler/coding_agent_executor.py:103`

Three-tier architecture, per the docstring at `coding_agent_executor.py:7`:

| Tier | Component | Role |
|---|---|---|
| 1 | Local LLM (e.g. `qwen3.5-35b-a3b`) | Wears the role persona + system prompt from `config/roles/popo.json.example:7`. Drives the loop, holds memory, calls `<FINAL_ANSWER>` |
| 2 | `OpenCodeBackend` or `ClaudeCodeBackend` from `coding-agent-mcp-tool` | The "doer" — shell, files, tests, tools |
| 3 | MoJo orchestration in `coding_agent_executor.py` | Permission bridging, HITL routing, session persistence, iteration budget, dream/memory hooks |

**Trigger:** roles with `executor="coding_agent"` in their config (`app/scheduler/handlers/agentic.py:22`). Popo is the canonical example: `executor=coding_agent, backend_type=opencode` (`popo.json.example:7-9`).

**Properties:** role persona, memory, sessions, permission policy, HITL, dream consolidation. The full stack of MoJo's value-add.

In the current worktree, Route B attempts CubeSandbox first when `use_sandbox` is
enabled and no explicit `opencode_url` / `server_id` is set, then falls back to a
direct host URL if the sandbox stack is unavailable.

---

## Decision matrix

| Need | Use |
|---|---|
| Role-driven coding work (persona, memory, multi-step, HITL) | **Route B** (`CodingAgentExecutor`) |
| Spawn Claude Code as a *peer agent* that itself uses MoJo as MCP | **Route A** `run_task` (headless `claude -p` pointed back at MoJo) |
| Direct backend ops from any MCP client | **Route A** `backend_*` |
| One-off "ask the user a question" from a coding subprocess | **Route A** `ask_user` / `check_reply` |
| User-invocable surface (dashboard, voice, Discord, Claude Desktop) | **Bridge + Skills** (this doc) |

**Key insight:** Routes A and B are not competing. Route A's `backend_*` is *exactly* what Route B's Tier 2 calls. The real choice is about *who wears the hat* and *which surface exposes the work*.

---

## Does the 3rd-party agent need another model?

**Yes — and the architecture already enforces this.** Per the docstring at `coding_agent_executor.py:5-12`:

> Tier 1 — local LLM (e.g. qwen3.5-35b-a3b) prompted as the role personality
> Tier 2 — OpenCodeBackend (coding-agent-mcp-tool submodule) — all HTTP API details
> Tier 3 — this file — orchestration, permission bridging, HITL routing

The local LLM is the **thinker** (memory, persona, goal tracking, `<FINAL_ANSWER>` synthesis). The coding agent is the **doer** (shell, files, tests, tools). OpenCode can be called with zero LLM involvement — it has its own model — but then you lose:

- MoJo's memory context (no role, no dreaming, no conversation history)
- Permission policy enforcement
- HITL routing back to the user
- Iteration budget + session persistence
- Cross-role handoff (e.g. Popo → Rebecca for review)

That's why every coding-agent role in MoJo specifies both `executor=coding_agent` and a `model_preference` (or accepts one from the resource pool). The local LLM is **not optional** for in-MoJo work — it is the "soul", the coding agent is the "hands".

---

## Bridge vs. Skill

| Concept | What | Where | Lifetime |
|---|---|---|---|
| **Bridge** | Static MCP tool that calls 3rd-party protocol | `app/mcp/core/tools.py` | Code, lives in repo |
| **Skill** | Parameterized, installable, config-driven dynamic tool | `config/skill_blueprints/*.json` | JSON, installable into `~/.memory/config/dynamic_tools.json` |

The `external_agent` MCP tool **is** the bridge — a static, programmatic call surface in `app/mcp/core/tools.py:6513` that 3rd-party backends flow through. It works at runtime inside MoJo's process.

A **skill** is a different layer: parameterized, installable, config-driven. Skills are user-invocable from any tool surface (Claude Desktop, dashboard, voice) without writing code. They live as JSON blueprints in `config/skill_blueprints/` and are rendered into `CapabilityDefinition` entries by `app/scheduler/skill_provider.py:_render_and_write` (line 143).

**Why both?** Two reasons:
1. **Single source of truth.** The MCP hub already handles the protocol. A skill that calls `external_agent(...)` exposes 3rd-party ops to surfaces that don't easily call MCP tools directly (Discord, voice, dashboard buttons).
2. **Config-driven extensibility** (per `Coding Agents Rules.md:60-87`). Adding a new 3rd party (Cursor, Codex CLI, Aider) should be a config change, not a code change. A skill blueprint is exactly that.

---

## Decision

**Bridge + Skills.** Keep `external_agent` as the bridge, add a thin skill layer on top.

This is the only option that:
- Keeps the protocol gateway in one place (`external_agent`).
- Makes 3rd-party coding agents user-invocable from every surface.
- Stays config-driven (no code change for new 3rd parties).
- Honors the Tier 1 / Tier 2 separation (assistant stays the thinker).

---

## Implementation plan

### Step 1 — Skill blueprints (done, `c5f5544`)

Two new blueprints in `config/skill_blueprints/`, both using the existing `shell` executor pattern with inline Python (matches `sandbox_create.json`, `curl_request.json`):

| File | Purpose | MCP action |
|---|---|---|
| `config/skill_blueprints/opencode_session.json:1` | Create a session on the OpenCode backend and send one prompt | `backend_session_create` → `backend_session_message` |
| `config/skill_blueprints/claude_code_session.json:1` | Spawn a headless Claude Code subprocess with MoJo as its MCP server | `run_task` (which handles MCP config injection internally) |

**Why `shell` and not `mcp_proxy`:** The `mcp_proxy` executor (`app/scheduler/capability_registry.py:1500`) passes args verbatim. That would force the user to know about the `action` enum and the JSON-RPC shape. The `shell`+`python` pattern lets the skill translate user-facing args (`prompt`, `working_dir`, `model`) into the right `external_agent` payload, giving a focused UX.

**Template vars:** `MOJO_BASE_URL` is a `template_vars` entry (default `http://localhost:8000`), allowing non-local deployment via `install(env={"MOJO_BASE_URL": "https://mojo.example.com"})`.

**Validation:** Both blueprints load through the real loader (`app/scheduler/skill_provider.py:_load_blueprint_file`). All 30 skill-provider conformance tests pass.

### Step 2 — Nothing in `tools.py`

The bridge (`app/mcp/core/tools.py:6513`) is already complete. No code changes were needed. The skills are pure config-driven extensions — exactly the "extensibility through configuration alone" principle from `Coding Agents Rules.md:60`.

### Step 3 — How a user invokes the skills

After install (or after MoJo restart picks up the system-layer blueprint):

```
opencode_session(prompt="Refactor the auth module", working_dir="/home/alex/proj")
claude_code_session(prompt="Find all SQL injection risks in api/", working_dir="/home/alex/proj", model="opus")
```

Both return JSON; the Claude Code variant returns `{task_id, pid, working_dir}` so the user can monitor with `scheduler(action="get", task_id=...)`.

### Step 4 — Future work (not in this branch)

- **Multi-turn chat skills.** Today both skills are single-prompt. A follow-up `opencode_session_chat` / `claude_code_session_chat` could accept a pre-existing `session_id` and continue the conversation.
- **Per-backend skill selection.** As more backends are registered (Cursor, Codex CLI, Aider), one skill per backend keeps the config-driven property. Adding a new backend = drop a new JSON file in `config/skill_blueprints/`.
- **Skill-level permission gates.** Today `danger_level=medium` is just metadata. A future policy layer could enforce it against the role's `available_tools`.

---

## Files added

| File | Lines | Purpose |
|---|---|---|
| `config/skill_blueprints/opencode_session.json` | 35 | OpenCode session skill blueprint |
| `config/skill_blueprints/claude_code_session.json` | 35 | Claude Code headless run skill blueprint |

**Baseline commit:** `c5f5544` on branch `wip_coding_agent_skill_bridge`
**Current worktree delta:** CubeSandbox client + sandbox-first OpenCode bootstrap in
`app/scheduler/sandbox/` and `app/scheduler/handlers/coding_session_opencode.py`

---

## Key file:line references

| Concern | File:line |
|---|---|
| `external_agent` hub dispatcher | `app/mcp/core/tools.py:6513` |
| HITL bridge (`ask_user` / `check_reply`) | `app/mcp/core/tools.py:6562` |
| Headless Claude Code spawn (`run_task`) | `app/mcp/core/tools.py:6576` |
| Claude Code MCP config generator | `app/mcp/core/tools.py:6685` |
| Backend actions (`backend_*`) | `app/mcp/core/tools.py:6702` |
| Three-tier executor | `app/scheduler/coding_agent_executor.py:103` |
| Role executor routing | `app/scheduler/handlers/agentic.py:22` |
| Popo role config | `config/roles/popo.json.example:7-9` |
| OpenCode backend | `submodules/coding-agent-mcp-tool/src/coding_agent_mcp/backends/opencode.py:29` |
| Claude Code backend | `submodules/coding-agent-mcp-tool/src/coding_agent_mcp/backends/claude_code.py:42` |
| Skill loader | `app/scheduler/skill_provider.py:51` |
| Skill installer (writes to `dynamic_tools.json`) | `app/scheduler/skill_provider.py:143` |
| `mcp_proxy` executor (alternative pattern) | `app/scheduler/capability_registry.py:1500` |
| Task type definition | `app/scheduler/models.py:44` |
| Skill blueprints dir | `config/skill_blueprints/` |

---

## Open questions

1. **Permission policy for skills.** `danger_level=medium` is metadata only. Should we wire it into the role's `available_tools` filter? Currently any role can call the skill if it's installed.
2. **`MOJO_BASE_URL` per-skill vs global.** Today it's a per-skill template var. A global env var would simplify install but couple all skills to one host. The per-skill approach is more flexible and follows the existing config pattern.
3. **Test coverage.** Both skills have `test_args: {}` so `test()` skips. A non-destructive smoke test (e.g. "ping the MoJo /health endpoint") would be a useful addition. Should the install-time test be improved to do this?
4. **Naming.** `opencode_session` is action-oriented; `claude_code_session` is the same shape. If we add a multi-turn chat skill, the naming pair becomes `opencode_session` (single) / `opencode_chat` (multi). Worth aligning now.
