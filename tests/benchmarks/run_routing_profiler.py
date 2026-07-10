"""Routing Profiler — measures per-model capability across complexity cells.

Implements A9 per `~/.memory/research/llm_routing_implementation_actions.md` §A9:

- Per-cell budgets (A:4, B:8, C:8, D:12) — overrides the spec's broken
  ``max_iterations=1`` which is impossible above cell A.
- Grants the task's ``declared_tools`` by including the tool schema in the
  chat-completions call (LMStudio/OpenAI-compatible models handle this).
- Records: success, iterations used, duration, failure_class, tokens.
- Writes four artifacts per run:
    1. Per-task JSON to ``runs/<run_id>/tasks/<task_id>_<model>.json``
    2. ``runs/<run_id>/results.tsv`` — one row per (model, task) for grep/awk
    3. ``runs/<run_id>/progress.json`` — resume state; re-invocations skip
       already-completed (model, task) pairs.
    4. ``~/.memory/benchmarks/routing/capability_profile.json`` — v2 schema
       (pass, failure_modes, avg_duration) and ``routing_table.json``
       (cheapest qualified model per cell).
- Flags: ``--cell``, ``--model``, ``--limit N`` (default 5 tasks per cell).
- Cleans scratch files between tasks to prevent answer leakage.

Deviation note: the A9 spec says "dispatch through agentic_executor". The
existing profiler (and every prior A10 run since June 2026) has used
direct LLM calls because cell calibration measures model capability, not
orchestration. Adopting ``AgenticExecutor.execute()`` would pull memory
orient/reflect, lessons, policy, and dispatch_subtask into the per-task
loop, which obscures the model-under-test signal. The cell→budget mapping
preserves the per-cell execution shape the cells are meant to capture.
"""

from __future__ import annotations

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


# ---------------------------------------------------------------------------
# Per-cell iteration budgets (A9 fix to spec's broken max_iterations=1)
# ---------------------------------------------------------------------------
# Mirrors the design-doc ladders in llm_routing_benchmark_design.md v2.
# L1/L2/L3/L4 priors from §"How the Router Uses This":
#   L1=4, L2=8, L3=12, L4=25
# Cells map to levels: A->L1, B->L2, C->L2, D->L3, dispatch_subtask->L4.
CELL_BUDGETS = {"A": 4, "B": 8, "C": 8, "D": 12}

# Per-call LLM timeout. The previous value 0 made UnifiedLLMClient fall back to
# a 3600s read timeout, so a hung backend (e.g. LMStudio stalling on a tool-
# schema request — the default path since every calibration task declares tools)
# blocked the whole sequential run for up to an hour with zero output. 180s
# catches true hangs fast while leaving room for slow thinking models; a timeout
# surfaces as a failure_class (timeout), not a silent stall.
PER_CALL_TIMEOUT_S = 180

# Default scratch dir for tasks that write outputs (cells B/D).
SCRATCH_DIR = Path.home() / ".memory" / "benchmarks" / "routing" / "scratch"

# Default model list — current IDs after the 2026-07-01 resource-pool cleanup.
# Use ``--models`` to override; never edit the embedded list to "fix" a
# model name — that's a routing bug, not a profiler bug.
DEFAULT_MODELS = ",".join([
    "lmstudio_gemma4_12b",
    "lmstudio_google_gemma_4_26b_a4b",
    "lmstudio_qwen36_27b_mtp",
    "lmstudio_qwen36_31b_a3b_mtp",
    "lmstudio_ornith_35b_mtp_apex",
])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_tasks(cell: Optional[str] = None, max_per_cell: int = 15) -> List[Dict[str, Any]]:
    """Load routing benchmark tasks, optionally filtered by cell."""
    base = Path.home() / ".memory" / "benchmarks" / "routing" / "tasks"
    tasks: List[Dict[str, Any]] = []
    cells = [f"cell{cell}"] if cell else ["cellA", "cellB", "cellC", "cellD"]
    for c in cells:
        cell_dir = base / c
        if not cell_dir.exists():
            continue
        loaded = []
        for f in sorted(cell_dir.glob("*.json")):
            try:
                loaded.append(json.loads(f.read_text()))
            except Exception as e:
                print(f"  WARN: skipping {f}: {e}", file=sys.stderr)
        tasks.extend(loaded[:max_per_cell])
    return tasks


