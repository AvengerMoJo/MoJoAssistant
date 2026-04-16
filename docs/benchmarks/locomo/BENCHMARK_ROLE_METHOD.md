# LOCOMO Benchmark Role Method

## Why This Exists

The original LOCOMO benchmark work in MoJo explored raw retrieval and ABCD retrieval directly.

That is useful for diagnosis, but it does not fully represent the intended MoJo product path.

MoJo is not meant to answer memory questions from dreamed artifacts alone.
It is meant to answer from:

- role-private factual memory first
- ABCD dreaming second

This document defines the LOCOMO benchmark method for that intended design.

## Benchmark Role

Primary benchmark role:

- `ben`

Ben is a dedicated memory benchmark role. He exists only to evaluate memory behavior honestly.

His contract is:

- answer from role-private memory only
- treat conversation facts as primary evidence
- treat ABCD as secondary support
- abstain when evidence is insufficient

## Benchmark Variants

### `facts_only`

LOCOMO sessions are ingested into Ben's private memory as factual records.

Ben answers questions from those facts only.

This is the main baseline.

### `facts_plus_abcd`

The same factual memory is present, and LOCOMO sessions are also processed through the dreaming pipeline.

Ben answers from factual memory first, with ABCD available as augmentation.

This is the main product-path evaluation.

### `abcd_only`

Diagnostic mode only.

Useful for understanding the standalone performance of dreamed memory, but not a primary product claim.

## Ingestion Method

LOCOMO sessions are loaded into Ben's private memory as role-scoped factual records.

Each stored record should preserve:

- dialogue id
- session id
- turn id
- date
- speaker
- raw text

This ensures factual recall and temporal grounding remain possible.

## Dreaming Method

When `facts_plus_abcd` is used:

- the same LOCOMO sessions are processed by the real `DreamingPipeline`
- dream archives are stored under Ben's role-private path
- the benchmark may reuse existing dreams only when that is explicitly disclosed

## Answer Method

Ben answers with this evidence order:

1. conversation facts
2. dreamed `B` chunks
3. dreamed `C` clusters

The answer prompt must instruct Ben:

- do not speculate
- do not replace missing facts with themes
- say `I don't have that information.` when evidence is insufficient

## What This Method Tests

This method answers the real product question:

> Does MoJo's dreaming pipeline improve a role's ability to answer from its own private memory?

That is more important than asking whether ABCD alone is strong in isolation.

## Accepted Comparison

For LOCOMO, the preferred comparison order is:

1. `facts_only`
2. `facts_plus_abcd`
3. `abcd_only` diagnostic
4. optional synthetic ablations such as `raw_context`, `raw_retrieval`, `abcd_b`, `abcd_bc`

## Required Disclosures

Every accepted result should disclose:

- role id
- variant
- whether role memory was reset
- whether dreams were freshly prepared or reused
- dialogue count
- question count
- answer model
- judge model if used
- embedding backend/model
- artifact paths

## Current Runner

The current product-path LOCOMO runner is:

- `tests/benchmarks/run_locomo_role_memory.py`

The supporting ABCD end-to-end runner remains:

- `tests/benchmarks/run_locomo_abcd_e2e.py`

The synthetic ablation runner remains:

- `tests/benchmarks/run_locomo.py`
