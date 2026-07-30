# Sandbox Systems — Which One Am I Looking At?

MoJoAssistant currently has **two separate, mutually unaware systems** that both give an
agent an isolated place to work with a git checkout. They exist because they were built
for different executors at different times, and they were never unified — a real gap,
not a design choice worth keeping. This doc exists so debugging starts in the right file.
A scoping plan for actually unifying them exists at
`~/.memory/research/sandbox_manager_spec.md` (Phase B — deferred; see the plan history
around 2026-07-30 for why a full merge wasn't attempted immediately).

## Quick answer: which system handles my role?

| Role executor | System | Backing process |
|---|---|---|
| `AgenticHandler` roles (default — no `executor` set, e.g. Paul) | **`SandboxManager`** | Docker container or host subprocess, per-task |
| `executor: "coding_agent"` roles (e.g. Popo) | **OpenCode `BackendRegistry`** | Long-lived OpenCode HTTP server, per-project |

## System 1 — `SandboxManager`

- **Code**: `app/scheduler/sandbox/` (`manager.py`, `base.py`, `docker_backend.py`,
  `host_backend.py`, `hooks.py`, `registry.py`, `project_registry.py`)
- **Config**: `~/.memory/config/sandbox.json` (`default_backend`, per-backend settings,
  `auto_provision` rules)
- **Session persistence**: `~/.memory/sandbox_sessions.json`
- **Working dir convention**: Docker backend mounts the host working dir at `/workspace`
  inside the container; host backend uses a real host path, default
  `~/.memory/sandboxes/<name>`.
- **Permission model**: **none**. Isolation is delegated entirely to the container/process
  boundary — once a sandbox handle is active, `capability_registry.py`'s
  `bash_exec`/`read_file`/`write_file`/`list_files` route straight through with no path
  validation (the container itself is the sandbox).
- **Used by**: `AgenticHandler` (`app/scheduler/handlers/agentic.py`) — provisions a
  sandbox and auto-grants `+bash_exec/+read_file/+write_file/+list_files` when a task's
  goal references a git URL or `project_label`.
- **Tests**: `tests/unit/test_sandbox_*.py`

## System 2 — OpenCode `BackendRegistry`

- **Code**: `app/mcp/opencode/` (`manager.py`, `env_manager.py`, `ssh_manager.py`,
  `process_manager.py`) + the `coding-agent-mcp-tool` submodule
  (`submodules/coding-agent-mcp-tool/src/coding_agent_mcp/`)
- **Config**: `~/.memory/opencode-mcp-tool-servers.json` (list of server entries: `id`
  (=git_url), `url`, `password`, `base_dir`; pydantic `ServerEntry` model has
  `extra="allow"`, so project-specific opt-in flags like
  `auto_approve_external_directory` can be added directly to a server's JSON entry
  without a schema change)
- **SSH deploy keys**: `~/.memory/opencode-keys/<owner-repo>-deploy(.pub)`
- **Working dir convention**: `~/.memory/opencode-sandboxes/<owner-repo>/repo` — a
  **host-native subprocess** (`nohup opencode web ...`), never containerized. There is
  no `/workspace` path in this system — don't reuse `SandboxManager`'s conventions here.
- **Permission model**: OpenCode's own long-lived HTTP `/permission` API, proxied
  transparently by the submodule with zero normalization. `CodingAgentExecutor`
  (`app/scheduler/coding_agent_executor.py`) auto-grants permissions whose `directory`/
  `patterns` fields match `/workspace` or `/tmp` — **but OpenCode's API never populates
  those fields for `external_directory`-type permissions**, so that type can never
  auto-match on path alone. As of 2026-07-30, a project can opt in to auto-approving
  `external_directory` specifically via `auto_approve_external_directory: true` on its
  server entry (see `_server_auto_approves_external_directory()` in
  `coding_agent_executor.py`) — coarser than path-matching, justified because each
  OpenCode server is already scoped to exactly one repo.
- **Used by**: `CodingAgentExecutor` — any role with `executor: "coding_agent"` in its
  role config.
- **Tests**: `submodules/coding-agent-mcp-tool/tests/*.py` (submodule-local; no
  repo-level tests for the OpenCode integration itself as of 2026-07-30)

## If you're debugging...

- **A tool call failing/permission stuck for an `AgenticHandler` role** (Paul, Rebecca,
  most roles) → look in `app/scheduler/sandbox/`.
- **A tool call failing/permission stuck for a `coding_agent` role** (Popo) → look in
  `app/scheduler/coding_agent_executor.py` and the `coding-agent-mcp-tool` submodule.
- **"Which working directory is this file actually in?"** → check the role's `executor`
  field first; the two systems' path conventions (`/workspace` vs
  `~/.memory/opencode-sandboxes/...`) are not interchangeable and mixing them up is a
  real, previously-hit bug (a dispatch goal once told Popo to write to
  `~/.memory/content/`, a host path meaningless inside his OpenCode session).

## Known dead/orphaned code (do not treat as a third system)

- `app/scheduler/sandbox_manager.py` — deleted 2026-07-30, confirmed zero references.
- `app/scheduler/security/sandbox_runtime.py` (`SandboxRuntime`) — **not dead**, has real
  test coverage (`tests/unit/test_v1_3_0_security.py`), but is not yet wired into
  `ContainmentEngine`'s MEDIUM-tier honeypot redirect (only mentioned in that file's
  docstring). If you're looking for "the honeypot sandbox," this is a separate,
  unrelated concept from both systems above — built but not integrated.
