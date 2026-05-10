"""
LOCOMO benchmark runner for a role-scoped assistant memory path.

This runner benchmarks the intended MoJo design:
  conversation facts in role-private memory are primary
  ABCD dreaming is optional augmentation

It is designed around a benchmark role such as `ben`.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import re
import shutil
import statistics
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
SUBMODULE_SRC = PROJECT_ROOT / "submodules" / "dreaming-memory-pipeline" / "src"
if SUBMODULE_SRC.exists():
    sys.path.insert(0, str(SUBMODULE_SRC))

from app.config.paths import get_memory_subpath
from app.dreaming.pipeline import DreamingPipeline
from app.llm.llm_interface import LLMInterface
from app.roles.role_manager import RoleManager
from mojo_memory.services.hybrid_memory_service import HybridMemoryService
from tests.benchmarks.run_locomo import (
    build_run_id,
    llm_judge,
    load_dream_archives,
    load_locomo,
    retrieve_abcd,
    token_f1,
)


def parse_args():
    p = argparse.ArgumentParser(
        description="Run LOCOMO against a role-scoped MoJo memory path.\n\n"
        "Intended workflow (memory is persistent — do each phase once):\n"
        "  1. --setup-only  : ingest all dialogues + build complete ABCD dreams\n"
        "  2. --eval-only   : answer all questions against existing memory (fast, repeatable)\n"
        "  3. No flag       : full pipeline in one shot (first run only)\n"
    )
    p.add_argument("--data-dir", required=True, help="Path to cloned locomo/data directory")
    p.add_argument("--output", default="results/locomo_role_memory.jsonl")
    p.add_argument("--run-id", default=None)
    p.add_argument("--role-id", default="ben", help="Benchmark role id")
    p.add_argument(
        "--variant",
        default="facts_plus_abcd",
        choices=("facts_only", "facts_plus_abcd", "abcd_only"),
        help="Benchmark path to test",
    )
    p.add_argument("--benchmark-root", default=str(Path.home() / ".memory/benchmarks/locomo"))
    p.add_argument("--dataset-version", default="locomo10")
    p.add_argument("--model", default=None)
    p.add_argument("--max-dialogues", type=int, default=None,
                   help="Limit dialogues (default: all). Omit for a real benchmark run.")
    p.add_argument("--max-questions", type=int, default=None)
    p.add_argument("--max-sessions", type=int, default=None)
    p.add_argument("--embedding-backend", default="huggingface")
    p.add_argument("--embedding-model", default="BAAI/bge-m3")
    p.add_argument("--quality-level", default="good", choices=("basic", "good", "premium"),
                   help="Dream quality level (default: good — extracts key_facts)")
    p.add_argument("--facts-top-k", type=int, default=20,
                   help="Facts retrieved per question (default: 20)")
    p.add_argument("--top-b", type=int, default=10)
    p.add_argument("--top-c", type=int, default=15,
                   help="C-cluster summaries retrieved (default: 15)")
    p.add_argument("--judge", action="store_true")
    p.add_argument("--reset-role-memory", action="store_true",
                   help="Wipe role memory before ingest. Use only when re-ingesting from scratch.")
    p.add_argument("--setup-only", action="store_true",
                   help="Ingest facts + build ABCD dreams, then exit. Run once per dataset.")
    p.add_argument("--eval-only", action="store_true",
                   help="Skip ingest/dreams, use existing memory. Fast repeated evaluations.")
    p.add_argument(
        "--validation-mode",
        default="none",
        choices=("none", "abcd_v1"),
        help="Validation profile. abcd_v1 enables stage checks + run validity artifacts.",
    )
    p.add_argument(
        "--fail-on-empty-facts",
        action="store_true",
        help="Fail fast when factual retrieval is unexpectedly empty in facts-first variants.",
    )
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def _slugify(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in text)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "run"


def resolve_run_paths(args) -> dict[str, Path]:
    run_id = build_run_id(args)
    benchmark_root = Path(args.benchmark_root).expanduser()
    run_dir = benchmark_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    detailed_output = Path(args.output).expanduser()
    if not detailed_output.is_absolute():
        detailed_output = PROJECT_ROOT / detailed_output
    detailed_output.parent.mkdir(parents=True, exist_ok=True)

    role_memory_dir = Path(get_memory_subpath("roles")) / args.role_id
    return {
        "run_id": Path(_slugify(run_id)),
        "run_dir": run_dir,
        "detailed_output": detailed_output,
        "summary_output": run_dir / "results.json",
        "role_memory_dir": role_memory_dir,
        "dreams_dir": role_memory_dir / "dreams",
    }


def _load_role(role_id: str) -> dict[str, Any]:
    role = RoleManager().get(role_id)
    if not role:
        raise ValueError(f"Role '{role_id}' not found")
    return role


def _reset_role_memory(role_memory_dir: Path) -> None:
    if role_memory_dir.exists():
        shutil.rmtree(role_memory_dir)
    role_memory_dir.mkdir(parents=True, exist_ok=True)


def _ingested_sessions_path(role_memory_dir: Path) -> Path:
    return role_memory_dir / "locomo_ingested_sessions.json"


def _load_ingested_sessions(role_memory_dir: Path) -> set[str]:
    """Return set of session IDs already stored in Ben's memory."""
    path = _ingested_sessions_path(role_memory_dir)
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_ingested_sessions(role_memory_dir: Path, session_ids: set[str]) -> None:
    path = _ingested_sessions_path(role_memory_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sorted(session_ids), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _build_memory_service(args) -> HybridMemoryService:
    return HybridMemoryService(
        embedding_model=args.embedding_model,
        embedding_backend=args.embedding_backend,
        embedding_device="cpu",
        config={
            "multi_model_enabled": True,
            "working_memory_max_tokens": 8000,
            "active_memory_max_pages": 100,
        },
    )


def _session_text(dialogue_idx: int, session_idx: int, session_date: str, turns: list[dict], speaker_a: str, speaker_b: str) -> str:
    lines = [
        f"=== LOCOMO Dialogue {dialogue_idx} Session {session_idx} ===",
        f"Date: {session_date}",
        "",
    ]
    for turn in turns:
        speaker = turn.get("speaker") or ""
        if speaker == "speaker_a":
            speaker = speaker_a
        elif speaker == "speaker_b":
            speaker = speaker_b
        text = (turn.get("text") or "").strip()
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines).strip()


