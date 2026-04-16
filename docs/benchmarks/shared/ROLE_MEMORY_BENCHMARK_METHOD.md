# Role Memory Benchmark Method

## Purpose

This method benchmarks MoJoAssistant the way the product is actually intended to answer memory questions:

- a role owns private factual memory
- conversation/session facts are primary evidence
- dreaming (`A -> B -> C -> D`) is optional augmentation
- answers are generated through the role's own prompt contract

This is different from a synthetic retrieval benchmark where ABCD artifacts are queried directly without going through a role memory surface.

## Core Design

The benchmark role answers from two memory layers:

1. **Conversation facts**
   - raw factual records stored in role-private memory
   - these are the primary answer substrate
   - they preserve date, speaker, turn order, and literal evidence

2. **ABCD dreaming artifacts**
   - optional secondary layer
   - used to expand, connect, summarize, or bridge facts across sessions
   - must not replace direct factual evidence for factual recall questions

## Supported Variants

### `facts_only`

The role answers using only role-private factual memory.

Use this as the product-path baseline.

### `facts_plus_abcd`

The role answers using factual memory first and ABCD as secondary support.

Use this to test whether dreaming improves the real product path.

### `abcd_only`

Diagnostic only.

This is useful for understanding the standalone strength of dreamed memory, but it is not the main product-path benchmark.

## Retrieval Philosophy

The benchmark must follow this evidence order:

1. role-private conversation facts
2. dreamed `B` chunks
3. dreamed `C` clusters
4. archive/version metadata if needed for provenance

The benchmark should never treat `C` as a replacement for factual memory.

## Valid Benchmark Question

The key product question is:

> Does ABCD dreaming make a role better at answering from its own private memory than factual memory alone?

That means the most important comparison is:

1. `facts_only`
2. `facts_plus_abcd`

Synthetic retrieval ablations are still useful, but they are secondary.

## Isolation Rules

- use a dedicated benchmark role
- reset or isolate the role memory before accepted runs
- do not mix benchmark data with live user/assistant memory
- role-private retrieval must never fall back to shared user memory

## Accepted Claim Pattern

A strong memory claim should be framed like:

- `facts_plus_abcd` improved over `facts_only` on the same dataset slice
- exact runner, role, model, and artifact paths are disclosed
- failure modes are disclosed by category

Not like:

- one ABCD-only score in isolation

## Recommended Artifacts

Each run should produce:

- per-question detailed artifact
- machine-readable summary artifact
- role id used
- whether role memory was reset
- whether dreams were freshly prepared or reused
