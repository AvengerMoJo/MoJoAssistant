# HITLOrchestrator

A task scheduler and Human-In-The-Loop runtime for autonomous agents.

Handles the full agentic execution loop:

```
schedule → execute → pause for human → resume from exact iteration
```

## What makes this different

Most task schedulers fail or timeout when an agent can't proceed alone.
HITLOrchestrator suspends the agent, routes a question to the owner's inbox,
and resumes execution from the exact iteration where it paused — once the
human replies.

## Architecture

```
HITLOrchestrator/
  scheduler/          Task queue, tick loop, cron triggers, executor registry
  hitl/               Pause/resume contract, question routing, reply handling
  runtime/            Agentic loop, resource pool, policy pipeline
```

### Scheduler

The loop engine. Picks up pending tasks on a tick, dispatches them to
pluggable executor handlers, manages task lifecycle (pending → running →
completed/failed/waiting).

Executor handlers are registered by task type — adding a new task type
means a new handler file and one `register()` call. The core loop never
changes.

### HITLOrchestrator (the component)

Owns the contract for suspending an agent mid-execution and resuming it
on human reply:

- `send_question(task_id, question, choices)` — pause + route to inbox
- `wait_for_reply(task_id)` — hold task in WAITING_FOR_INPUT state  
- `resume(task_id, reply)` — inject reply and continue iteration loop

The inbox *implementation* (dashboard, Slack, email) is injected by the
host application. The contract lives here.

### Runtime

The generic agentic execution loop — think-act iterations, resource
routing, capability resolution, and policy enforcement. No
application-specific imports.

## Relationship to MoJoAssistant

HITLOrchestrator is extracted from [MoJoAssistant](https://github.com/AvengerMoJo/MoJoAssistant).
MoJo wires in its own inbox implementation (dashboard + SSE), dreaming
pipeline hooks, and role-specific surfaces on top of this runtime.

## Status

Early extraction — boundary being established. Not yet ready for
standalone use.
