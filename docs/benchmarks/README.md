# Benchmarks

This directory is the human-readable benchmark home for MoJoAssistant.

Use it to keep three things aligned:

1. **Design**
   - what question a benchmark is meant to answer
   - what systems are being compared
   - what counts as a valid run

2. **Implementation references**
   - which runner in `tests/benchmarks/` produced the results
   - which dataset/version was used
   - which storage paths and models were involved

3. **Accepted results**
   - reproducible benchmark outcomes
   - caveats and limitations
   - what improved and what still fails

## Layout

```text
docs/benchmarks/
  README.md
  shared/
    METRICS.md
    EVALUATION_POLICY.md
    RESULT_SCHEMA.md
  locomo/
    DESIGN.md
    RUNBOOK.md
    RESULTS.md
    ABLATIONS.md
  longmemeval/
    DESIGN.md
    RUNBOOK.md
    RESULTS.md
    ABLATIONS.md
```

## Code vs Docs

- Runnable benchmark code belongs in:
  - `tests/benchmarks/`

- Human-facing benchmark design and accepted result summaries belong here.

## Benchmark Rule

Do not treat `/tmp` scripts or one-off local experiments as benchmark authority.

Exploration is fine in `/tmp`.

Accepted claims must point to:

- a committed runner
- a documented method
- a stored result artifact
- a clearly scoped dataset/run configuration

## Core Product Question

For MoJoAssistant memory, the central benchmark question is:

`Does MoJo's memory + dreaming pipeline improve long-horizon retrieval and answer quality over naive history retrieval?`

That means benchmark reports should favor:

- ablations
- retrieval quality
- answer quality
- abstention behavior
- reproducibility

over isolated one-off scores.