def _is_output_format_invalid(text: str) -> tuple[bool, str | None]:
    t = (text or "").strip()
    if not t:
        return True, "empty_answer"
    if "<SPECIAL_" in t:
        return True, "special_token_artifact"
    if re.search(r"<\|[^>]+?\|>", t):
        return True, "tokenizer_control_token_leakage"
    if "Thinking Process:" in t:
        return True, "reasoning_leakage"
    return False, None


def _validate_stage_a_input(dialogues: list[dict], max_sessions: int | None = None) -> dict[str, Any]:
    issues: list[str] = []
    sessions_total = 0
    sessions_empty = 0
    missing_dates = 0
    turns_total = 0
    turns_empty_text = 0

    for d_idx, dialogue in enumerate(dialogues):
        conv = dialogue.get("conversation", {})
        i = 1
        session_indices: list[int] = []
        while f"session_{i}" in conv:
            session_indices.append(i)
            i += 1
        if max_sessions:
            session_indices = session_indices[:max_sessions]

        for session_idx in session_indices:
            sessions_total += 1
            session_date = conv.get(f"session_{session_idx}_date_time", "")
            if not str(session_date).strip():
                missing_dates += 1
                issues.append(f"missing_date:d{d_idx:02d}s{session_idx:02d}")
            turns = conv.get(f"session_{session_idx}", [])
            if not turns:
                sessions_empty += 1
                issues.append(f"empty_session:d{d_idx:02d}s{session_idx:02d}")
            for turn_idx, turn in enumerate(turns):
                turns_total += 1
                if not str(turn.get("text", "")).strip():
                    turns_empty_text += 1
                    issues.append(f"empty_turn_text:d{d_idx:02d}s{session_idx:02d}t{turn_idx:02d}")

    return {
        "stage": "A_input_integrity",
        "sessions_total": sessions_total,
        "sessions_empty": sessions_empty,
        "missing_dates": missing_dates,
        "turns_total": turns_total,
        "turns_empty_text": turns_empty_text,
        "passed": sessions_total > 0 and sessions_empty == 0 and missing_dates == 0,
        "issues": issues[:50],
    }


