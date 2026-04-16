# LOCOMO Runbook

## Runner

Primary runner:

- `tests/benchmarks/run_locomo.py`
- `tests/benchmarks/run_locomo_abcd_e2e.py` for ABCD end-to-end preparation + evaluation
- `tests/benchmarks/run_locomo_role_memory.py` for the intended product path: role-private conversation facts with optional ABCD augmentation

Future rule:

- no accepted LOCOMO results should depend on `/tmp/*.py`

## Dataset

Recommended local dataset staging path:

- `/tmp/locomo/data`

This is acceptable for local data staging.
It is not the benchmark authority.

## Run Types

We should support at least:

- `raw_context`
- `raw_retrieval`
- `abcd_b`
- `abcd_bc`
- `facts_only` via a benchmark role such as `ben`
- `facts_plus_abcd` via the same benchmark role

## Storage

Dream artifacts should live in an isolated role/runtime path, for example:

- `~/.memory/roles/locomo_bench_<variant>/`

Do not reuse contaminated role dirs across accepted runs without making that explicit.

## Result Artifacts

Store machine-readable results under:

- `~/.memory/benchmarks/locomo/<run_id>/results.json`

Then summarize accepted runs in:

- `docs/benchmarks/locomo/RESULTS.md`

## End-to-End ABCD Command

To prepare dreamed LOCOMO archives with the real `DreamingPipeline` write path and then benchmark them in one command:

```bash
python3 tests/benchmarks/run_locomo_abcd_e2e.py \
  --data-dir /tmp/locomo/data \
  --variant abcd_bc \
  --max-dialogues 1 \
  --output results/locomo_abcd_bc_d1.jsonl
```

Useful options:

- `--max-sessions N` for faster smoke runs during pipeline tuning
- `--reuse-existing` to avoid re-dreaming sessions that already have archives
- `--prepare-only` to build the dreamed role tree without running evaluation

## Product-Path Benchmark Command

To benchmark MoJo the way it is intended to answer questions:

- conversation facts are stored in a role-private memory
- ABCD dreaming is optional augmentation
- the answering prompt is driven by the benchmark role system prompt

Use:

```bash
python3 tests/benchmarks/run_locomo_role_memory.py \
  --data-dir /tmp/locomo/data \
  --role-id ben \
  --variant facts_plus_abcd \
  --prepare-dreams \
  --reset-role-memory \
  --max-dialogues 1 \
  --output results/locomo_ben_facts_plus_abcd_d1.jsonl
```

For the baseline:

```bash
python3 tests/benchmarks/run_locomo_role_memory.py \
  --data-dir /tmp/locomo/data \
  --role-id ben \
  --variant facts_only \
  --reset-role-memory \
  --max-dialogues 1 \
  --output results/locomo_ben_facts_only_d1.jsonl
```

Recommended runner behavior:

- every run gets a stable `run_id`
- every run writes:
  - detailed per-question JSONL
  - normalized summary JSON
- raw ingestion runs should use isolated role dirs such as:
  - `~/.memory/roles/locomo_bench_<run_id>/dialogue_00/`
- dreamed retrieval runs should point `--role-dir` at an already-built dreamed role tree
