# Evaluation Policy

This file defines what counts as a valid benchmark claim for MoJoAssistant.

## Accepted Evidence

A benchmark claim is only considered valid if it is backed by:

1. a committed runner in `tests/benchmarks/`
2. a documented method under `docs/benchmarks/`
3. a machine-readable run artifact
4. a human-readable summary with caveats

## Not Accepted As Final Evidence

These are valid for exploration but not for accepted benchmark claims:

- `/tmp/*.py` scripts
- shell-only experiments with no stored result artifact
- one-dialogue pilot runs presented as full benchmark conclusions
- scores without exact model, dataset, and retrieval configuration

## Required Disclosure

Every benchmark result summary must disclose:

- benchmark runner used
- dataset version
- number of dialogues
- number of questions
- whether the run used fresh dreaming or prebuilt dream artifacts
- model used for answering
- model used for judging
- embedding backend/model
- whether the run used:
  - raw context
  - raw retrieval
  - ABCD B only
  - ABCD B + C

## Recommended Comparison Pattern

For memory benchmarks, we should prefer ablations over isolated scores:

1. `RawContext`
2. `RawRetrieval`
3. `ABCD-B`
4. `ABCD-BC`

This shows whether dreaming actually adds value.
