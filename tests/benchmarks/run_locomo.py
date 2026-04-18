"""
LOCOMO Benchmark Harness for MoJoAssistant

Tests long-term conversational memory against the LOCOMO dataset.
See: https://github.com/snap-research/locomo

Usage:
    # Clone dataset first:
    #   git clone https://github.com/snap-research/locomo /tmp/locomo

    venv/bin/python tests/benchmarks/run_locomo.py \
        --data-dir /tmp/locomo/data \
        --output results/locomo_results.jsonl \
        --embedding-backend huggingface

    # With dreaming pre-built (point at existing role dir):
    venv/bin/python tests/benchmarks/run_locomo.py \
        --data-dir /tmp/locomo/data \
        --output results/locomo_dreaming.jsonl \
        --role-dir ~/.memory/roles/locomo_bench_d3 \
        --skip-ingest

Metrics produced:
    - Token F1 on answers (LOCOMO standard)
    - Per-category F1 (single-hop, multi-hop, temporal, commonsense)
    - Adversarial abstention rate (category 5)
    - p95 retrieval latency
    - Average context tokens fed to LLM

LOCOMO categories:
    1 = single-hop factual
    2 = multi-hop reasoning
    3 = temporal ordering / recency
    4 = commonsense + world knowledge
    5 = adversarial (answer NOT in memory — should abstain)
"""

import argparse
import json
import os
import re
import sys
import time
import datetime
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.memory.knowledge_manager import KnowledgeManager
from app.memory.simplified_embeddings import SimpleEmbedding


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Run LOCOMO benchmark against MoJoAssistant memory")
    p.add_argument("--data-dir", required=True, help="Path to cloned locomo/data directory")
    p.add_argument("--output", default="results/locomo_results.jsonl")
    p.add_argument("--run-id", default=None, help="Stable run identifier (default: auto-generated)")
    p.add_argument(
        "--benchmark-root",
        default=str(Path.home() / ".memory/benchmarks/locomo"),
        help="Directory for normalized benchmark artifacts",
    )
    p.add_argument(
        "--role-root",
        default=str(Path.home() / ".memory/roles"),
        help="Base directory for benchmark role/runtime state",
    )
    p.add_argument(
        "--variant",
        default="raw_retrieval",
        choices=("raw_context", "raw_retrieval", "abcd_b", "abcd_bc"),
        help="Benchmark system variant to run",
    )
    p.add_argument("--model", default=None, help="LLM model ID override (default: from llm_config.json)")
    p.add_argument("--max-questions", type=int, default=None)
    p.add_argument("--max-dialogues", type=int, default=None)
    p.add_argument("--embedding-backend", default="huggingface", help="huggingface|random")
    p.add_argument("--embedding-model", default="BAAI/bge-m3")
    p.add_argument("--embedding-cache", default=str(Path.home() / ".memory/embedding_cache"))
    p.add_argument("--role-dir", default=None, help="Pre-built role dir to load knowledge from (skip ingest)")
    p.add_argument(
        "--dataset-version",
        default="locomo10",
        help="Dataset version label stored in benchmark artifacts",
    )
    p.add_argument("--skip-ingest", action="store_true", help="Skip ingestion, use existing role-dir")
    p.add_argument("--top-k", type=int, default=15, help="Number of chunks to retrieve per question")
    p.add_argument(
        "--raw-context-max-docs",
        type=int,
        default=40,
        help="For raw_context variant, max ingested docs to stuff into prompt context",
    )
    p.add_argument(
        "--top-c",
        type=int,
        default=8,
        help="For abcd_bc retrieval, number of top C clusters to retrieve",
    )
    p.add_argument(
        "--top-b",
        type=int,
        default=12,
        help="For abcd_b / abcd_bc retrieval, number of top B chunks to retrieve",
    )
    p.add_argument("--abstention-threshold", type=float, default=0.35,
                   help="Max similarity below which system abstains (category 5)")
    p.add_argument("--rerank", action="store_true",
                   help="Use LLM to rerank top-K candidates before answering")
    p.add_argument("--rerank-top-k", type=int, default=25,
                   help="Broad retrieval pool before reranking (default 25)")
    p.add_argument("--rerank-top-n", type=int, default=5,
                   help="Final chunks kept after reranking (default 5)")
    p.add_argument("--judge", action="store_true",
                   help="Run local Qwen as LLM judge for J score (slower but meaningful)")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_locomo(data_dir: str) -> list[dict]:
    data_path = Path(data_dir)
    for name in ("locomo10.json", "locomo.json", "dataset.json"):
        candidate = data_path / name
        if candidate.exists():
            with open(candidate) as f:
                data = json.load(f)
            print(f"Loaded {len(data)} dialogues from {candidate}")
            return data

    files = sorted(data_path.glob("*.json"))
    if files:
        dialogues = [json.load(open(f)) for f in files]
        print(f"Loaded {len(dialogues)} dialogue files from {data_path}")
        return dialogues

    raise FileNotFoundError(f"No LOCOMO data found in {data_dir}")


