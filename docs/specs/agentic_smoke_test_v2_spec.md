# Spec: Agentic Smoke Test v2

## Problem

The current `AgenticSmokeTest` is useful, but it mixes together three different
questions:

1. Can this model emit valid tool calls?
2. Can this model complete a minimal MoJo agent loop correctly?
3. Are the underlying MoJo backends for those tools actually available?

That coupling creates false signals.

Example:

- the current primary smoke goal requires `memory_search`
- the smoke harness constructs `AgenticExecutor` without a `memory_service`
- the model still passes if it calls the tool correctly and produces
  `<FINAL_ANSWER>`
- but the returned content says the memory service is unavailable

This is confusing for humans and weak as a release gate.

The current smoke test also does not clearly distinguish:

- a fast compatibility gate for all local models
- a stronger gate for models marked `agentic_capable`
- a harder reasoning profile for "thinking" models that should solve
  multi-step tool tasks rather than only obey one forced tool instruction

## Desired Outcome

We want a smoke system that is:

- accurate: failures identify the correct layer
- fast: a default gate should finish quickly enough for routine use
- representative: it should reflect MoJo's real executor path
- graded: not every model needs the same depth of evaluation
- debuggable: failures should explain whether the issue is tool calling,
  executor compliance, backend wiring, argument quality, or latency

## Non-Goals

- Replace LOCOMO or deeper benchmark suites
- Judge open-ended answer quality
- Prove full product correctness across all tool categories
- Use one single smoke profile for every resource type

## Root Issues in v1

### 1. Hidden backend dependency

The primary smoke task uses `memory_search`, but the smoke harness does not bind
the executor to a live memory service. That means the test is partly checking a
tool backend that is not actually present in the harness.

Result:

- model behavior may be correct
- smoke output still reads like a tool/backend failure
- operators cannot immediately tell whether the resource or the harness is at fault

### 2. Over-forced prompt shape

The default prompts use "MUST call X". This is useful for strict tool-call
validation, but weak for evaluating whether a model can choose the right tool in
a more realistic setting.

Result:

- good for API fidelity
- not good enough for higher-confidence `agentic_capable` approval

### 3. Single-level pass/fail

Today `agentic_capable` is mostly a boolean gate. That is too coarse for local
model routing decisions.

We also care about:

- speed
- first-tool latency
- malformed argument rate
- multi-step stability
- reasoning-model performance on harder tasks

### 4. Ambiguous scope

The current smoke test is part resource gate, part executor smoke, part backend
smoke. These should be related, but they should not be the same check.

## Proposal

Split smoke coverage into three layers with explicit purposes.

### Layer A: Resource Gate Smoke

Purpose:

- answer "can this resource drive the executor correctly?"
- no dependency on memory, external MCP, or nonessential services
- fast enough to run often

This becomes the default check behind:

- `config(action="resource_smoke_test")`
- first-run approval
- periodic `agentic_capable` refresh

### Layer B: Integration Smoke

Purpose:

- answer "can this resource work against real MoJo backend services?"
- slower and more environment-sensitive
- should report backend failures separately from model failures

This is optional by profile or explicit flag.

### Layer C: Reasoning Stress Smoke

Purpose:

- answer "is this model suitable for harder agentic tasks?"
- intended for local thinking models and premium resources
- not required for every local model

This should not block basic `agentic_capable` unless configured to do so.

## Smoke Profiles

### Profile 1: `fast_gate`

Target:

- all local resources
- quick retest after config changes
- routine `agentic_capable` refresh

Budget:

- target under 20 seconds on a healthy local model
- hard cap 45 seconds

Checks:

1. Tool call emitted through executor path
2. Valid `<FINAL_ANSWER>`
3. Multi-step write workflow succeeds
4. No XML/plain-text tool leakage
5. Argument payload parses and matches required schema

Tool surface:

- deterministic built-in smoke tools only

Recommended tools:

- `smoke_lookup`
- `write_file`

`smoke_lookup` should return deterministic local data from the harness, for
example:

```json
{"query":"alpha","result":"smoke_lookup_ok:alpha"}
```

This removes the hidden memory-service dependency from the default smoke path.

### Profile 2: `standard_agentic`

Target:

- models being approved for normal MoJo autonomous tasks

Budget:

- target under 60 seconds
- hard cap 120 seconds

Checks:

1. All `fast_gate` checks
2. Tool choice from a small menu, not only one forced tool
3. Two-step task requiring read-then-write or lookup-then-write
4. Final answer grounded in actual tool result
5. Retry stability: model recovers from one injected tool error or empty result

Tool surface:

- deterministic smoke tools
- optional local file tool

Example task:

- "Find the token for project alpha via `smoke_lookup`, then write it to a temp
  file and confirm the exact token in `<FINAL_ANSWER>`."

This is still deterministic but closer to a real multi-step agent loop.

### Profile 3: `reasoning_stress`

Target:

- thinking models
- high-priority local resources
- resources intended for harder orchestration or coding tasks

Budget:

- target under 180 seconds
- hard cap configurable by resource tier

Checks:

1. Tool selection among distractors
2. Constraint handling across multiple steps
3. One small planning decision with at least two viable branches
4. No premature final answer before required evidence is gathered
5. Stable output under higher context and longer prompt

Example task class:

- "You need the cheapest valid plan that satisfies constraints A/B/C. Read
  three synthetic tool responses, compare them, write the chosen plan, and
  explain why the others fail."

