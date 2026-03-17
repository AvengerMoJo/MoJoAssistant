# Release Notes v1.2.0 — Planned

## Theme: Role Safety + Human-in-the-Loop + Extensible Tools + Config Doctor

Four features that complete the role/agentic system started in v1.1.x.

---

## Feature 1: Role Policy Monitor (Runtime Permission Enforcement)

### Problem

Roles currently receive their tool set at scheduling time (setup-time ceiling) — whatever is listed in `available_tools` when the task is created. There is no runtime enforcement. A badly configured task or a future code change could allow a role to exceed its intended permissions.

### Design

Two-layer policy enforcement:

| Layer | When | What it does |
|-------|------|-------------|
| **Setup-time ceiling** | Task creation | Role's `allowed_tools` in `~/.memory/roles/{id}.json` caps what `available_tools` can contain. Rejected at `scheduler_add_task` time with a clear error. |
| **Runtime intercept** | Each tool call inside the agentic loop | `PolicyMonitor` intercepts before `DynamicToolRegistry.execute_tool()`. Checks role + tool + current context. Can block, warn, or log. |

### Role config additions (`~/.memory/roles/{id}.json`)

```json
{
  "policy": {
    "allowed_tools": ["bash_exec", "memory_search", "read_file", "list_files"],
    "denied_tools": [],
    "require_confirmation_for": ["bash_exec"],
    "max_bash_exec_per_task": 20,
    "sandbox_paths_only": true
  }
}
```

### Files to create/change

- **New**: `app/scheduler/policy_monitor.py` — `PolicyMonitor` class
  - `check(role_id, tool_name, args, context) -> PolicyDecision`
  - `PolicyDecision`: allow / block / warn
  - Loads role policy from `RoleManager`
- **`app/scheduler/agentic_executor.py`**
  - Pass `PolicyMonitor` into executor init
  - Wrap `_execute_tool_calls` — call `policy_monitor.check()` before each tool dispatch
  - Block returns a synthetic tool result: `{"error": "policy_blocked", "reason": "..."}`
- **`app/mcp/core/tools.py`**
  - In `scheduler_add_task`: validate `available_tools` against role's `allowed_tools` ceiling if `role_id` present
- **`app/roles/role_manager.py`**
  - Add `get_policy(role_id) -> dict` helper

### Verification

```bash
# Role with bash_exec denied tries to run bash → blocked at runtime
# Task config lists a denied tool → rejected at scheduler_add_task
# Policy violation logged to event log (severity: warning)
```

---

## Feature 2: Human-in-the-Loop Inbox

### Problem

Agentic tasks run fully autonomously. There is no way for an agent to pause mid-task and ask the user a question, then resume with the answer. The agent either guesses or fails.

### Design

New task status: `WAITING_FOR_INPUT`

Agent emits a special tool call `ask_user(question)` → executor sets task status to `WAITING_FOR_INPUT`, stores the question in `task.pending_question`. Task stops iterating. When the user replies via `reply_to_task`, execution resumes with the answer injected into the message history.

### New MCP tool: `reply_to_task`

```
reply_to_task(
    task_id: str      — task currently in WAITING_FOR_INPUT status
    reply: str        — user's answer to the agent's question
)
```

Returns the task back to `PENDING` or `RUNNING` with the reply appended as a `tool` message in session history.

### New agent tool: `ask_user`

Available to agentic tasks the same way as `bash_exec` — must be explicitly listed in `available_tools`. When called:

```json
{ "tool": "ask_user", "args": { "question": "Which subnet should I scan — 192.168.1.0/24 or 10.0.0.0/24?" } }
```

Executor stores the question, sets status `WAITING_FOR_INPUT`, and returns. SSE emits a `task_waiting_for_input` event with `notify_user: true`.

### New SSE event type

```json
{
  "event_type": "task_waiting_for_input",
  "severity": "warning",
  "notify_user": true,
  "title": "Agent is waiting for your input",
  "data": {
    "task_id": "ahman_network_scan_now",
    "question": "Which subnet should I scan?"
  }
}
```

### Files to create/change

- **`app/scheduler/models.py`**: Add `WAITING_FOR_INPUT` to `TaskStatus` enum
- **`app/scheduler/dynamic_tool_registry.py`**: Register `ask_user` built-in tool
- **`app/scheduler/agentic_executor.py`**
  - Handle `ask_user` tool call: save question to task, set status, emit SSE event, return sentinel to break loop
  - On resume: inject reply as `{"role": "tool", "content": "User reply: {reply}"}` into message history
- **`app/scheduler/core.py`**: Add `resume_task_with_reply(task_id, reply)` method
- **`app/mcp/core/tools.py`**: Register `reply_to_task` tool + executor
- **`app/mcp/adapters/sse.py`**: Add `task_waiting_for_input` event type to envelope

