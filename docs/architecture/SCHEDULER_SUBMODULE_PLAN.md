# Scheduler Submodule Plan

## Purpose

`app/scheduler` is no longer a small scheduler package.

It currently mixes:

- task models and queueing
- the core ticker loop
- task execution routing
- the internal agentic runtime
- LLM resource routing
- MCP client lifecycle
- role-chat surfaces
- policy and security gates
- benchmark/session persistence
- MoJo-specific memory and dreaming integration

That makes the package harder to:

- reuse outside MoJo
- test in isolation
- evolve cleanly
- benchmark as a scheduler/runtime product on its own

The goal is to split the current package into:

1. a reusable scheduler/runtime submodule
2. a thin MoJo integration layer that wires the runtime into MoJo memory, dreaming, roles, and MCP surfaces

This is the same move already made for the dreaming pipeline: keep the generic engine modular, keep product wiring local.

## Current State

The current `app/scheduler` tree contains at least five concerns:

### 1. Core scheduling

- [core.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/core.py)
- [queue.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/queue.py)
- [triggers.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/triggers.py)
- [models.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/models.py)

### 2. Task execution and runtime

- [executor.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/executor.py)
- [agentic_executor.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/agentic_executor.py)
- [coding_agent_executor.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/coding_agent_executor.py)
- [session_storage.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/session_storage.py)

### 3. Capability and tool orchestration

- [capability_registry.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/capability_registry.py)
- [capability_resolver.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/capability_resolver.py)
- [capability_gap_checker.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/capability_gap_checker.py)
- [mcp_client_manager.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/mcp_client_manager.py)

### 4. Resource, safety, and interaction policy

- [resource_pool.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/resource_pool.py)
- [interaction_mode.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/interaction_mode.py)
- [security_gate.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/security_gate.py)
- [safety_policy.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/safety_policy.py)
- [policy/](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/policy/)

### 5. MoJo-specific application surfaces

- [role_chat.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/role_chat.py)
- [google_calendar_bridge.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/google_calendar_bridge.py)
- [benchmark_store.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/benchmark_store.py)
- [planning_prompt_manager.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/planning_prompt_manager.py)
- [role_template_engine.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/role_template_engine.py)
- [ninechapter.py](/home/alex/Development/Personal/MoJoAssistant/app/scheduler/ninechapter.py)

The old scheduler architecture note at [SCHEDULER_ARCHITECTURE.md](/home/alex/Development/Personal/MoJoAssistant/docs/architecture/SCHEDULER_ARCHITECTURE.md) still describes a much smaller system. The code has outgrown that shape.

## Extraction Goal

Create a reusable submodule for the generic scheduler/runtime engine.

Working name:

- `submodules/mojo-scheduler-runtime`

This name is not final. The important part is the boundary.

The submodule should own:

- task data contracts
- queue/storage interfaces
- scheduler loop
- trigger interfaces
- execution contracts
- agentic loop runtime
- capability registry/resolution contracts
- session/task persistence contracts
- resource routing contracts
- MCP server connection abstraction
- safety/security hooks as pluggable policies

MoJo should keep:

- role memory integration
- dreaming integration
- owner-profile overlays
- NineChapter overlays
- role chat surface
- benchmark-specific storage
- Google calendar bridge
- dashboard/chat specific contracts
- product-specific policy bundles

## Proposed Boundary

### Move into submodule

These are the strongest candidates for extraction:

- `models.py`
- `queue.py`
- `core.py`
- `triggers.py`
- `session_storage.py`
- `capability_registry.py`
- `capability_resolver.py`
- `capability_gap_checker.py`
- `resource_pool.py`
- `mcp_client_manager.py`
- `interaction_mode.py`
- `security_gate.py`
- `safety_policy.py`
- `policy/base.py`
- `policy/content.py`
- `policy/context.py`
- `policy/data_boundary_checker.py`
- `policy/monitor.py`
- `policy/sensitive_domain.py`
- `policy/static.py`
- the reusable parts of `agentic_executor.py`

### Keep in MoJo app

These should stay in the main repo as product integrations or adapters:

- `executor.py`
- `role_chat.py`
- `planning_prompt_manager.py`
- `role_template_engine.py`
- `ninechapter.py`
- `google_calendar_bridge.py`
- `benchmark_store.py`
- the MoJo-specific parts of `agentic_executor.py`
- dreaming task wiring in `executor.py`
- MoJo role/memory/profile imports used by the agent runtime

## The Hard Part

The main extraction problem is not `core.py`.

It is `agentic_executor.py`.

That file currently mixes:

- generic LLM think-act loop behavior
- tool-call parsing and normalization
- session trimming and budget logic
- capability-based tool loading
- owner/role prompt composition
- MoJo role overlays
- interaction mode behavior
- MoJo-specific tool names and contracts

This means the correct split is not:

- "move `agentic_executor.py` as-is"

It is:

- extract a generic runtime core
- keep MoJo prompt assembly and product wiring as local adapters

## Proposed Layered Design

### Layer 1: Runtime Core submodule

Reusable package, no MoJo memory/role assumptions.

Owns:

- `Task`
- `TaskResult`
- `TaskQueue`
- `Scheduler`
- runtime session model/storage
- generic `AgentRuntime`
- generic capability registry/resolver
- resource manager interface and default implementation
- MCP connector abstraction
- policy hook interfaces

Suggested package layout:

```text
submodules/mojo-scheduler-runtime/
├── src/mojo_scheduler_runtime/
│   ├── models.py
│   ├── queue.py
│   ├── scheduler.py
│   ├── triggers.py
│   ├── sessions.py
│   ├── runtime/
│   │   ├── agent_runtime.py
│   │   ├── tool_protocol.py
│   │   ├── capability_registry.py
│   │   ├── capability_resolver.py
│   │   └── context_budget.py
│   ├── resources/
│   │   ├── resource_pool.py
│   │   └── model_registry.py
│   ├── mcp/
│   │   └── client_manager.py
│   ├── policy/
│   │   ├── base.py
│   │   ├── safety.py
│   │   ├── security.py
│   │   └── content.py
│   └── interfaces/
│       ├── task_executor.py
│       ├── tool_registry.py
│       └── session_store.py
└── docs/
```

### Layer 2: MoJo adapter package

Lives in the main repo.

Owns:

- MoJo task routing
- Dreaming task execution
- role-aware prompt building
- owner-context overlays
- NineChapter overlays
- role chat
- benchmark hooks
- MoJo-specific MCP tool registration conventions

Suggested package layout:

```text
app/scheduler/
├── adapters/
│   ├── mojo_task_executor.py
│   ├── mojo_agent_runtime_adapter.py
│   ├── mojo_memory_context.py
│   ├── mojo_role_prompt_builder.py
│   └── mojo_dreaming_adapter.py
├── role_chat.py
├── google_calendar_bridge.py
├── benchmark_store.py
└── ...
```

## Stable Contracts Required Before Extraction

Before any code move, define stable interfaces for:

### 1. Task execution

The core scheduler should depend on:

- `TaskExecutorProtocol`

Not directly on MoJo's `TaskExecutor`.

### 2. Tool registry / tool calling

The agent runtime should depend on:

- a tool registry protocol
- a tool invocation protocol
- a session store protocol

Not directly on MoJo MCP tool names or memory services.

### 3. Prompt/context assembly

The generic runtime should accept:

- system prompt
- tool catalog
- mode contract
- external context bundle

It should not import:

- `app.roles.owner_context`
- `app.scheduler.ninechapter`
- `app.scheduler.role_template_engine`

Those belong in MoJo adapters.

### 4. Resource routing

The runtime should know:

- "select a model/resource with these constraints"

It should not know:

- MoJo-specific config layering details
- benchmark-specific routing rules

### 5. MCP lifecycle

The runtime can depend on an MCP manager abstraction, but the product should decide:

- which servers exist
- where config is loaded from
- which categories map to which role capabilities

## Migration Plan

### Phase 0: Write the contracts

No file moves yet.

Do first:

- define runtime interfaces/protocols
- define what is generic vs MoJo-owned
- update architecture docs

Deliverable:

- no behavior change
- only boundary clarification

### Phase 1: Internal refactor inside current repo

Still no submodule extraction yet.

Do:

- split `agentic_executor.py` into:
  - generic loop/runtime pieces
  - MoJo prompt/context adapters
- split `executor.py` into:
  - generic dispatcher contract
  - MoJo task handlers
- move policy/resource/MCP files behind interfaces

Deliverable:

- same repo
- cleaner seams
- easier tests

### Phase 2: Create the submodule skeleton

Create:

- `submodules/mojo-scheduler-runtime`

Populate with:

- models
- queue
- scheduler loop
- session storage
- resource routing
- capability registry/resolver
- policy base abstractions

Keep MoJo adapters local.

Deliverable:

- first import path uses submodule for generic core
- MoJo still owns high-level behavior

### Phase 3: Move the generic runtime

Extract:

- generic agentic runtime
- MCP manager abstraction/implementation
- generic safety/security hook layer

Deliverable:

- main repo depends on the submodule instead of local copies

### Phase 4: Shrink `app/scheduler`

End state:

- `app/scheduler` becomes a thin integration surface
- reusable logic lives in the submodule

## What Not To Do

### Do not move everything

This should not become:

- "take the whole `app/scheduler` folder and make it a submodule"

That would just move the monolith.

### Do not extract MoJo-specific prompt logic

Role prompts, owner-context injection, NineChapter overlays, dashboard chat rules, and MoJo memory boundaries are product behavior.

They are not scheduler-runtime core.

### Do not force benchmark code into the submodule

Benchmarking is useful, but benchmark stores and benchmark-specific harnesses should stay local until the runtime API is stable.

## First Concrete Refactor Targets

If implementation starts, the first high-value cuts should be:

1. Extract a `runtime_context.py` or equivalent from `agentic_executor.py`
   - token budgeting
   - tool-call normalization
   - message trimming

2. Extract a prompt-builder adapter layer
   - owner context
   - role template
   - NineChapter overlay
   - interaction mode overlay

3. Turn `TaskExecutor` into MoJo application dispatch
   - Dreaming
   - role-memory integration
   - product-specific scheduled tasks

4. Put queue/core/models/session storage behind a clean package contract

These four moves will determine whether the submodule extraction is real or just renaming directories.

## Success Criteria

The extraction is successful if:

- the core scheduler can run without importing MoJo roles or memory modules
- the generic runtime can execute a tool-using task loop with pluggable tools and policies
- MoJo-specific prompt shaping lives outside the core runtime
- `app/scheduler` becomes mostly adapters and product entry points
- tests can run the scheduler core without needing the full MoJo product stack

## Recommendation

Do not create the submodule first.

First:

- refactor the boundaries locally
- especially around `agentic_executor.py` and `executor.py`

Then:

- extract the stable core into a submodule

Otherwise the submodule will just inherit the current monolith and make future changes slower.
