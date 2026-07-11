"""Task Router — assigns minimum viable model to each task.

Classifies tasks into complexity cells (A/B/C/D) based on tool breadth
and dependency depth, then routes to the smallest model that can handle it.

Spec: ~/.memory/research/task_routing_research_question.md
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config.paths import get_memory_path
from app.scheduler.evals.models import ComplexityLevel
from app.scheduler.routing_profile import (
    DISQUALIFY_FAILURE_RATE, PASS_RATE_THRESHOLD,
    SLOW_DOMINANT_RATE, derive_routing_table, load_profile,
)

logger = logging.getLogger(__name__)

# Tool categories (7-bit vector: memory/file/web/code/agent/system/external)
TOOL_CATEGORIES = {
    "memory_search": "memory", "knowledge_search": "memory",
    "read_file": "file", "write_file": "file", "list_files": "file",
    "web_search": "web", "fetch_url": "web",
    "bash_exec": "code", "docker_sandbox_exec": "code",
    "dispatch_subtask": "agent", "ask_user": "agent",
    "read_config": "system", "write_config": "system",
}

# Tools with high argument complexity (A_c bonus)
HIGH_AC_TOOLS = {"bash_exec", "docker_sandbox_exec", "dispatch_subtask",
                 "write_file", "write_config"}

# Keywords that signal sequential dependency (D_d proxy)
DEPENDENCY_KEYWORDS = [
    "then", "after", "based on", "use the result", "use that",
    "once you have", "given what you found", "with that", "using the output",
]


# S_f (spec fuzziness) is NOT measured here: goals are pre-validated by the spec
# quality gate (app/scheduler/spec_qualifier.py) at the dispatch boundary, so this
# router assumes gate-ready goals. S_s (state space) is folded into the depth score.
def compute_cell(goal_text: str, declared_tools: list[str]) -> str:
    """Classify task complexity into cell A/B/C/D.

    Returns one of: 'A' (low breadth, low depth), 'B' (low breadth, high depth),
    'C' (high breadth, low depth), 'D' (high breadth, high depth).
    """
    # Breadth score: distinct tool categories + A_c bonus
    categories = {TOOL_CATEGORIES.get(t, "other") for t in declared_tools}
    ac_bonus = 1 if any(t in HIGH_AC_TOOLS for t in declared_tools) else 0
    breadth_score = len(categories) + ac_bonus

    # Depth score: dependency keywords + state-passing tool presence
    goal_lower = goal_text.lower()
    kw_count = sum(1 for kw in DEPENDENCY_KEYWORDS if kw in goal_lower)
    state_bonus = 1 if any(t in {"write_file", "bash_exec", "dispatch_subtask"}
                            for t in declared_tools) else 0
    depth_score = kw_count + state_bonus

    # Thresholds (tunable)
    HIGH_BREADTH = breadth_score >= 2
    HIGH_DEPTH = depth_score >= 1

    if HIGH_BREADTH and HIGH_DEPTH:
        return "D"
    if HIGH_BREADTH and not HIGH_DEPTH:
        return "C"
    if not HIGH_BREADTH and HIGH_DEPTH:
        return "B"
    return "A"


# Cell → demanded capability level (v2 ladder).
# dispatch_subtask in declared_tools overrides to L4_orchestration regardless of cell.
_CELL_TO_LEVEL = {
    "A": ComplexityLevel.L1_SINGLE_CALL,
    "B": ComplexityLevel.L2_MULTI_STEP,
    "C": ComplexityLevel.L2_MULTI_STEP,
    "D": ComplexityLevel.L3_FEEDBACK,
}


# Per-level iteration budgets. Mirrors the design-doc per-level priors
# (llm_routing_benchmark_design.md §"How the Router Uses This"):
#
#   L1=4, L2=8, L3=12, L4=25
#
# These are the values the A7 budget_hint="raise" signal promotes to
# when a model is slow/timeout-dominant but otherwise clears the
# pass-rate threshold. The executor's max_iterations comes from
# config (with a fallback to task.resources.max_iterations); when
# budget_hint fires, we write the per-level prior into config so the
# executor picks it up.
#
# L4 has a higher prior because orchestration (dispatch_subtask +
# wait + evaluate + synthesize) is structurally multi-step.
LEVEL_ITERATION_PRIORS: Dict[str, int] = {
    ComplexityLevel.L1_SINGLE_CALL.value: 4,
    ComplexityLevel.L2_MULTI_STEP.value: 8,
    ComplexityLevel.L3_FEEDBACK.value: 12,
    ComplexityLevel.L4_ORCHESTRATION.value: 25,
}


def apply_budget_hint(
    routing: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Consume the v2 router's budget_hint signal and bump max_iterations.

    Per A7: when the router flags a model as ``budget_hint="raise"`` it
    means the model passes the threshold but its failures are
    dominated by ``final_answer_slow`` / ``timeout`` — the model is
    *capable but under-budgeted*. The right action is to extend
    ``max_iterations`` (and proportionally the wall-clock cap) so the
    model has the time to do the work, not disqualify it.

    The function writes:
      - config["max_iterations"] = LEVEL_ITERATION_PRIORS[level]
        (only if the routing's level is mapped; never lowers an
        existing higher value — operators can override explicitly).
      - config["max_duration_seconds"] = max(existing, prior * 30)
        — 30s per iteration is the rough A10 budget average, used as
        a safety floor. Operators can still raise it explicitly.
      - config["_budget_hint_source"] = {level, prior, source_routing}
        so the downstream executor can log why the budget was raised.

    Returns the mutated config (same object, in-place + returned for
    convenience). Idempotent: re-applying the same hint is a no-op.

    Out of scope (per the A7 spec):
      - Auto-disqualifying slow models. The router only attaches
        budget_hint; it does not flip the model's pass/fail. The
        handler's job is to give the model more rope.
      - Forcing a different model. Slow-but-capable wins; the
        alternative is escalation, and that's a separate signal.
    """
    if not routing or routing.get("budget_hint") != "raise":
        return config

    level = routing.get("level")
    if not level:
        return config
    prior = LEVEL_ITERATION_PRIORS.get(level)
    if prior is None:
        return config

    # Only raise max_iterations, never lower it. An operator who set
    # config["max_iterations"] = 50 explicitly gets 50, not 8.
    current_iters = config.get("max_iterations")
    if current_iters is None or prior > int(current_iters):
        config["max_iterations"] = prior

    # Wall-clock cap: scale with iterations so a level-2 task with
    # 8 iterations gets at least 240s. Don't lower existing values.
    floor_seconds = prior * 30
    current_duration = config.get("max_duration_seconds")
    if current_duration is None or floor_seconds > int(current_duration):
        config["max_duration_seconds"] = floor_seconds

    # Provenance for downstream logging.
    config["_budget_hint_source"] = {
        "level": level,
        "prior_iterations": prior,
        "floor_seconds": floor_seconds,
        "model_id": routing.get("model_id"),
        "routing_cell": routing.get("cell"),
    }
    return config