def _validate_stage_bc_archives(archives: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[str] = []
    total = len(archives)
    missing_b = 0
    missing_c = 0
    malformed = 0

    for i, arch in enumerate(archives):
        if not isinstance(arch, dict):
            malformed += 1
            issues.append(f"malformed_archive:{i}")
            continue
        b_chunks = arch.get("b_chunks", [])
        c_clusters = arch.get("c_clusters", [])
        if not isinstance(b_chunks, list):
            malformed += 1
            issues.append(f"malformed_b_chunks:{i}")
            b_chunks = []
        if not isinstance(c_clusters, list):
            malformed += 1
            issues.append(f"malformed_c_clusters:{i}")
            c_clusters = []
        if not b_chunks:
            missing_b += 1
            issues.append(f"missing_b_chunks:{i}")
        if not c_clusters:
            missing_c += 1
            issues.append(f"missing_c_clusters:{i}")

    return {
        "stage": "B_C_archive_integrity",
        "archives_total": total,
        "missing_b_chunks": missing_b,
        "missing_c_clusters": missing_c,
        "malformed_archives": malformed,
        "passed": total > 0 and missing_b == 0 and missing_c == 0 and malformed == 0,
        "issues": issues[:50],
    }


def ingest_dialogues_to_role_memory(
    args,
    svc: HybridMemoryService,
    dialogues: list[dict],
    role_id: str,
    already_ingested: set[str],
) -> tuple[int, set[str]]:
    """
    Store conversation turns into Ben's persistent role memory.

    Each LOCOMO session maps to one conversation session in MoJo:
      Dialogue  → relationship context (who is talking)
      Session   → one persistent conversation (stored once, never re-ingested)
      Turn      → one fact stored in role-scoped knowledge

    Returns (turns_added, newly_ingested_session_ids).
    Already-ingested sessions are skipped automatically.
    """
    added = 0
    new_sessions: set[str] = set()

    for d_idx, dialogue in enumerate(dialogues):
        conv = dialogue.get("conversation", {})
        speaker_a = conv.get("speaker_a", "A")
        speaker_b = conv.get("speaker_b", "B")

        session_indices: list[int] = []
        i = 1
        while f"session_{i}" in conv:
            session_indices.append(i)
            i += 1
        if args.max_sessions:
            session_indices = session_indices[:args.max_sessions]

        for session_idx in session_indices:
            session_id = f"locomo_d{d_idx:02d}_s{session_idx:02d}"

            if session_id in already_ingested:
                continue  # persistent memory — session already stored, skip

            session_date = conv.get(f"session_{session_idx}_date_time", "")
            turns = conv.get(f"session_{session_idx}", [])
            session_turns = 0

            for turn_idx, turn in enumerate(turns):
                speaker = turn.get("speaker") or ""
                if speaker == "speaker_a":
                    speaker = speaker_a
                elif speaker == "speaker_b":
                    speaker = speaker_b
                text = (turn.get("text") or "").strip()
                if not text:
                    continue
                content = (
                    f"[session={session_id} date={session_date} turn={turn_idx}]"
                    f" {speaker}: {text}"
                )
                svc.add_to_knowledge_base(
                    content,
                    metadata={
                        "source": "locomo_conversation",
                        "session_id": session_id,
                        "dialogue_idx": d_idx,
                        "session_idx": session_idx,
                        "turn_idx": turn_idx,
                        "date": session_date,
                        "speaker": speaker,
                    },
                    role_id=role_id,
                )
                added += 1
                session_turns += 1

            new_sessions.add(session_id)
            print(f"[ingest] {session_id}: {session_turns} turns stored", flush=True)

    return added, new_sessions


async def prepare_dreams(args, role_memory_dir: Path, dialogues: list[dict]) -> None:
    llm = LLMInterface(config_file=str(PROJECT_ROOT / "config/llm_config.json"))
    if args.model:
        llm.set_active_interface(args.model)
    pipeline = DreamingPipeline(
        llm_interface=llm,
        quality_level=args.quality_level,
        storage_path=role_memory_dir / "dreams",
    )

    for d_idx, dialogue in enumerate(dialogues):
        conv = dialogue.get("conversation", {})
        speaker_a = conv.get("speaker_a", "A")
        speaker_b = conv.get("speaker_b", "B")

        session_indices: list[int] = []
        i = 1
        while f"session_{i}" in conv:
            session_indices.append(i)
            i += 1
        if args.max_sessions:
            session_indices = session_indices[:args.max_sessions]

        for session_idx in session_indices:
            conversation_id = f"locomo_d{d_idx:02d}_s{session_idx:02d}"
            print(f"[dream] building {conversation_id}", flush=True)
            archive_path = role_memory_dir / "dreams" / conversation_id / "archive_v1.json"
            if args.reuse_existing_dreams and archive_path.exists():
                print(f"[dream] reuse existing {conversation_id}", flush=True)
                continue

            session_date = conv.get(f"session_{session_idx}_date_time", "")
            turns = conv.get(f"session_{session_idx}", [])
            conversation_text = _session_text(d_idx, session_idx, session_date, turns, speaker_a, speaker_b)
            if not conversation_text:
                print(f"[dream] skip empty {conversation_id}", flush=True)
                continue
            result = await pipeline.process_conversation(
                conversation_id=conversation_id,
                conversation_text=conversation_text,
                metadata={
                    "source": "locomo_benchmark_role_memory",
                    "dialogue_idx": d_idx,
                    "session_idx": session_idx,
                    "original_text": conversation_text,
                    "quality_level": args.quality_level,
                    "session_date": session_date,
                },
            )
            if result.get("status") != "success":
                raise RuntimeError(f"Dreaming failed for {conversation_id}: {result}")
            print(f"[dream] done {conversation_id}", flush=True)


async def retrieve_facts(svc: HybridMemoryService, query: str, role_id: str, top_k: int) -> tuple[list[tuple[str, float]], float]:
    t0 = time.perf_counter()
    results = await svc.get_context_for_query_async(query, max_items=top_k, role_id=role_id)
    ms = (time.perf_counter() - t0) * 1000
    hits = [(item.get("content", ""), float(item.get("relevance", 0.0))) for item in results if item.get("content")]
    return hits, ms


def _combine_retrievals(facts: list[tuple[str, float]], dreams: list[tuple[str, float]]) -> list[tuple[str, float]]:
    merged: dict[str, float] = {}
    for text, score in facts:
        merged[text] = max(merged.get(text, 0.0), score + 0.15)
    for text, score in dreams:
        merged[text] = max(merged.get(text, 0.0), score)
    return sorted(merged.items(), key=lambda x: x[1], reverse=True)


def _context_sections(facts: list[tuple[str, float]], dreams: list[tuple[str, float]], variant: str) -> str:
    sections = []
    if variant in ("facts_only", "facts_plus_abcd"):
        fact_lines = [f"[score={score:.3f}] {text}" for text, score in facts]
        sections.append("Conversation facts:\n" + ("\n".join(fact_lines) if fact_lines else "None"))
    if variant in ("facts_plus_abcd", "abcd_only"):
        dream_lines = [f"[score={score:.3f}] {text}" for text, score in dreams]
        sections.append("ABCD memory:\n" + ("\n".join(dream_lines) if dream_lines else "None"))
    return "\n\n".join(sections)


def answer_question(llm: LLMInterface, role: dict[str, Any], question: str, facts: list[tuple[str, float]], dreams: list[tuple[str, float]], variant: str) -> str:
    system_prompt = role.get("system_prompt", "You are a benchmark assistant.")
    context_str = _context_sections(facts, dreams, variant)
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"{context_str}\n\n"
                f"Question: {question}\n\n"
                "Instructions:\n"
                "- Conversation facts are primary evidence.\n"
                "- ABCD memory is secondary support only.\n"
                "- If the answer is not supported by retrieved evidence, respond exactly: \"I don't have that information.\"\n"
                "- Be concise. Answer with the fewest words that fully answer the question.\n"
                "- Date resolution: if the context contains relative dates (e.g. 'yesterday', 'last year', 'next month', '3 years ago') and the session date is shown, resolve them to exact absolute dates (e.g. '7 May 2023', '2022') in your answer.\n"
            ),
        },
    ]
    return llm.generate_chat_response(messages).strip()


