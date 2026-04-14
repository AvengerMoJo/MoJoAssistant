# LOCOMO Runbook

## Runner

Primary runner:

- `tests/benchmarks/run_locomo.py`

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

## Storage

Dream artifacts should live in an isolated role/runtime path, for example:

- `~/.memory/roles/locomo_bench_<variant>/`

Do not reuse contaminated role dirs across accepted runs without making that explicit.

## Result Artifacts

Store machine-readable results under:

- `~/.memory/benchmarks/locomo/<run_id>/results.json`

Then summarize accepted runs in:

- `docs/benchmarks/locomo/RESULTS.md`