def load_resource(resource_id: str) -> Optional[Dict[str, Any]]:
    """Load a resource from the resource pool config."""
    pool_path = Path.home() / ".memory" / "config" / "resource_pool.json"
    if not pool_path.exists():
        return None
    pool = json.loads(pool_path.read_text())
    resource = pool.get("resources", {}).get(resource_id)
    if isinstance(resource, str):
        try:
            resource = json.loads(resource)
        except json.JSONDecodeError:
            return None
    return resource


def filter_models(all_models: List[str], model_filter: Optional[str]) -> List[str]:
    """Apply --model filter (substring match). Returns original list if unset."""
    if not model_filter:
        return all_models
    return [m for m in all_models if model_filter in m]


def clean_scratch_for_task(task: Dict[str, Any]) -> int:
    """Delete any scratch files referenced by this task's goal.

    Cell B/D tasks write to ``scratch/cellX_NNN.txt``; cleaning before the
    run prevents a previous attempt's answer from being read by the model.
    Returns the number of files removed.
    """
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    goal = task.get("goal", "")
    removed = 0
    # Match patterns like scratch/cellB_001.txt or ~/.memory/.../scratch/cellD_005.txt
    import re
    for match in re.finditer(r"scratch/(cell[A-D]_\d+\.\w+)", goal):
        target = SCRATCH_DIR / match.group(1)
        if target.exists():
            target.unlink()
            removed += 1
    return removed


def build_tool_schema(declared_tools: List[str]) -> List[Dict[str, Any]]:
    """Build a minimal OpenAI tools schema for the declared tool names.

    Real tool definitions are out of scope for the cell-calibration
    profiler (we measure model capability, not tool execution). The schema
    is just enough that the model knows what tools it could call; in
    practice the model answers directly because the tasks are designed
    for read/write/bash one-shots, not multi-turn tool use.
    """
    schema: Dict[str, Dict[str, Any]] = {
        "read_file": {"params": {"path": "string"}},
        "write_file": {"params": {"path": "string", "content": "string"}},
        "list_files": {"params": {"path": "string"}},
        "bash_exec": {"params": {"command": "string"}},
        "memory_search": {"params": {"query": "string"}},
    }
    out: List[Dict[str, Any]] = []
    for name in declared_tools:
        spec = schema.get(name, {"params": {}})
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": f"{name} tool (profiler stub — answers directly)",
                "parameters": {
                    "type": "object",
                    "properties": {k: {"type": v} for k, v in spec["params"].items()},
                    "required": list(spec["params"].keys()),
                },
            },
        })
    return out


def build_system_prompt(task: Dict[str, Any]) -> str:
    """Build the system prompt from the task's setup field."""
    setup = task.get("setup", "")
    base = "You are a helpful assistant. Answer concisely and accurately."
    if setup.startswith("role="):
        role_id = setup.split("=", 1)[1]
        role_path = Path.home() / ".memory" / "roles" / f"{role_id}.json"
        if role_path.exists():
            return base + f"\n\nRole config:\n{role_path.read_text()[:2000]}"
    if setup.startswith("file="):
        file_path = Path(setup.split("=", 1)[1]).expanduser()
        if not file_path.is_absolute():
            file_path = PROJECT_ROOT / file_path
        if file_path.exists():
            return base + f"\n\nFile content:\n{file_path.read_text()[:2000]}"
    if setup == "roles":
        roles_dir = Path.home() / ".memory" / "roles"
        summaries = []
        for f in sorted(roles_dir.glob("*.json"))[:20]:
            try:
                r = json.loads(f.read_text())
                summaries.append(f"{r.get('id','?')}: capabilities={r.get('capabilities',[])}")
            except Exception:
                pass
        return base + "\n\nRoles:\n" + "\n".join(summaries)
    return base


def check_answer(response_text: str, task: Dict[str, Any]) -> bool:
    """Verify the model's response against the task's correct_answer."""
    match_type = task.get("match_type", "contains")
    correct = task.get("correct_answer", "")
    if not response_text:
        return False
    if match_type == "exact":
        return bool(correct) and response_text.strip().lower() == correct.strip().lower()
    if match_type == "contains":
        return bool(correct) and correct.lower() in response_text.lower()
    if match_type == "structural":
        # Structural: the agent wrote *something* substantive. The profile
        # doesn't read the scratch file; this measures engagement, not
        # file-write correctness.
        return len(response_text.strip()) > 10
    return False


