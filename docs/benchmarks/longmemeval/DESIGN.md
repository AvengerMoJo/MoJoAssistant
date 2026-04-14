# LongMemEval Design

## Goal

Use LongMemEval to test MoJoAssistant on longer-horizon memory tasks with a
focus on retrieval evidence quality and answer quality across compressed memory.

## Why It Complements LOCOMO

LOCOMO is strong for conversational QA structure.

LongMemEval is useful for:

- larger history surfaces
- evidence-based retrieval evaluation
- comparison between raw history retrieval and dreamed retrieval

## Core Comparison

Use the same ablation philosophy as LOCOMO:

1. `RawContext`
2. `RawRetrieval`
3. `ABCD-B`
4. `ABCD-BC`
