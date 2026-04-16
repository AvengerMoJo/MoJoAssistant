# LOCOMO Design

## Goal

Use LOCOMO to measure whether MoJoAssistant's memory system, especially the
ABCD dreaming pipeline, improves long-horizon conversational recall and synthesis.

## Core Comparison

The benchmark should compare these system variants:

1. `RawContext`
2. `RawRetrieval`
3. `ABCD-B`
4. `ABCD-BC`

These are still useful synthetic retrieval ablations.

However, the preferred product-path comparison is now:

1. `facts_only`
2. `facts_plus_abcd`

Optional later variant:

5. `ABCD-BC+D-metadata`

## Why LOCOMO Fits MoJo

LOCOMO evaluates:

- long-horizon conversational memory
- multi-session reasoning
- temporal recall
- adversarial abstention

That matches MoJo's product claim better than a simple short-context QA benchmark.

## MoJo-Specific Hypothesis

Expected strengths:

- `B` chunks help single-hop and temporal recall
- `C` clusters help multi-hop and commonsense questions

For the product-path benchmark:

- role-private conversation facts should anchor factual and temporal recall
- ABCD should improve cross-session linkage and abstraction without degrading factual grounding

Expected weakness:

- adversarial abstention is likely weak until explicitly tuned

## Preferred Method

LOCOMO should not be evaluated only as an ABCD-only memory system.

The preferred method is:

- benchmark role-private factual memory first
- add ABCD as augmentation second

See:

- [BENCHMARK_ROLE_METHOD.md](/home/alex/Development/Personal/MoJoAssistant/docs/benchmarks/locomo/BENCHMARK_ROLE_METHOD.md)
- [ROLE_MEMORY_BENCHMARK_METHOD.md](/home/alex/Development/Personal/MoJoAssistant/docs/benchmarks/shared/ROLE_MEMORY_BENCHMARK_METHOD.md)

## Required Outputs

Each LOCOMO run should report:

- dialogue count
- question count
- per-category scores
- retrieval latency
- context token size
- abstention behavior
- exact retrieval mode
