"""Routing Profiler — measures per-model success rate across complexity cells.

Runs benchmark tasks against multiple models to build a capability profile
that feeds the task routing table.

Usage:
    python -m tests.benchmarks.run_routing_profiler
    python -m tests.benchmarks.run_routing_profiler --models lmstudio_gemma4_12b,lmstudio_qwen36_27b_mtp
    python -m tests.benchmarks.run_routing_profiler --cell A --tasks-per-cell 5
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.scheduler.task_router import compute_cell
from app.scheduler.routing_profile import (
    TaskRecord, aggregate_profile, derive_routing_table,
)


def load_tasks(cell: Optional[str] = None, max_per_cell: int = 15) -> List[Dict[str, Any]]:
    """Load routing benchmark tasks."""
    base = Path.home() / ".memory" / "benchmarks" / "routing" / "tasks"
    tasks = []
    cells = [cell] if cell else ["cellA", "cellB", "cellC", "cellD"]
    for c in cells:
        cell_dir = base / c
        if not cell_dir.exists():
            continue
        loaded = []
        for f in sorted(cell_dir.glob("*.json")):
            try:
                loaded.append(json.loads(f.read_text()))
            except Exception:
                pass
        tasks.extend(loaded[:max_per_cell])
    return tasks


def load_resource(resource_id: str) -> Optional[Dict[str, Any]]:
    """Load a resource from the resource pool config."""
    pool_path = Path.home() / ".memory" / "config" / "resource_pool.json"
    if not pool_path.exists():
        return None
    pool = json.loads(pool_path.read_text())
    resource = pool.get("resources", {}).get(resource_id)
    # Handle case where resource is stored as JSON string
    if isinstance(resource, str):
        try:
            resource = json.loads(resource)
        except json.JSONDecodeError:
            return None
    return resource


async def run_task_with_model(
    task: Dict[str, Any],
    resource_id: str,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Run a single task against a specific model."""
    task_id = task["id"]
    goal = task["goal"]
    start = time.time()

    result = {
        "task_id": task_id,
        "cell": task.get("cell", "?"),
        "resource_id": resource_id,
        "success": False,
        "response": "",
        "iterations": 1,
        "elapsed_s": 0,
        "error": None,
        "failure_class": None,  # filled below; None means "clean pass"
    }

    try:
        resource = load_resource(resource_id)
        if not resource:
            result["error"] = f"Resource '{resource_id}' not found"
            return result

        from app.llm.unified_client import UnifiedLLMClient
        client = UnifiedLLMClient()

        # Build context from task setup
        setup = task.get("setup", "")
        system_prompt = "You are a helpful assistant. Answer concisely and accurately."
        
        if setup.startswith("role="):
            role_id = setup.split("=")[1]
            role_path = Path.home() / ".memory" / "roles" / f"{role_id}.json"
            if role_path.exists():
                system_prompt += f"\n\nRole config:\n{role_path.read_text()[:2000]}"
        elif setup.startswith("file="):
            file_path = Path(setup.split("=", 1)[1]).expanduser()
            if not file_path.is_absolute():
                file_path = PROJECT_ROOT / file_path
            if file_path.exists():
                system_prompt += f"\n\nFile content:\n{file_path.read_text()[:2000]}"
        elif setup == "roles":
            roles_dir = Path.home() / ".memory" / "roles"
            summaries = []
            for f in sorted(roles_dir.glob("*.json"))[:20]:
                try:
                    r = json.loads(f.read_text())
                    summaries.append(f"{r.get('id','?')}: capabilities={r.get('capabilities',[])}")
                except:
                    pass
            system_prompt += "\n\nRoles:\n" + "\n".join(summaries)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": goal},
        ]

        resource_config = {
            "base_url": resource.get("base_url", ""),
            "model": resource.get("model", ""),
            "api_key": resource.get("api_key", ""),
            "output_limit": min(resource.get("output_limit", 8192), 8192),
            "message_format": "openai",
            "provider": resource.get("provider", ""),
            "timeout": 0,  # No timeout — let thinking models run as long as needed
        }

        data = await client.call_async(
            messages=messages,
            resource_config=resource_config,
            model_override=resource.get("model"),
        )

        choices = data.get("choices", [])
        if choices:
            response_text = choices[0].get("message", {}).get("content", "")
            result["response"] = response_text

            # Check answer
            match_type = task.get("match_type", "contains")
            correct = task.get("correct_answer", "")
            if correct and response_text:
                if match_type == "exact":
                    result["success"] = response_text.strip().lower() == correct.strip().lower()
                elif match_type == "contains":
                    result["success"] = correct.lower() in response_text.lower()
                elif match_type == "structural":
                    result["success"] = len(response_text.strip()) > 10  # has real content
            elif match_type == "structural":
                result["success"] = len(response_text.strip()) > 10

    except Exception as e:
        result["error"] = str(e)

    result["elapsed_s"] = round(time.time() - start, 1)
    # A7 — classify the failure (or clean-pass signal) so the profile can
    # carry failure_modes per cell. classify_failure is pure and lives in
    # evals.models; we re-import locally to keep this runner self-contained.
    from app.scheduler.evals.models import classify_failure
    fc = classify_failure(
        success=result["success"],
        elapsed_s=result["elapsed_s"],
        error=result["error"],
        response=result["response"],
        iterations=result["iterations"],
    )
    result["failure_class"] = fc.value if fc is not None else None
    return result


