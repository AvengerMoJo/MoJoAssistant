# Spec: Agent Orchestration Pipeline — v1.3.2

## Problem

MoJo roles can execute individual tasks well, but there is no mechanism for
multi-role workflows where tasks depend on each other's outputs. A real
research-to-implementation pipeline requires:

1. Bao/Ahman installs a sandbox in Portainer
2. Rebecca researches a topic → produces findings
3. Popo implements code/tests based on Rebecca's findings
4. Ahman/Bao runs the tests in the sandbox → collects results
5. Rebecca writes an analysis report from the test results

Today each step must be manually triggered, output must be manually copied
between tasks, and there is no way to declare "don't start step 3 until
step 2 is complete."

---

## Mental Model

**A pipeline is a directed acyclic graph (DAG) of tasks.**

Each node is a task assigned to a role. Edges are dependencies. When all
dependencies of a node are in `completed` status, the scheduler automatically
starts it, optionally injecting the prior task's output into its goal.

```
install (bao)
    ↓
research (rebecca) ──────────────────────┐
    ↓ output injected                    │
implement (popo)                         │
    ↓                                    ↓
run_tests (ahman) ← depends_on: [install, implement]
    ↓ output injected
report (rebecca)
```

---

## Desired Behaviour

### Defining a pipeline

A single MCP call creates the full pipeline:

```
scheduler add
  type="pipeline"
  pipeline_id="context_strategy_v1"
  steps=[
    {
      "id": "install",
      "role_id": "bao",
      "goal": "Install autoresearch sandbox in Portainer at http://...",
      "max_iterations": 20
    },
    {
      "id": "research",
      "role_id": "rebecca",
      "goal": "Research context window allocation strategies for LLM agents. Focus on...",
      "depends_on": ["install"],
      "max_iterations": 25
    },
    {
      "id": "implement",
      "role_id": "popo",
      "goal": "Implement 3 test cases based on this research:\n\n{{research.output}}\n\nStore tests in ~/.memory/opencode-sandboxes/context-strategy-tests/",
      "depends_on": ["research"],
      "max_iterations": 20
    },
    {
      "id": "run_tests",
      "role_id": "ahman",
      "goal": "Run the test suite at ~/.memory/opencode-sandboxes/context-strategy-tests/ and collect results.",
      "depends_on": ["install", "implement"],
      "max_iterations": 15
    },
    {
      "id": "report",
      "role_id": "rebecca",
      "goal": "Write an analysis report based on these test results:\n\n{{run_tests.output}}\n\nInclude recommendations for implementation.",
      "depends_on": ["run_tests"],
      "max_iterations": 15
    }
  ]
```

### Output injection

`{{step_id.output}}` in a goal template is replaced at task start with the
`final_answer` from the referenced completed step. If the step has no
`final_answer`, injection is skipped and a warning is logged.

Additional injection variables:
- `{{step_id.output}}` — final_answer text
- `{{step_id.summary}}` — first 300 chars of final_answer (for long outputs)
- `{{step_id.report_file}}` — path to the task_report_v2 artifact

### Pipeline lifecycle

```
pipeline_created
    ↓
steps with no depends_on → status=pending (start immediately)
    ↓
each step completes → scheduler checks which steps are now unblocked
    ↓
unblocked steps → inject outputs → status=pending
    ↓
all steps completed → pipeline_completed event
    ↓ (or)
any step permanently failed → pipeline_failed event + notify user
```

### Failure handling

- **Retry**: failed steps retry up to `max_retries` (same as today)
- **Block propagation**: if step A permanently fails, all steps depending on A
  are marked `blocked` (not failed) so the user can intervene and resume
- **Manual override**: user can mark a blocked step `pending` to force it to
  run with a partial/missing input, or provide the missing output via HITL

---

## Implementation Plan

### Phase 1 — Data model (Task + Pipeline)

**`app/scheduler/models.py`**

Add to `Task`:
```python
depends_on: List[str] = field(default_factory=list)   # task IDs this task waits for
pipeline_id: Optional[str] = None                      # pipeline this task belongs to
input_template: Optional[str] = None                   # raw goal template with {{}} vars
```

Add `TaskStatus.BLOCKED` — waiting on a dependency that failed permanently.

Add `Pipeline` dataclass:
```python
@dataclass
class Pipeline:
    id: str
    steps: List[str]          # ordered task IDs
    status: str               # pending | running | completed | failed
    created_at: datetime
    completed_at: Optional[datetime] = None
```

