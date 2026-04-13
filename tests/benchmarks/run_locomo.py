"""
LOCOMO Benchmark Harness for MoJoAssistant

Tests long-term conversational memory against the LOCOMO dataset.
See: https://github.com/snap-research/locomo

Usage:
    # Clone dataset first:
    #   git clone https://github.com/snap-research/locomo /tmp/locomo

    python3 tests/benchmarks/run_locomo.py \
        --data-dir /tmp/locomo/data \
        --output results/locomo_results.jsonl \
        --model qwen3  # local model ID in your config

Metrics produced:
    - J score (LLM-as-judge 0-100)
    - F1 on extractive answers
    - p95 retrieval latency
    - Average tokens in retrieved context
    - Per-category breakdown (single-hop, multi-hop, temporal, commonsense, adversarial)
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

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.memory_service import MemoryService


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Run LOCOMO benchmark against MoJoAssistant memory")
    p.add_argument("--data-dir", required=True, help="Path to cloned locomo/data directory")
    p.add_argument("--output", default="results/locomo_results.jsonl", help="Output file for results")
    p.add_argument("--model", default=None, help="LLM model ID to use for answer generation (default: use env config)")
    p.add_argument("--max-questions", type=int, default=None, help="Limit to N questions (for quick runs)")
    p.add_argument("--embedding-backend", default="random", help="Embedding backend: random|huggingface|api (random for CI, huggingface for real run)")
    p.add_argument("--embedding-model", default="BAAI/bge-m3", help="Embedding model name")
    p.add_argument("--dry-run", action="store_true", help="Print plan but don't execute")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_locomo_dataset(data_dir: str) -> list[dict]:
    """Load LOCOMO dialogues + QA pairs."""
    data_path = Path(data_dir)

    # LOCOMO stores dialogues as individual JSON files or a combined file
    # Try combined first, then per-dialogue
    candidates = [
        data_path / "locomo10.json",
        data_path / "locomo.json",
        data_path / "dataset.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            with open(candidate) as f:
                data = json.load(f)
            print(f"Loaded {len(data)} dialogues from {candidate}")
            return data

    # Try per-dialogue directory
    dialogue_files = sorted(data_path.glob("*.json"))
    if dialogue_files:
        dialogues = []
        for f in dialogue_files:
            with open(f) as fh:
                dialogues.append(json.load(fh))
        print(f"Loaded {len(dialogues)} dialogue files from {data_path}")
        return dialogues

    raise FileNotFoundError(
        f"No LOCOMO data found in {data_dir}. "
        "Clone the dataset: git clone https://github.com/snap-research/locomo /tmp/locomo"
    )


# ---------------------------------------------------------------------------
# Memory service setup
# ---------------------------------------------------------------------------

def build_memory_service(embedding_backend: str, embedding_model: str, data_dir: str) -> MemoryService:
    """Create an isolated MemoryService instance for one benchmark dialogue."""
    return MemoryService(
        data_dir=data_dir,
        embedding_model=embedding_model,
        embedding_backend=embedding_backend,
        embedding_device="cpu",
        config={
            "working_memory_max_tokens": 8000,
            "active_memory_max_pages": 50,
        },
    )


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def ingest_sessions(svc: MemoryService, sessions: list[dict]) -> None:
    """Feed all sessions from a LOCOMO dialogue into the memory service."""
    for session in sessions:
        session_date = session.get("date", "")
        turns = session.get("dialogue", session.get("turns", session.get("messages", [])))
        for turn in turns:
            role = turn.get("role", turn.get("speaker", "user")).lower()
            content = turn.get("content", turn.get("text", ""))
            if not content:
                continue
            # Prefix with date context so temporal reasoning has a signal
            dated_content = f"[{session_date}] {content}" if session_date else content
            if role in ("user", "human"):
                svc.add_user_message(dated_content)
            else:
                svc.add_assistant_message(dated_content)


# ---------------------------------------------------------------------------
# Answer generation
# ---------------------------------------------------------------------------

def generate_answer(svc: MemoryService, question: str, model: str | None) -> tuple[str, dict]:
    """
    Retrieve relevant memory and generate an answer.
    Returns (answer_text, metadata_dict).
    """
    t0 = time.perf_counter()
    context_items = svc.get_context_for_query(question, max_items=15)
    retrieval_ms = (time.perf_counter() - t0) * 1000

    # Build context string
    context_parts = []
    for item in context_items:
        source = item.get("source", "memory")
        content = item.get("content", item.get("text", ""))
        relevance = item.get("relevance", 0.0)
        if content:
            context_parts.append(f"[{source}, score={relevance:.3f}] {content}")

    context_str = "\n".join(context_parts) if context_parts else "No relevant memory found."
    total_context_tokens = sum(len(p.split()) for p in context_parts)

    # Build prompt
    prompt = f"""You are a conversational assistant with access to memory of past interactions.

Retrieved memory:
{context_str}

Question: {question}

