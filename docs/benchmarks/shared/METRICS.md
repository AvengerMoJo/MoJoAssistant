# Benchmark Metrics

These are the core metrics we should track consistently across benchmark runs.

## Primary Metrics

### Answer Quality

- `J score`
  - LLM-as-judge semantic equivalence
  - useful for LOCOMO-style conversational QA

- `F1`
  - token overlap / extractive-style answer quality
  - useful where exact answer structure matters

### Retrieval Quality

- `retrieval_recall_at_k`
- `retrieval_precision_at_k`
- `evidence_hit_rate`
- `relevant_chunks_retrieved`

These matter because MoJo is not just an answer generator. It is a memory system.

### Adversarial / Abstention

- `abstention_rate`
- `false_positive_answer_rate`

These are especially important for:

- LOCOMO category 5
- LongMemEval no-answer or insufficient-context cases

## Secondary Metrics

- `mean_retrieval_latency_ms`
- `p95_retrieval_latency_ms`
- `mean_generation_latency_ms`
- `tokens_in_context`
- `chunks_retrieved`
- `tier_breakdown`
  - how much came from raw history vs B chunks vs C clusters vs reports

## Reporting Rule

Every accepted benchmark result should include:

- dataset scope
- dialogue/question counts
- primary metric
- retrieval metric
- abstention metric if relevant
- latency summary
- exact model / embedding backend