def summarize_results(
    *,
    args,
    run_id: str,
    question_count: int,
    role_id: str,
    all_results: list[dict[str, Any]],
    latencies: list[float],
    f1_by_cat: dict[str, list[float]],
    j_by_cat: dict[str, list[float]],
    adv_by_cat: dict[str, dict[str, int]],
    validation: dict[str, Any],
) -> dict[str, Any]:
    all_f1 = [r["f1"] for r in all_results if not r["adversarial"]]
    all_j = [r["j_score"] for r in all_results if not r["adversarial"] and r.get("j_score") is not None]
    total_adv = sum(v["total"] for v in adv_by_cat.values())
    total_abstain = sum(v["abstain"] for v in adv_by_cat.values())
    sorted_latencies = sorted(latencies)
    p95_latency = sorted_latencies[int(len(sorted_latencies) * 0.95)] if sorted_latencies else None

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
        "role_id": role_id,
        "questions": question_count,
        "answer_model": args.model or "default_from_llm_config",
        "judge_model": args.model if args.judge and args.model else ("default_from_llm_config" if args.judge else None),
        "embedding_model": args.embedding_model,
        "metrics": {
            "f1": round(statistics.mean(all_f1), 4) if all_f1 else None,
            "j_score": round(statistics.mean(all_j), 1) if all_j else None,
            "abstention_rate_cat5": round(total_abstain / max(total_adv, 1), 4) if total_adv else None,
            "mean_retrieval_latency_ms": round(statistics.mean(latencies), 2) if latencies else None,
            "p95_retrieval_latency_ms": round(p95_latency, 2) if p95_latency is not None else None,
        },
        "retrieval": {
            "mode": args.variant,
            "facts_top_k": args.facts_top_k,
            "top_b": args.top_b,
            "top_c": args.top_c,
        },
        "provenance": {
            "runner": "tests/benchmarks/run_locomo_role_memory.py",
            "role_id": role_id,
            "eval_only": args.eval_only,
            "reset_role_memory": args.reset_role_memory,
            "detailed_output": str(Path(args.output).expanduser()),
        },
        "validation": validation,
        "per_category": per_category,
        "notes": [
            "This benchmark follows the intended MoJo design: conversation facts first, ABCD second.",
            "Accepted runs should reset the benchmark role memory or use a fresh dedicated benchmark role.",
        ],
    }