def _slugify(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in text)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "run"


def build_run_id(args) -> str:
    if args.run_id:
        return _slugify(args.run_id)

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = [stamp, "locomo", args.variant]
    if args.model:
        parts.append(_slugify(args.model))
    if args.max_dialogues:
        parts.append(f"d{args.max_dialogues}")
    if args.max_questions:
        parts.append(f"q{args.max_questions}")
    return "_".join(parts)


def resolve_run_paths(args) -> dict[str, Path]:
    run_id = build_run_id(args)
    benchmark_root = Path(args.benchmark_root).expanduser()
    run_dir = benchmark_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    if args.role_dir:
        role_dir = Path(args.role_dir).expanduser()
    else:
        role_dir = Path(args.role_root).expanduser() / f"locomo_bench_{run_id}"

    detailed_output = Path(args.output).expanduser()
    if not detailed_output.is_absolute():
        detailed_output = PROJECT_ROOT / detailed_output
    detailed_output.parent.mkdir(parents=True, exist_ok=True)

    return {
        "run_id": Path(run_id),
        "run_dir": run_dir,
        "role_dir": role_dir,
        "detailed_output": detailed_output,
        "summary_output": run_dir / "results.json",
    }


def resolve_dialogue_role_dir(base_role_dir: Path, dialogue_idx: int) -> Path:
    candidate = base_role_dir / f"dialogue_{dialogue_idx:02d}"
    return candidate if candidate.exists() else base_role_dir


# ---------------------------------------------------------------------------
# Embedding + KnowledgeManager
# ---------------------------------------------------------------------------

def build_km(role_dir: Path, backend: str, model: str, cache_dir: str) -> KnowledgeManager:
    role_dir.mkdir(parents=True, exist_ok=True)
    embedding = SimpleEmbedding(
        backend=backend,
        model_name=model,
        device="cpu",
        cache_dir=cache_dir,
    )
    return KnowledgeManager(embedding=embedding, data_dir=str(role_dir))


def _get_embedding(role_dir: Path, backend: str, model: str, cache_dir: str) -> SimpleEmbedding:
    return SimpleEmbedding(
        backend=backend,
        model_name=model,
        device="cpu",
        cache_dir=cache_dir,
    )


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def ingest_dialogue(km: KnowledgeManager, dialogue: dict) -> int:
    """
    Ingest all sessions from one LOCOMO dialogue into KnowledgeManager.
    Stores one document per conversation pair (user turn + assistant turn).
    Date context is prefixed so temporal queries have a signal.
    Returns number of documents added.
    """
    conv = dialogue.get("conversation", {})
    added = 0
    i = 1
    while True:
        date_key = f"session_{i}_date_time"
        sess_key = f"session_{i}"
        if sess_key not in conv:
            break
        date = conv.get(date_key, "")
        turns = conv[sess_key]

        # Pair consecutive turns into user/assistant chunks
        for j in range(0, len(turns) - 1, 2):
            user_turn = turns[j]
            asst_turn = turns[j + 1] if j + 1 < len(turns) else None
            user_text = user_turn.get("text", "")
            if not user_text:
                continue
            doc = f"[{date}] {user_turn.get('speaker','')}: {user_text}"
            if asst_turn:
                doc += f"\n[{date}] {asst_turn.get('speaker','')}: {asst_turn.get('text','')}"
            km.add_documents(
                documents=[doc],
                metadatas=[{"session": i, "date": date, "source": "locomo"}],
            )
            added += 1

        i += 1
    return added


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

