"""
End-to-end LOCOMO ABCD benchmark runner.

This companion script prepares dreamed LOCOMO archives with the real
DreamingPipeline write path, then calls the benchmark runner against the
generated role tree so ABCD evaluation is a single command.

Example:
    python3 tests/benchmarks/run_locomo_abcd_e2e.py \
        --data-dir /tmp/locomo/data \
        --variant abcd_bc \
        --max-dialogues 1 \
        --output results/locomo_abcd_bc_d1.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.dreaming.pipeline import DreamingPipeline
from app.llm.llm_interface import LLMInterface
from tests.benchmarks.run_locomo import build_run_id, load_locomo


def parse_args():
    p = argparse.ArgumentParser(description="Prepare LOCOMO dreams and run the ABCD benchmark end to end")
    p.add_argument("--data-dir", required=True, help="Path to cloned locomo/data directory")
    p.add_argument("--variant", default="abcd_bc", choices=("abcd_b", "abcd_bc"))
    p.add_argument("--output", default="results/locomo_abcd_e2e.jsonl")
    p.add_argument("--run-id", default=None, help="Stable run identifier (default: auto-generated)")
    p.add_argument("--role-root", default=str(Path.home() / ".memory/roles"))
    p.add_argument("--role-dir", default=None, help="Optional preselected benchmark role root")
    p.add_argument("--benchmark-root", default=str(Path.home() / ".memory/benchmarks/locomo"))
    p.add_argument("--model", default=None, help="LLM model override for answer generation")
    p.add_argument("--embedding-backend", default="huggingface")
    p.add_argument("--embedding-model", default="BAAI/bge-m3")
    p.add_argument("--embedding-cache", default=str(Path.home() / ".memory/embedding_cache"))
    p.add_argument("--dataset-version", default="locomo10")
    p.add_argument("--quality-level", default="basic", choices=("basic", "good", "premium"))
    p.add_argument("--max-dialogues", type=int, default=None)
    p.add_argument("--max-questions", type=int, default=None)
    p.add_argument("--max-sessions", type=int, default=None, help="Limit sessions per dialogue during dream preparation")
    p.add_argument("--top-k", type=int, default=15)
    p.add_argument("--top-b", type=int, default=12)
    p.add_argument("--top-c", type=int, default=8)
    p.add_argument("--judge", action="store_true")
    p.add_argument("--rerank", action="store_true")
    p.add_argument("--rerank-top-k", type=int, default=25)
    p.add_argument("--rerank-top-n", type=int, default=5)
    p.add_argument("--raw-context-max-docs", type=int, default=40)
    p.add_argument("--abstention-threshold", type=float, default=0.35)
    p.add_argument("--reuse-existing", action="store_true", help="Skip dream preparation for sessions that already have archives")
    p.add_argument("--prepare-only", action="store_true", help="Build dream archives but do not run the benchmark")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def _build_role_dir(args) -> Path:
    if args.role_dir:
        return Path(args.role_dir).expanduser()
    run_id = build_run_id(SimpleNamespace(
        run_id=args.run_id,
        variant=args.variant,
        model=args.model,
        max_dialogues=args.max_dialogues,
        max_questions=args.max_questions,
    ))
    return Path(args.role_root).expanduser() / f"locomo_bench_{run_id}"


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
        if not text:
            continue
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines).strip()


async def prepare_dreams(args, role_dir: Path) -> None:
    dialogues = load_locomo(args.data_dir)
    if args.max_dialogues:
        dialogues = dialogues[:args.max_dialogues]

    if args.dry_run:
        total_sessions = 0
        for dialogue in dialogues:
            conv = dialogue.get("conversation", {})
            session_count = sum(1 for key in conv if key.startswith("session_") and not key.endswith("_date_time"))
            total_sessions += min(session_count, args.max_sessions or session_count)
        print(f"[DRY RUN] Would prepare dreams for {len(dialogues)} dialogues and {total_sessions} sessions under {role_dir}")
        return

    llm = LLMInterface(config_file=str(PROJECT_ROOT / "config/llm_config.json"))

    for d_idx, dialogue in enumerate(dialogues):
        conv = dialogue.get("conversation", {})
        speaker_a = conv.get("speaker_a", "A")
        speaker_b = conv.get("speaker_b", "B")
        dialogue_role_dir = role_dir / f"dialogue_{d_idx:02d}"
        pipeline = DreamingPipeline(
            llm_interface=llm,
            quality_level=args.quality_level,
            storage_path=dialogue_role_dir / "dreams",
        )

        print(f"\nPreparing dreams for dialogue {d_idx + 1}/{len(dialogues)} in {dialogue_role_dir}")

        session_indices: list[int] = []
        i = 1
        while f"session_{i}" in conv:
            session_indices.append(i)
            i += 1
        if args.max_sessions:
            session_indices = session_indices[:args.max_sessions]

        for session_idx in session_indices:
            conversation_id = f"locomo_d{d_idx:02d}_s{session_idx:02d}"
            archive_path = dialogue_role_dir / "dreams" / conversation_id / "archive_v1.json"
            if args.reuse_existing and archive_path.exists():
                print(f"  Reusing {conversation_id}")
                continue

            session_date = conv.get(f"session_{session_idx}_date_time", "")
            turns = conv.get(f"session_{session_idx}", [])
            conversation_text = _session_text(d_idx, session_idx, session_date, turns, speaker_a, speaker_b)
            if not conversation_text:
                print(f"  Skipping empty {conversation_id}")
                continue

            print(f"  Dreaming {conversation_id}")
            result = await pipeline.process_conversation(
                conversation_id=conversation_id,
                conversation_text=conversation_text,
                metadata={
                    "source": "locomo_benchmark",
                    "dialogue_idx": d_idx,
                    "session_idx": session_idx,
                    "original_text": conversation_text,
                    "quality_level": args.quality_level,
                    "session_date": session_date,
                },
            )
            if result.get("status") != "success":
                raise RuntimeError(f"Dreaming failed for {conversation_id}: {result}")


def _benchmark_command(args, role_dir: Path) -> list[str]:
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "tests/benchmarks/run_locomo.py"),
        "--data-dir", args.data_dir,
        "--variant", args.variant,
        "--role-dir", str(role_dir),
        "--skip-ingest",
        "--output", args.output,
        "--benchmark-root", args.benchmark_root,
        "--role-root", args.role_root,
        "--dataset-version", args.dataset_version,
        "--embedding-backend", args.embedding_backend,
        "--embedding-model", args.embedding_model,
        "--embedding-cache", args.embedding_cache,
        "--top-k", str(args.top_k),
        "--top-b", str(args.top_b),
        "--top-c", str(args.top_c),
        "--raw-context-max-docs", str(args.raw_context_max_docs),
        "--abstention-threshold", str(args.abstention_threshold),
    ]
    if args.run_id:
        cmd.extend(["--run-id", args.run_id])
    if args.model:
        cmd.extend(["--model", args.model])
    if args.max_dialogues:
        cmd.extend(["--max-dialogues", str(args.max_dialogues)])
    if args.max_questions:
        cmd.extend(["--max-questions", str(args.max_questions)])
    if args.judge:
        cmd.append("--judge")
    if args.rerank:
        cmd.extend(["--rerank", "--rerank-top-k", str(args.rerank_top_k), "--rerank-top-n", str(args.rerank_top_n)])
    return cmd


def main() -> int:
    args = parse_args()
    role_dir = _build_role_dir(args)

    asyncio.run(prepare_dreams(args, role_dir))
    if args.dry_run or args.prepare_only:
        return 0

    cmd = _benchmark_command(args, role_dir)
    print("\nRunning benchmark:")
    print(" ".join(cmd))
    completed = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