async def preload_model(resource_id: str) -> Dict[str, Any]:
    """Send a tiny chat-completion ping to force LMStudio to load the model.

    LMStudio loads models lazily on first request after a restart, which
    can take 30s+ on cold disk. Worse, cold-loaded "thinking" models
    burn their entire output budget on reasoning before producing content,
    poisoning the first real task. A10 runs many requests per model;
    preloading avoids that outlier.

    The ping uses a small output_limit (256 tokens) — large enough that
    reasoning doesn't eat everything, small enough to be cheap.
    """
    resource = load_resource(resource_id)
    if not resource:
        return {"resource_id": resource_id, "ok": False,
                "error": f"Resource '{resource_id}' not found", "elapsed_s": 0.0}

    from app.llm.unified_client import UnifiedLLMClient
    client = UnifiedLLMClient()

    resource_config = {
        "base_url": resource.get("base_url", ""),
        "model": resource.get("model", ""),
        "api_key": resource.get("api_key", ""),
        "output_limit": 256,
        "message_format": "openai",
        "provider": resource.get("provider", ""),
        "timeout": PER_CALL_TIMEOUT_S,
    }

    start = time.time()
    result = {
        "resource_id": resource_id,
        "model": resource.get("model", ""),
        "ok": False,
        "elapsed_s": 0.0,
        "error": None,
        "response": "",
    }
    try:
        data = await client.call_async(
            messages=[
                {"role": "system", "content": "You must answer the user. Be concise."},
                {"role": "user", "content": "Reply with a single word: ready."},
            ],
            resource_config=resource_config,
            model_override=resource.get("model"),
        )
        choices = data.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "") or ""
            result["response"] = content
            # An empty content + length-stop is the cold-load signature.
            finish = choices[0].get("finish_reason", "")
            if not content and finish == "length":
                result["error"] = "hit output_limit on reasoning — likely cold-loaded"
            else:
                result["ok"] = True
        else:
            result["error"] = "no choices in response"
    except Exception as e:
        result["error"] = str(e)
    result["elapsed_s"] = round(time.time() - start, 2)
    return result


# ---------------------------------------------------------------------------
# Per-task execution with budget-aware iteration
# ---------------------------------------------------------------------------