This is the right place to evaluate whether a "thinking model" is actually
useful, rather than only obedient.

## Detailed Changes

### 1. Replace `memory_search` in the default smoke path

Do not use `memory_search` as the primary default smoke tool.

Reason:

- it is not deterministic
- it depends on backend wiring
- it obscures whether failure belongs to the resource or the harness

Replace it with a harness-owned deterministic tool such as `smoke_lookup`.

Requirements for `smoke_lookup`:

- no network
- no embeddings
- no external MCP
- deterministic response
- structured return payload

### 2. Keep `write_workflow` as a mandatory default check

The `write_file` workflow is still valuable because it catches:

- XML tool-call leakage
- plain-text "I wrote the file" hallucinations
- multi-step executor failures

Keep it mandatory in `fast_gate` and above.

### 3. Add explicit backend-integration mode

If we want to test real `memory_search`, do it in a separate named check such as:

- `integration_memory_search`

That check must:

- inject a real memory service into the executor, or
- run through the actual runtime surface that already owns one

If the memory service is absent, report:

- `status="skip"` with reason `memory_backend_unavailable`

Do not phrase it as a model failure.

### 4. Add per-check failure classes

Each check should emit a machine-readable failure class:

- `tool_not_called`
- `wrong_tool`
- `malformed_arguments`
- `final_answer_missing`
- `premature_final_answer`
- `tool_backend_unavailable`
- `executor_exception`
- `timeout`
- `xml_tool_leakage`
- `verification_mismatch`

This is more important than a prose message for later routing and doctor output.

### 5. Add latency metrics

Persist at least:

- total duration
- first-tool latency
- time-to-final-answer
- iteration count
- per-tool-call count

This allows MoJo to separate:

- correct but too slow
- fast but unstable
- strong reasoning but expensive

## Scoring Model

Keep `agentic_capable` as the coarse gate, but attach richer metadata.

Suggested output:

```json
{
  "agentic_capable": true,
  "smoke_profile": "standard_agentic",
  "checks": {
    "tool_calling": {"status": "pass"},
    "write_workflow": {"status": "pass"},
    "tool_choice": {"status": "pass"}
  },
  "metrics": {
    "duration_seconds": 24.6,
    "first_tool_latency_seconds": 6.1,
    "iterations_used": 3
  },
  "rating": {
    "obedience": "high",
    "stability": "high",
    "speed": "medium",
    "reasoning": "unknown"
  }
}
```

Notes:

- `agentic_capable` remains the scheduling gate
- `rating` supports smarter routing and benchmark analysis
- `reasoning` should remain `unknown` unless the harder profile ran

## Smarter Routing Use

The smoke system should support routing decisions such as:

- fast local model for lightweight assistant tasks
- slower thinking model for negotiation, planning, or complex coding

That means the smoke result should expose enough information to answer:

- is this model fast enough for chat-like agent loops?
- is this model stable enough for tool-heavy execution?
- is this model smart enough for multi-step constraint solving?

## Implementation Sketch

### New harness-owned smoke tools

Add deterministic internal tools only for the smoke harness:

- `smoke_lookup(query)`
- `smoke_compare(options, constraints)`
- optional `smoke_fail_once(key)` for retry behavior

These should be:

- executor-local
- side-effect free except where explicitly intended
- not exported as general-purpose user tools

### `AgenticSmokeTest` API

Extend `run()` to accept:

- `profile`: `fast_gate | standard_agentic | reasoning_stress`
- `integration_checks`: optional list such as `["memory_search"]`
- `max_duration_seconds`
- `speed_tier`: optional thresholds for local vs remote resources

### MCP surface

Extend `config(action="resource_smoke_test")` to accept:

- `profile`
- `integration_checks`
- `record_benchmark`

Default behavior:

- `profile="fast_gate"`
- no backend integration checks unless requested

### Persistence

Persist the latest smoke metadata alongside `agentic_capable` TTL data:

- profile used
- check breakdown
- timing metrics
- failure classes

## Migration Plan

### Phase 1

- keep current `write_workflow`
- replace default `memory_search` path with deterministic `smoke_lookup`
- add failure classes
- add timing breakdown

### Phase 2

- add `standard_agentic` profile
- add tool-choice and multi-step deterministic scenario
- expose `profile` through MCP

### Phase 3

- add optional integration checks with real backend injection
- report backend unavailability separately from model failures

### Phase 4

- add `reasoning_stress`
- integrate result into benchmark store and routing heuristics

## Acceptance Criteria

1. Default smoke no longer reports a fake `memory_search unavailable` signal when
   the model behavior is correct.
2. A model can fail because of backend integration without being mislabeled as a
   generic tool-calling failure.
3. Default smoke runtime is materially faster and deterministic.
4. `agentic_capable` remains a clear gate, but richer metrics are available for
   routing and debugging.
5. At least one harder profile exists that can distinguish obedient models from
   genuinely useful reasoning models.

## Recommendation

Build this in the following order:

1. fix the default smoke contract by removing hidden backend dependencies
2. keep the write verification path as the baseline multi-step check
3. add deterministic tool-choice coverage
4. add a separate real-backend integration layer
5. add a reasoning-stress profile for slower thinking models

That sequence fixes the current misleading behavior first, improves speed next,
and only then adds the more expensive "smarter model" evaluation.