async def run_profiler(
    models: List[str],
    cell: Optional[str] = None,
    tasks_per_cell: int = 5,
) -> Dict[str, Any]:
    """Run profiling across models and cells."""
    tasks = load_tasks(cell=cell, max_per_cell=tasks_per_cell)
    if not tasks:
        print("No tasks found!")
        return {}

    run_id = f"profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = Path.home() / ".memory" / "benchmarks" / "routing" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"Routing profiler: {run_id}")
    print(f"Models: {models}")
    print(f"Tasks: {len(tasks)} ({tasks_per_cell}/cell)")
    print()

    all_results = []
    raw_records: List[TaskRecord] = []

    for model_id in models:
        print(f"=== {model_id} ===")

        for task in tasks:
            cell = task.get("cell", "?")
            print(f"  {task['id']} (Cell {cell}): {task['goal'][:50]}...", end=" ")

            result = await run_task_with_model(task, model_id, {})
            all_results.append(result)
            raw_records.append(TaskRecord(
                task_id=result["task_id"],
                cell=result["cell"],
                resource_id=result["resource_id"],
                success=result["success"],
                elapsed_s=result["elapsed_s"],
                iterations=result["iterations"],
                error=result["error"],
                response=result["response"],
                failure_class=result["failure_class"],
            ))

            status = "✓" if result["success"] else "✗"
            fc = result["failure_class"] or "clean"
            print(f"{status} ({result['elapsed_s']:.1f}s, {fc})")

    # Aggregate into v2 profile schema (pass, failure_modes, avg_duration, ...).
    profile = aggregate_profile(raw_records)
    for model_id, by_cell in profile.items():
        for cell, stats in sorted(by_cell.items()):
            fm = stats.get("failure_modes") or {}
            fm_str = ",".join(f"{k}={v}" for k, v in sorted(fm.items())) or "-"
            print(f"  {model_id} Cell {cell}: pass={stats['pass']:.3f} "
                  f"({stats['success']}/{stats['total']}) modes=[{fm_str}] "
                  f"avg_dur={stats['avg_duration']:.1f}s")

    # Derive routing_table.json from the profile. Cheapest-first ordering is
    # the order the caller passed in (matches priority in the resource pool).
    routing_table = derive_routing_table(profile, candidate_order=list(models))
    print("\nDerived routing table:")
    for cell, model_id in routing_table.items():
        if cell.startswith("_"):
            continue
        print(f"  {cell} -> {model_id or '(none qualified)'}")

    # Save summary (includes both per-task records and aggregated profile).
    summary = {
        "run_id": run_id,
        "models": models,
        "tasks_per_cell": tasks_per_cell,
        "profile": profile,
        "per_task": all_results,
        "routing_table": {k: v for k, v in routing_table.items() if not k.startswith("_")},
        "cell_decisions": routing_table.get("_cell_decisions", {}),
        "thresholds": routing_table.get("_thresholds", {}),
        "timestamp": datetime.now().isoformat(),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    # Persist derived routing_table.json (live, at ~/.memory/benchmarks/routing/).
    routing_path = Path.home() / ".memory" / "benchmarks" / "routing" / "routing_table.json"
    routing_table_persisted = {k: v for k, v in routing_table.items() if not k.startswith("_")}
    routing_path.write_text(json.dumps(routing_table_persisted, indent=2))
    print(f"\nWrote routing_table.json -> {routing_path}")

    # Save capability profile (v2 schema — pass, failure_modes, avg_duration).
    profile_path = Path.home() / ".memory" / "benchmarks" / "routing" / "capability_profile.json"
    profile_path.write_text(json.dumps(profile, indent=2))
    print(f"Wrote capability_profile.json -> {profile_path}")

    return summary


def main():
    parser = argparse.ArgumentParser(description="Run routing profiler")
    parser.add_argument("--models", default="lmstudio_gemma4_12b,lmstudio__google_gemma_4_26b_a4b,lmstudio_qwen36_27b_mtp,lmstudio_qwen36_mtp,lmstudio_ornith_35b_mtp_apex",
                       help="Comma-separated model IDs")
    parser.add_argument("--cell", help="Run specific cell only")
    parser.add_argument("--tasks-per-cell", type=int, default=5)
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",")]
    asyncio.run(run_profiler(models, cell=args.cell, tasks_per_cell=args.tasks_per_cell))


if __name__ == "__main__":
    main()
