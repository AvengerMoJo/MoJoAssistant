## v1.1.5-beta — Agentic Safety Policy & AI Self-Modification System

This release adds a safety policy layer that governs what agentic tasks can do at runtime. All tool execution is sandboxed to `~/.memory/`, bash commands are restricted to a safe whitelist, and every operation is tracked in an audit log. The system also introduces a dynamic tool registry and a planning prompt manager — both configurable at runtime via the `config` MCP tool.

### Highlights

**Safety Policy Enforcement** — Immutable rules block dangerous tool names (`rm`, `kill`, `dd`, etc.) and restrict file operations to the `~/.memory/` sandbox. AI agents can read the policy but cannot modify it.

**Dynamic Tool Registry** — Six built-in tools (`read_file`, `write_file`, `list_files`, `search_in_files`, `bash_exec`, `memory_search`) with sandbox security, file size limits, and safe-command whitelisting for bash.

**Planning Prompt Manager** — Four default planning workflows (`agentic_planning`, `documentation_update`, `coding_task`, `debugging_task`) loaded from versioned JSON config. Prompts are swappable at runtime.

**Operation Tracking** — Every tool execution (allowed or blocked) is logged to `config/tool_operation_logs.json` with timestamps, tool names, success status, and block reasons.

**Runtime Config Modules** — Three new `config` modules (`agentic_tools`, `agentic_prompts`, `policy`) let agents inspect and update tools/prompts without server restart. Safety policy is read-only.

---

### New Files

| File | Purpose |
|------|---------|
| `app/scheduler/safety_policy.py` | Sandbox enforcement, immutable rules, operation audit log |
| `app/scheduler/dynamic_tool_registry.py` | Runtime tool registry with 6 built-in tools and sandbox security |
| `app/scheduler/planning_prompt_manager.py` | Versioned planning prompt management with 4 default workflows |
| `config/safety_policy.json` | Immutable safety policy (sandbox paths, blocked tools, danger levels) |
| `config/agentic_tools.json` | Dynamic tool registry persistence |
| `config/agentic_prompts.json` | Planning prompt definitions |

### Modified Files

| File | Changes |
|------|---------|
| `app/mcp/core/tools.py` | Added `agentic_tools`, `agentic_prompts`, `policy` config modules; removed incorrect `tool_registry_*` / `planning_*` MCP tools |
| `app/scheduler/agentic_executor.py` | Integrated safety policy check before tool execution; uses planning prompt manager and dynamic tool registry |
| `app/scheduler/executor.py` | Passes safety context to agentic executor |

### Bug Fixes (post-release)

Nine runtime bugs were caught and fixed before the first real execution:

| Bug | Description |
|-----|-------------|
| Tilde not expanded in `makedirs` | `os.makedirs("~/.memory/")` created a literal `~` directory |
| Tilde not expanded in sandbox check | `Path("~/.memory/").resolve()` doesn't expand `~` — added `.expanduser()` |
| `bash_exec` sandbox path check | Full command string was treated as a file path — removed sandbox check for `bash_exec` (has its own whitelist) |
| Missing `reason` parameter | `track_operation()` was called with `reason=` but didn't accept it |
| `_memory_service` never initialized | `_memory_search()` referenced `self._memory_service` but `__init__` never set it |
| `subprocess.run()` without `shell=True` | String command passed without `shell=True` treated entire string as executable name |
| Type mismatch in policy check | `ToolDefinition` object passed where `Dict` was expected — now calls `.to_dict()` |
| Module-level singletons | `PlanningPromptManager()` and `DynamicToolRegistry()` instantiated at import time, causing side effects — moved to `AgenticExecutor.__init__` |
| Unused imports | `httpx` and `SessionStorage` imported but never used |

### Quickstart

```bash
# Schedule an agentic task (tools are sandboxed automatically)
scheduler_add_task(task_id="my_task", task_type="agentic", config={"goal": "Research X and summarize"})

# Watch it live
task_session_read(task_id="my_task")

# Stream events
curl -N http://localhost:8000/events/tasks

# Resume if it times out
scheduler_resume_task(task_id="my_task")

# Inspect safety policy (read-only)
config(action="get", module="policy")

# List available tools
config(action="get", module="agentic_tools")
```