@dataclass
class RoutingResult:
    """Result of task routing."""
    cell: str
    model_id: str
    confidence: float
    explain: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cell": self.cell,
            "model_id": self.model_id,
            "confidence": self.confidence,
            "explain": self.explain,
        }


class TaskRouter:
    """Routes tasks to minimum viable model based on complexity classification."""

    def __init__(self, routing_table: Dict[str, str], capability_profile: Optional[Dict] = None):
        self._routing_table = routing_table
        self._capability_profile = capability_profile or {}

    @classmethod
    def load(cls) -> "TaskRouter":
        """Load routing table and capability profile from ~/.memory/benchmarks/routing/."""
        base = Path(get_memory_path()) / "benchmarks" / "routing"

        # Load routing table
        table_path = base / "routing_table.json"
        if table_path.exists():
            routing_table = json.loads(table_path.read_text())
        else:
            # Default hypothesis
            routing_table = {
                "A": "lmstudio_gemma4_12b",
                "B": "lmstudio_qwen36_27b_mtp",
                "C": "lmstudio_google_gemma_4_26b_a4b",
                "D": "lmstudio_ornith_35b_mtp_apex",
            }

        # Load capability profile (handles both v2 and pre-A7 schemas).
        profile_path = base / "capability_profile.json"
        capability_profile = load_profile(profile_path)

        return cls(routing_table=routing_table, capability_profile=capability_profile)

    def classify_and_route(
        self,
        goal: str,
        role_id: str,
        declared_tools: list[str],
    ) -> Dict[str, Any]:
        """Classify task and select minimum viable model.

        Returns dict with: cell, level, model_id, confidence, explain,
        and (when the v2 profile is in play) budget_hint, disqualified.

        Level is the demanded capability rung (L1–L4); dispatch_subtask in
        declared_tools forces L4_orchestration regardless of cell.

        A7 failure-mode-aware rules (from the design doc §"Capability
        profile (v2 — failure-mode aware)"):
          - xml_tool_leakage / malformed_arguments rate >= 0.20 at the
            selected cell → hard-disqualify that model, walk the cost
            ordering to the next qualified model.
          - final_answer_slow / timeout rate dominant (>= 0.50) and the
            model still clears pass_rate >= 0.80 → keep the model but
            attach budget_hint="raise" so the executor can extend
            max_iterations (Bonsai signal — out of scope here to apply).
          - Otherwise route on pass_rate >= PASS_RATE_THRESHOLD.
        """
        cell = compute_cell(goal, declared_tools)
        level = _CELL_TO_LEVEL.get(cell, ComplexityLevel.L1_SINGLE_CALL)

        # L4 override: any task that dispatches subtasks demands orchestration.
        l4_override = "dispatch_subtask" in declared_tools
        if l4_override:
            level = ComplexityLevel.L4_ORCHESTRATION

        # Routing lookup: prefer a level-keyed "levels" sub-table (new format);
        # fall back to the cell-keyed table (old/default format).
        levels_table = self._routing_table.get("levels")
        if isinstance(levels_table, dict) and level.value in levels_table:
            model_id = levels_table[level.value]
        else:
            model_id = self._routing_table.get(cell, self._routing_table.get("A", ""))

        disqualified: List[str] = []
        budget_hint: Optional[str] = None
        confidence = 0.5  # default: hypothesis only
        explain_parts: List[str] = []

        # Apply A7 rules if we have a v2 profile that includes failure_modes
        # for the selected model at this cell.
        cell_profile = (
            self._capability_profile.get(model_id, {}).get(cell)
            if model_id else None
        )
        if cell_profile and "failure_modes" in cell_profile:
            fm = cell_profile.get("failure_modes", {}) or {}
            pass_rate = float(cell_profile.get("pass", cell_profile.get("success_rate", 0.0)) or 0.0)

            # Hard-disqualify check.
            leakage_rate = fm.get("xml_tool_leakage", 0.0)
            malformed_rate = fm.get("malformed_arguments", 0.0)
            if leakage_rate >= DISQUALIFY_FAILURE_RATE or malformed_rate >= DISQUALIFY_FAILURE_RATE:
                disqualified.append(model_id)
                explain_parts.append(
                    f"disqualified ({model_id}: leakage={leakage_rate:.2f}, "
                    f"malformed={malformed_rate:.2f})"
                )
                # Walk candidate ordering — any model listed in routing_table
                # at this cell is a candidate; we try the cheapest next.
                model_id = self._find_qualified_fallback(cell, level, declared_tools)
                cell_profile = (
                    self._capability_profile.get(model_id, {}).get(cell)
                    if model_id else None
                )
                if cell_profile:
                    pass_rate = float(cell_profile.get("pass", 0.0) or 0.0)

            # Budget hint: passes threshold but slow/timeout dominates.
            if cell_profile:
                slow = fm.get("final_answer_slow", 0.0)
                timeout = fm.get("timeout", 0.0)
                if (slow + timeout) >= SLOW_DOMINANT_RATE and pass_rate >= PASS_RATE_THRESHOLD:
                    budget_hint = "raise"
                    explain_parts.append("budget_hint=raise (slow/timeout dominant)")

            confidence = pass_rate
        elif cell_profile:
            # Legacy schema (success_rate) — no failure modes, no disqualify.
            confidence = float(cell_profile.get("success_rate", cell_profile.get("pass", 0.0)) or 0.0)

        explain = (
            f"Cell {cell} → level {level.value}"
            + (" [L4 override: dispatch_subtask]" if l4_override else "")
            + f": {self._cell_description(cell)} → {model_id or '(no qualified model)'}"
            + (f" [{'; '.join(explain_parts)}]" if explain_parts else "")
        )

        result: Dict[str, Any] = {
            "cell": cell,
            "level": level.value,
            "model_id": model_id,
            "confidence": round(confidence, 3),
            "explain": explain,
        }
        if budget_hint:
            result["budget_hint"] = budget_hint
        if disqualified:
            result["disqualified"] = disqualified
        return result

    def _find_qualified_fallback(
        self,
        cell: str,
        level: ComplexityLevel,
        declared_tools: list[str],
    ) -> str:
        """Find the next-cheapest model that passes the A7 rules at this cell.

        Walks the cost ordering in priority order. Returns "" if nothing
        qualifies — the caller surfaces that as ``model_id == ''`` so the
        executor falls back to default resource selection.

        Cost-order source (A11.7): the runner's ``derive_routing_table``
        writes ``_cost_order`` into the live routing table. When present
        it is the single source of truth for model ordering. We fall back
        to the cell/levels table order (which is lossy but always
        present) when ``_cost_order`` is missing — for routing tables
        authored by hand or by older runs.
        """
        candidates: List[str] = []
        cost_order = self._routing_table.get("_cost_order")
        if isinstance(cost_order, list) and cost_order:
            for v in cost_order:
                if v and v not in candidates:
                    candidates.append(v)
        levels_table = self._routing_table.get("levels")
        if isinstance(levels_table, dict):
            for v in levels_table.values():
                if v and v not in candidates:
                    candidates.append(v)
        for c, v in self._routing_table.items():
            if c.startswith("_") or not isinstance(v, str):
                continue
            if v and v not in candidates:
                candidates.append(v)

        for cand in candidates:
            cell_profile = self._capability_profile.get(cand, {}).get(cell)
            if not cell_profile or "failure_modes" not in cell_profile:
                # No profile data: assume clean (caller's call).
                return cand
            fm = cell_profile.get("failure_modes", {}) or {}
            leakage_rate = fm.get("xml_tool_leakage", 0.0)
            malformed_rate = fm.get("malformed_arguments", 0.0)
            if leakage_rate >= DISQUALIFY_FAILURE_RATE or malformed_rate >= DISQUALIFY_FAILURE_RATE:
                continue
            pass_rate = float(cell_profile.get("pass", 0.0) or 0.0)
            if pass_rate < PASS_RATE_THRESHOLD:
                continue
            return cand
        return ""

    def _cell_description(self, cell: str) -> str:
        descriptions = {
            "A": "low breadth, low depth — single tool, no chaining",
            "B": "low breadth, high depth — sequential with state passing",
            "C": "high breadth, low depth — parallel independent lookups",
            "D": "high breadth, high depth — multi-tool sequential with state",
        }
        return descriptions.get(cell, "unknown")

    def validate_tool_call(
        self,
        call: Dict[str, Any],
        role_tools: list[str],
    ) -> Tuple[bool, str]:
        """Validate a tool call against role's available tools.

        Returns (valid, reason).
        """
        tool_name = call.get("function", {}).get("name", "") if "function" in call else call.get("name", "")
        if not tool_name:
            return False, "No tool name in call"
        if tool_name not in role_tools:
            return False, f"Tool '{tool_name}' not in role's available tools"
        return True, ""

    def should_escalate(
        self,
        execution_trace: List[Dict],
    ) -> Tuple[bool, str]:
        """Check if execution should be escalated to a larger model.

        Returns (escalate, reason).
        """
        if len(execution_trace) < 2:
            return False, ""

        # Check for loops: same tool called twice with same args
        recent = execution_trace[-2:]
        if len(recent) == 2:
            t1 = recent[0].get("tool_name", "")
            t2 = recent[1].get("tool_name", "")
            a1 = json.dumps(recent[0].get("args", {}), sort_keys=True)
            a2 = json.dumps(recent[1].get("args", {}), sort_keys=True)
            if t1 == t2 and a1 == a2:
                return True, f"Loop detected: {t1} called twice with same args"

        # Check for consecutive errors
        errors = [t for t in execution_trace[-3:] if t.get("error")]
        if len(errors) >= 2:
            return True, f"{len(errors)} consecutive errors"

        return False, ""
