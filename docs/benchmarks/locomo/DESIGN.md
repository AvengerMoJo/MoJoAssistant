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

Expected weakness:

- adversarial abstention is likely weak until explicitly tuned

## Required Outputs

Each LOCOMO run should report:

- dialogue count
- question count
- per-category scores
- retrieval latency
- context token size
- abstention behavior
- exact retrieval mode
