# Release Notes v1.2.0 — Planned

## Theme: Role Safety + Human-in-the-Loop

Two features that complete the role/agentic system started in v1.1.x.

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
