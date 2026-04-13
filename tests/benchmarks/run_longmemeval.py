"""
LongMemEval Benchmark Harness for MoJoAssistant

Tests long-term memory against LongMemEval (ICLR 2025).
See: https://github.com/xiaowu0162/LongMemEval

Usage:
    # Setup:
    #   git clone https://github.com/xiaowu0162/LongMemEval /tmp/longmemeval
    #   cd /tmp/longmemeval && pip install -r requirements_minimal.txt
    #   # Download data from HuggingFace (see LongMemEval README)

    python3 tests/benchmarks/run_longmemeval.py \
        --data /tmp/longmemeval/data/longmemeval_s_cleaned.json \
        --output results/longmemeval_s_hypothesis.jsonl \
        --embedding-backend random  # use huggingface for real run

    # Then evaluate with their official script:
    #   cd /tmp/longmemeval/src/evaluation
    #   python3 evaluate_qa.py gpt-4o ../../results/longmemeval_s_hypothesis.jsonl \
    #       ../../data/longmemeval_oracle.json

The 5 question types in LongMemEval:
    single_session_user      — fact stated in one session
    multi_session_user       — reasoning across sessions
    temporal_reasoning       — time-based ordering/recency
    knowledge_update         — newer fact overrides older
    abstention               — answer not in memory (should say IDK)
"""

import argparse
import json
import os
import sys
import time
import tempfile
import datetime
import statistics
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.memory_service import MemoryService


# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Run LongMemEval against MoJoAssistant memory")
    p.add_argument("--data", required=True, help="Path to longmemeval_s_cleaned.json or longmemeval_m_cleaned.json")
    p.add_argument("--output", default="results/longmemeval_hypothesis.jsonl", help="Output hypothesis file")
    p.add_argument("--model", default=None, help="LLM model ID for answer generation")
    p.add_argument("--max-questions", type=int, default=None, help="Limit to N questions for quick runs")
    p.add_argument("--question-types", nargs="*", help="Filter to specific question types (e.g. temporal_reasoning)")
    p.add_argument("--embedding-backend", default="random", help="random|huggingface|api")
    p.add_argument("--embedding-model", default="BAAI/bge-m3")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def load_longmemeval(path: str) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    raise ValueError(f"Unexpected LongMemEval format in {path}")


# ---------------------------------------------------------------------------
# Memory service
# ---------------------------------------------------------------------------

def build_memory_service(backend: str, model: str, data_dir: str) -> MemoryService:
    return MemoryService(
        data_dir=data_dir,
        embedding_model=model,
        embedding_backend=backend,
        embedding_device="cpu",
        config={
            "working_memory_max_tokens": 8000,
            "active_memory_max_pages": 100,
        },
    )


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def ingest_question_history(svc: MemoryService, question_data: dict) -> None:
    """
    Feed all sessions from a LongMemEval question into memory.

    LongMemEval question format:
    {
      "question_id": "...",
      "question": "...",
      "answer": "...",
      "question_type": "...",
      "sessions": [
        {
          "session_id": "...",
          "date": "YYYY-MM-DD",
          "messages": [
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."}
          ]
        }
      ]
    }
    """
    for session in question_data.get("sessions", []):
        date = session.get("date", "")
        for msg in session.get("messages", []):
            role = msg.get("role", "user").lower()
            content = msg.get("content", "")
            if not content:
                continue
            dated = f"[{date}] {content}" if date else content
            if role in ("user", "human"):
                svc.add_user_message(dated)
            else:
                svc.add_assistant_message(dated)


# ---------------------------------------------------------------------------
# Answer generation
# ---------------------------------------------------------------------------

def generate_answer(svc: MemoryService, question: str, model: str | None) -> tuple[str, dict]:
    t0 = time.perf_counter()
    context_items = svc.get_context_for_query(question, max_items=15)
    retrieval_ms = (time.perf_counter() - t0) * 1000

    context_parts = []
    for item in context_items:
        source = item.get("source", "memory")
        content = item.get("content", item.get("text", ""))
        relevance = item.get("relevance", 0.0)
        if content:
            context_parts.append(f"[{source} score={relevance:.3f}] {content}")

    context_str = "\n".join(context_parts) if context_parts else "No memory found."
    context_tokens = sum(len(p.split()) for p in context_parts)

    prompt = f"""You are a conversational assistant with memory of past user interactions.

Retrieved memory:
{context_str}

Question: {question}

Instructions:
- Answer based only on the retrieved memory.
- If the answer is not in memory, respond exactly: "I don't have that information."
- Be concise and factual.

Answer:"""

    answer = _call_llm(prompt, model)

    meta = {
        "retrieval_ms": round(retrieval_ms, 2),
        "context_items": len(context_items),
        "context_tokens": context_tokens,
        "tier_breakdown": {
            item.get("source", "unknown"): 0
            for item in context_items
        },
    }
    for item in context_items:
        tier = item.get("source", "unknown")
        meta["tier_breakdown"][tier] = meta["tier_breakdown"].get(tier, 0) + 1

    return answer, meta