Persist pipelines to `~/.memory/scheduler_pipelines.json`.

### Phase 2 — Dependency resolver in scheduler tick

**`app/scheduler/core.py`** — in `_tick()`:

Before promoting a task to RUNNING, check:
```python
def _is_ready(self, task: Task) -> bool:
    if not task.depends_on:
        return True
    for dep_id in task.depends_on:
        dep = self.queue.get(dep_id)
        if dep is None or dep.status != TaskStatus.COMPLETED:
            return False
    return True
```

If a dependency is `FAILED` (permanently), mark the task `BLOCKED` and
broadcast a `pipeline_step_blocked` event.

### Phase 3 — Output injection at task start

**`app/scheduler/core.py`** — before dispatching to executor:

```python
def _inject_pipeline_inputs(self, task: Task) -> Task:
    if not task.input_template:
        return task
    goal = task.input_template
    for dep_id in task.depends_on:
        dep = self.queue.get(dep_id)
        if dep and dep.result:
            output = (dep.result.metrics or {}).get("final_answer", "")
            summary = output[:300]
            report_file = (dep.result.metrics or {}).get("session_file", "")
            goal = goal.replace(f"{{{{{dep_id}.output}}}}", output)
            goal = goal.replace(f"{{{{{dep_id}.summary}}}}", summary)
            goal = goal.replace(f"{{{{{dep_id}.report_file}}}}", report_file)
    task.config["goal"] = goal
    return task
```

### Phase 4 — Pipeline MCP tool

**`app/mcp/core/tools.py`** — add `pipeline` hub:

```
action='create'   pipeline_id, steps[]          — define and queue a pipeline
action='status'   pipeline_id                   — overall pipeline status
action='get'      pipeline_id                   — full pipeline detail + per-step status
action='list'                                   — all pipelines
action='cancel'   pipeline_id                   — cancel pending/blocked steps
action='resume'   pipeline_id, step_id          — force a blocked step to pending
```

### Phase 5 — Pipeline scheduler MCP add path

In `scheduler(action='add', type='pipeline', ...)`:
1. Parse `steps` array
2. Create a `Task` per step with `pipeline_id`, `depends_on`, `input_template`
3. Create and persist a `Pipeline` record
4. Add all tasks to the queue (resolver handles which start immediately)

---

## Orchestrator Mode (Alternative / Complement)

For **adaptive pipelines** where the next step depends on the content of
prior output (not just its completion), an orchestrator role can be used:

```
scheduler add
  type='assistant'
  role_id='mojo'           # or a dedicated orchestrator role
  goal="Orchestrate the context strategy research pipeline: ..."
```

The orchestrator uses `dispatch_subtask` to fire each step and waits for
results before deciding the next action. Best for workflows where:
- The number of steps isn't known upfront
- Step selection is conditional on prior output
- Failure recovery requires judgment

The DAG pipeline (Phase 1–5) handles the deterministic case.
The orchestrator handles the adaptive case.
Both can coexist — a DAG pipeline can include an orchestrator step.

---

## Success Criteria

1. `scheduler add type='pipeline' steps=[...]` creates all tasks with correct
   dependency graph in one call
2. Steps with no dependencies start immediately; dependent steps wait
3. `{{step_id.output}}` in a goal is correctly injected from prior step's
   `final_answer` at task start
4. When a step permanently fails, dependent steps go to `BLOCKED` and a
   notification fires
5. `scheduler(action='status', pipeline_id=...)` returns per-step status at a glance
6. Full pipeline (5 steps, 2 branches) completes end-to-end without manual intervention

---

## Scope Boundaries

- **Not in this spec**: visual pipeline builder UI
- **Not in this spec**: pipeline versioning or rollback
- **Not in this spec**: cross-machine distributed pipelines
- **Not in this spec**: conditional branching (if/else in DAG) — orchestrator mode covers this

---

## Relationship to Existing Architecture

- Builds on `Task` model (adds `depends_on`, `pipeline_id`, `input_template`)
- Uses existing `task_report_v2` artifacts as output source for injection
- Uses existing `_schedule_dreaming_for_agentic_task` — each completed step
  is dreamed independently as today
- Orchestrator mode uses existing `dispatch_subtask` tool
- HITL (`ask_user` / `reply_to_task`) works unchanged within each step

---

## Target Version: v1.3.2
