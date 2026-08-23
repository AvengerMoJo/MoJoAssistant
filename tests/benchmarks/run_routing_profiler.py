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
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
# This module's own directory must also be on sys.path for the bare
# `from profiler_tool_executor import ...` below to resolve. Running the
# script directly (`python tests/benchmarks/run_routing_profiler.py`) gets
# this for free (Python adds the script's own dir to sys.path[0]), but the
# docstring's documented `-m tests.benchmarks.run_routing_profiler` form
# does not — sys.path[0] is the invoking cwd in that case, not this
# directory, so the import used to raise ModuleNotFoundError.
sys.path.insert(0, str(Path(__file__).parent))

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

# Seconds to allow per LLM round-trip when deriving a per-cell wall-clock
# cap from CELL_BUDGETS (see _effective_max_duration_s). Real observed
# per-call latency across every model profiled this project ranges ~10s
# (fast, simple cell-A answers) to ~100s (slower models on multi-step cell
# C/D tasks with tool calls) -- 75s is a deliberately generous middle
# ground so the cap isn't the thing cutting a call short.
SECONDS_PER_ITERATION_BUDGET = 75.0

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


def _lms_ps_loaded_model_keys() -> Optional[set]:
    """Query `lms ps --json` for model identifiers currently resident in
    LMStudio's VRAM. Returns None (never an empty set) on any failure --
    the caller must not mistake "couldn't check" for "nothing is loaded"
    and skip every model.
    """
    import subprocess
    try:
        proc = subprocess.run(
            ["lms", "ps", "--json"], capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return None
        loaded = json.loads(proc.stdout)
    except Exception:
        return None
    keys: set = set()
    for entry in loaded if isinstance(loaded, list) else []:
        if isinstance(entry, dict):
            for field_name in ("identifier", "modelKey", "path"):
                v = entry.get(field_name)
                if v:
                    keys.add(v)
    return keys


def validate_models_loaded(models: List[str]) -> List[str]:
    """Drop any local-resource model that isn't actually loaded in LMStudio
    right now, instead of silently sending it requests.

    Bug found live 2026-08-23: the profiler resolved a model's base_url/model
    straight from resource_pool.json and fired requests at it with no check
    that LMStudio actually has those weights resident. An unloaded local
    model either 400s immediately or JIT-loads mid-run -- either way the
    result reflects LMStudio's load state at that moment, not the model's
    capability, which is exactly the class of framework artifact this
    harness exists to eliminate (see build_system_prompt's docstring for a
    prior instance of the same failure mode, with context truncation).
    """
    loaded_keys = _lms_ps_loaded_model_keys()
    if loaded_keys is None:
        print("WARNING: could not query `lms ps` -- skipping loaded-model "
              "validation. If a model below isn't actually loaded, its "
              "results may be skewed by JIT-load cold-start.")
        return models

    validated = []
    for model_id in models:
        resource = load_resource(model_id)
        if resource is None:
            print(f"  SKIP {model_id}: no resource_pool.json entry")
            continue
        if resource.get("type") != "local":
            validated.append(model_id)  # API resources have no load state
            continue
        model_key = resource.get("model", "")
        if model_key in loaded_keys:
            validated.append(model_id)
        else:
            print(f"  SKIP {model_id}: not loaded in LMStudio "
                  f"(model='{model_key}') -- run `lms load {model_key}` first")
    return validated


def _effective_max_duration_s(cell: str, requested_max_duration_s: float) -> float:
    """Scale the wall-clock cap to the cell's own iteration budget.

    Bug found live 2026-08-17: max_duration_s was a single flat value
    (default 300s) applied identically to every cell, independent of how
    many iterations that cell's budget actually allows. Cell D's budget
    is 12, but at REAL observed per-call latency (27-66s for a model that
    was otherwise scoring 100% on cells A-C) even a model making steady,
    correct progress needs 5-11 iterations and 300-800+ seconds to use
    that budget -- the 300s cap was cutting it off mid-task, misclassified
    as "executor_exception" (see the classify_failure fix below) rather
    than genuine incapability. This was very likely the dominant reason
    cell D scored near-0% across every model profiled all project,
    predating this specific fix pass.

    Takes the LARGER of the caller's requested value and a budget-derived
    floor, so an explicit --max-duration-s override for a fast smoke-test
    run is never shrunk, but a cell whose budget implies more real time is
    needed gets that time instead of being silently truncated.
    """
    budget = CELL_BUDGETS.get(cell, 4)
    return max(requested_max_duration_s, budget * SECONDS_PER_ITERATION_BUDGET)


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
    """Build the system prompt from the task's setup field.

    Injected file/role content is NOT truncated. Every model in the pool
    has a 262144-token context window (~1M+ chars) -- config/role files
    here top out around 12KB, i.e. under 0.3% of that budget. A prior
    hardcoded [:2000] char cap silently dropped 80%+ of larger files
    (e.g. resource_pool.json at ~12KB) from context, forcing "single
    read_file lookup, low breadth" cell-A/C tasks into unguided
    multi-file-path-guessing that had nothing to do with the model's real
    capability. Found 2026-08-15 auditing why qwen3.8-27b only scored 60%
    on cell A. Affected 10/15 cell-A and most resource_pool.json-based
    cell-C tasks, across all 34 historical profiler runs since this tool's
    first commit (2026-07-09) -- every prior capability_profile.json for
    every model is suspect for those specific tasks.
    """
    setup = task.get("setup", "")
    base = "You are a helpful assistant. Answer concisely and accurately."
    if setup.startswith("role="):
        role_id = setup.split("=", 1)[1]
        role_path = Path.home() / ".memory" / "roles" / f"{role_id}.json"
        if role_path.exists():
            return base + f"\n\nRole config:\n{role_path.read_text()}"
    if setup.startswith("file="):
        file_path = Path(setup.split("=", 1)[1]).expanduser()
        if not file_path.is_absolute():
            file_path = PROJECT_ROOT / file_path
        if file_path.exists():
            return base + f"\n\nFile content:\n{file_path.read_text()}"
    if setup == "roles":
        roles_dir = Path.home() / ".memory" / "roles"
        summaries = []
        # No [:20] cap -- was silently dropping roles once the count grew
        # past 20 (17 live as of 2026-08-16, i.e. already close), same
        # truncation-without-warning class as the other caps fixed this
        # session.
        for f in sorted(roles_dir.glob("*.json")):
            try:
                r = json.loads(f.read_text())
                # Bug found live 2026-08-16 on cellC_005: this summary only
                # ever included id+capabilities. Several tasks ask about
                # executor/agent_type/nine_chapter_score, none of which were
                # in context -- forcing the model to go hunting for a
                # source file, and since roles are stored one-per-file
                # (~/.memory/roles/<id>.json), not a single combined
                # "roles.json", it burned its whole budget guessing
                # nonexistent combined-file paths and never found one.
                # system_prompt deliberately excluded: too verbose to
                # summarize for every role, and the one task that needs it
                # (cellD_001, full-text word count) needs the real file
                # regardless of any summary.
                summaries.append(
                    f"{r.get('id','?')}: capabilities={r.get('capabilities',[])} "
                    f"executor={r.get('executor')} agent_type={r.get('agent_type')} "
                    f"nine_chapter_score={r.get('nine_chapter_score')} "
                    f"max_iterations={r.get('max_iterations')}"
                )
            except Exception:
                pass
        return (
            base + "\n\nRoles (individual files at ~/.memory/roles/<id>.json "
            "if you need a field not shown here, e.g. system_prompt):\n"
            + "\n".join(summaries)
        )
    if setup.startswith("dir="):
        # Bug found live 2026-08-16: this branch didn't exist at all, so
        # every "dir=..." task (cellC_004, cellC_014, cellD_015) got ZERO
        # grounding -- just the bare base prompt. A model with no idea
        # where it even is has to blind-discover the filesystem from
        # scratch: confirmed live on cellD_015, a model burned its entire
        # 12-call budget on `pwd`, `find / -maxdepth 3 -type d -name
        # config`, and scanning unrelated project directories before ever
        # reaching the actual question. Fix: inject the resolved absolute
        # path plus a directory listing, mirroring what "file=" already
        # does for single files.
        dir_path = Path(setup.split("=", 1)[1]).expanduser()
        if not dir_path.is_absolute():
            dir_path = PROJECT_ROOT / dir_path
        if dir_path.exists() and dir_path.is_dir():
            entries = sorted(p.name + ("/" if p.is_dir() else "") for p in dir_path.iterdir())
            return (
                base
                + f"\n\nDirectory: {dir_path}\nContents:\n" + "\n".join(entries)
            )
    return base


def _extract_scratch_target(task: Dict[str, Any]) -> Optional[Path]:
    """Extract the scratch file a task's goal instructs the model to write to.

    Cell B/D tasks reference ``scratch/cellX_NNN.ext`` in their goal text
    (the same pattern ``clean_scratch_for_task`` matches to clear stale
    answers before a run). Cell A/C tasks never mention scratch — they're
    answered directly in chat — so this returns None for them, which is
    the signal ``check_answer`` uses to fall back to text matching.
    """
    goal = task.get("goal", "")
    m = re.search(r"scratch/(cell[A-D]_\d+\.\w+)", goal)
    if not m:
        return None
    return SCRATCH_DIR / m.group(1)


def check_answer(
    response_text: str,
    task: Dict[str, Any],
    scratch_target: Optional[Path] = None,
) -> bool:
    """Verify the model's answer against the task's correct_answer.

    Bug found live 2026-07-19 (see ~/.memory/research/
    routing_harness_verification_flaw_2607.md): for any task whose goal
    says "write the answer to a scratch file that a verifier checks
    byte-for-byte", this function used to check the model's CHAT PROSE
    instead — the file was never read. A model could describe the right
    answer without ever writing it, or (worse, combined with the feedback
    leak this same incident fixed in run_task_with_model) simply parrot
    a hinted string back in a sentence explicitly REFUSING the task and
    still score a pass. Confirmed false positives: MiniMax M3 on
    cellD_001/cellD_004 (paid), two local models on cellC_005 — all
    scored "success" with zero tool calls, by quoting a value they never
    verified.

    Fix: when ``scratch_target`` is given (task goal references a scratch
    file), read THAT file and verify its content — the actual deliverable,
    not what the model said about it. Falls back to response_text only for
    cell A/C tasks, which have no file to check by design (chat-answer-only).

    Bug found live 2026-08-16: several tasks ask about live, mutable
    system state (resource_pool.json contents, config/ directory
    contents, role configs). A frozen ``correct_answer`` snapshot of that
    state goes stale the instant it changes -- which happens routinely --
    failing even a model that computed the true current answer correctly.
    When a task carries ``correct_answer_fn``, the expected value is
    computed fresh right now via dynamic_answers.resolve_dynamic_answer()
    instead of read from the frozen JSON field, so the check is correct
    at any point in time. Falls back to the static correct_answer if the
    function is unknown or the live computation fails for any reason.
    """
    match_type = task.get("match_type", "contains")
    correct = task.get("correct_answer", "")
    correct_answer_fn = task.get("correct_answer_fn")
    if correct_answer_fn:
        from dynamic_answers import resolve_dynamic_answer
        dynamic = resolve_dynamic_answer(correct_answer_fn)
        if dynamic is not None:
            correct = dynamic
    # structural tasks have no correct_answer by design (see below); only
    # exact/contains require one to have anything to check against.
    if not correct and match_type != "structural":
        return False

    text_to_check = response_text
    if scratch_target is not None:
        # The task's own deliverable is the file. Don't fall back to prose
        # if the file is missing — that means the model never wrote it,
        # which is a fail regardless of what it claimed in chat.
        if not scratch_target.exists():
            return False
        try:
            text_to_check = scratch_target.read_text(errors="replace")
        except Exception:
            return False

    if not text_to_check:
        return False
    if match_type == "exact":
        stripped_response = text_to_check.strip().lower()
        stripped_correct = correct.strip().lower()
        if stripped_response == stripped_correct:
            return True
        # Bug found live 2026-08-17 on cellD_015 ("count total lines"):
        # `wc -l` (what a model naturally reaches for via bash_exec) and
        # Python's `str.splitlines()` (what dynamic_answers.py uses to
        # compute the expected value) disagree by one line per file
        # lacking a trailing newline -- a real, defensible ambiguity in
        # what "line count" means, not a wrong answer. A model that
        # traced the exact right files and used a reasonable counting
        # method shouldn't fail sheer method choice. Only applies when a
        # task opts in via "numeric_tolerance" -- exact tasks without it
        # keep the strict byte-for-byte bar unchanged.
        tolerance = task.get("numeric_tolerance")
        if tolerance is not None:
            try:
                response_num = float(stripped_response)
                correct_num = float(stripped_correct)
                return abs(response_num - correct_num) <= tolerance
            except ValueError:
                pass
        return False
    if match_type in ("contains", "structural") and correct:
        # List-shaped correct_answer (comma-joined, cellA/C multi-item tasks):
        # check each item independently rather than requiring the exact
        # joined string. Found live 2026-07-19 re-verifying this fix: models
        # that correctly listed every item as a bullet/numbered list (instead
        # of the literal "a,b,c" the answer key uses) failed the single-
        # substring check even though the content was fully correct — e.g.
        # gemma4_12b and ornith both listed all 15 correct role IDs on
        # cellC_002 as "1. **ahman** ...", which doesn't contain the literal
        # substring "ahman,anna,bao,...". Per-item checking still requires
        # EVERY item present, so a genuinely incomplete list (confirmed
        # separately: qwen36_31b_a3b_mtp dropped 6 of 23 files on cellC_004)
        # still correctly fails — this only tolerates formatting, not gaps.
        #
        # ``structural`` tasks share this path when correct_answer is set:
        # found live the same day, re-verifying cellB_002 ("36"). structural
        # was designed for tasks with no fixed answer (prose-length is the
        # only signal) — but some structural tasks DO carry a real
        # correct_answer, and a short-but-exact value ("36", 2 chars) will
        # always fail a length>10 bar once that bar is checked against file
        # content instead of verbose chat prose. If a correct_answer exists,
        # checking it beats a length heuristic regardless of match_type label.
        # Bug found live 2026-08-15 auditing why every model ever profiled
        # scored suspiciously close to 0% on cell D: this only ever split
        # on ",". Several task authors used ";" as the top-level separator
        # for multi-entity answers (e.g. "id=v1,v2;id=v2,v3" — role→
        # capability-list pairs, joined by role) either alone or mixed with
        # "," inside each entity's value list. A "," in the answer sent
        # THOSE straight to the whole-blob check below, which requires the
        # model to reproduce the entire semicolon-joined answer key
        # verbatim as one substring — unwinnable by any model, correct or
        # not. Affected 12 tasks (7/15 cell C, 5/15 cell D) — see
        # ~/.memory/benchmarks/routing/tasks/ for the ";" in correct_answer.
        # Fix: split recursively on both "," and ";" to a flat list of
        # atomic tokens and require each present independently. This keeps
        # the same "tolerates formatting, not gaps" philosophy as the
        # 2026-07-19 comma fix above — it can't verify which entity a
        # capability belongs to (neither could the comma-only version), but
        # it can verify every fact was actually stated, which is the
        # signal this checker has always been designed to catch.
        if "," in correct or ";" in correct:
            items = [
                p.strip().lower()
                for chunk in correct.split(";")
                for p in chunk.split(",")
                if p.strip()
            ]
            haystack = text_to_check.lower()

            # How many items in THIS answer key have a purely-numeric value.
            # Used below to decide whether the independent-substring
            # fallback is safe for a numeric value: with only one numeric
            # fact in the whole answer (e.g. "count=7"), there's nothing
            # else it could coincidentally collide with, so the fallback is
            # safe. With multiple (e.g. a priority list "id_a=4,id_b=5,..."),
            # a wrong pairing could slip through by matching a DIFFERENT
            # item's correct number, so the stricter glued-token check stays
            # required. Bug found live 2026-08-17 re-verifying cell D: the
            # blanket numeric guard below was blocking "count=7" (the only
            # number in its answer) just because a response wrote
            # "Total count: 7" instead of the literal "count=7".
            _numeric_value_count = sum(
                1 for it in items if "=" in it and it.partition("=")[2].strip().isdigit()
            )

            def _item_satisfied(item: str) -> bool:
                if item in haystack:
                    return True
                if "=" in item:
                    # Bug found live 2026-08-16 on cellC_005, in two stages.
                    # Stage 1 (None values): a model that correctly reports a
                    # field absent rarely writes the literal Python token
                    # "None" -- "not present"/"n/a"/"unset" are equally
                    # correct, but the glued "key=None" substring check
                    # rejected them.
                    # Stage 2 (real values, found re-verifying stage 1):
                    # the SAME glued-token brittleness also hits real
                    # values -- qwen36_31b_a3b_mtp wrote `popo: "coding_agent"`
                    # (colon+quotes) instead of the literal "popo=coding_agent"
                    # and failed despite being completely correct. No model
                    # naturally writes Python dict-literal syntax in prose.
                    # Fix: fall back to checking key and value as two
                    # INDEPENDENT substrings (key present AND value present,
                    # anywhere in the response, not necessarily adjacent).
                    # This can't verify the two are actually paired together
                    # -- but neither can any other multi-item check in this
                    # function (see the semicolon-fix comment above); that
                    # tradeoff is already accepted throughout this checker.
                    # None-valued items keep an additional synonym set since
                    # "None" itself is even less likely to appear verbatim
                    # than a real value is.
                    key, _, value = item.partition("=")
                    key = key.strip()
                    value = value.strip()
                    if not key:
                        return False
                    if value == "none":
                        none_synonyms = (
                            "none", "not present", "n/a", "unset",
                            "not set", "no executor", "not specified", "null",
                        )
                        return key in haystack and any(s in haystack for s in none_synonyms)
                    if value:
                        if len(value) >= 3 and not value.isdigit():
                            return key in haystack and value in haystack
                        if value.isdigit() and _numeric_value_count <= 1:
                            # Only numeric fact in this answer -- nothing
                            # else it could coincidentally collide with.
                            return key in haystack and value in haystack
                        # Multiple numeric items (e.g. a priority list) --
                        # require the glued literal to avoid a wrong
                        # pairing slipping through via a different item's
                        # correct number.
                return False

            return bool(items) and all(_item_satisfied(item) for item in items)
        return correct.lower() in text_to_check.lower()
    if match_type == "structural":
        # No correct_answer at all — "wrote something substantive" is the
        # only signal available, by design.
        return len(text_to_check.strip()) > 10
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
        # resource.get("api_key", "") only ever worked for local LMStudio
        # entries which store a literal key. Real paid providers correctly
        # use api_key_env (never raw secrets in config) -- resolve_key is
        # the canonical resolver every other caller (ResourceManager) uses.
        # Bug found live 2026-07-17: every DeepSeek/MiniMax call 401'd
        # because the profiler silently sent an empty Bearer token.
        "api_key": UnifiedLLMClient.resolve_key(resource_id, resource),
        "output_limit": 256,
        "message_format": resource.get("message_format", "openai"),
        "completions_path": resource.get("completions_path"),
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
    # Give the model the resolved path for its own read_file/write_file
    # call when the task setup already tells the harness exactly which
    # file is involved. Without this, a model that (reasonably) wants to
    # re-verify system-prompt-injected content via a real tool call has to
    # guess the path from the goal's bare filename (e.g. "resource_pool.json"
    # -> tries "resources.json", "config/resources.json", ...), burning
    # iteration/wall-clock budget on wrong guesses that have nothing to do
    # with the model's real capability. Found live 2026-08-15 on cellB_004:
    # the model reasoned correctly but was marked "timeout" at 312.7s vs a
    # 300s cap, having spent 2 of 8 iterations on wrong path guesses.
    setup = task.get("setup", "")
    if setup.startswith("file=") and ("read_file" in declared_tools or "write_file" in declared_tools):
        hint_path = Path(setup.split("=", 1)[1]).expanduser()
        if not hint_path.is_absolute():
            hint_path = PROJECT_ROOT / hint_path
        goal = goal + f"\n\n(File path for read_file, if you need it: {hint_path})"
    elif setup.startswith("dir=") and declared_tools:
        # Same reasoning as the file= hint above, for directory-scoped
        # tasks (cellC_004, cellC_014, cellD_015). Without this the model
        # only knows the directory NAME from the goal text ("config/"),
        # not where it actually is relative to its bash_exec cwd (locked
        # to the scratch dir, nowhere near the project) -- confirmed live
        # 2026-08-16 burning a full budget on `find / -maxdepth 3 -type d
        # -name config` before ever reaching the actual question.
        hint_path = Path(setup.split("=", 1)[1]).expanduser()
        if not hint_path.is_absolute():
            hint_path = PROJECT_ROOT / hint_path
        goal = goal + f"\n\n(Directory path, if you need it: {hint_path})"
    # None for cell A/C (chat-answer-only); a scratch Path for cell B/D
    # tasks, whose real deliverable is the file, not the chat reply.
    scratch_target = _extract_scratch_target(task)

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
            # See preload_model's identical fix for why resolve_key is required
            # instead of a literal resource.get("api_key", "") read.
            "api_key": UnifiedLLMClient.resolve_key(resource_id, resource),
            "output_limit": min(resource.get("output_limit", 8192), 8192),
            "message_format": resource.get("message_format", "openai"),
            "completions_path": resource.get("completions_path"),
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
            if check_answer(response_text, task, scratch_target):
                result["success"] = True
                break

            # ---- Verification-mismatch: craft retry feedback ----
            # This is the same retry-with-feedback pattern from A9,
            # preserved for tasks that don't use tools. The model got
            # the goal, produced prose, and it didn't verify — give it
            # a hint and let it try again within the budget.
            #
            # NEVER put task["correct_answer"] in this feedback. The prior
            # version did (an f-string interpolating the raw answer key
            # into "must include the exact substring ... quote it
            # verbatim") which handed the model the ground truth on a
            # plate — any later turn that merely repeated that
            # string, including one explicitly REFUSING to answer with it,
            # then passed check_answer's naive substring match. Confirmed
            # false positives this caused: MiniMax M3 on cellD_001/cellD_004
            # (paid), two local models on cellC_005 — all zero tool calls.
            # See ~/.memory/research/routing_harness_verification_flaw_2607.md.
            match_type = task.get("match_type", "contains")
            if scratch_target is not None:
                feedback = (
                    f"No verified answer yet. This task's deliverable is the file "
                    f"{scratch_target.name} in the scratch dir — call write_file with "
                    f"the value you find there. Re-read the source first if you "
                    f"haven't verified it with a tool call; don't guess or write "
                    f"something you haven't confirmed."
                )
            elif match_type == "exact":
                feedback = ("Your answer doesn't exactly match the source data. "
                            "Re-read the source — don't guess or recall from memory — "
                            "and state the precise value you find.")
            elif match_type == "contains":
                feedback = ("Your answer doesn't match what the source data actually "
                            "shows. Re-check the source directly rather than guessing, "
                            "and don't state a value you haven't verified.")
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
        if check_answer(result["response"], task, scratch_target):
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

    models = validate_models_loaded(models)
    if not models:
        print("No models left after loaded-state validation! "
              "Load at least one with `lms load <model>` and retry.")
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

            effective_max_duration_s = _effective_max_duration_s(cell_letter, max_duration_s)
            result = await run_task_with_model(task, model_id, budget, effective_max_duration_s)
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
    #
    # MUST merge with what's already on disk, not blindly overwrite. `profile`
    # here only ever covers the (models, cell) combination THIS invocation
    # touched -- e.g. a --cell D --models deepseek,minimax run only has D-cell
    # entries for those two models. A plain write_text would silently erase
    # every other model/cell already profiled (this happened for real on
    # 2026-07-17: a paid-model D-cell run wiped the full A/B/C/D dataset for
    # all 5 local models). Merge per (model, cell) instead: new data replaces
    # only the matching keys, everything else already on disk is preserved.
    profile_path = Path.home() / ".memory" / "benchmarks" / "routing" / "capability_profile.json"
    merged_profile: Dict[str, Any] = {}
    if profile_path.exists():
        try:
            merged_profile = json.loads(profile_path.read_text())
        except Exception:
            merged_profile = {}
    for model_id, by_cell in profile.items():
        merged_profile.setdefault(model_id, {}).update(by_cell)
    profile_path.write_text(json.dumps(merged_profile, indent=2))

    routing_path = Path.home() / ".memory" / "benchmarks" / "routing" / "routing_table.json"
    # Re-derive the routing table from the FULL merged profile (not just this
    # run's subset) so a partial run never regresses cells/models it didn't
    # touch. Cost order MUST be preserved-then-appended, not "this run's
    # models first" -- that would wrongly promote a paid model ahead of
    # already-profiled free/local ones just because it happened to be the
    # subset under test. Load the existing _cost_order (built up over prior
    # runs) as the base and append any model this run introduced that isn't
    # in it yet, in the order given.
    existing_cost_order: List[str] = []
    if routing_path.exists():
        try:
            existing_cost_order = json.loads(routing_path.read_text()).get("_cost_order") or []
        except Exception:
            existing_cost_order = []
    full_candidate_order = list(existing_cost_order)
    for m in models:
        if m not in full_candidate_order:
            full_candidate_order.append(m)
    for m in merged_profile.keys():
        if m not in full_candidate_order:
            full_candidate_order.append(m)
    merged_routing_table = derive_routing_table(merged_profile, candidate_order=full_candidate_order)
    routing_path.write_text(json.dumps(
        {k: v for k, v in merged_routing_table.items() if not k.startswith("_")}, indent=2,
    ))
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