# Spec: Capability to Tool Translation

## Purpose

MoJoAssistant should use **capabilities** as the stable abstraction for:

- role design
- MCP/operator surfaces
- policy and permission reasoning
- dashboard/UI labels

But scheduled assistant execution still depends on concrete **tool-calling**
schemas understood by the active LLM backend.

This spec defines the boundary:

- `capability` = what an assistant is allowed to do
- `tool` = how the runtime exposes that ability to the model

## Why This Matters

Recent task failures showed that this boundary was not enforced strictly enough:

- roles correctly declared `capabilities: ["file"]`
- the model received concrete tools like `list_files` and `search_in_files`
- but one exported schema did not match its runtime handler
- the model followed the exported schema faithfully and the task failed anyway

This means the translation layer itself must be treated as a first-class contract.

## Definitions

### Capability

A stable, human-facing and policy-facing abstraction.

Examples:

- `memory`
- `file`
- `web`
- `browser`
- `orchestration`

Capabilities appear in:

- role JSON
- MCP role/config management
- dashboard capability strips
- policy reasoning

### Tool

A concrete model-facing execution primitive exposed through OpenAI-style function calling.

Examples:

- `read_file(path)`
- `list_files(path)`
- `search_in_files(query, path?)`
- `web_search(query)`

Tools appear in:

- `DynamicToolRegistry`
- model payload `tools`
- `message.tool_calls`
- tool-execution logs

## Core Rule

MoJo surfaces should prefer **capability language**.

The scheduler/runtime must translate those capabilities into exact tool schemas
for the active model call.

The model must never be expected to infer that mapping implicitly.

## Translation Contract

When a scheduled assistant task starts:

1. Load role capabilities from `role.capabilities`
2. Resolve capabilities into concrete tool names via `capability_catalog.json`
3. Load the concrete tool schemas from `DynamicToolRegistry`
4. Export those tool schemas in the LLM request
5. Enforce that runtime handlers accept the same argument names the model was shown

This translation happens inside the assistant runtime, not in MCP clients and not in role definitions.

## Invariants

### Invariant 1: Capability is not tool

`file` is not the same thing as `read_file`.

A capability may map to multiple tools.

### Invariant 2: Exported schema must match runtime handler

If a tool schema says:

```json
{
  "name": "search_in_files",
  "parameters": {
    "required": ["query"]
  }
}
```

then the runtime handler must accept `query`.

If the runtime accepts aliases for backward compatibility, that is fine, but the
canonical exported schema must match the canonical runtime argument names.

### Invariant 3: Prompts may describe capabilities, but execution depends on tools

System prompts may say:

- "You have the `file` capability"

but the model payload must still include:

- `read_file`
- `list_files`
- `search_in_files`

with exact schemas.

### Invariant 4: Capability descriptions must not encourage tool invention

Capability summaries should explain:

- what categories the assistant has
- that the runtime will translate them into concrete tools
- that the model must not invent unavailable tool names

## Urgent

- Audit every exported tool schema against the real runtime handler
- Fix any schema/runtime mismatches immediately
- Add regression tests for each built-in tool exposed to models
- Keep backward-compatible aliases in handlers only where needed for old runs

## Important

- Ensure capability-oriented prompts explicitly state that capabilities are abstractions
- Keep MCP, dashboard, and role-designer surfaces capability-based
- Keep model payloads tool-based
- Add model-comparison regression scripts for local providers (Qwen, Gemma, others)

## Planned

- Generate a machine-readable capability-to-tool map for diagnostics
- Add a doctor check for schema/runtime mismatch
- Add per-model tool-calling compatibility profiles
- Track tool-schema fidelity as part of smoke validation for local models

## Recommended Implementation Shape

### Role / MCP / UI layer

Use:

- `capabilities`

Examples:

```json
{
  "capabilities": ["memory", "file", "web"]
}
```

### Scheduler / LLM layer

Use:

- concrete OpenAI-style tool schemas

Examples:

```json
[
  {
    "type": "function",
    "function": {
      "name": "read_file",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string"}
        },
        "required": ["path"]
      }
    }
  }
]
```

## Failure Modes This Prevents

- a role having the correct capability but receiving a broken tool schema
- a model calling the argument names it was shown while the runtime expects different names
- prompt language causing the model to invent tools rather than use exported ones
- product/UI drift where users think roles have stable permissions but runtime behavior changes underneath

## Success Criteria

1. Roles and MCP surfaces remain capability-based
2. All model payloads use concrete tool schemas only
3. Every exported built-in tool schema matches its runtime handler
4. Capability summaries tell the model that the runtime maps capabilities to tools
5. Tool-calling regression tests catch schema drift before release
