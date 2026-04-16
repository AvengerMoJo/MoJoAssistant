# Benchmark Showcase Subdirectory Plan

## Goal

Create a dedicated benchmark area that makes MoJoAssistant's memory and dreaming
capabilities:

- reproducible
- reviewable
- comparable across runs
- presentable as evidence of system ability

The current benchmark work is promising, but it is split across:

- `tests/benchmarks/` implementation
- top-level docs like `docs/locomo_benchmark_report.md`
- one-off local scripts under `/tmp`

That is fine for experimentation, but weak for a real showcase.

This plan creates a stable benchmark subdirectory structure for:

1. benchmark design
2. benchmark implementation references
3. recorded test results
4. reproducibility instructions

## Recommended Structure

Use two coordinated locations:

### 1. Code and harnesses

Keep executable code in:

`tests/benchmarks/`

This is already the correct place for:

- `run_locomo.py`
- `run_longmemeval.py`
- future benchmark runners
- helper retrieval evaluators
- fixture loaders

### 2. Benchmark design and published results

Add a new docs subdirectory:

`docs/benchmarks/`

Recommended layout:

```text
docs/benchmarks/
  README.md
  locomo/
    DESIGN.md
    METHOD.md
    RESULTS.md
    ABLATIONS.md
    RUNBOOK.md
  longmemeval/
    DESIGN.md
    METHOD.md
    RESULTS.md
    ABLATIONS.md
    RUNBOOK.md
  shared/
    METRICS.md
    EVALUATION_POLICY.md
    RESULT_SCHEMA.md
```

## Why This Split

This keeps responsibilities clean:

- `tests/benchmarks/` = runnable benchmark code
- `docs/benchmarks/` = what the benchmark means, how to run it, and what results count

That matters because benchmark claims should not depend on:

- `/tmp/*.py`
- private shell history
- memory of how a run was performed

## Benchmark Design Principles

Every benchmark in this area should answer one concrete product question.

For MoJo memory, the core product question is:

`Does dreamed memory retrieval outperform naive memory retrieval for long-horizon assistant recall and synthesis?`

Each benchmark design doc should explicitly define:

1. system under test
2. baseline systems
3. datasets
4. evaluation metrics
5. reproducibility requirements
6. failure modes and caveats

## LOCOMO Design

For LOCOMO, the showcase should not present one single run as "the number."

It should present an ablation ladder:

### Systems to compare

1. `RawContext`
- direct context stuffing baseline
- no MoJo memory retrieval

2. `RawRetrieval`
- retrieval over ingested raw conversation/session material
- no ABCD dreaming

3. `ABCD-B`
- dreamed retrieval using B chunks only

4. `ABCD-BC`
- dreamed retrieval using both B chunks and C clusters

5. `ABCD-BC+D-metadata` (optional)
- same as above, but D archive metadata can influence ranking or provenance

### Required outputs

For each LOCOMO run, record:

- dialogue count
- question count
- category breakdown
- answer metric
- adversarial abstention rate
- retrieval latency
- generation latency
- context token size
- storage path used
- exact model and embedding backend

### Required caveats

Every report must say clearly whether the run used:

- one dialogue only
- all dialogues
- local judge LLM
- external judge LLM
- pre-built dreams or fresh dreaming

## LongMemEval Design

LongMemEval should be used similarly, but the focus is different:

- longer memory horizon
- retrieval evidence quality
- answer quality with larger history surfaces

For MoJo, LongMemEval is best used to measure:

- dreamed retrieval vs raw retrieval
- evidence session recall
- ability to answer from compressed memory instead of full logs

## Shared Result Schema

Every benchmark run should produce two artifacts:

### 1. Machine-readable result file

Store in a repo-ignored runtime location, for example:

`~/.memory/benchmarks/<benchmark>/<run_id>/results.json`

Suggested fields:

```json
{
  "benchmark": "locomo",
  "run_id": "2026-04-14_locomo_abcd_bc_qwen35",
  "dataset_version": "locomo10",
  "systems": ["ABCD-BC"],
  "dialogues": 10,
  "questions": 1990,
  "model": "qwen/qwen3.5-35b-a3b",
  "embedding_model": "BAAI/bge-m3",
  "metrics": {
    "j_score": 76.3,
    "abstention_rate_cat5": 0.0,
    "mean_retrieval_latency_ms": 71.9
  },
  "provenance": {
    "runner": "tests/benchmarks/run_locomo.py",
    "dreaming_mode": "fresh",
    "role_dir": "~/.memory/roles/locomo_bench_d3"
  }
}
```

### 2. Human-readable report

Store in:

`docs/benchmarks/<benchmark>/RESULTS.md`

This file should summarize:

- latest accepted runs
- key comparisons
- important caveats
- next hypotheses

## What Should Not Be Used for Final Claims

These are acceptable for exploration, but not for showcase claims:

- `/tmp/run_locomo_abcd.py`
- one-off scripts not committed to the repo
- one-dialogue pilot scores presented like full benchmark numbers
- reports without exact run configuration

## Implementation Plan

### Phase 1 — Directory and governance

Create:

- `docs/benchmarks/README.md`
- `docs/benchmarks/locomo/`
- `docs/benchmarks/longmemeval/`
- `docs/benchmarks/shared/`

Populate the shared docs first:

- `METRICS.md`
- `EVALUATION_POLICY.md`
- `RESULT_SCHEMA.md`

### Phase 2 — LOCOMO cleanup

Move benchmark authority into repo code:

- consolidate `/tmp` benchmark logic into `tests/benchmarks/run_locomo.py`
- add explicit runner modes:
  - `raw_context`
  - `raw_retrieval`
  - `abcd_b`
  - `abcd_bc`

Write docs:

- `docs/benchmarks/locomo/DESIGN.md`
- `docs/benchmarks/locomo/RUNBOOK.md`

### Phase 3 — Result discipline

Require each accepted result to include:

- command used
- dataset scope
- hardware/runtime notes
- model
- embedding backend
- whether dreams were rebuilt

### Phase 4 — LongMemEval alignment

Apply the same structure to:

- `tests/benchmarks/run_longmemeval.py`
- `docs/benchmarks/longmemeval/*`

## Showcase Narrative

The benchmark area should demonstrate three distinct claims:

1. MoJo can store long-lived conversational memory
2. MoJo's ABCD dreaming pipeline improves retrieval quality over naive history retrieval
3. MoJo can do this locally, with inspectable artifacts and reproducible runs

That is the real showcase.

Not:

- "we got one good score once"

But:

- "here is the benchmark design"
- "here is the code that ran it"
- "here are the stored results"
- "here is what improved and what still fails"

## Recommended First Deliverables

Create first:

1. `docs/benchmarks/README.md`
2. `docs/benchmarks/locomo/DESIGN.md`
3. `docs/benchmarks/locomo/RUNBOOK.md`
4. `docs/benchmarks/shared/RESULT_SCHEMA.md`

Then update:

5. `tests/benchmarks/run_locomo.py`

Only after that:

6. publish a refreshed `RESULTS.md`

## My Recommendation

Yes, create a benchmark showcase subdirectory.

The clean architecture is:

- `tests/benchmarks/` for runnable implementations
- `docs/benchmarks/` for benchmark design, methodology, and accepted results

This will turn the current memory benchmark work from exploratory testing into
something you can confidently point to as evidence of MoJoAssistant's ability.
