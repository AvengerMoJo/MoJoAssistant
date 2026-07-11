"""Routing profile derivation (A7 — failure-mode aware).

Pure functions that take per-task profiling records and produce:
  - the new v2 capability_profile.json schema
    ({model_id: {cell: {pass, total, success, failure_modes, avg_duration}}})
  - a routing_table.json derived from the profile (cheapest qualified model
    per cell, with leakage-disqualification and slow-budget hints applied)

Backwards-compatible with the pre-A7 summary.json shape — see
:meth:`RoutingProfile.from_legacy` for the migration.

Spec: ~/.memory/research/llm_routing_benchmark_design.md v2 §"Capability
profile (v2 — failure-mode aware)" and §"How the Router Uses This".
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.scheduler.evals.models import (
    FailureClass,
    classify_failure,
)

logger = logging.getLogger(__name__)


# Routing thresholds from the design doc. Centralized so the router and the
# profile derivation agree on what "qualified" means.
PASS_RATE_THRESHOLD = 0.80        # design §"How the Router Uses This"
DISQUALIFY_FAILURE_RATE = 0.20    # leakage / malformed rate >= this -> hard DQ
SLOW_DOMINANT_RATE = 0.50         # final_answer_slow / timeout >= this -> budget_hint


@dataclass
class TaskRecord:
    """One profiling run: a single (model, task) result.

    Mirrors the per-task dict written by ``run_routing_profiler.py``. Kept as
    a dataclass (not a dict) so the aggregation has typed inputs.
    """
    task_id: str
    cell: str
    resource_id: str
    success: bool
    elapsed_s: float = 0.0
    iterations: int = 1
    error: Optional[str] = None
    response: str = ""
    # If the profiler already classified the failure, prefer that.
    failure_class: Optional[str] = None
    # A11.3 — tool-execution telemetry from the A11.2 loop. Optional
    # so legacy records (pre-A11.2) and the legacy-migrated
    # {success_rate} summary shape still load without error.
    tool_call_count: int = 0
    tool_error_count: int = 0
    # Per-call log: list of {tool, args, ok, error, elapsed_s}. Kept
    # here for completeness; aggregate_profile summarizes it.
    tool_calls_log: Optional[List[Dict[str, Any]]] = None

    def resolved_failure_class(self) -> Optional[FailureClass]:
        """Return the failure class for this record, classifying if needed.

        A None result means "clean pass" — the task succeeded quickly with
        no signal worth bucketing. Caller should treat None as "no
        contribution to failure_modes aggregation".
        """
        if self.failure_class:
            try:
                return FailureClass(self.failure_class)
            except ValueError:
                pass  # fall through to heuristic classifier
        return classify_failure(
            success=self.success,
            elapsed_s=self.elapsed_s,
            error=self.error,
            response=self.response,
            iterations=self.iterations,
        )


def aggregate_profile(records: Iterable[TaskRecord]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Aggregate per-task records into the v2 capability_profile schema.

    Returns a dict of the form::

        {model_id: {cell: {
            "pass": float,                          # success rate 0..1
            "total": int,
            "success": int,
            "failure_modes": {FailureClass.value: float, ...},
            "avg_duration": float,
            "avg_iterations": float,
            # A11.3 — tool-execution aggregates (only populated for
            # cells B/C/D tasks that use tools; cell A tasks have
            # tool_call_count=0 by default).
            "avg_tool_calls": float,                # mean tool calls per task
            "tool_error_rate": float,               # errors / calls, over cells that used tools
            "tasks_using_tools": int,               # how many of the N tasks actually called a tool
        }}}

    Failure-mode rates are computed over the *failed* population only (a
    leakage rate of 1.0 means "every failure was leakage"; a 0.0 means
    "no leakage observed"). This matches the design doc's intent: the
    router uses the distribution of *how* a model fails, not its
    absolute success rate.

    The new tool_execution aggregates are diagnostic — they don't
    affect ``derive_routing_table``'s pass-rate threshold logic, but
    they reveal *how* a model uses tools (does it know which tool to
    call? does it get the args right? does it call out-of-scope
    paths?) which the v2 router can use in future revisions for
    finer-grained tool-aware routing.
    """
    bucket: Dict[str, Dict[str, List[TaskRecord]]] = {}
    for r in records:
        bucket.setdefault(r.resource_id, {}).setdefault(r.cell, []).append(r)

    profile: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for model_id, by_cell in bucket.items():
        profile[model_id] = {}
        for cell, rs in by_cell.items():
            total = len(rs)
            successes = sum(1 for r in rs if r.success)
            pass_rate = (successes / total) if total else 0.0
            failed = [r for r in rs if not r.success]
            n_failed = len(failed)
            failure_counts: Dict[str, int] = {}
            for r in rs:
                fc = r.resolved_failure_class()
                if fc is None:
                    continue
                failure_counts[fc.value] = failure_counts.get(fc.value, 0) + 1
            # Rates are over the failed population, matching design-doc semantics.
            failure_modes = {
                k: round(v / n_failed, 3) for k, v in failure_counts.items() if n_failed
            }
            avg_duration = round(sum(r.elapsed_s for r in rs) / total, 2) if total else 0.0
            avg_iterations = round(sum(r.iterations for r in rs) / total, 2) if total else 0.0

            # A11.3 — tool-execution aggregates. Backwards compatible:
            # legacy records (pre-A11.2) have tool_call_count=0, so
            # avg_tool_calls is 0 and tool_error_rate is 0.
            total_tool_calls = sum(r.tool_call_count for r in rs)
            total_tool_errors = sum(r.tool_error_count for r in rs)
            tasks_using_tools = sum(1 for r in rs if r.tool_call_count > 0)
            avg_tool_calls = round(total_tool_calls / total, 2) if total else 0.0
            # Tool error rate is over the population of tool calls,
            # not over tasks. A model that makes 1 bad call out of
            # 10 total has tool_error_rate=0.1, regardless of how
            # many tasks it ran.
            tool_error_rate = (
                round(total_tool_errors / total_tool_calls, 3)
                if total_tool_calls else 0.0
            )

            profile[model_id][cell] = {
                "pass": round(pass_rate, 3),
                "total": total,
                "success": successes,
                "failure_modes": failure_modes,
                "avg_duration": avg_duration,
                "avg_iterations": avg_iterations,
                "avg_tool_calls": avg_tool_calls,
                "tool_error_rate": tool_error_rate,
                "tasks_using_tools": tasks_using_tools,
            }
    return profile