### Client flow

```
1. Agent runs → hits uncertainty → calls ask_user("Which subnet?")
2. Task status → WAITING_FOR_INPUT
3. SSE fires task_waiting_for_input (notify_user: true)
4. MCP client surfaces question to user
5. User answers → client calls reply_to_task(task_id, "192.168.1.0/24")
6. Task resumes from where it left off
```

### Verification

```bash
# Schedule agentic task that includes ask_user in available_tools
# Agent calls ask_user → task shows WAITING_FOR_INPUT in scheduler_list_tasks
# reply_to_task resumes it → task completes with FINAL_ANSWER
# get_recent_events shows task_waiting_for_input event
```

---

---

## Feature 3: Extensible Tool Executor System

### Problem

Adding a new agent tool currently requires three code changes every time: add a `ToolDefinition` in `_register_builtins()`, add an `elif` branch in `execute_tool()`, and write a handler method. MCP tools, Python scripts, and shell scripts cannot be added as agent tools without touching the core registry code.

### Design

Add an `executor` field to `ToolDefinition` that describes *how* to run the tool. `execute_tool()` dispatches on executor type instead of tool name. New tools become pure config — no code change needed.

#### Executor types

| `executor.type` | Use case | How to add a new tool |
|---|---|---|
| `"builtin"` | Existing hardcoded handlers | No change (backwards compatible) |
| `"shell"` | Python scripts, bash scripts, any subprocess | JSON entry pointing to the script |
| `"python"` | Python module/function | Drop a `.py` file + JSON entry |
| `"mcp_proxy"` | Bridge any MCP tool into the agent toolset | JSON entry with the MCP tool name |

#### Shell executor contract

Args are passed as JSON on stdin; the script writes a JSON result to stdout. Any language can implement this.

```json
{
  "name": "nmap_scan",
  "description": "Run nmap scan on a target IP or range",
  "parameters": {"type": "object", "properties": {
    "target": {"type": "string", "description": "IP or hostname"}
  }, "required": ["target"]},
  "executor": {"type": "shell", "command": "python3 ~/.memory/tools/nmap_scan.py"},
  "danger_level": "high"
}
```

#### MCP proxy executor

```json
{
  "name": "web_search",
  "description": "Search the web for current information",
  "parameters": {"type": "object", "properties": {
    "query": {"type": "string"}
  }, "required": ["query"]},
  "executor": {"type": "mcp_proxy", "tool": "mcp__MoJoAssistant__web_search"}
}
```

### Files to change

- **`app/scheduler/dynamic_tool_registry.py`**
  - Add `executor: dict` field to `ToolDefinition` (default `{"type": "builtin"}`)
  - Persist/load `executor` in `to_dict()` / `from_dict()`
  - `execute_tool()`: dispatch on `tool.executor["type"]` instead of `if name == ...`
  - Add `_run_shell_executor(tool, args)` — subprocess with JSON stdin/stdout
  - Add `_run_python_executor(tool, args)` — dynamic `importlib` + call
  - Add `_run_mcp_proxy_executor(tool, args)` — call through MCP client

### Verification

```bash
# Add a shell tool via JSON, no code change
# Schedule agentic task with the new tool in available_tools
# Agent calls it → executor routes to subprocess → result returned to agent
```

---

---

## Feature 4: Configuration Doctor

### Problem

Misconfigured values (wrong model names, bad API keys, unreachable servers, typos in role files) cause tasks to fail with cryptic errors at runtime — often deep inside the execution loop with no clear pointer back to the config mistake. Example: Ahman's `model_preference: "qwen/qwen3-35b-a3b"` (missing `.5`) caused consistent 400 errors that looked like a network or auth issue.

### Design

A `mcp__MoJoAssistant__config_doctor` MCP tool (and a standalone CLI script) that validates all runtime configuration before issues surface during task execution.

#### What it checks

| Category | Checks |
|---|---|
| **LLM resources** | Each entry in `api_models` / `local_models`: reachability (HEAD /v1/models), API key present, model name exists on server |
| **Roles** | `model_preference` matches an available model on the assigned resource; `allowed_tools` names exist in registry |
| **Scheduler tasks** | `available_tools` names exist in registry; `role_id` resolves to an existing role; `tier_preference` is a valid tier |
| **API keys** | `key_var` env vars actually set; inline keys are not template placeholders (`{{...}}`) |
| **Local servers** | LMStudio / Ollama reachable; model list non-empty |

#### Output format

```json
{
  "status": "warn",
  "checks": [
    {"category": "role", "id": "ahman", "field": "model_preference",
     "value": "qwen/qwen3-35b-a3b", "status": "error",
     "message": "Model not found on lmstudio. Available: qwen/qwen3.5-35b-a3b"},
    {"category": "resource", "id": "gemini_tinyi", "field": "api_key",
     "status": "warn", "message": "GEMINI_API_KEY_TINYI not set in environment"}
  ],
  "summary": {"errors": 1, "warnings": 2, "passed": 14}
}
```

