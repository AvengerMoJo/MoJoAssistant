# Result Schema

Benchmark runs should produce a machine-readable artifact in a runtime path such as:

`~/.memory/benchmarks/<benchmark>/<run_id>/results.json`

They should also produce a detailed per-question artifact, typically JSONL, that can be traced back from the summary:

`results/<benchmark>_<run_id>.jsonl`

## Suggested Shape

```json
{
  "benchmark": "locomo",
  "run_id": "2026-04-14_locomo_abcd_bc_qwen35",
  "dataset_version": "locomo10",
  "system_variant": "ABCD-BC",
  "dialogues": 10,
  "questions": 1990,
  "answer_model": "qwen/qwen3.5-35b-a3b",
  "judge_model": "qwen/qwen3.5-35b-a3b",
  "embedding_model": "BAAI/bge-m3",
  "metrics": {
    "j_score": 76.3,
    "f1": null,
    "abstention_rate_cat5": 0.0,
    "mean_retrieval_latency_ms": 71.9,
    "p95_retrieval_latency_ms": 115.6
  },
  "retrieval": {
    "top_k": 15,
    "mode": "abcd_bc",
    "chunks_retrieved_mean": 10.2
  },
  "provenance": {
    "runner": "tests/benchmarks/run_locomo.py",
    "dreaming_mode": "fresh",
    "role_dir": "~/.memory/roles/locomo_bench_d3",
    "detailed_output": "results/locomo_2026-04-14_abcd_bc.jsonl"
  },
  "notes": [
    "Pilot run",
    "Dialogue 0 only"
  ]
}
```

## Human Summary Pairing

Each machine-readable result should have a corresponding summary entry in:

- `docs/benchmarks/locomo/RESULTS.md`
- or `docs/benchmarks/longmemeval/RESULTS.md`

The summary should include:

- what was run
- why it matters
- what the number means
- what caveats apply
