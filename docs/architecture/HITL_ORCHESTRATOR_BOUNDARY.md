# HITLOrchestrator Submodule Boundary

**Submodule:** `submodules/HITLOrchestrator`  
**Repo:** https://github.com/AvengerMoJo/HITLOrchestrator  
**Status:** Boundary established (Phase 1). Physical extraction post-v2.0.0.

## What HITLOrchestrator is

A task scheduler and Human-In-The-Loop runtime for autonomous agents.

The distinctive capability: an agent mid-execution can suspend itself,
route a question to the owner's inbox, and resume from the exact iteration
on reply. The scheduler, the HITL pause/resume contract, and the agentic
loop are one cohesive runtime — not three separate things bolted together.

## Three components

```
HITLOrchestrator/
  scheduler/     Loop engine — tick, queue, cron, executor registry
  hitl/          Pause/resume contract — send_question, wait_for_reply, resume
  runtime/       Agentic loop, resource pool, capability resolution, policy
```

## The boundary rule

**Nothing in HITLOrchestrator imports from the MoJo application layer.**  
(`app.roles`, `app.dreaming`, `app.mcp` are all forbidden inside the submodule.)

The host application (MoJo) imports from HITLOrchestrator and injects:
- `mailbox` — concrete inbox implementation (`DashboardInbox`)
- `executor_registry` — MoJo-specific task handlers (dreaming, calendar)
- `resource_manager` — shared `ResourceManager` instance

## What stays in app/scheduler/ (MoJo integration layer)

| File | Reason it stays |
|------|----------------|
| `executor.py` | MoJo task routing, dreaming + calendar handlers |
| `role_chat.py` | MoJo role chat surface |
| `ninechapter.py` | MoJo personality system |
| `benchmark_store.py` | MoJo benchmark persistence |
| `role_template_engine.py` | MoJo system prompt generation |
| `planning_prompt_manager.py` | MoJo planning prompt library |
| `google_calendar_bridge.py` | MoJo calendar integration |

## Migration phases

### Phase 1 — Executor registry (pre-beta) ← current
Extract `executor.py`'s `if/elif TaskType` chain into a pluggable handler
registry. Each `TaskType` maps to a handler class. New task type = new
file + one `register()` call. No file movement yet.

### Phase 2 — Boundary annotation (pre-beta)
Annotate every file in `app/scheduler/` with either:
- `# [hitl-orchestrator: generic]` — safe to move to submodule
- `# [mojo-integration]` — stays, has MoJo-specific imports

### Phase 3 — Physical extraction (post-v2.0.0)
Move annotated generic files into `submodules/HITLOrchestrator/`.
`app/scheduler/` becomes a thin MoJo integration wrapper that imports
from the submodule and wires in MoJo-specific implementations.

## Relationship to SCHEDULER_SUBMODULE_PLAN.md

This document supersedes `SCHEDULER_SUBMODULE_PLAN.md`. The working name
`mojo-scheduler-runtime` has been replaced by `HITLOrchestrator`. The
boundary and extraction strategy are the same; the naming now leads with
the distinctive value (HITL) rather than the infrastructure (scheduler).