async def run_task_with_model(
    task: Dict[str, Any],
    resource_id: str,
    budget: int,
    max_duration_s: float,
) -> Dict[str, Any]:
    """Run a single task against a specific model under the cell's budget.

    Loop shape (A11.2 — replaces the A9 single-shot shape):

        for it in range(budget):
            call LLM with current messages + tool schema
            if response.tool_calls:
                execute each call via ProfilerExecutionContext
                append assistant msg + tool-result msgs to messages
                continue  # re-prompt with tool results
            else:
                # No tool calls — model gave a final answer
                check_answer(response.content, task)
                break

    Budget is consumed by every LLM call (not by tool calls). The loop
    exits when: the model gives a final answer (pass or fail); the
    budget runs out; the wall-clock cap fires; or an unrecoverable
    error occurs.

    Deviation from spec: spec says "dispatch through agentic_executor".
    Real agentic execution drags memory/lessons/policy into the loop.
    For cell calibration (which measures model capability, not
    orchestration), a budgeted tool-call loop is the right
    abstraction. See module docstring. A11.1 added the sandboxed
    tool executor; A11.2 wires the loop.
    """
    from app.llm.unified_client import UnifiedLLMClient
    from app.scheduler.evals.models import classify_failure
    from profiler_tool_executor import ProfilerExecutionContext

    task_id = task["id"]
    cell = task.get("cell", "?")
    goal = task["goal"]
    declared_tools = task.get("declared_tools", [])

    start = time.time()
    result: Dict[str, Any] = {
        "task_id": task_id,
        "cell": cell,
        "resource_id": resource_id,
        "success": False,
        "response": "",
        "iterations": 0,
        "elapsed_s": 0.0,
        "tokens_prompt": 0,
        "tokens_completion": 0,
        "tokens_total": 0,
        "error": None,
        "failure_class": None,
        "declared_tools": declared_tools,
        "budget": budget,
        # A11.3 hooks — these feed the new profile schema.
        "tool_call_count": 0,
        "tool_error_count": 0,
        "tool_calls_log": [],
    }

    try:
        resource = load_resource(resource_id)
        if not resource:
            result["error"] = f"Resource '{resource_id}' not found"
            result["elapsed_s"] = round(time.time() - start, 2)
            return result

        client = UnifiedLLMClient()
        system_prompt = build_system_prompt(task)
        tools_schema = build_tool_schema(declared_tools) if declared_tools else None

        resource_config = {
            "base_url": resource.get("base_url", ""),
            "model": resource.get("model", ""),
            "api_key": resource.get("api_key", ""),
            "output_limit": min(resource.get("output_limit", 8192), 8192),
            "message_format": "openai",
            "provider": resource.get("provider", ""),
            "timeout": PER_CALL_TIMEOUT_S,  # real per-call cap — see PER_CALL_TIMEOUT_S
        }

        # Sandboxed tool dispatcher (A11.1).
        tool_ctx = ProfilerExecutionContext(task=task)

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": goal},
        ]

        last_error: Optional[str] = None
        timed_out = False
        response_text = ""

        for it in range(1, budget + 1):
            if time.time() - start > max_duration_s:
                timed_out = True
                last_error = f"max_duration_s exceeded ({max_duration_s}s)"
                break

            try:
                data = await client.call_async(
                    messages=messages,
                    resource_config=resource_config,
                    model_override=resource.get("model"),
                    tools=tools_schema,
                )
            except Exception as e:
                last_error = f"LLM call failed: {e}"
                break

            result["iterations"] = it
            usage = data.get("usage", {}) or {}
            # Sum across iterations: each call is billed for its full (growing)
            # prompt, so the total reflects real task cost — what Bonsai budget
            # calibration needs. max() would understate multi-retry tasks.
            result["tokens_prompt"] += usage.get("prompt_tokens", 0)
            result["tokens_completion"] += usage.get("completion_tokens", 0)
            result["tokens_total"] += usage.get("total_tokens", 0)

            choices = data.get("choices", [])
            if not choices:
                last_error = "no choices in response"
                break

            choice = choices[0]
            assistant_msg = choice.get("message", {}) or {}
            response_text = assistant_msg.get("content", "") or ""
            tool_calls = assistant_msg.get("tool_calls") or []
            previous_answer = response_text
            result["response"] = response_text

            # ---- Tool-call branch: execute, append, continue ----
            if tool_calls:
                # Record this assistant turn (carries the tool_calls).
                # Some providers require content=null when tool_calls present;
                # we preserve whatever the provider returned.
                messages.append(assistant_msg)

                # Execute each tool call serially. The dispatcher is sync,
                # so wrap in to_thread — file I/O is small but bash_exec
                # can take up to 10s and we don't want to block the loop.
                for tc in tool_calls:
                    tc_id = tc.get("id", "")
                    fn = tc.get("function", {}) or {}
                    fn_name = fn.get("name", "")
                    fn_args = fn.get("arguments", "")
                    try:
                        tool_result = await asyncio.to_thread(
                            tool_ctx.execute, fn_name, fn_args
                        )
                    except Exception as e:
                        # The dispatcher shouldn't raise, but guard anyway.
                        from profiler_tool_executor import ToolResult
                        tool_result = ToolResult(
                            tool=fn_name, args={}, ok=False,
                            error=f"dispatcher exception: {e}",
                        )

                    result["tool_call_count"] += 1
                    if not tool_result.ok:
                        result["tool_error_count"] += 1
                    result["tool_calls_log"].append({
                        "iteration": it,
                        "tool": tool_result.tool,
                        "args": tool_result.args,
                        "ok": tool_result.ok,
                        "error": tool_result.error,
                        "elapsed_s": tool_result.elapsed_s,
                    })

                    # OpenAI tool result message — the model's next call
                    # will see this. Embed the full payload (ok/error/content)
                    # so the model can react if a tool failed.
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": json.dumps(tool_result.to_message()),
                    })

                # Loop continues — next iteration sees the tool results.
                continue

            # ---- Final-answer branch: no tool_calls, check and exit ----
            if check_answer(response_text, task):
                result["success"] = True
                break

            # ---- Verification-mismatch: craft retry feedback ----
            # This is the same retry-with-feedback pattern from A9,
            # preserved for tasks that don't use tools. The model got
            # the goal, produced prose, and the prose doesn't verify —
            # give it a hint and let it try again within the budget.
            match_type = task.get("match_type", "contains")
            correct = task.get("correct_answer", "")
            if match_type == "exact" and correct:
                feedback = f"Your answer does not exactly match the expected value '{correct}'. Re-state it precisely."
            elif match_type == "contains" and correct:
                feedback = f"Your answer must include the exact substring '{correct}'. Search the source file again and quote the value verbatim."
            elif match_type == "structural":
                feedback = "Provide a substantive answer (at least a few words) addressing the question."
            else:
                feedback = "Re-examine the source and answer the question directly."
            messages.append({"role": "user", "content": feedback})

    except Exception as e:
        last_error = f"runner exception: {e}"

    # If the deadline fired after a response arrived, give that response
    # one final check — a slow-but-correct model shouldn't be mis-classified.
    if timed_out and result["response"] and not result["success"]:
        if check_answer(result["response"], task):
            result["success"] = True

    # Only surface an error string if we have no usable response.
    if last_error and not result["response"]:
        result["error"] = last_error

    result["elapsed_s"] = round(time.time() - start, 2)
    # A7 — classify the failure (or clean-pass signal).
    fc = classify_failure(
        success=result["success"],
        elapsed_s=result["elapsed_s"],
        error=result["error"],
        response=result["response"],
        iterations=result["iterations"],
    )
    result["failure_class"] = fc.value if fc is not None else None
    return result


