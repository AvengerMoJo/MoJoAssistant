# Spec: Doctor Benchmark Module

## Problem

The current doctor surface is useful, but it mixes four different concerns:

1. Runtime health checks
2. Agentic smoke gates
3. Behavioral comparisons such as full vs lean tool schemas
4. Improvement/advice actions

That coupling made sense while the system was small, but it is already showing
strain:

- smoke checks live inside one hardcoded harness
- benchmark-like comparisons are exposed as one-off doctor actions
- persisted result formats are split across smoke log, benchmark store, and
  resource metadata
- unit tests are tightly coupled to `smoke_*` task IDs and scenario names

This makes it harder to answer the actual product question:

> Which model can do what, reliably, and at what speed?

## Desired Outcome

We want doctor to become the operational front end of a reusable model
evaluation system.

That system should support:

- health checks for operators
- qualification gates for approval and routing
- benchmark suites for model characterization
- stable storage of structured results
- generic test scenarios rather than smoke-only hardcoding

## Non-Goals

- Replace LOCOMO or other deeper domain benchmarks
- Build an external public benchmark product in this phase
- Judge open-ended answer quality for every task family
- Collapse all model evaluation into one pass/fail boolean

## Design Principles

### 1. Separate gate checks from characterization

Smoke tests answer:

- "is this resource safe to use at all?"

Benchmarks answer:

- "how capable is this resource across task families and complexity levels?"

These are related, but they are not the same thing and should not share one
result contract.

### 2. Doctor is the SDK surface, benchmark is the engine

Doctor/config actions are the stable operator API.

The evaluation engine should live behind that API as reusable modules:

- scenario definitions
- runners
- scorers
- persistence
- summaries

### 3. Results must be structured enough for routing

The system should not stop at:

- `agentic_capable = true|false`

It should produce routing-grade metadata such as:

- success rate
- latency band
- retry stability
- tool accuracy
- constraint accuracy
- maximum reliable complexity

### 4. Scenarios should be declarative

The current smoke harness embeds scenario logic directly in Python control flow.

That is acceptable for a first implementation, but it scales poorly. The next
step should be a scenario schema that supports multiple suites without requiring
new ad hoc methods every time.

## Module Split

### A. Doctor Module

Purpose:

- operator-facing diagnostics and control surface

Responsibilities:

- expose health checks
- run qualification and benchmark suites
- read history and summaries
- provide improvement suggestions

Recommended surface:

- `config(action="doctor_health", ...)`
- `config(action="doctor_eval_run", ...)`
- `config(action="doctor_eval_history", ...)`
- `config(action="doctor_eval_summary", ...)`
- `config(action="doctor_improve", ...)`
- `config(action="doctor_apply", ...)`

Backward-compatible aliases can preserve current actions:

- `doctor_smoke_history`
- `doctor_mcp_surface`
- `doctor_mcp_surface_eval`

but these should become wrappers over the new generic evaluation engine.

### B. Evaluation Engine

Purpose:

- generic execution and scoring of model-evaluation scenarios

Recommended location:

- `app/scheduler/evals/`

Suggested files:

- `app/scheduler/evals/models.py`
- `app/scheduler/evals/scenarios.py`
- `app/scheduler/evals/runner.py`
- `app/scheduler/evals/scorers.py`
- `app/scheduler/evals/store.py`
- `app/scheduler/evals/suites.py`

### C. Benchmark Store

Purpose:

- append-only storage of scenario results
- aggregate summaries for routing and doctor output

Important point:

This should reuse the current `BenchmarkStore` ideas, but not overload its
execution-rerun log with unrelated qualification records.

Recommended storage layout:

- `~/.memory/benchmarks/execution_log.jsonl` for production/rerun task history
- `~/.memory/benchmarks/eval_log.jsonl` for explicit doctor/benchmark runs
- `~/.memory/benchmarks/eval_summary.json` for cached aggregates

## Evaluation Taxonomy

We should split evaluation into three top-level categories.

### 1. Health

Answers:

- is config valid?
- is endpoint reachable?
- is auth present?
- is model responding?
- are backends available?

Examples:

- endpoint probe
- context probe
- config validation
- MCP tool list sizing

### 2. Qualification

Answers:

- can this model be approved for agentic use?
- which MoJo profile can it safely support?

Examples:

- `fast_gate`
- `standard_agentic`
- `reasoning_stress`

### 3. Characterization

Answers:

- where does this model become unreliable?
- how does it compare to peers?
- what task complexity band should routing assign to it?

Examples:

- full vs lean comparison
- complexity ladder
- retry robustness
- noisy-context robustness
- longer-horizon planning

## Generic Scenario Model

Replace smoke-specific branching with a generic scenario definition model.

### Core objects

#### `EvalScenario`

Fields:

- `id`
- `suite`
- `category` (`health`, `qualification`, `characterization`)
- `task_family`
- `complexity_level`
- `goal_template`
- `available_tools`
- `tool_schema_mode` (`full`, `lean`, `either`)
- `max_iterations`
- `max_duration_seconds`
- `requires_backends`
- `artifact_expectations`
- `checks`
- `tags`

#### `EvalCheck`

Fields:

- `id`
- `kind`
- `required`
- `failure_class`
- `params`

Supported kinds in phase 1:

- `tool_called`
- `final_answer_present`
- `final_answer_contains`
- `file_written_exact`
- `min_tool_call_count`
- `retry_after_failure`
- `backend_available`
- `duration_under`

#### `EvalSuite`

Fields:

- `id`
- `display_name`
- `category`
- `default_scenarios`
- `gating_policy`
- `summary_metrics`

## Initial Suite Set

### Suite 1: `qualification_fast`

Purpose:

- replace current `fast_gate`

Complexity:

- `L1`

Scenarios:

- deterministic lookup
- write workflow

### Suite 2: `qualification_standard`

Purpose:

- replace current `standard_agentic`

Complexity:

- `L2`

Scenarios:

- lookup then write
- retry-after-failure
- grounded final answer

### Suite 3: `qualification_reasoning`

Purpose:

- replace current `reasoning_stress`

Complexity:

- `L3`

Scenarios:

- constrained plan selection
- multi-lookup evidence gathering
- exact write artifact

### Suite 4: `characterization_tool_schema`

Purpose:

- compare `full` vs `lean`

Complexity:

- same base scenario under multiple schema modes

### Suite 5: `characterization_complexity_ladder`

Purpose:

- classify what the model can do

Complexity bands:

- `L1 Basic`
- `L2 Workflow`
- `L3 Constrained reasoning`
- `L4 Noisy context`
- `L5 Long-horizon`

This is the suite the product actually needs for routing decisions.

## SDK / MCP Surface

The operator API should be stable and generic.

### `config(action="doctor_eval_run")`

Runs one suite or one scenario against one resource.

Parameters:

- `resource_id` required
- `suite` optional
- `scenario_id` optional
- `repeats` optional
- `tool_schema_mode` optional
- `integration_checks` optional
- `store_result` optional, default true

Rules:

- exactly one of `suite` or `scenario_id` must be provided
- `suite` may expand into multiple scenarios
- repeated runs are stored individually and summarized in the response

### `config(action="doctor_eval_history")`

Returns historical evaluation rows.

Parameters:

- `resource_id` optional
- `suite` optional
- `scenario_id` optional
- `category` optional
- `limit` optional

### `config(action="doctor_eval_summary")`

Returns aggregated capability view.

Parameters:

- `resource_id` optional
- `suite` optional
- `window_days` optional

Suggested output:

- `success_rate`
- `avg_latency`
- `p95_latency`
- `failing_checks`
- `max_reliable_complexity`
- `recommended_uses`
- `avoid_uses`

### `config(action="doctor_health")`

Replaces fragmented health-only diagnostics with one typed surface:

- config validity
- endpoint reachability
- context probe summary
- stale evaluation status

## Persistence Model

Introduce a generic evaluation record.

### `EvalRecord`

Fields:

- `ts`
- `resource_id`
- `model`
- `suite`
- `scenario_id`
- `category`
- `task_family`
- `complexity_level`
- `tool_schema_mode`
- `success`
- `checks`
- `iterations_used`
- `duration_seconds`
- `artifacts`
- `error`
- `tags`
- `debug_artifact_path`

This should be append-only JSONL.

### Resource metadata

`resource_pool_meta.json` should keep only the latest summary fields relevant to
resource routing, for example:

- latest qualification result
- last qualified at
- highest passing complexity level
- median latency band
- stale flag

Do not store full benchmark history in `resource_pool_meta.json`.

## Scoring and Routing Summary

The system should compute a derived capability card per resource.

Recommended summary fields:

- `qualified_for_basic_agentic`
- `qualified_for_standard_agentic`
- `qualified_for_reasoning_tasks`
- `max_reliable_complexity`
- `median_fast_gate_s`
- `median_standard_agentic_s`
- `tool_accuracy`
- `retry_recovery_rate`
- `constraint_accuracy`
- `schema_sensitivity`