@dataclass
class RoutingDecision:
    """Output of :func:`derive_routing_table` for a single cell.

    ``disqualified`` lists models rejected at this cell (leakage/malformed
    threshold breached). ``budget_hint_models`` lists models that pass but
    show slow-dominant failure distribution and should get a budget bump.
    """
    cell: str
    model_id: Optional[str]            # cheapest qualified model; None if none qualifies
    disqualified: List[str] = field(default_factory=list)
    budget_hint_models: List[str] = field(default_factory=list)


def _is_disqualified_at(cell_profile: Dict[str, Any]) -> bool:
    """Hard-disqualify if leakage/malformed dominates failures.

    Mirrors design doc §"Capability profile (v2 — failure-mode aware)":
    ``xml_tool_leakage`` / ``malformed_arguments`` at rate >= 0.2 → the
    model is agentically unusable at that level.
    """
    fm = cell_profile.get("failure_modes", {})
    return (
        fm.get(FailureClass.XML_TOOL_LEAKAGE.value, 0.0) >= DISQUALIFY_FAILURE_RATE
        or fm.get(FailureClass.MALFORMED_ARGUMENTS.value, 0.0) >= DISQUALIFY_FAILURE_RATE
    )


def _wants_budget_hint(cell_profile: Dict[str, Any]) -> bool:
    """True if the model passes but its failures are dominated by slow/timeout.

    Per design doc: ``final_answer_slow`` / ``timeout`` → model is *capable
    but under-budgeted*; raise iteration budget rather than disqualify.
    """
    fm = cell_profile.get("failure_modes", {})
    slow = fm.get(FailureClass.FINAL_ANSWER_SLOW.value, 0.0)
    timeout = fm.get(FailureClass.TIMEOUT.value, 0.0)
    return (slow + timeout) >= SLOW_DOMINANT_RATE and cell_profile.get("pass", 0.0) >= PASS_RATE_THRESHOLD


