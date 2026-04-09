# Proposal: Assistant Task Execution End-to-End Fix

## Problem

The capability-to-tool distinction is now documented, but the end-to-end
assistant task flow is still not fully self-evident to MCP clients or fully
guarded by tests.

Current reality:

- role configs correctly use `capabilities`
- runtime translates capabilities into tools
- docs now explain this boundary

But remaining gaps still cause job failures:

- external clients do not have one canonical end-to-end guide
- runtime/tool schemas can still drift from handlers
- some tasks depend on generic file tools when a domain-specific tool would be safer
- success can still be reported even when the task's semantic goal was not really met

## Desired Outcome

An MCP client brain should be able to do this reliably:

1. choose a role
2. schedule an assistant task
3. trust capabilities as the stable abstraction
4. rely on runtime translation to concrete tools
5. understand the iteration/final-answer lifecycle
6. inspect the correct result artifacts

## Urgent

### 1. Lock schema ↔ handler parity

Add a regression suite that asserts:

- every built-in exported tool schema matches its runtime handler
- required argument names are identical
- backward-compatible aliases remain handler-only, not canonical export

This prevents more failures like:

- exported `search_in_files(pattern)`
- runtime expecting `query`

### 2. Add task-level semantic completion checks

Current runtime knows whether a final answer exists.
It does not always know whether the requested job was actually completed.

Proposal:

- add optional task validators for specific task classes
- examples:
  - file-output-required
  - evidence-count-required
  - task-session-analysis-required

If the semantic validator fails:

- task should not be marked normal `completed`
- return `completed_incomplete` or `failed_validation`

### 3. Add domain-specific tools for hard analysis tasks

Some tasks are too fragile when routed through generic file tools.

Example:

- task session analysis over `~/.memory/task_sessions/`

Proposal:

Add tools like:

- `task_session_read(task_id)`
- `task_session_search(query, role_id?, limit?)`
- `task_report_read(task_id)`

This reduces:

- path guessing
- schema confusion
- raw filesystem dependence

## Important

### 4. Add one canonical assistant-task smoke test

Create an end-to-end smoke test covering:

1. role with `file` capability
2. `scheduler(action="add", type="assistant", ...)`
3. capability translation to working file tools
4. one successful tool call
5. valid `FINAL_ANSWER`
6. task report written

This should verify the full path, not only pieces.

### 5. Make scheduler MCP help teach the execution contract directly

Improve the `scheduler` help text with one complete example:

- schedule assistant task
- explain role capabilities
- explain `available_tools` override
- explain session/report outputs

### 6. Add doctor/smoke checks for tool-calling model profiles

Track local models like:

- Qwen 3.5
- Gemma 4

and explicitly record:

- tool-call fidelity
- duplicate call behavior
- malformed argument behavior

This should become a visible compatibility profile, not tribal knowledge.

## Planned

### 7. Generate a machine-readable capability map

Expose a runtime view like:

```json
{
  "file": ["read_file", "write_file", "list_files", "search_in_files"],
  "memory": ["memory_search", "add_conversation"]
}
```

Use cases:

- diagnostics
- MCP inspection
- dashboard explanation
- smoke tests

### 8. Add task-intent classes

Some assistant tasks should declare intent:

- `research`
- `analysis`
- `file_output`
- `review`
- `orchestration`

This allows:

- better validation
- better prompt shaping
- better completion checks

### 9. Add result-contract declarations

Allow tasks to declare expected outputs such as:

```json
{
  "result_contract": {
    "requires_final_answer": true,
    "requires_output_file": false,
    "requires_evidence_count": 2
  }
}
```

This would let the runtime detect undercompleted tasks more honestly.

## Implementation Plan

### Phase 1

- keep roles and MCP surfaces capability-based
- keep scheduler model payloads tool-based
- enforce schema ↔ handler parity with tests

### Phase 2

- improve scheduler help text
- add the end-to-end assistant task smoke test
- expose machine-readable capability map

### Phase 3

- add domain-specific task session/report tools
- add semantic completion validators

### Phase 4

- add task intent + result contract support
- integrate model compatibility checks into doctor/smoke flow

## Acceptance Criteria

1. A client can schedule an assistant task using only role/capability concepts
2. Runtime reliably translates capabilities into correct concrete tool schemas
3. Exported tool schemas match handler expectations
4. At least one end-to-end assistant task smoke test passes
5. File-analysis tasks no longer depend on fragile raw-path guessing
6. Tasks that do not satisfy semantic expectations are not marked plain `completed`

## Short Recommendation

If you want the highest-value next fix order:

1. schema/handler parity tests
2. canonical end-to-end smoke test
3. `task_session_*` / `task_report_*` tools
4. semantic completion validation
