# Assistant Task Execution Contract

This guide explains how an MCP client or external LLM should create and reason
about scheduled assistant tasks in MoJoAssistant.

The goal is to make one contract explicit:

- MCP/client side speaks in **capabilities**
- scheduler/runtime translates capabilities into **concrete tool calls**
- task results are returned through the scheduler lifecycle, not ad-hoc chat conventions

## Core Concepts

### 1. Role

A role is the assistant identity that will execute the task.

Examples:

- `researcher`
- `reporter`
- `analyst`

The role defines:

- persona
- behavior overlays
- escalation rules
- capabilities

### 2. Capability

A capability is the stable abstraction used by:

- role definitions
- MCP descriptions
- dashboard/UI
- policy

Examples:

- `memory`
- `file`
- `web`
- `browser`

Capabilities are **not** the same thing as model-facing function names.

### 3. Tool

A tool is the concrete function-call definition exposed to the model at runtime.

Examples:

- `read_file(path)`
- `list_files(path)`
- `search_in_files(query, path?)`
- `web_search(query)`

The scheduler resolves role capabilities into these concrete tools before making
 the LLM call.

## Canonical MCP Path

To run a role as an assistant task, use:

```text
scheduler(action="add", type="assistant", role_id="<role>", goal="<task>")
```

Example:

```text
scheduler(
  action="add",
  type="assistant",
  task_id="researcher_context_analysis_001",
  role_id="researcher",
  goal="Analyze task session context growth patterns and recommend a context strategy.",
  max_iterations=25
)
```

This is the canonical command path for agentic assistant work.

## Execution Flow

When the scheduler starts an assistant task:

1. Load the role by `role_id`
2. Read the role's `capabilities`
3. Resolve those capabilities into concrete tool names via `capability_catalog.json`
4. Load the tool schemas from `DynamicToolRegistry`
5. Build the model request:
   - system prompt
   - role overlay
   - capability summary
   - concrete `tools`
6. Run the think/act loop until one of these happens:
   - final answer produced
   - waiting for input
   - failure
   - timeout / iteration exhaustion

## Important Distinction: `capabilities` vs `available_tools`

### Role default

Roles define their default surface with:

```json
{
  "capabilities": ["memory", "file", "web"]
}
```

### Per-task override

A task may override the role default with:

```text
available_tools=["read_file","search_in_files","memory_search"]
```

This is a runtime override for a specific task run.

Use this when:

- you want a narrower surface for a risky task
- you want to isolate a reproduction
- you want to force a known-safe subset

## What the Model Should Understand

If you are writing prompts for an MCP client brain or assistant wrapper:

- speak about the role's **capabilities**
- do not assume the model can infer the concrete tools
- let the scheduler/runtime supply the actual tool schemas

Good framing:

- "The researcher role has `memory`, `file`, and `web` capabilities."
- "The runtime will translate those capabilities into concrete tools."

Bad framing:

- "The researcher probably can use some file tools, figure out which ones."

## Iteration and Final Answer Lifecycle

Assistant tasks run in an iteration loop.

Possible terminal states:

- `completed`
- `completed_fallback`
- `waiting_for_input`
- `failed`
- `timed_out`
- `iteration_exhausted`

Expected behavior:

- if the task is complete, the model should produce `<FINAL_ANSWER>`
- if blocked and only the user can unblock it, use `ask_user`
- if the runtime recovers a usable answer without tags, it may mark completion as fallback

## Result Artifacts

A completed assistant task can produce up to 3 outputs:

1. Session artifact
   - `~/.memory/task_sessions/{task_id}.json`
2. Task report
   - `~/.memory/task_reports/{task_id}.json`
3. Explicit deliverable files
   - only if the assistant actually writes them with file tools

Do not assume the task report is the same thing as a user-facing deliverable file.

## Recommended MCP Client Behavior

If you are building a client brain that dispatches assistant tasks:

1. Choose the correct `role_id`
2. Express the goal clearly in task language
3. Trust role `capabilities` as the stable abstraction
4. Use `available_tools` only when you need a task-specific override
5. Poll `scheduler(action="get", task_id=...)` or use notifications for terminal state
6. Read:
   - session artifact for execution detail
   - task report for normalized result

## Common Mistakes

### Mistake 1: Treating capabilities as direct tool names

Wrong:

```json
{"capabilities": ["read_file", "list_files"]}
```

This may work in some cases, but it bypasses the abstraction you want roles to use.

Preferred:

```json
{"capabilities": ["file"]}
```

### Mistake 2: Expecting a custom output file automatically

Wrong assumption:

- "If the task completed, there must be a markdown output file somewhere."

Correct:

- completion always yields session/report artifacts
- a custom output file exists only if the task explicitly wrote one

### Mistake 3: Expecting the model to infer tool schemas from capability descriptions

The model still needs exact concrete tool definitions in the request payload.

## Checklist for Reliable Assistant Task Calls

- correct `role_id`
- `type="assistant"`
- clear `goal`
- appropriate `max_iterations`
- role capabilities are sufficient
- `available_tools` only if you intentionally want an override
- model/resource supports tool calling reliably

## Related Docs

- [capability_to_tool_translation.md](/home/alex/Development/Personal/MoJoAssistant/docs/specs/capability_to_tool_translation.md)
- [task_report_v2.md](/home/alex/Development/Personal/MoJoAssistant/docs/specs/task_report_v2.md)
- [task_session_memory_v1.2.15.md](/home/alex/Development/Personal/MoJoAssistant/docs/specs/task_session_memory_v1.2.15.md)