def derive_routing_table(
    profile: Dict[str, Dict[str, Dict[str, Any]]],
    candidate_order: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Pick the cheapest qualified model per cell from the v2 profile.

    ``candidate_order`` controls the cost ordering — the first model in the
    list that qualifies wins. Defaults to a stable sort by model_id, which
    is *not* cost-ordered; production code should pass an explicit ordering
    from the resource pool (e.g. by tier + priority).

    The output also includes a ``cell_decisions`` debug field with the
    per-cell disqualified/budget-hint lists; the live routing_table.json
    keeps only the {cell: model_id} mapping the router consumes.

    Returns a dict suitable for writing to routing_table.json. A "levels"
    sub-table is also emitted (same mapping by level value) so the new
    format co-exists with the cell-keyed lookup. See
    :meth:`TaskRouter.classify_and_route` for the level-preferred logic.
    """
    if candidate_order is None:
        candidate_order = sorted(profile.keys())

    out: Dict[str, Any] = {}
    decisions: Dict[str, Dict[str, Any]] = {}

    # Collect every cell that appears in the profile (cheap models may not
    # cover every cell).
    cells = sorted({cell for by_cell in profile.values() for cell in by_cell.keys()})

    for cell in cells:
        disqualified: List[str] = []
        budget_hint_models: List[str] = []
        winner: Optional[str] = None

        for model_id in candidate_order:
            cell_profile = profile.get(model_id, {}).get(cell)
            if not cell_profile:
                continue
            if cell_profile.get("total", 0) == 0:
                continue
            if _is_disqualified_at(cell_profile):
                disqualified.append(model_id)
                continue
            if cell_profile.get("pass", 0.0) < PASS_RATE_THRESHOLD:
                continue
            if _wants_budget_hint(cell_profile):
                budget_hint_models.append(model_id)
            if winner is None:
                winner = model_id

        out[cell] = winner or ""  # empty string means "no model qualified"
        decisions[cell] = {
            "model_id": winner,
            "disqualified": disqualified,
            "budget_hint_models": budget_hint_models,
        }

    # Also emit a levels-keyed mirror so the router's level-preferred path
    # can resolve directly when given a level rather than a cell. Mirrors
    # the mapping in app/scheduler/task_router.py:_CELL_TO_LEVEL — kept
    # inline to avoid an import cycle between the two peer modules.
    _CELL_TO_LEVEL_VALUE = {
        "A": "L1_single_call",
        "B": "L2_multi_step",
        "C": "L2_multi_step",
        "D": "L3_feedback",
    }
    levels_table: Dict[str, str] = {}
    for cell, model_id in out.items():
        if not model_id or cell.startswith("_"):
            continue
        level = _CELL_TO_LEVEL_VALUE.get(cell)
        if level is None:
            continue
        # First model wins per level (cells map 1:1 to levels except B and C
        # which both map to L2 — keep the cheapest of the two).
        levels_table.setdefault(level, model_id)
    if levels_table:
        out["levels"] = levels_table

    out["_cell_decisions"] = decisions
    out["_thresholds"] = {
        "pass_rate": PASS_RATE_THRESHOLD,
        "disqualify_failure_rate": DISQUALIFY_FAILURE_RATE,
        "slow_dominant_rate": SLOW_DOMINANT_RATE,
    }

    # A11.7 — emit an explicit cost order alongside the cell-keyed
    # mapping. The runner passed ``candidate_order``; we preserve it so
    # the live routing table carries the ordering the router should
    # walk when looking for fallbacks. The cell-keyed mapping alone
    # is one model per cell, so it can't represent order; the levels
    # table also drops order. This list is the single source of truth.
    if candidate_order:
        out["_cost_order"] = list(candidate_order)

    return out


# ---------------------------------------------------------------------------
# Backwards compatibility — read pre-A7 summary.json (scalar success_rate)
# and re-emit as the v2 schema with empty failure_modes.
# ---------------------------------------------------------------------------


def from_legacy_summary(summary: Dict[str, Any]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Convert the old per-cell {success_rate, total, success} into v2 schema.

    Old shape::

        {model_id: {cell: {"success_rate": 0.8, "total": 5, "success": 4}}}

    v2 shape::

        {model_id: {cell: {"pass": 0.8, "total": 5, "success": 4,
                           "failure_modes": {}, "avg_duration": 0.0,
                           "avg_iterations": 0.0, "avg_tool_calls": 0.0,
                           "tool_error_rate": 0.0, "tasks_using_tools": 0,
                           "_legacy_migrated": True}}}

    Failure-mode and tool-execution information is lost in the legacy
    summary (it was never recorded); the migrated profile will disqualify
    nothing and trigger no budget hints. Re-profiling is required for
    full A7/A11.3 behaviour.
    """
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for model_id, by_cell in summary.get("profile", {}).items():
        out[model_id] = {}
        for cell, stats in by_cell.items():
            out[model_id][cell] = {
                "pass": stats.get("success_rate", stats.get("pass", 0.0)),
                "total": stats.get("total", 0),
                "success": stats.get("success", 0),
                "failure_modes": {},
                "avg_duration": 0.0,
                "avg_iterations": 0.0,
                "avg_tool_calls": 0.0,
                "tool_error_rate": 0.0,
                "tasks_using_tools": 0,
                "_legacy_migrated": True,
            }
    return out


def load_profile(path: Path) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Load a capability_profile.json, handling both schemas.

    Detection rule: if any cell entry has a ``failure_modes`` key, treat as
    v2. Otherwise apply :func:`from_legacy_summary` migration.
    """
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    # Distinguish profile-summary from TaskRouter.run_summary; both have a
    # "profile" key but only the profile summary has the per-cell stats.
    profile_section = data.get("profile", data) if isinstance(data, dict) else data
    # v2 schema: {model_id: {cell: {...}}}
    is_v2 = False
    if isinstance(profile_section, dict):
        for by_cell in profile_section.values():
            if isinstance(by_cell, dict):
                for stats in by_cell.values():
                    if isinstance(stats, dict) and "failure_modes" in stats:
                        is_v2 = True
                        break
            if is_v2:
                break
    if is_v2:
        return profile_section
    # Legacy shape: either the inner dict directly, or wrapped in {"profile": ...}
    return from_legacy_summary(data if "profile" in data else {"profile": profile_section})