# MoJoAssistant Memory Benchmark — LongMemEval & LOCOMO

**Status**: Design phase — no runs yet  
**Created**: 2026-04-13  
**Priority**: CRITICAL — benchmark before v1.3 feature freeze

---

## Why This Matters

MoJoAssistant's multi-tier dreaming memory is the central architectural bet of the project. Before adding features on top, we need to know where we stand relative to the state of the art. The field has converged on two standard benchmarks. We run both.

---

## The Benchmarks

### 1. LongMemEval (ICLR 2025)

**Repo**: https://github.com/xiaowu0162/LongMemEval  
**Paper**: https://arxiv.org/abs/2410.10813

500 manually curated questions testing five core long-term memory abilities across realistic multi-session chat histories:

| Ability | What It Tests |
|---|---|
| Information extraction | Recall a specific fact stated sessions ago |
| Multi-session reasoning | Connect facts across two or more sessions |
| Temporal reasoning | Reason about when things happened, what changed |
| Knowledge updates | Prefer newer information over older contradictions |
| Abstention | Know when memory does NOT contain the answer |

Two scale settings:
- **LongMemEval_S**: ~115,000 token histories (primary benchmark)
- **LongMemEval_M**: up to 1.5 million tokens (stress test)

Evaluation: GPT-4o as judge, or `evaluate_qa.py` script with ground truth oracle.

### 2. LOCOMO (ACL 2024)

**Repo**: https://github.com/snap-research/locomo  
**Paper**: https://arxiv.org/abs/2402.17753