def build_llm():
    from app.llm.llm_interface import LLMInterface
    return LLMInterface(config_file=str(PROJECT_ROOT / "config/llm_config.json"))


def call_llm(llm, prompt: str, model: str | None) -> str:
    try:
        if model:
            llm.set_active_interface(model)
        return llm.generate_response(query=prompt, context=None)
    except Exception as e:
        return f"[LLM_ERROR: {e}]"


# ---------------------------------------------------------------------------
# Retrieval + reranking + answer generation
# ---------------------------------------------------------------------------

def retrieve(km: KnowledgeManager, question: str, top_k: int) -> tuple[list[tuple[str, float]], float]:
    t0 = time.perf_counter()
    results = km.query(question, similarity_top_k=top_k)
    ms = (time.perf_counter() - t0) * 1000
    return results, ms


def load_dream_archives(role_dir: Path) -> list[dict]:
    dreams_dir = role_dir / "dreams"
    if not dreams_dir.exists():
        raise FileNotFoundError(f"No dreams directory found at {dreams_dir}")

    archives: list[dict] = []
    for archive_path in sorted(dreams_dir.glob("*/archive_v*.json")):
        with open(archive_path, encoding="utf-8") as f:
            archive = json.load(f)
        metadata = archive.get("metadata", {})
        if metadata.get("status", "active") != "active":
            continue
        archives.append(archive)
    if not archives:
        raise FileNotFoundError(f"No active dream archives found under {dreams_dir}")
    return archives


def _cosine(a: list[float], b: list[float]) -> float:
    import math
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def retrieve_abcd(
    embedding: SimpleEmbedding,
    archives: list[dict],
    question: str,
    variant: str,
    top_b: int,
    top_c: int,
) -> tuple[list[tuple[str, float]], float]:
    t0 = time.perf_counter()
    query_vec = embedding.get_text_embedding(question, prompt_name="query")

    scored_b: list[tuple[str, float]] = []
    scored_c: list[tuple[str, float, list[str]]] = []

    for archive in archives:
        for b in archive.get("b_chunks", []):
            key_facts = b.get("key_facts") or []
            if key_facts:
                text = "\n".join(f"- {f}" for f in key_facts if f)
            else:
                text = b.get("content", "").strip()
            if not text:
                continue
            vec = embedding.get_text_embedding(text, prompt_name="passage")
            scored_b.append((text, _cosine(query_vec, vec)))

        for c in archive.get("c_clusters", []):
            theme = (c.get("theme") or "").strip()
            key_facts = c.get("key_facts") or []
            if key_facts:
                facts_str = "\n".join(f"- {f}" for f in key_facts if f)
                text = f"{theme}\n{facts_str}".strip()
            else:
                content = (c.get("content") or "").strip()
                text = f"{theme}\n{content}".strip()
            if not text:
                continue
            vec = embedding.get_text_embedding(text, prompt_name="passage")
            scored_c.append((text, _cosine(query_vec, vec), list(c.get("related_chunks", []))))

    scored_b.sort(key=lambda x: x[1], reverse=True)
    scored_c.sort(key=lambda x: x[1], reverse=True)

    if variant == "abcd_b":
        results = scored_b[:top_b]
    else:
        top_clusters = scored_c[:top_c]
        wanted_ids = {cid for _, _, related in top_clusters for cid in related}

        indexed_b: dict[str, tuple[str, float]] = {}
        for archive in archives:
            for b in archive.get("b_chunks", []):
                bid = b.get("id")
                key_facts = b.get("key_facts") or []
                if key_facts:
                    text = "\n".join(f"- {f}" for f in key_facts if f)
                else:
                    text = b.get("content", "").strip()
                if not bid or not text:
                    continue
                vec = embedding.get_text_embedding(text, prompt_name="passage")
                indexed_b[bid] = (text, _cosine(query_vec, vec))

        selected: list[tuple[str, float]] = [(text, score) for text, score, _ in top_clusters]
        for bid in wanted_ids:
            if bid in indexed_b:
                selected.append(indexed_b[bid])
        selected.extend(scored_b[:top_b])

        dedup: dict[str, float] = {}
        for text, score in selected:
            if text not in dedup or score > dedup[text]:
                dedup[text] = score
        results = sorted(dedup.items(), key=lambda x: x[1], reverse=True)[: max(top_b, top_c)]

    ms = (time.perf_counter() - t0) * 1000
    return results, ms


