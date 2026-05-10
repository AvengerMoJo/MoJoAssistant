# ABCD Validation Checklist v1

Date: 2026-05-10  
Status: Active validation protocol for memory + dreaming redesign

## Purpose

Ensure ABCD is validated behavior-by-behavior, not only by high-level intent.
This checklist is required for benchmark claims that rely on dreaming output.

## Run Preconditions

1. Runner is committed under `tests/benchmarks/`.
2. Validation mode is enabled (`--validation-mode abcd_v1` where supported).
3. Model interface resolves correctly (no missing interface fallback).
4. Role memory state is declared (`--reset-role-memory`, `--setup-only`, or `--eval-only`).
5. Dataset slice and question count are explicitly disclosed.

## Stage A — Input Integrity

Pass criteria:
1. Session input is non-empty for all evaluated sessions.
2. Required metadata exists: dialogue id, session id, date, speaker, text.
3. No silent truncation or dropped turn segments.

Fail examples:
1. Missing session date metadata.
2. Empty session body with non-empty session id.
3. Empty turn text in source turns.

## Stage B — Chunk Integrity

Pass criteria:
1. Chunk payload schema is valid.
2. Chunks are non-empty and informational.
3. Sampled chunk statements are traceable to source session text.

Fail examples:
1. Empty or malformed chunk list.
2. Template/noise-only chunks.
3. Unsupported factual statements.

## Stage C — Cluster Integrity

Pass criteria:
1. Cluster payload schema is valid.
2. Each cluster has supporting evidence from B-chunks.
3. Cluster content is not generic filler.

Fail examples:
1. Missing `c_clusters`.
2. Cluster claims with no support references.
3. Non-informational cluster summaries.

## Stage D — Archive + Retrieval Integrity

Pass criteria:
1. Archive files are present and parseable.
2. Retrieval probe returns non-empty combined evidence in evaluated questions.
3. Indexed dreamed artifacts remain retrievable in role-scoped queries.

Fail examples:
1. Archive exists but retrieval always empty.
2. All combined hits are zero across evaluated questions.
3. Stage B/C data present but not discoverable in retrieval.

## Runtime Output Validity

Pass criteria:
1. Model output is plain answer text.
2. No tokenizer/control-token leakage.
3. No internal reasoning/template leakage in final answer channel.

Fail examples:
1. `<SPECIAL_*>` token streams.
2. `<|...|>` control tokens in answer.
3. `Thinking Process:` blocks in final answer output.

## Facts-First Contract Gate

For `facts_only` and `facts_plus_abcd` variants:
1. Factual retrieval is primary evidence.
2. Empty factual retrieval is treated as a validation failure (unless explicitly waived for a diagnostic run).
3. ABCD evidence may augment but should not silently replace missing factual retrieval.

## Artifact Requirements

Each accepted run must include:
1. Machine-readable detailed result artifact (`.jsonl`).
2. Machine-readable summary artifact (`results.json`).
3. Validation block with:
   - mode
   - run validity flag
   - stage check pass/fail records
   - invalid reasons list
   - counters (`invalid_output_count`, `empty_facts_count`, `questions_checked`)

## Acceptance Rule

A run is accepted only if:
1. All stage checks pass.
2. Output validity checks pass.
3. Facts-first contract is satisfied for product-path variants.
4. Required disclosures in `EVALUATION_POLICY.md` are complete.

Otherwise the run is exploratory/diagnostic and must not be used as a final quality claim.
