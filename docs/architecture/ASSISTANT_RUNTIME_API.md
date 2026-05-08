# Assistant Runtime API (Pre-Beta Modularization Spec)

Status: Draft for pre-beta gating  
Date: 2026-04-29

## 1. Goal

Define a hard runtime boundary so each assistant role/character runs in an isolated process with independent policy enforcement, memory scope, and failure containment.

This spec is the contract for extracting assistant runtime into modular components before beta.

## 2. Required Modules

1. `mojo-assistant-runtime`
- One assistant instance per process.
- Owns agent loop, local prompt assembly, and tool-intent emission.
- Must not execute tools directly without policy gateway approval.

2. `mojo-role-kernel`
- Compiles role definition into runtime prompt package.
- Owns behavior rules, overlays, role versioning, and capability declarations.
- Exposes immutable role bundle for each assistant process launch.

3. `mojo-policy-gateway`
- Mandatory intercept for every tool call intent.
- Enforces allow/deny/escalate with risk budgets and policy checkers.
- Emits structured policy decision events for audit and monitoring.

4. `mojo-assistant-supervisor`
- Starts/stops/restarts isolated assistant processes.
- Enforces resource quotas and health checks.
- Contains crash/retry policies and lifecycle state transitions.

## 3. Isolation Guarantees

Each assistant process MUST have:
- Distinct `assistant_id` and `role_id`.
- Distinct in-memory runtime state (no shared mutable objects).
- Distinct memory namespace by default.
- Distinct policy context (risk budget, checker state).
- Distinct session/event stream identity.

Cross-assistant communication is forbidden by default and only allowed via explicit broker APIs with policy review.

## 4. Runtime Execution Contract

## 4.1 Inbound Task Envelope

```json
{
  "assistant_id": "assistant_researcher_01",
  "role_id": "researcher",
  "task_id": "task_20260429_001",
  "goal": "...",
  "interaction_mode": "scheduler_agentic_task",
  "available_tools": ["memory_search", "task_session_read"],
  "max_iterations": 8,
  "max_duration_seconds": 300,
  "tier_preference": ["free", "free_api"],
  "context": {}
}
```

## 4.2 Tool Intent Envelope (runtime -> policy gateway)

```json
{
  "assistant_id": "assistant_researcher_01",
  "role_id": "researcher",
  "task_id": "task_20260429_001",
  "iteration": 3,
  "tool_name": "memory_search",
  "arguments": {"query": "tool-calling regression"},
  "trace_id": "trace_abc123",
  "timestamp": "2026-04-29T14:30:00Z"
}
```

## 4.3 Policy Decision Envelope (policy gateway -> runtime)

```json
{
  "decision": "allow",
  "reason": "within capability and risk budget",
  "severity": "info",
  "checker_results": [
    {"checker": "capability", "status": "pass"},
    {"checker": "data_boundary", "status": "pass"}
  ],
  "risk_budget": {
    "before": 40,
    "after": 35
  },
  "trace_id": "trace_abc123"
}
```

Possible `decision` values:
- `allow`
- `deny`
- `escalate` (requires HITL/user confirmation)

## 4.4 Tool Result Envelope (tool runtime -> assistant runtime)

```json
{
  "ok": true,
  "tool_name": "memory_search",
  "result": {"items": []},
  "error": null,
  "trace_id": "trace_abc123"
}
```

## 5. Security and Policy Rules

1. No bypass path
- All tool calls must pass through `mojo-policy-gateway`.
- Direct tool invocation from assistant runtime is prohibited.

2. Role capability ceiling
- Effective tools = system defaults ∩ role capabilities ∩ runtime override.
- Policy denies out-of-ceiling calls before tool execution.

3. Risk budget accounting
- Every tool call decrements per-assistant risk budget by tool danger level.
- Budget exhaustion forces `escalate` or `deny`.

4. Harmful action controls
- Dangerous tool patterns (filesystem escape, secret exfiltration, privilege misuse) trigger deny with incident event.

5. Audit integrity
- Every intent and decision must emit immutable audit event with `assistant_id`, `task_id`, `trace_id`, and checker evidence.

## 6. Prompt and Role Boundary Rules

1. Mode contract precedence
- Execution-mode policy text is non-overridable.
- Role/personality overlays are additive only.

2. Personality scope
- Persona text may shape tone and explanation style.
- Persona text must not override tool-use requirements, policy rules, or completion contracts.

3. Deterministic tool-attempt tracking
- Runtime must track tool attempts in process state and event log.
- Completion validation must use deterministic attempt counters.

## 7. Process Model

## 7.1 Supervisor State Machine

- `created` -> `starting` -> `ready` -> `busy` -> `idle` -> `stopping` -> `stopped`
- `failed` can occur from `starting`, `ready`, or `busy`

## 7.2 Restart Policy

- Crash backoff: exponential with cap.
- Max restart attempts per window.
- Hard quarantine if repeated crashes exceed threshold.

## 7.3 Quotas

Per assistant process:
- CPU quota
- Memory cap
- Max concurrent tasks
- Max task duration

## 8. Observability Contract

Every module must emit structured events with shared keys:
- `assistant_id`
- `role_id`
- `task_id`
- `trace_id`
- `module`
- `event_type`
- `severity`
- `timestamp`

Required event families:
- `assistant.lifecycle.*`
- `assistant.loop.iteration`
- `tool.intent`
- `policy.decision`
- `tool.result`
- `assistant.final_answer`
- `assistant.failure`

## 9. MCP and API Integration

The existing MCP surface remains orchestrator-facing. New modular runtime surfaces should be internal APIs:

- `assistant_runtime.spawn(role_id, assistant_id, policy_profile)`
- `assistant_runtime.dispatch(task_envelope)`
- `assistant_runtime.status(assistant_id)`
- `assistant_runtime.stop(assistant_id)`
- `policy_gateway.evaluate(tool_intent_envelope)`

MCP tools should call supervisor/runtime APIs, not process internals.

## 10. Minimum Pre-Beta Test Matrix

1. Isolation tests
- Assistant A cannot read Assistant B role-private memory.
- Assistant A crash does not interrupt Assistant B tasks.

2. Policy enforcement tests
- Forbidden tool call is denied before execution.
- Budget exhaustion forces escalation path.

3. Prompt-precedence tests
- Personality-heavy role still emits required tool call in dynamic smoke test.
- Mode contract text always present in runtime system prompt.

4. Failure-containment tests
- Tool timeout in one process does not deadlock supervisor.
- Repeated crash leads to quarantine, not restart loop.

5. Audit tests
- Every tool intent has matching policy decision and trace_id.
- Incident events include checker evidence.

## 11. Migration Plan (Pre-Beta)

Phase 1 (now)
- Freeze this interface spec.
- Add smoke tests for dynamic role/persona prompt behavior.

Phase 2
- Extract assistant runtime process boundary behind supervisor API.
- Route all tool execution through policy gateway interface.

Phase 3
- Extract role compilation into role-kernel module.
- Enforce role bundle version pinning per task run.

Phase 4
- Enable multi-assistant long-running mode with per-assistant process isolation.
- Gate beta release on passing the minimum test matrix above.

## 12. Release Gate

Beta cannot be declared until:
- This boundary is implemented (not doc-only).
- Minimum test matrix passes in CI and local smoke.
- No direct tool bypass path exists outside policy gateway.