def build_raw_context_from_km(km: KnowledgeManager, max_docs: int) -> list[tuple[str, float]]:
    docs = []
    for doc in getattr(km, "documents", [])[:max_docs]:
        text = doc.get("content") or doc.get("text") or ""
        if text:
            docs.append((text, 1.0))
    return docs


def summarize_results(
    *,
    args,
    run_id: str,
    role_dir: Path,
    dialogues_count: int,
    questions_count: int,
    latencies: list[float],
    all_results: list[dict[str, Any]],
    f1_by_cat: dict[str, list[float]],
    j_by_cat: dict[str, list[float]],
    adv_by_cat: dict[str, dict[str, int]],
) -> dict[str, Any]:
    all_f1 = [r["f1"] for r in all_results if not r["adversarial"]]
    all_j = [r["j_score"] for r in all_results if not r["adversarial"] and r.get("j_score") is not None]
    total_adv = sum(v["total"] for v in adv_by_cat.values())
    total_abstain = sum(v["abstain"] for v in adv_by_cat.values())
    sorted_latencies = sorted(latencies)
    p95_latency = sorted_latencies[int(len(sorted_latencies) * 0.95)] if sorted_latencies else None
    context_tokens = [r["context_tokens"] for r in all_results]
    similarity_scores = [r["max_similarity"] for r in all_results]

    per_category: dict[str, Any] = {}
    for cat, scores in sorted(f1_by_cat.items()):
        per_category[cat] = {
            "f1": round(statistics.mean(scores), 4),
            "count": len(scores),
            "j_score": round(statistics.mean(j_by_cat[cat]), 1) if cat in j_by_cat else None,
        }

    for cat, stats in sorted(adv_by_cat.items()):
        per_category[cat] = {
            "abstention_rate": round(stats["abstain"] / max(stats["total"], 1), 4),
            "count": stats["total"],
        }

    return {
        "benchmark": "locomo",
        "run_id": run_id,
        "dataset_version": args.dataset_version,
        "system_variant": args.variant,
        "dialogues": dialogues_count,
        "questions": questions_count,
        "answer_model": args.model or "default_from_llm_config",
        "judge_model": args.model if args.judge and args.model else ("default_from_llm_config" if args.judge else None),
        "embedding_model": args.embedding_model,
        "metrics": {
            "f1": round(statistics.mean(all_f1), 4) if all_f1 else None,
            "j_score": round(statistics.mean(all_j), 1) if all_j else None,
            "abstention_rate_cat5": round(total_abstain / max(total_adv, 1), 4) if total_adv else None,
            "mean_retrieval_latency_ms": round(statistics.mean(latencies), 2) if latencies else None,
            "p95_retrieval_latency_ms": round(p95_latency, 2) if p95_latency is not None else None,
            "mean_context_tokens": round(statistics.mean(context_tokens), 2) if context_tokens else None,
            "mean_max_similarity": round(statistics.mean(similarity_scores), 4) if similarity_scores else None,
        },
        "retrieval": {
            "mode": args.variant,
            "top_k": args.top_k,
            "top_b": args.top_b,
            "top_c": args.top_c,
            "raw_context_max_docs": args.raw_context_max_docs,
            "rerank": args.rerank,
            "rerank_top_k": args.rerank_top_k if args.rerank else None,
            "rerank_top_n": args.rerank_top_n if args.rerank else None,
        },
        "provenance": {
            "runner": "tests/benchmarks/run_locomo.py",
            "data_dir": str(Path(args.data_dir).expanduser()),
            "dreaming_mode": "prebuilt" if args.skip_ingest else "fresh",
            "role_dir": str(role_dir),
            "embedding_backend": args.embedding_backend,
            "judge_enabled": args.judge,
            "detailed_output": str(Path(args.output).expanduser()),
        },
        "per_category": per_category,
        "notes": [
            "Accepted benchmark runs should use isolated role dirs per run.",
            "Compare summary.json artifacts across variants rather than ad-hoc console output.",
        ],
    }


