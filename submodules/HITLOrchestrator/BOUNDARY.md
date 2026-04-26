# HITLOrchestrator — Layer Boundary

## The rule

Nothing inside `HITLOrchestrator` may import from the host application.
The host application imports from `HITLOrchestrator` and injects its
implementations via constructor arguments or a registry.

## Layer map

### Generic (lives here)

| File | What it owns |
|------|-------------|
| `scheduler/models.py` | Task, TaskResult, TaskStatus, TaskType, Schedule |
| `scheduler/queue.py` | Task queue + persistence interface |
| `scheduler/triggers.py` | CronTrigger, one-shot trigger |
| `scheduler/registry.py` | Executor handler registry |
| `scheduler/core.py` | Tick loop, task lifecycle |
| `hitl/interface.py` | AgentMailbox ABC: send_question, wait_for_reply, resume |
| `hitl/bridge.py` | HITL pause/resume state machine |
| `runtime/agentic_loop.py` | Think-act iteration loop |
| `runtime/resource_pool.py` | ResourceManager, ResourceTier |
| `runtime/capability_resolver.py` | Capability → tool name resolution |
| `runtime/policy/` | Pluggable policy pipeline |

### MoJo integration (stays in app/scheduler/)

| File | What it owns |
|------|-------------|
| `executor.py` | MoJo task routing + dreaming/calendar handlers |
| `role_chat.py` | Role chat surface |
| `ninechapter.py` | NineChapter personality system |
| `benchmark_store.py` | Benchmark persistence |
| `role_template_engine.py` | System prompt generation |
| `planning_prompt_manager.py` | Planning prompt library |

## Injection points

The host app wires HITLOrchestrator by injecting:

```python
from hitl_orchestrator import Scheduler, HITLOrchestrator

scheduler = Scheduler(
    mailbox=DashboardInbox(sse_notifier),   # host-specific inbox impl
    executor_registry=build_mojo_registry(), # host-specific task handlers
    resource_manager=ResourceManager(),
)
```

## Migration plan

**Phase 1 (pre-beta):** Executor registry inside `app/scheduler/executor.py`.
Files stay in place. Boundary documented here.

**Phase 2 (pre-beta):** Files annotated with `# [hitl-orchestrator]` vs
`# [mojo-integration]` comments so the boundary is visible in the code.

**Phase 3 (post-v2.0.0):** Physical file move into this submodule.
`app/scheduler/` becomes a thin MoJo integration wrapper.