async def run_benchmark(args) -> None:
    role = _load_role(args.role_id)
    paths = resolve_run_paths(args)
    run_id = str(paths["run_id"])
    role_memory_dir = paths["role_memory_dir"]

    dialogues = load_locomo(args.data_dir)
    if args.max_dialogues:
        dialogues = dialogues[:args.max_dialogues]

    validation_mode = args.validation_mode == "abcd_v1"
    validation: dict[str, Any] = {
        "mode": args.validation_mode,
        "run_valid": True,
        "invalid_reasons": [],
        "stage_checks": [],
        "counters": {
            "invalid_output_count": 0,
            "empty_facts_count": 0,
            "questions_checked": 0,
        },
    }
    if validation_mode:
        validation["stage_checks"].append(
            _validate_stage_a_input(dialogues, max_sessions=args.max_sessions)
        )

    if args.dry_run:
        total_sessions = sum(
            sum(1 for k in d.get("conversation", {}) if k.startswith("session_") and not k.endswith("_date_time"))
            for d in dialogues
        )
        total_qa = sum(len(d.get("qa", [])) for d in dialogues)
        already = _load_ingested_sessions(paths["role_memory_dir"])
        print(
            f"[DRY RUN] {len(dialogues)} dialogues, {total_sessions} sessions, "
            f"~{total_qa} QA pairs | role={args.role_id}, variant={args.variant}\n"
            f"  Already in memory: {len(already)} sessions  "
            f"  Needs ingest: {total_sessions - len(already)} sessions"
        )
        return

    # ── Setup phase (one-time, persistent) ────────────────────────────────
    # Memory is permanent. Sessions are stored once and never re-ingested.
    # --reset-role-memory is the only way to start over from scratch.
    if not args.eval_only:
        if args.reset_role_memory:
            _reset_role_memory(role_memory_dir)

        svc = _build_memory_service(args)
        already_ingested = _load_ingested_sessions(role_memory_dir)

        added, new_sessions = ingest_dialogues_to_role_memory(
            args, svc, dialogues, args.role_id, already_ingested
        )
        if new_sessions:
            all_ingested = already_ingested | new_sessions
            _save_ingested_sessions(role_memory_dir, all_ingested)
            print(f"[ingest] stored {added} turns across {len(new_sessions)} new sessions "
                  f"({len(all_ingested)} total in memory)", flush=True)
        else:
            print(f"[ingest] all {len(already_ingested)} sessions already in memory — nothing to add", flush=True)

        if args.variant in ("facts_plus_abcd", "abcd_only"):
            # Build only missing dream archives (skip existing ones)
            args.reuse_existing_dreams = True
            await prepare_dreams(args, role_memory_dir, dialogues)
    else:
        print(f"[eval-only] using existing persistent memory for role:{args.role_id}", flush=True)
        svc = _build_memory_service(args)

    if args.setup_only:
        print(f"\n[setup-only] Memory and dreams ready for role:{args.role_id}. Run with --eval-only to benchmark.")
        return

    # ── Eval phase ─────────────────────────────────────────────────────────
    llm = LLMInterface(config_file=str(PROJECT_ROOT / "config/llm_config.json"))
    if args.model:
        llm.set_active_interface(args.model)

    archives = []
    if args.variant in ("facts_plus_abcd", "abcd_only"):
        archives = load_dream_archives(role_memory_dir)
        if validation_mode:
            validation["stage_checks"].append(_validate_stage_bc_archives(archives))
    embedding = svc.embedding

    all_results: list[dict[str, Any]] = []
    latencies: list[float] = []
    f1_by_cat: dict[str, list[float]] = {}
    j_by_cat: dict[str, list[float]] = {}
    adv_by_cat: dict[str, dict[str, int]] = {}
    question_count = 0

    for d_idx, dialogue in enumerate(dialogues):
        qa_pairs = dialogue.get("qa", [])
        for qa in qa_pairs:
            if args.max_questions and question_count >= args.max_questions:
                break

            question = qa.get("question", "")
            ground_truth = str(qa.get("answer", qa.get("adversarial_answer", "")))
            category = str(qa.get("category", "?"))
            adversarial = qa.get("category") == 5
            if not question:
                continue

            facts_hits, facts_ms = await retrieve_facts(svc, question, args.role_id, args.facts_top_k)
            dream_hits: list[tuple[str, float]] = []
            dream_ms = 0.0
            if args.variant in ("facts_plus_abcd", "abcd_only"):
                dream_hits, dream_ms = retrieve_abcd(
                    embedding=embedding,
                    archives=archives,
                    question=question,
                    variant="abcd_bc",
                    top_b=args.top_b,
                    top_c=args.top_c,
                )

            if args.variant == "facts_only":
                combined = facts_hits
            elif args.variant == "abcd_only":
                combined = dream_hits
            else:
                combined = _combine_retrievals(facts_hits, dream_hits)

            retrieval_ms = facts_ms + dream_ms
            latencies.append(retrieval_ms)

            if args.variant in ("facts_only", "facts_plus_abcd") and not facts_hits:
                validation["counters"]["empty_facts_count"] += 1
                if args.fail_on_empty_facts or validation_mode:
                    raise RuntimeError(
                        "Validation failed: empty factual retrieval in facts-first variant. "
                        f"dialogue={d_idx} category={category} question={question[:80]!r}"
                    )

            answer = answer_question(llm, role, question, facts_hits, dream_hits, args.variant)
            invalid_output, invalid_reason = _is_output_format_invalid(answer)
            if invalid_output:
                validation["run_valid"] = False
                validation["counters"]["invalid_output_count"] += 1
                validation["invalid_reasons"].append(invalid_reason or "unknown_output_invalid")

            if adversarial:
                abstained = answer.strip() == "I don't have that information."
                f1 = 1.0 if abstained else 0.0
                adv_by_cat.setdefault(category, {"total": 0, "abstain": 0})
                adv_by_cat[category]["total"] += 1
                if abstained:
                    adv_by_cat[category]["abstain"] += 1
                j_score, j_reason = None, None
            else:
                f1 = token_f1(answer, ground_truth)
                f1_by_cat.setdefault(category, []).append(f1)
                j_score, j_reason = None, None
                if args.judge:
                    j_frac, j_reason = llm_judge(llm, question, ground_truth, answer)
                    j_score = round(j_frac * 100, 1)
                    j_by_cat.setdefault(category, []).append(j_score)

            result = {
                "dialogue_idx": d_idx,
                "role_id": args.role_id,
                "variant": args.variant,
                "question": question,
                "category": category,
                "adversarial": adversarial,
                "ground_truth": ground_truth,
                "prediction": answer,
                "f1": round(f1, 4),
                "j_score": j_score,
                "j_reason": j_reason,
                "retrieval_ms": round(retrieval_ms, 2),
                "facts_hits": len(facts_hits),
                "dream_hits": len(dream_hits),
                "combined_hits": len(combined),
                "max_similarity": round(max((s for _, s in combined), default=0.0), 4),
                "facts_context": [
                    {"score": round(score, 4), "text": text}
                    for text, score in facts_hits
                ],
                "dream_context": [
                    {"score": round(score, 4), "text": text}
                    for text, score in dream_hits
                ],
                "combined_context": [
                    {"score": round(score, 4), "text": text}
                    for text, score in combined
                ],
                "timestamp": datetime.datetime.now().isoformat(),
                "run_validity": {
                    "valid_output_format": not invalid_output,
                    "invalid_reason": invalid_reason,
                },
            }
            all_results.append(result)
            question_count += 1
            validation["counters"]["questions_checked"] = question_count

            cat_name = {"1": "single-hop", "2": "multi-hop", "3": "temporal", "4": "commonsense", "5": "adversarial"}.get(category, category)
            print(f"  Q{question_count} [{cat_name:12s}] F1={f1:.2f} lat={retrieval_ms:.0f}ms | GT: {ground_truth[:25]!r} | A: {answer[:45]!r}")

        if args.max_questions and question_count >= args.max_questions:
            break

    with open(paths["detailed_output"], "w", encoding="utf-8") as f:
        for r in all_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    if validation_mode:
        for stage in validation["stage_checks"]:
            if not stage.get("passed", False):
                validation["run_valid"] = False
                validation["invalid_reasons"].append(f"stage_failed:{stage.get('stage','unknown')}")
        # Stage D check: if we evaluated questions and combined retrieval is always empty, fail.
        if question_count > 0:
            all_combined_empty = all(r.get("combined_hits", 0) == 0 for r in all_results)
            stage_d = {
                "stage": "D_retrieval_probe",
                "questions_checked": question_count,
                "all_combined_empty": all_combined_empty,
                "passed": not all_combined_empty,
                "issues": ["all_combined_hits_empty"] if all_combined_empty else [],
            }
            validation["stage_checks"].append(stage_d)
            if all_combined_empty:
                validation["run_valid"] = False
                validation["invalid_reasons"].append("stage_failed:D_retrieval_probe")

    summary = summarize_results(
        args=args,
        run_id=run_id,
        question_count=question_count,
        role_id=args.role_id,
        all_results=all_results,
        latencies=latencies,
        f1_by_cat=f1_by_cat,
        j_by_cat=j_by_cat,
        adv_by_cat=adv_by_cat,
        validation=validation,
    )
    paths["summary_output"].write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    all_f1 = [r["f1"] for r in all_results if not r["adversarial"]]
    total_adv = sum(v["total"] for v in adv_by_cat.values())
    total_abstain = sum(v["abstain"] for v in adv_by_cat.values())
    print("\n" + "=" * 60)
    print(f"LOCOMO BENCHMARK — role:{args.role_id} [{args.variant}]")
    print("=" * 60)
    print(f"Questions answered:  {question_count}")
    print(f"Mean token F1:       {statistics.mean(all_f1):.4f}" if all_f1 else "Mean token F1: N/A")
    print(f"Adversarial correct: {total_abstain}/{total_adv} = {total_abstain / max(total_adv, 1) * 100:.1f}%")
    if latencies:
        s = sorted(latencies)
        print(f"Mean latency:        {statistics.mean(latencies):.1f}ms")
        print(f"p95 latency:         {s[int(len(s) * 0.95)]:.1f}ms")
    print(f"\nDetailed results written to: {paths['detailed_output']}")
    print(f"Summary artifact written to: {paths['summary_output']}")


if __name__ == "__main__":
    asyncio.run(run_benchmark(parse_args()))