RERANK_PROMPT = """You are a memory retrieval expert. Given a question and a list of memory chunks, select the most relevant chunks for answering the question.

Question: {question}

Memory chunks:
{chunks}

Return ONLY a JSON object with the indices of the top {top_n} most relevant chunks (1-based), ordered by relevance:
{{"top": [<idx1>, <idx2>, ...]}}

Return ONLY valid JSON, no other text."""


def llm_rerank(llm, question: str, candidates: list[tuple[str, float]], top_n: int = 5) -> list[tuple[str, float]]:
    """
    Use LLM to rerank candidates. Returns top_n reranked chunks.
    Falls back to original order if LLM fails.
    """
    import re
    if len(candidates) <= top_n:
        return candidates

    # Build numbered chunk list (truncate each to 200 chars to fit context)
    chunk_lines = []
    for i, (text, score) in enumerate(candidates, 1):
        snippet = text.replace("\n", " ")[:200]
        chunk_lines.append(f"[{i}] {snippet}")

    prompt = RERANK_PROMPT.format(
        question=question,
        chunks="\n".join(chunk_lines),
        top_n=top_n,
    )

    try:
        raw = llm.generate_response(query=prompt, context=None)
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        m = re.search(r"\{.*?\}", raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
            indices = data.get("top", [])
            reranked = []
            seen = set()
            for idx in indices:
                i = int(idx) - 1  # convert to 0-based
                if 0 <= i < len(candidates) and i not in seen:
                    reranked.append(candidates[i])
                    seen.add(i)
            if reranked:
                return reranked[:top_n]
    except Exception:
        pass

    # Fallback: return top_n by original embedding score
    return candidates[:top_n]


def build_context_str(retrieved: list[tuple[str, float]]) -> str:
    parts = []
    for text, score in retrieved:
        parts.append(f"[score={score:.3f}] {text}")
    return "\n".join(parts) if parts else "No relevant memory found."


def generate_answer(llm, question: str, context_str: str, model: str | None) -> str:
    prompt = f"""You are a conversational assistant with access to memory of past conversations.

Retrieved memory:
{context_str}

Question: {question}

Instructions:
- Answer using only the retrieved memory above.
- If the memory does not contain enough information to answer, respond exactly: "I don't have that information."
- Be concise and factual. Do not speculate beyond what is in memory.

Answer:"""
    return call_llm(llm, prompt, model)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _normalize_answer(s: str) -> str:
    """SQuAD-style answer normalization: lowercase, strip punctuation, collapse whitespace."""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def token_f1(prediction: str, ground_truth: str) -> float:
    """Standard token-level F1 (LOCOMO/SQuAD style, with punctuation normalization)."""
    pred_tokens = _normalize_answer(prediction).split()
    truth_tokens = _normalize_answer(ground_truth).split()
    if not truth_tokens:
        return 1.0 if not pred_tokens else 0.0
    if not pred_tokens:
        return 0.0
    common = Counter(pred_tokens) & Counter(truth_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision = num_same / len(pred_tokens)
    recall = num_same / len(truth_tokens)
    return 2 * precision * recall / (precision + recall)


JUDGE_PROMPT = """You are an objective evaluator assessing whether a system's answer correctly responds to a question based on a ground-truth reference answer.

Question: {question}
Ground truth: {ground_truth}
System answer: {prediction}

Score the system answer on a scale of 0 to 100:
- 100: Fully correct — same meaning as ground truth, even if phrased differently
- 75: Mostly correct — contains the key information with minor gaps or extra detail
- 50: Partially correct — some relevant information but missing key facts
- 25: Mostly wrong — tangentially related but does not answer the question
- 0: Wrong or refused when answer was available

Respond with ONLY a JSON object in this exact format:
{{"score": <integer 0-100>, "reason": "<one sentence>"}}"""


def llm_judge(llm, question: str, ground_truth: str, prediction: str) -> tuple[float, str]:
    """
    Use local Qwen as judge. Returns (score_0_to_1, reason).
    Falls back to 0.0 if LLM fails or returns unparseable output.
    """
    import re
    prompt = JUDGE_PROMPT.format(
        question=question,
        ground_truth=ground_truth,
        prediction=prediction,
    )
    try:
        raw = llm.generate_response(query=prompt, context=None)
        # Strip think tokens if present
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        # Find JSON object
        m = re.search(r"\{.*?\}", raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
            score = float(data.get("score", 0))
            reason = data.get("reason", "")
            return min(max(score, 0.0), 100.0) / 100.0, reason
    except Exception:
        pass
    return 0.0, "parse_error"


def is_adversarial(qa: dict) -> bool:
    return qa.get("category") == 5


def check_abstention(retrieved: list[tuple[str, float]], threshold: float) -> bool:
    """True if max similarity is below threshold — system correctly abstains."""
    if not retrieved:
        return True
    return max(score for _, score in retrieved) < threshold


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_benchmark(args) -> None:
    paths = resolve_run_paths(args)
    run_id = str(paths["run_id"])
    role_dir = paths["role_dir"]
    detailed_output = paths["detailed_output"]
    summary_output = paths["summary_output"]

    dialogues = load_locomo(args.data_dir)
    if args.max_dialogues:
        dialogues = dialogues[:args.max_dialogues]

    if args.dry_run:
        total_qa = sum(len(d.get("qa", [])) for d in dialogues)
        print(f"[DRY RUN] {len(dialogues)} dialogues, ~{total_qa} QA pairs")
        return

    llm = build_llm()
    all_results = []
    latencies = []
    f1_by_cat: dict[str, list[float]] = {}
    j_by_cat: dict[str, list[float]] = {}
    adv_by_cat: dict[str, dict] = {}

    question_count = 0

    if args.variant in ("abcd_b", "abcd_bc") and not args.role_dir:
        raise ValueError("--role-dir is required for abcd_b and abcd_bc variants")

    for d_idx, dialogue in enumerate(dialogues):
        conv = dialogue.get("conversation", {})
        qa_pairs = dialogue.get("qa", [])
        speaker_a = conv.get("speaker_a", "A")
        speaker_b = conv.get("speaker_b", "B")

        if not qa_pairs:
            continue

        # Build per-dialogue knowledge store
        if args.skip_ingest and args.role_dir:
            active_role_dir = resolve_dialogue_role_dir(role_dir, d_idx)
            print(f"\nDialogue {d_idx+1} — loading pre-built knowledge from {active_role_dir}")
        else:
            dialogue_role_dir = role_dir / f"dialogue_{d_idx:02d}"
            print(f"\nDialogue {d_idx+1}/{len(dialogues)} — {speaker_a} & {speaker_b}")
            km_ingest = build_km(dialogue_role_dir, args.embedding_backend, args.embedding_model, args.embedding_cache)
            n_docs = ingest_dialogue(km_ingest, dialogue)
            print(f"  Ingested {n_docs} conversation pairs")
            active_role_dir = dialogue_role_dir

        km = build_km(active_role_dir, args.embedding_backend, args.embedding_model, args.embedding_cache)
        embedding = _get_embedding(active_role_dir, args.embedding_backend, args.embedding_model, args.embedding_cache)
        archives = None
        if args.variant in ("abcd_b", "abcd_bc"):
            archives = load_dream_archives(active_role_dir)

        for qa in qa_pairs:
            if args.max_questions and question_count >= args.max_questions:
                break

            question = qa.get("question", "")
            ground_truth = str(qa.get("answer", qa.get("adversarial_answer", "")))
            category = str(qa.get("category", "?"))
            adversarial = is_adversarial(qa)

            if not question:
                continue

            if args.variant == "raw_context":
                retrieved = build_raw_context_from_km(km, args.raw_context_max_docs)
                latency_ms = 0.0
            elif args.variant == "raw_retrieval":
                pool_k = args.rerank_top_k if args.rerank else args.top_k
                retrieved, latency_ms = retrieve(km, question, pool_k)
            else:
                retrieved, latency_ms = retrieve_abcd(
                    embedding=embedding,
                    archives=archives or [],
                    question=question,
                    variant=args.variant,
                    top_b=args.top_b,
                    top_c=args.top_c,
                )
            latencies.append(latency_ms)

            # Optional LLM reranking
            if args.rerank and retrieved and args.variant != "raw_context":
                retrieved = llm_rerank(llm, question, retrieved, top_n=args.rerank_top_n)

            context_str = build_context_str(retrieved)
            context_tokens = sum(len(t.split()) for t, _ in retrieved)

            if adversarial:
                # Category 5: system should say "I don't have that information"
                abstained = check_abstention(retrieved, args.abstention_threshold)
                if not abstained:
                    # Let LLM decide — check if it says IDK
                    answer = generate_answer(llm, question, context_str, args.model)
                    abstained = any(phrase in answer.lower() for phrase in [
                        "i don't have", "i don't know", "no information", "not in memory",
                        "cannot find", "not available", "i have no",
                    ])
                else:
                    answer = "I don't have that information."

                f1 = 1.0 if abstained else 0.0
                adv_by_cat.setdefault(category, {"total": 0, "abstain": 0})
                adv_by_cat[category]["total"] += 1
                if abstained:
                    adv_by_cat[category]["abstain"] += 1
            else:
                answer = generate_answer(llm, question, context_str, args.model)
                f1 = token_f1(answer, ground_truth)
                f1_by_cat.setdefault(category, [])
                f1_by_cat[category].append(f1)

                # Optional LLM judge pass
                j_score, j_reason = 0.0, ""
                if args.judge:
                    j_score, j_reason = llm_judge(llm, question, ground_truth, answer)
                    j_by_cat.setdefault(category, [])
                    j_by_cat[category].append(j_score)

            result = {
                "dialogue_idx": d_idx,
                "variant": args.variant,
                "question": question,
                "category": category,
                "adversarial": adversarial,
                "ground_truth": ground_truth,
                "prediction": answer,
                "f1": round(f1, 4),
                "j_score": round(j_score * 100, 1) if args.judge and not adversarial else None,
                "j_reason": j_reason if args.judge else None,
                "retrieval_ms": round(latency_ms, 2),
                "context_tokens": context_tokens,
                "max_similarity": round(max((s for _, s in retrieved), default=0.0), 4),
                "timestamp": datetime.datetime.now().isoformat(),
            }
            all_results.append(result)
            question_count += 1

            cat_name = {"1":"single-hop","2":"multi-hop","3":"temporal","4":"commonsense","5":"adversarial"}.get(category, category)
            j_str = f" J={j_score*100:.0f}" if args.judge and not adversarial else ""
            print(f"  Q{question_count} [{cat_name:12s}] F1={f1:.2f}{j_str} lat={latency_ms:.0f}ms | GT: {ground_truth[:25]!r} | A: {answer[:45]!r}")

        if args.max_questions and question_count >= args.max_questions:
            break

    # Write results
    with open(detailed_output, "w", encoding="utf-8") as f:
        for r in all_results:
            f.write(json.dumps(r) + "\n")

    summary = summarize_results(
        args=args,
        run_id=run_id,
        role_dir=role_dir,
        dialogues_count=len(dialogues),
        questions_count=question_count,
        latencies=latencies,
        all_results=all_results,
        f1_by_cat=f1_by_cat,
        j_by_cat=j_by_cat,
        adv_by_cat=adv_by_cat,
    )
    summary_output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Summary
    all_f1 = [r["f1"] for r in all_results if not r["adversarial"]]
    all_j = [r["j_score"] for r in all_results if not r["adversarial"] and r.get("j_score") is not None]
    total_adv = sum(v["total"] for v in adv_by_cat.values())
    total_abstain = sum(v["abstain"] for v in adv_by_cat.values())

    cat_names = {"1":"single-hop","2":"multi-hop","3":"temporal","4":"commonsense","5":"adversarial"}

    mode_str = []
    mode_str.append(args.variant)
    if args.rerank:
        mode_str.append(f"rerank(top{args.rerank_top_k}→{args.rerank_top_n})")
    if args.judge:
        mode_str.append("judge")
    mode_label = " | ".join(mode_str) if mode_str else "base"

    print("\n" + "=" * 60)
    print(f"LOCOMO BENCHMARK — MoJoAssistant [{mode_label}]")
    print("=" * 60)
    print(f"Questions answered:  {question_count}")
    print(f"Mean token F1:       {statistics.mean(all_f1):.4f}" if all_f1 else "Mean token F1: N/A")
    if all_j:
        print(f"Mean J score:        {statistics.mean(all_j):.1f} / 100")
    print(f"Adversarial correct: {total_abstain}/{total_adv} = {total_abstain/max(total_adv,1)*100:.1f}%")

    if latencies:
        s = sorted(latencies)
        print(f"Mean latency:        {statistics.mean(latencies):.1f}ms")
        print(f"p95 latency:         {s[int(len(s)*0.95)]:.1f}ms")

    print("\nPer-category scores (regular questions):")
    for cat in sorted(f1_by_cat):
        scores = f1_by_cat[cat]
        name = cat_names.get(cat, cat)
        j_str = ""
        if cat in j_by_cat:
            j_str = f"  J={statistics.mean(j_by_cat[cat])*100:.1f}"
        print(f"  cat {cat} ({name:12s}): F1={statistics.mean(scores):.4f}{j_str}  n={len(scores)}")

    print("\nAdversarial abstention:")
    for cat in sorted(adv_by_cat):
        r = adv_by_cat[cat]
        name = cat_names.get(cat, cat)
        print(f"  cat {cat} ({name:12s}): {r['abstain']}/{r['total']} = {r['abstain']/max(r['total'],1)*100:.1f}%")

    print(f"\nDetailed results written to: {detailed_output}")
    print(f"Summary artifact written to: {summary_output}")
    print("\nCompetitor reference (LOCOMO J score, 0–100):")
    print("  Zep 76.6  |  Mem0 75.7  |  LangMem 58.1  |  Full-ctx baseline ~55")


if __name__ == "__main__":
    args = parse_args()
    run_benchmark(args)
