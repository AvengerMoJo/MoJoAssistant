# Sub-Agent Dispatch

**Status:** Implemented — v1.2.7
**Design date:** 2026-03-27

---

## The Problem

A single agent role has a fixed capability surface. A researcher that cannot
run shell commands cannot clone a repository. A synthesizer that has no browser
access cannot verify a claim in real-time.

Today the only solution is manual relay: the user reads the researcher's output,
queues a provisioner task, waits, then queues the synthesizer again. Three
scheduler cycles, three human touch-points, for what should be one workflow.

---

## Two Dispatch Modes

```
scheduler_add_task          dispatch_subtask
──────────────────          ────────────────
Fire and forget             Block until result
Returns immediately         Returns sub-task's final_answer
Sub-task visible in queue   Sub-task visible in queue
No result in current task   Result available inline
Use for: handoffs           Use for: dependencies
```

Both go through the scheduler queue. Both appear in the event log with parent
linkage. The difference is whether the calling agent waits for the output.

---

## dispatch_subtask — How It Works

When an agent calls `dispatch_subtask(role_id, goal)`:

1. A new `Task` is created with `parent_task_id` set to the current task's ID
   and `dispatch_depth = parent.dispatch_depth + 1`
2. The task is added to the scheduler queue
3. The current agent's tool call blocks, polling every 3 seconds
4. When the sub-task completes, `result.metrics["final_answer"]` is returned
   as the tool result
5. The calling agent continues with that output in its context

The scheduler's `max_concurrent` (default 3) allows the sub-task to run while
the parent is polling — no deadlock.

---

## Depth Limit

Sub-tasks are capped at depth 2. A depth-0 task (user-initiated) can dispatch
to depth-1. A depth-1 task can dispatch to depth-2. Depth-2 tasks cannot
dispatch further.

This prevents runaway recursion without requiring a global lock or complex
coordination.

```
user → scheduler_add_task → depth-0 task
                              └─ dispatch_subtask → depth-1 task
                                                      └─ dispatch_subtask → depth-2 task
                                                                              └─ BLOCKED
```

---

## Data Boundary

`dispatch_subtask` and `scheduler_add_task` are both blocked when a role has
`data_boundary.allow_external_mcp: false`. Dispatching work to another role is
an outbound action — it crosses the role's isolation boundary.

A `local_only: true` role can use all local tools (file, bash, memory) but
cannot delegate to other roles.

---

## Task Model

```python
@dataclass
class Task:
    ...
    parent_task_id: Optional[str] = None  # None = top-level
    dispatch_depth: int = 0               # 0 = user-initiated
```

Both fields are serialized to `scheduler_tasks.json` and survive restarts.
The dashboard task detail page renders "Dispatched by" as a clickable link to
the parent task.

---

## Tool Access

`dispatch_subtask` is in the `orchestration` category alongside
`scheduler_add_task`. A role gets both by declaring:

```json
"tool_access": ["orchestration"]
```

Roles that should NOT orchestrate others (isolated workers, local-only roles)
should omit `orchestration` from their `tool_access`.

---

## Example Workflow

```
Role A (orchestrator) receives goal: "Research X and verify the findings"
  │
  ├─ dispatch_subtask(role_id="<researcher>", goal="Find all sources on X")
  │     blocks until researcher's session completes
  │     returns: researcher's final_answer (sources, summaries)
  │
  ├─ [uses researcher output in context]
  │
  ├─ dispatch_subtask(role_id="<verifier>", goal="Verify these claims: ...")
  │     blocks until verifier's session completes
  │     returns: verifier's final_answer (confirmed / disputed)
  │
  └─ synthesizes both outputs into own final_answer
```

Each dispatched role runs its own full agentic session with its own tool
access, memory, and personality. The orchestrator sees only the `final_answer`.

---

## Timeout

Default timeout: 300 seconds. Configurable per call:

```json
dispatch_subtask(role_id="...", goal="...", timeout_s=600)
```

On timeout the sub-task continues running in the queue (it is not cancelled).
The calling agent receives an error and can decide to continue without the
result or call `ask_user` to escalate.

---

## v1.3.x Extensions

- **Parallel dispatch** — fire multiple `scheduler_add_task` calls, then poll
  each task ID to collect results (no new primitives needed)
- **Result streaming** — SSE events as sub-task completes iterations (v1.3.x)
- **Cross-role referral in chat** — chat mode can suggest "ask role X" and
  hand off session context (v1.3.2)