# ---------------------------------------------------------------------------
# Run orchestration + artifact writing + resume
# ---------------------------------------------------------------------------

def _read_progress(progress_path: Path) -> Dict[str, Any]:
    if progress_path.exists():
        try:
            return json.loads(progress_path.read_text())
        except Exception:
            pass
    return {"completed": [], "models": [], "run_id": None}


def _find_resumable_run(
    runs_root: Path,
    models: List[str],
    cell: Optional[str],
    tasks_per_cell: int,
    model_filter: Optional[str] = None,
) -> Optional[str]:
    """Find the most recent run that matches these filters AND still has
    un-completed (model, task) pairs.

    Returns the run_id, or None to indicate "no resumable run; create new".
    """
    if not runs_root.exists():
        return None
    # Sort newest first so the latest incomplete run wins.
    for run_dir in sorted(runs_root.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        progress_path = run_dir / "progress.json"
        if not progress_path.exists():
            continue
        try:
            state = json.loads(progress_path.read_text())
        except Exception:
            continue
        # Filter compatibility: same models set, same cell, same tasks_per_cell.
        prev_models = set(state.get("models", []))
        # Compare against post-filter models (the actual set the runner will
        # iterate). Without this, an invocation without --model would
        # mismatch the prior run's filtered set and skip resume.
        if prev_models != set(models):
            continue
        if state.get("cell_filter") != cell:
            continue
        if state.get("model_filter") != model_filter:
            continue
        if state.get("tasks_per_cell") != tasks_per_cell:
            continue
        # Is there an un-completed (model, task) pair?
        completed = set(state.get("completed", []))
        # Determine tasks the run *would* attempt.
        task_ids = [t["id"] for t in load_tasks(cell=cell, max_per_cell=tasks_per_cell)]
        all_pairs = {f"{m}|{tid}" for m in models for tid in task_ids}
        if all_pairs - completed:
            return run_dir.name
    return None


def _find_all_done_run(
    runs_root: Path,
    models: List[str],
    cell: Optional[str],
    tasks_per_cell: int,
    model_filter: Optional[str] = None,
) -> Optional[str]:
    """Like _find_resumable_run but for runs whose (model, task) pairs are
    ALL completed. Returns the run_id, or None.
    """
    if not runs_root.exists():
        return None
    for run_dir in sorted(runs_root.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        progress_path = run_dir / "progress.json"
        if not progress_path.exists():
            continue
        try:
            state = json.loads(progress_path.read_text())
        except Exception:
            continue
        prev_models = set(state.get("models", []))
        if prev_models != set(models):
            continue
        if state.get("cell_filter") != cell:
            continue
        if state.get("model_filter") != model_filter:
            continue
        if state.get("tasks_per_cell") != tasks_per_cell:
            continue
        completed = set(state.get("completed", []))
        task_ids = [t["id"] for t in load_tasks(cell=cell, max_per_cell=tasks_per_cell)]
        all_pairs = {f"{m}|{tid}" for m in models for tid in task_ids}
        if all_pairs and all_pairs <= completed:
            return run_dir.name
    return None


def _write_progress(progress_path: Path, state: Dict[str, Any]) -> None:
    progress_path.write_text(json.dumps(state, indent=2))


def _write_task_json(tasks_dir: Path, model_id: str, result: Dict[str, Any]) -> Path:
    """Write per-task result JSON. Returns the path."""
    fname = f"{result['task_id']}_{model_id}.json"
    p = tasks_dir / fname
    p.write_text(json.dumps(result, indent=2))
    return p


def _write_tsv_row(tsv_path: Path, result: Dict[str, Any], header: bool = False) -> None:
    cols = [
        "task_id", "cell", "resource_id", "success", "iterations", "elapsed_s",
        "tokens_prompt", "tokens_completion", "tokens_total",
        "failure_class", "budget",
    ]
    if header:
        tsv_path.write_text("\t".join(cols) + "\n")
        return
    row = "\t".join(str(result.get(c, "")) for c in cols) + "\n"
    with tsv_path.open("a") as f:
        f.write(row)


async def run_profiler(
    models: List[str],
    cell: Optional[str] = None,
    tasks_per_cell: int = 5,
    model_filter: Optional[str] = None,
    max_duration_s: float = 300.0,
    resume_run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run profiling across models and cells. Resumes from progress.json.

    Resume semantics:
      - ``resume_run_id`` explicit → resume that run.
      - Otherwise → look for the latest run dir whose progress.json has
        filters matching this invocation AND that still has un-completed
        (model, task) pairs; if found, resume it.
      - Otherwise → create a new run dir with a fresh timestamp.

    The verify-by clause from A9 is satisfied by the auto-resume path:
    re-invoking the same command picks up where the previous run stopped.
    """
    models = filter_models(models, model_filter)
    if not models:
        print("No models after filtering!")
        return {}

    tasks = load_tasks(cell=cell, max_per_cell=tasks_per_cell)
    if not tasks:
        print("No tasks found!")
        return {}

    runs_root = Path.home() / ".memory" / "benchmarks" / "routing" / "runs"

    # Resolve run_id: explicit resume, else auto-resume, else fresh.
    run_id: Optional[str] = None
    if resume_run_id:
        run_id = resume_run_id
    else:
        run_id = _find_resumable_run(runs_root, models, cell, tasks_per_cell, model_filter)
        if run_id:
            print(f"Auto-resuming previous run: {run_id}")

    # If we have a candidate run, also check whether *all* (model, task)
    # pairs are already done. If so, report and exit (no work to do).
    # This catches the "everything's done" case before _find_resumable_run
    # rejects the run for "no pending work".
    if run_id:
        cand_state = _read_progress(runs_root / run_id / "progress.json")
        completed = set(cand_state.get("completed", []))
        task_ids = [t["id"] for t in tasks]
        all_pairs = {f"{m}|{tid}" for m in models for tid in task_ids}
        if all_pairs and all_pairs <= completed:
            print(f"Run {run_id} already has all {len(all_pairs)} "
                  f"(model, task) pairs completed. Nothing to do.")
            print("Pass a different --cell / --tasks-per-cell / --model, "
                  "or --resume <run_id> to inspect an existing run.")
            return {"run_id": run_id, "no_op": True}

    # Also check whether an *all-done* run exists with matching filters —
    # if so, surface that even if _find_resumable_run returned None.
    if not run_id:
        done_run = _find_all_done_run(runs_root, models, cell, tasks_per_cell, model_filter)
        if done_run:
            print(f"Run {done_run} already has all matching (model, task) pairs completed. Nothing to do.")
            return {"run_id": done_run, "no_op": True}

    if not run_id:
        run_id = f"profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    run_dir = runs_root / run_id
    tasks_dir = run_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    progress_path = run_dir / "progress.json"
    tsv_path = run_dir / "results.tsv"
    state = _read_progress(progress_path)
    state["run_id"] = run_id
    state["models"] = models
    if cell:
        state["cell_filter"] = cell
    if model_filter:
        state["model_filter"] = model_filter
    state["tasks_per_cell"] = tasks_per_cell

    print(f"Routing profiler: {run_id}")
    print(f"Models: {models}")
    print(f"Tasks: {len(tasks)} ({tasks_per_cell}/cell)")
    print(f"Budgets: {CELL_BUDGETS}")
    print()

    # Initialize TSV header on first run.
    if not tsv_path.exists():
        _write_tsv_row(tsv_path, {}, header=True)

    raw_records: List[TaskRecord] = []
    completed_keys = set(state.get("completed", []))

    for model_id in models:
        print(f"=== {model_id} ===")
        for task in tasks:
            key = f"{model_id}|{task['id']}"
            if key in completed_keys:
                print(f"  [skip] {task['id']} (Cell {task.get('cell','?')}) — already done")
                continue

            cell_letter = task.get("cell", "?")
            budget = CELL_BUDGETS.get(cell_letter, 4)
            cleaned = clean_scratch_for_task(task)
            print(f"  {task['id']} (Cell {cell_letter}, budget={budget})"
                  + (f" [scratch cleaned: {cleaned}]" if cleaned else "")
                  + f": {task['goal'][:50]}...",
                  end=" ", flush=True)

            result = await run_task_with_model(task, model_id, budget, max_duration_s)
            _write_task_json(tasks_dir, model_id, result)
            _write_tsv_row(tsv_path, result)

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

            completed_keys.add(key)
            state["completed"] = sorted(completed_keys)
            _write_progress(progress_path, state)

            status = "✓" if result["success"] else "✗"
            fc = result["failure_class"] or "clean"
            print(f"{status} ({result['elapsed_s']:.1f}s, iter={result['iterations']}, {fc})")

    # Aggregate into v2 profile schema (pass, failure_modes, avg_duration, ...).
    # Combine new records with any prior in the same run dir.
    for prior in tasks_dir.glob("*.json"):
        try:
            d = json.loads(prior.read_text())
            # Only add if not already in raw_records (idempotent resume).
            key = (d["resource_id"], d["task_id"])
            if not any((r.resource_id, r.task_id) == key for r in raw_records):
                raw_records.append(TaskRecord(
                    task_id=d["task_id"], cell=d["cell"], resource_id=d["resource_id"],
                    success=d["success"], elapsed_s=d["elapsed_s"],
                    iterations=d["iterations"], error=d.get("error"),
                    response=d.get("response", ""),
                    failure_class=d.get("failure_class"),
                ))
        except Exception:
            pass

    profile = aggregate_profile(raw_records)
    for model_id, by_cell in profile.items():
        for c, stats in sorted(by_cell.items()):
            fm = stats.get("failure_modes") or {}
            fm_str = ",".join(f"{k}={v}" for k, v in sorted(fm.items())) or "-"
            print(f"  {model_id} Cell {c}: pass={stats['pass']:.3f} "
                  f"({stats['success']}/{stats['total']}) modes=[{fm_str}] "
                  f"avg_dur={stats['avg_duration']:.1f}s")

    # Derive routing_table.json from the profile.
    routing_table = derive_routing_table(profile, candidate_order=list(models))
    print("\nDerived routing table:")
    for c, model_id in routing_table.items():
        if c.startswith("_"):
            continue
        print(f"  {c} -> {model_id or '(none qualified)'}")

    # Save summary (includes per-task + aggregated profile).
    summary = {
        "run_id": run_id,
        "models": models,
        "cell_filter": cell,
        "model_filter": model_filter,
        "tasks_per_cell": tasks_per_cell,
        "budgets": CELL_BUDGETS,
        "max_duration_s": max_duration_s,
        "profile": profile,
        "per_task_dir": str(tasks_dir),
        "routing_table": {k: v for k, v in routing_table.items() if not k.startswith("_")},
        "cell_decisions": routing_table.get("_cell_decisions", {}),
        "thresholds": routing_table.get("_thresholds", {}),
        "timestamp": datetime.now().isoformat(),
        "completed": sorted(completed_keys),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    # Persist derived routing_table.json + capability_profile.json live.
    routing_path = Path.home() / ".memory" / "benchmarks" / "routing" / "routing_table.json"
    routing_path.write_text(json.dumps(
        {k: v for k, v in routing_table.items() if not k.startswith("_")}, indent=2,
    ))
    profile_path = Path.home() / ".memory" / "benchmarks" / "routing" / "capability_profile.json"
    profile_path.write_text(json.dumps(profile, indent=2))
    print(f"\nWrote: {run_dir}/summary.json")
    print(f"      {run_dir}/results.tsv ({len(completed_keys)} rows)")
    print(f"      {run_dir}/tasks/*.json ({len(list(tasks_dir.glob('*.json')))} files)")
    print(f"      {routing_path}")
    print(f"      {profile_path}")

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Run routing profiler — A9 incremental, resumable.",
    )
    parser.add_argument("--models", default=DEFAULT_MODELS,
                        help="Comma-separated model IDs (substring match for --model filter).")
    parser.add_argument("--model", default=None,
                        help="Substring filter for --models (e.g. 'ornith' or 'qwen36').")
    parser.add_argument("--cell", choices=["A", "B", "C", "D"], default=None,
                        help="Run only the specified cell.")
    parser.add_argument("--tasks-per-cell", "--limit", dest="tasks_per_cell",
                        type=int, default=5,
                        help="Max tasks per cell (default 5 — never run the full 60 by default).")
    parser.add_argument("--max-duration-s", type=float, default=300.0,
                        help="Per-task wall-clock cap (default 300s).")
    parser.add_argument("--resume", default=None,
                        help="Resume a specific run_id (default: auto-detect latest incomplete matching run).")
    parser.add_argument("--preload", action="store_true",
                        help="Send a tiny ping to each model before the run, "
                             "so LMStudio has time to load weights off disk "
                             "after a restart. Reports cold/warm timing. "
                             "Use before A10 to avoid poisoning the first "
                             "task's profile slice with a 30s+ outlier.")
    parser.add_argument("--preload-only", action="store_true",
                        help="Just preload, don't run the profiler. "
                             "Useful as a stand-alone 'warm the cache' step.")
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    models = filter_models(models, args.model)

    if args.preload or args.preload_only:
        asyncio.run(_preload_all(models))
        if args.preload_only:
            return

    asyncio.run(run_profiler(
        models=models,
        cell=args.cell,
        tasks_per_cell=args.tasks_per_cell,
        model_filter=args.model,
        max_duration_s=args.max_duration_s,
        resume_run_id=args.resume,
    ))


async def _preload_all(models: List[str]) -> None:
    """Run preload ping against each model, sequentially, with timing.

    Designed for the "just restarted LMStudio" workflow. The first ping
    forces weight load from disk (cold); subsequent pings to the same
    model hit the warm cache. Per the A10 spec we never parallel-blast
    the GPU, so this is one model at a time.
    """
    print(f"Preloading {len(models)} model(s) — sequential, one at a time.")
    print(f"(Use --preload-only to skip the actual profiler run.)")
    print()
    results = []
    for m in models:
        print(f"  → {m} ...", end=" ", flush=True)
        r = await preload_model(m)
        results.append(r)
        status = "OK" if r["ok"] else f"FAIL ({r.get('error')})"
        print(f"{r['elapsed_s']:.1f}s — {status} — {r.get('response','')[:40]!r}")
    print()
    print("Preload summary:")
    for r in results:
        marker = "✓" if r["ok"] else "✗"
        print(f"  {marker} {r['resource_id']:50} {r['elapsed_s']:>7.1f}s   model={r['model']}")
    cold = [r for r in results if r["ok"] and r["elapsed_s"] > 30]
    if cold:
        print(f"\n{len(cold)} model(s) took >30s — likely cold-loaded from disk.")
        print("Consider running --preload a second time before A10 so the profile")
        print("doesn't record cold-load latency as model slowness.")


if __name__ == "__main__":
    main()