# LongMemEval Runbook

## Runner

Primary runner:

- `tests/benchmarks/run_longmemeval.py`

## Result Discipline

Accepted results should not depend on:

- `/tmp` helper scripts
- undocumented local glue code

## Storage

Use isolated benchmark runtime paths under:

- `~/.memory/benchmarks/longmemeval/`