This should drive scheduler routing later, but in phase 1 it only needs to be
visible through doctor/config.

## Migration of Current Smoke Scenarios

Map current hardcoded smoke profiles into declarative scenarios.

### Existing `fast_gate`

Split into:

- `scenario.lookup_basic`
- `scenario.write_basic`

### Existing `standard_agentic`

Split into:

- `scenario.lookup_then_write`
- `scenario.retry_once`

### Existing `reasoning_stress`

Split into:

- `scenario.constraint_plan_choice`

### Existing integration checks

Split into:

- `scenario.integration_memory_search`
- `scenario.integration_bash_exec`

### Existing full vs lean comparison

Represent as:

- same scenario set
- run once with `tool_schema_mode=full`
- run once with `tool_schema_mode=lean`

## Test Migration Plan

Current test files are too tied to smoke internals such as:

- `smoke_test_*` task IDs
- `smoke_choice_*`
- `smoke_retry_*`
- direct expectations against hardcoded scenario branching

We should migrate them to generic evaluation-runner tests.

### New test layers

#### 1. Scenario contract tests

New file examples:

- `tests/unit/test_eval_scenarios.py`

Purpose:

- validate scenario definitions are well formed
- required fields exist
- check kinds are recognized
- gating metadata is valid

#### 2. Runner tests

New file examples:

- `tests/unit/test_eval_runner.py`

Purpose:

- runner executes one scenario
- multiple checks are evaluated correctly
- artifact verification works
- generic failure classes are assigned correctly

#### 3. Suite tests

New file examples:

- `tests/unit/test_eval_suites.py`

Purpose:

- `qualification_fast` expands to the right scenarios
- `qualification_standard` adds retry/workflow scenarios
- `characterization_tool_schema` runs both full and lean

#### 4. Store tests

New file examples:

- `tests/unit/test_eval_store.py`

Purpose:

- append-only persistence
- summary aggregation
- filtering by resource/suite/category

#### 5. Doctor surface tests

New file examples:

- `tests/unit/test_doctor_eval_actions.py`

Purpose:

- `doctor_eval_run`
- `doctor_eval_history`
- `doctor_eval_summary`

### Compatibility tests to keep temporarily

Keep a thin compatibility layer while migrating:

- current smoke wrapper tests
- current `doctor_smoke_history` tests
- current `doctor_mcp_surface_eval` tests

But rewrite them as alias tests over the generic engine rather than bespoke
behavior tests.

## Recommended File Migration

### Keep temporarily

- `app/scheduler/agentic_smoke_test.py`

### Add

- `app/scheduler/evals/models.py`
- `app/scheduler/evals/scenarios.py`
- `app/scheduler/evals/runner.py`
- `app/scheduler/evals/store.py`
- `app/scheduler/evals/suites.py`

### Then convert

- `AgenticSmokeTest.run(...)`
  becomes a thin adapter to `qualification_fast|standard|reasoning`

- `compare_tool_schema_modes(...)`
  becomes a thin adapter to `characterization_tool_schema`

- doctor actions call the generic eval runner rather than smoke-specific code

## Phased Implementation

### Phase 1: Generic storage and scenario objects

Deliver:

- `EvalRecord`
- scenario/check dataclasses
- `eval_log.jsonl`
- `doctor_eval_history`

### Phase 2: Runner extraction

Deliver:

- generic runner
- smoke profiles reimplemented as scenario suites
- current smoke API preserved as compatibility wrapper

### Phase 3: Doctor API consolidation

Deliver:

- `doctor_eval_run`
- `doctor_eval_summary`
- alias old actions to new engine

### Phase 4: Complexity ladder

Deliver:

- `characterization_complexity_ladder`
- capability summaries per resource
- routing-facing summary fields

## Acceptance Criteria

1. Current smoke functionality still works through compatibility wrappers.
2. At least one generic suite can run without mentioning "smoke" internally.
3. Eval history is stored in a generic benchmark log, not only smoke-specific
   metadata.
4. Tests no longer depend on hardcoded `smoke_*` task IDs for core runner
   behavior.
5. Doctor/config can answer:
   - is this model healthy?
   - what complexity level is it reliable at?
   - how does it compare under full vs lean tool schemas?

## Recommendation

Build this as a benchmark module with doctor as the operator shell.

That keeps the current operational entry point intact while giving MoJo a real
internal LLM tester:

- qualification for safety
- characterization for routing
- longitudinal history for tuning

That is the right shape if the product goal is to understand which model can do
what, rather than only whether a model passes one smoke gate.