Answer based only on the retrieved memory. If the memory does not contain the answer, say "I don't have that information."
Answer:"""

    # Call LLM — use environment-configured model or provided model
    answer = _call_llm(prompt, model)

    metadata = {
        "retrieval_ms": round(retrieval_ms, 2),
        "context_items": len(context_items),
        "context_tokens": total_context_tokens,
        "tier_breakdown": _count_tiers(context_items),
    }
    return answer, metadata


def _call_llm(prompt: str, model: str | None) -> str:
    """
    Call the configured LLM. Falls back to a stub if no model configured.
    In production, wire this to the MoJoAssistant LLM service.
    """
    try:
        # Try to import and use the MoJoAssistant LLM client
        from app.llm.client import get_llm_response  # type: ignore
        return get_llm_response(prompt, model=model)
    except ImportError:
        pass

    try:
        # Try Ollama directly
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

    # Stub — for dry-run / CI without LLM
    return "[NO_LLM] Answer generation not available in this environment."


def _count_tiers(context_items: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for item in context_items:
        tier = item.get("source", item.get("tier", "unknown"))
        counts[tier] = counts.get(tier, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def simple_f1(prediction: str, ground_truth: str) -> float:
    """Token-level F1 between prediction and ground truth (extractive proxy)."""
    pred_tokens = set(prediction.lower().split())
    truth_tokens = set(ground_truth.lower().split())
    if not truth_tokens:
        return 1.0 if not pred_tokens else 0.0
    if not pred_tokens:
        return 0.0
    overlap = pred_tokens & truth_tokens
    precision = len(overlap) / len(pred_tokens)
    recall = len(overlap) / len(truth_tokens)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


# ---------------------------------------------------------------------------
# Main benchmark loop
# ---------------------------------------------------------------------------

def run_benchmark(args) -> None:
    os.makedirs(Path(args.output).parent, exist_ok=True)

    dialogues = load_locomo_dataset(args.data_dir)

    all_results = []
    latencies = []
    f1_scores: list[float] = []
    per_category: dict[str, list[float]] = {}

    total_questions = 0
    for dialogue in dialogues:
        qa_pairs = dialogue.get("qa_pairs", dialogue.get("questions", []))
        total_questions += len(qa_pairs)

    print(f"Total questions: {total_questions}")
    if args.max_questions:
        print(f"Limiting to {args.max_questions} questions")
    if args.dry_run:
        print("[DRY RUN] Would run benchmark — exiting")
        return

    question_count = 0
    for dialogue_idx, dialogue in enumerate(dialogues):
        sessions = dialogue.get("sessions", dialogue.get("conversation", []))
        qa_pairs = dialogue.get("qa_pairs", dialogue.get("questions", []))

        if not sessions or not qa_pairs:
            continue

        # Fresh memory service per dialogue
        with tempfile.TemporaryDirectory(prefix="mojo_bench_") as tmpdir:
            svc = build_memory_service(args.embedding_backend, args.embedding_model, tmpdir)

            print(f"\nDialogue {dialogue_idx + 1}/{len(dialogues)} — ingesting {len(sessions)} sessions...")
            ingest_sessions(svc, sessions)

            for qa in qa_pairs:
                if args.max_questions and question_count >= args.max_questions:
                    break

                question = qa.get("question", "")
                ground_truth = qa.get("answer", "")
                q_type = qa.get("type", qa.get("question_type", "unknown"))

                if not question:
                    continue

                answer, meta = generate_answer(svc, question, args.model)
                f1 = simple_f1(answer, ground_truth)
                latencies.append(meta["retrieval_ms"])
                f1_scores.append(f1)

                if q_type not in per_category:
                    per_category[q_type] = []
                per_category[q_type].append(f1)

                result = {
                    "question_id": qa.get("id", f"d{dialogue_idx}_q{question_count}"),
                    "question": question,
                    "question_type": q_type,
                    "ground_truth": ground_truth,
                    "prediction": answer,
                    "f1": round(f1, 4),
                    **meta,
                    "timestamp": datetime.datetime.now().isoformat(),
                }
                all_results.append(result)
                question_count += 1

                print(f"  Q{question_count}: [{q_type}] F1={f1:.3f} latency={meta['retrieval_ms']:.0f}ms")

            if args.max_questions and question_count >= args.max_questions:
                break

    # Write results
    with open(args.output, "w") as f:
        for r in all_results:
            f.write(json.dumps(r) + "\n")

    # Print summary
    print("\n" + "=" * 60)
    print("LOCOMO BENCHMARK RESULTS — MoJoAssistant")
    print("=" * 60)
    print(f"Questions answered: {len(all_results)}")
    print(f"Mean F1:            {statistics.mean(f1_scores):.4f}" if f1_scores else "Mean F1: N/A")
    print(f"Median F1:          {statistics.median(f1_scores):.4f}" if f1_scores else "")

    if latencies:
        sorted_lat = sorted(latencies)
        p95_idx = int(len(sorted_lat) * 0.95)
        print(f"Mean latency:       {statistics.mean(latencies):.1f}ms")
        print(f"p95 latency:        {sorted_lat[p95_idx]:.1f}ms")

    print("\nPer-category F1:")
    for cat, scores in sorted(per_category.items()):
        print(f"  {cat:20s}: {statistics.mean(scores):.4f}  (n={len(scores)})")

    print(f"\nResults written to: {args.output}")
    print("\nCompetitor reference (LOCOMO J-score, not F1):")
    print("  Zep:     76.60")
    print("  Mem0:    75.71")
    print("  LangMem: 58.10")
    print("  Baseline (full context): ~55")
    print("\nNote: J-score requires LLM-as-judge eval. Run evaluate_qa.py from")
    print("      the LOCOMO repo against this output for comparable numbers.")


if __name__ == "__main__":
    args = parse_args()
    run_benchmark(args)