def _call_llm(prompt: str, model: str | None) -> str:
    try:
        from app.llm.client import get_llm_response  # type: ignore
        return get_llm_response(prompt, model=model)
    except ImportError:
        pass

    try:
        import httpx
        resp = httpx.post(
            "http://localhost:11434/api/generate",
            json={"model": model or "qwen3:30b", "prompt": prompt, "stream": False},
            timeout=120,
        )
        if resp.status_code == 200:
            return resp.json().get("response", "").strip()
    except Exception:
        pass

    return "[NO_LLM] Answer generation unavailable."


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_benchmark(args) -> None:
    os.makedirs(Path(args.output).parent, exist_ok=True)

    questions = load_longmemeval(args.data)

    if args.question_types:
        questions = [q for q in questions if q.get("question_type") in args.question_types]
        print(f"Filtered to {len(questions)} questions of types: {args.question_types}")

    if args.max_questions:
        questions = questions[: args.max_questions]

    print(f"LongMemEval: {len(questions)} questions to process")
    print(f"Embedding backend: {args.embedding_backend}")
    print(f"Output: {args.output}")

    if args.dry_run:
        type_counts: dict[str, int] = {}
        for q in questions:
            t = q.get("question_type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
        print("\n[DRY RUN] Question type distribution:")
        for t, count in sorted(type_counts.items()):
            print(f"  {t:30s}: {count}")
        return

    results = []
    latencies: list[float] = []
    per_type: dict[str, list[dict]] = {}

    for idx, question_data in enumerate(questions):
        qid = question_data.get("question_id", f"q{idx}")
        question = question_data.get("question", "")
        ground_truth = question_data.get("answer", "")
        q_type = question_data.get("question_type", "unknown")

        if not question:
            continue

        # Each question gets its own isolated memory (LongMemEval requires fresh context per Q)
        with tempfile.TemporaryDirectory(prefix="mojo_lme_") as tmpdir:
            svc = build_memory_service(args.embedding_backend, args.embedding_model, tmpdir)
            ingest_question_history(svc, question_data)
            answer, meta = generate_answer(svc, question, args.model)

        latencies.append(meta["retrieval_ms"])
        if q_type not in per_type:
            per_type[q_type] = []
        per_type[q_type].append(meta)

        result = {
            "question_id": qid,
            "question": question,
            "question_type": q_type,
            "ground_truth": ground_truth,
            "prediction": answer,
            **meta,
            "timestamp": datetime.datetime.now().isoformat(),
        }
        results.append(result)

        sessions_count = len(question_data.get("sessions", []))
        print(f"[{idx+1}/{len(questions)}] {q_type:30s} | sessions={sessions_count} | {meta['retrieval_ms']:.0f}ms | {answer[:60]!r}")

    # Write hypothesis file (format expected by evaluate_qa.py)
    with open(args.output, "w") as f:
        for r in results:
            # LongMemEval evaluate_qa.py expects: {"question_id": ..., "prediction": ...}
            f.write(json.dumps({
                "question_id": r["question_id"],
                "prediction": r["prediction"],
                # Extra fields for our own analysis
                "_meta": {k: v for k, v in r.items() if k not in ("question_id", "prediction")},
            }) + "\n")

    # Summary
    print("\n" + "=" * 60)
    print("LONGMEMEVAL RESULTS — MoJoAssistant")
    print("=" * 60)
    print(f"Questions answered: {len(results)}")

    if latencies:
        s = sorted(latencies)
        p95 = s[int(len(s) * 0.95)]
        print(f"Mean retrieval latency: {statistics.mean(latencies):.1f}ms")
        print(f"p95 retrieval latency:  {p95:.1f}ms")
        print(f"Mean context tokens:    {statistics.mean(r['context_tokens'] for r in results):.0f}")

    print("\nPer-question-type breakdown:")
    for qtype, metas in sorted(per_type.items()):
        avg_lat = statistics.mean(m["retrieval_ms"] for m in metas)
        avg_ctx = statistics.mean(m["context_items"] for m in metas)
        print(f"  {qtype:30s}: n={len(metas):3d}  avg_lat={avg_lat:.0f}ms  avg_ctx_items={avg_ctx:.1f}")

    print(f"\nHypothesis file written to: {args.output}")
    print("\nNext step — official accuracy evaluation:")
    print("  cd /tmp/longmemeval/src/evaluation")
    print(f"  python3 evaluate_qa.py gpt-4o {Path(args.output).resolve()} \\")
    print("      /tmp/longmemeval/data/longmemeval_oracle.json")
    print("\nCompetitor reference (LongMemEval_S accuracy):")
    print("  Emergence AI RAG: 86%")
    print("  Zep:              71.2%")
    print("  Mem0:             ~67%")
    print("  GPT-4o full ctx:  60-64%")
    print("  LangMem:          ~58%")


if __name__ == "__main__":
    args = parse_args()
    run_benchmark(args)