Severity: `error` = will definitely fail at runtime; `warn` = may fail; `pass` = OK.

### Files to create/change

- **New**: `app/config/doctor.py` — `ConfigDoctor` class with `run_all_checks() -> DoctorReport`
- **New**: `scripts/config_doctor.py` — CLI entry point (`python3 scripts/config_doctor.py`)
- **`app/mcp/core/tools.py`** — register `config_doctor` MCP tool
- **`app/scheduler/core.py`** — optionally run doctor on startup and log warnings

### Verification

```bash
python3 scripts/config_doctor.py
# → shows table of all checks, errors in red, warnings in yellow
# → exits non-zero if any errors found (useful in CI)
```

---

---

## Feature 5: Scheduler Model Smoke Test (Tool Calling + Thinking Capability Gate)

### Problem

When a model is added to the resource pool, there is no validation that it can actually follow the agentic execution flow. A model that hallucinates tool calls (claims success without calling the tool), ignores tool schemas, or can't produce `<FINAL_ANSWER>` tags will silently waste iterations and produce unreliable results. This was observed with Qwen 3.5 35B fabricating a write operation rather than calling `write_file`.

### Design

A lightweight smoke test that runs before a model is approved for agentic use. Two mandatory checks:

**Check 1 — Tool calling fidelity**: Schedule a minimal assistant task that requires exactly one tool call (`read_file` or `memory_search`) and verify:
- The model actually emits a tool call (not a hallucinated result)
- The tool result is used in the final answer

**Check 2 — Final answer compliance**: Same task must produce a `<FINAL_ANSWER>...</FINAL_ANSWER>` block within the iteration limit.

If either check fails, the resource is flagged as `agentic_incompatible` and only eligible for non-agentic uses (e.g., dreaming summarization).

### New MCP tool: `resource_pool_smoke_test`

```
resource_pool_smoke_test(
    resource_id: str    — resource to test
    full: bool = False  — if true, also tests write_file sandbox and parallel calls
)
```

Returns:
```json
{
  "resource_id": "lmstudio",
  "model": "qwen/qwen3.5-35b-a3b",
  "checks": {
    "tool_calling": "pass",
    "final_answer": "pass",
    "sandbox_write": "skip"
  },
  "agentic_capable": true,
  "iterations_used": 2,
  "duration_seconds": 14.2
}
```

### Integration with resource pool approval

`resource_pool_approve` gains an optional `--smoke-test` flag. If passed, runs the smoke test before approving. Fails approval if `agentic_capable: false`.

Config doctor (Feature 4) also runs the smoke test as part of its resource checks.

### Files to create/change

- **New**: `app/scheduler/agentic_smoke_test.py` — `AgenticSmokeTest` class
  - Defines minimal test tasks (hardcoded, not user-configurable)
  - Runs against a given resource via `AgenticExecutor`
  - Returns structured `SmokeTestResult`
- **`app/mcp/core/tools.py`** — register `resource_pool_smoke_test` tool
- **`app/scheduler/resource_pool.py`** — add `agentic_capable` flag to resource metadata; set on approval if smoke test run
- **`app/config/doctor.py`** — call smoke test as part of resource checks (optional, only if `full=True`)

### Verification

```bash
# Run smoke test on a known-good resource
resource_pool_smoke_test(resource_id="lmstudio")
# → tool_calling: pass, final_answer: pass, agentic_capable: true

# Run on a resource with a hallucinating model
resource_pool_smoke_test(resource_id="weak_local")
# → tool_calling: fail (no tool call emitted), agentic_capable: false
```

---

## Implementation Order

1. `app/scheduler/policy_monitor.py` (new)
2. `app/roles/role_manager.py` — add `get_policy()`
3. `app/scheduler/agentic_executor.py` — wrap tool dispatch with policy check
4. `app/mcp/core/tools.py` — setup-time ceiling validation in `scheduler_add_task`
5. `app/scheduler/models.py` — `WAITING_FOR_INPUT` status
6. `app/scheduler/dynamic_tool_registry.py` — `ask_user` tool
7. `app/scheduler/agentic_executor.py` — `ask_user` handler + resume logic
8. `app/scheduler/core.py` — `resume_task_with_reply()`
9. `app/mcp/core/tools.py` — `reply_to_task` tool
10. `app/mcp/adapters/sse.py` — `task_waiting_for_input` event
11. `app/scheduler/dynamic_tool_registry.py` — extensible executor system (Feature 3)
12. `app/config/doctor.py` + `scripts/config_doctor.py` + MCP tool (Feature 4)