50 long-running multi-agent dialogues (~16,000 tokens each, 19 sessions avg), ~2,000 QA pairs. Tests:
- Single-hop factual recall
- Multi-hop reasoning
- Temporal ordering
- Commonsense + world knowledge
- Adversarial (memory doesn't have the answer)

Evaluation: LLM-as-judge score (J) + F1 on extractive answers.

---

## Current State of the Art (as of April 2026)

### LongMemEval_S

| System | Accuracy | Notes |
|---|---|---|
| Emergence AI RAG | **86%** | SOTA; RAG over full-text summary index |
| Zep | 71.2% | Temporal graph + vector hybrid |
| Mem0 | ~67% | Managed API, best-in-class latency |
| GPT-4o (full context) | 60–64% | Baseline: just stuff everything in context |
| LangMem | ~58% | LangGraph-native, impractical latency (60s p95) |

### LOCOMO (LLM-judge score J)

| System | J Score | F1 | p95 Latency | Tokens/Conv |
|---|---|---|---|---|
| Zep | **76.60** | 49.56 | — | — |
| Mem0 | 75.71 | — | **0.200s** | **1,764** |
| LangMem | 58.10 | — | 59.82s | — |
| Full context | ~55 | — | — | 26,031 |

**Implication**: A system that combines Zep-level J score with Mem0-level latency doesn't exist yet. That's the gap.

---

## MoJoAssistant's Architectural Position

### Advantages

| Feature | MoJoAssistant | Field Comparison |
|---|---|---|
| **Privacy** | Fully local — no memory sent to third parties | Mem0, Zep, LangMem all cloud-only |
| **Role isolation** | Knowledge scoped per role — strict boundaries | Nobody else does this |
| **Semantic consolidation** | Dreaming A→B→C→D compresses raw chat into structured facts | Similar to Zep's graph approach but LLM-driven |
| **Multi-model embeddings** | nomic-embed-v2 + BAAI/bge-m3 in parallel | Reduces embedding monoculture |
| **4-tier hierarchy** | Working → Active → Archival → Knowledge | More granular than MemGPT's 3-tier |
| **Versioned archives** | Every dream version kept; old never deleted | Better than Mem0's overwrite-on-update |

### Risks Going Into the Benchmark

| Risk | Likely Impact |
|---|---|
| JSON-backed archival (no vector DB index) | High latency on large archives — linear scan |
| Dreaming runs nightly, not real-time | Yesterday's conversation not searchable until next dream |
| Working memory token limit (4000 tokens) | May truncate relevant context before it reaches archival |
| No temporal graph | Temporal reasoning questions may underperform Zep |
| Abstention tuning | Unknown — no prior testing |

---

## What We Need to Run LongMemEval

### Step 1: Clone and Download Data

```bash
git clone https://github.com/xiaowu0162/LongMemEval /tmp/longmemeval
cd /tmp/longmemeval

# Download datasets (from HuggingFace)
mkdir -p data
wget -P data/ https://huggingface.co/datasets/xiaowu0162/LongMemEval/resolve/main/longmemeval_oracle.json
wget -P data/ https://huggingface.co/datasets/xiaowu0162/LongMemEval/resolve/main/longmemeval_s_cleaned.json
wget -P data/ https://huggingface.co/datasets/xiaowu0162/LongMemEval/resolve/main/longmemeval_m_cleaned.json

pip install -r requirements_minimal.txt  # for evaluation script only
```

### Step 2: Understand Input Format

Each question in `longmemeval_s_cleaned.json`:
```json
{
  "question_id": "...",
  "question": "What restaurant did the user mention last March?",
  "answer": "Soba Noodle House",
  "question_type": "single_session_user",
  "sessions": [
    {
      "session_id": "...",
      "date": "2023-03-15",
      "messages": [
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."}
      ]
    }
    // ... more sessions
  ]
}
```

### Step 3: Build the MoJoAssistant Harness

We need a script at `tests/benchmarks/run_longmemeval.py` that:

1. **Ingests** each question's session history into a fresh MoJoAssistant memory instance
2. **Runs dreaming** on the ingested sessions (ABCD pipeline)
3. **Queries** the memory system with the benchmark question
4. **Records** the answer + retrieval metadata
5. **Writes** hypothesis file for `evaluate_qa.py`

```python
# tests/benchmarks/run_longmemeval.py  (DESIGN — not yet implemented)
#
# For each question in longmemeval_s_cleaned.json:
#   1. Create isolated MemoryService instance (temp dir)
#   2. Feed sessions via memory_service.add_to_working_memory()
#   3. Flush working → archival via memory_service.consolidate()
#   4. Optionally run dreaming pipeline on sessions
#   5. Query: memory_service.get_context_for_query(question, max_items=10)
#   6. Feed retrieved context + question to local LLM (Qwen)
#   7. Record answer, latency, token count, chunks retrieved
#   8. Write to hypothesis.jsonl
#
# Evaluate:
#   cd /tmp/longmemeval/src/evaluation
#   python3 evaluate_qa.py gpt-4o hypothesis.jsonl ../../data/longmemeval_oracle.json
```

### Step 4: Metrics to Capture (Beyond LongMemEval Score)

Track these per question to understand where we win/lose:

```
retrieval_latency_ms     — time from query to context returned
chunks_retrieved         — number of memory items used
relevant_chunks          — how many were actually cited in the answer
tokens_in_context        — total tokens fed to LLM
tier_breakdown           — how many chunks came from archival vs active vs knowledge
```

---

## What We Need to Run LOCOMO

```bash
git clone https://github.com/snap-research/locomo /tmp/locomo
# Dataset is in data/ — 50 dialogues + QA pairs
```

LOCOMO is simpler to run — shorter histories, structured QA pairs with clear answers. Good for rapid iteration before scaling to LongMemEval_M.

Start with LOCOMO: faster to run, well-established J/F1 metrics, field has published baselines. Once we have a LOCOMO number, compare to the competitor table above.

---

## Benchmark Implementation Plan

### Phase 1 — LOCOMO baseline (run now, local Qwen)

1. Clone LOCOMO repo
2. Write `tests/benchmarks/run_locomo.py` — feed each dialogue into fresh memory instance, query, record
3. Run against local Qwen3.5 (no external API)
4. Report J score and F1 vs competitor table

**Target**: Beat LangMem (58.10 J) as minimum bar. Competitive with Mem0 (75.71 J) as stretch goal.

### Phase 2 — LongMemEval_S (after Phase 1)

1. Download LongMemEval_S
2. Write `tests/benchmarks/run_longmemeval.py` 
3. Run all 500 questions — will take hours with local Qwen
4. Evaluate with `evaluate_qa.py`
5. Compare per-category: which of the 5 abilities are we strong/weak on?

**Target**: Baseline number by end of April. Iterate on retrieval before v1.3.

### Phase 3 — Ablation (which components matter?)

Run Phase 1/2 with components disabled:
- Without dreaming (raw session ingestion only)
- Without multi-model embeddings (single model only)
- Without 4-tier hierarchy (flat archival only)

This tells us which features earn their complexity.

---

## Predicted Weak Spots (fix candidates)

Based on the architecture and competitor scores:

### 1. Temporal Reasoning
- **Problem**: We have timestamps on memory items but no temporal graph or ordering index
- **Fix candidate**: Add time-weighted retrieval — boost recency for "what did user say recently" queries, boost oldest for "when did user first mention X"
- **Effort**: Medium — scoring function in `memory_service.py`

### 2. Knowledge Update (prefer newer fact)
- **Problem**: Archival memory retrieves by cosine similarity — old contradicted facts score equally with new ones
- **Fix candidate**: Add recency bias to similarity score: `final_score = cosine * 0.8 + recency_score * 0.2`
- **Effort**: Low — one-line change in archival retrieval

### 3. Abstention
- **Problem**: Unknown — we've never tested if the system correctly says "I don't remember"
- **Fix candidate**: Confidence threshold — if max retrieved similarity < 0.5, return "I don't have that information"
- **Effort**: Low — threshold in retrieval pipeline

### 4. Retrieval Latency at Scale
- **Problem**: JSON linear scan in archival memory — O(n) search
- **Fix candidate**: Migrate to ChromaDB or Qdrant for archival — O(log n) ANN search
- **Effort**: High — storage backend swap (post-benchmark, post-v1.2)

---

## Success Criteria

| Benchmark | Minimum (beat this) | Target | Stretch |
|---|---|---|---|
| LOCOMO J score | 58.10 (LangMem) | 70.0 | 75.71 (Mem0) |
| LOCOMO F1 | 40.0 | 45.0 | 49.56 (Zep) |
| LongMemEval_S | 58% (LangMem) | 65% | 71.2% (Zep) |
| p95 search latency | < 10s | < 2s | < 0.5s |

---

## Competitor Reference Links

- [LongMemEval GitHub](https://github.com/xiaowu0162/LongMemEval) — dataset + evaluation script
- [LOCOMO GitHub](https://github.com/snap-research/locomo) — dataset + QA pairs
- [Mem0 benchmark blog](https://mem0.ai/blog/benchmarked-openai-memory-vs-langmem-vs-memgpt-vs-mem0-for-long-term-memory-here-s-how-they-stacked-up) — Mem0's own numbers (biased, verify independently)
- [Letta rebuttal](https://www.letta.com/blog/benchmarking-ai-agent-memory) — questions Mem0 methodology
- [Emergence AI SOTA](https://www.emergence.ai/blog/sota-on-longmemeval-with-rag) — 86% RAG approach breakdown
- [AI Agent Memory Systems 2026 comparison](https://yogeshyadav.medium.com/ai-agent-memory-systems-in-2026-mem0-zep-hindsight-memvid-and-everything-in-between-compared-96e35b818da8) — landscape overview
