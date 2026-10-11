"""Deadline review: when a task reaches its time budget, decide extend-or-stop from evidence.

A fixed wall-clock budget is rigid: a task doing real work at the deadline is killed, a hung one
runs to the limit. At the deadline we gather evidence from the run itself (deterministic code),
ask a model for a judgment, then enforce the hard limits in code -- the model can only choose
within them. No fallback: if the review cannot be completed, the answer is "stop", with the reason.
"""
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# The scheduler's outer wall-clock cap for tasks with no max_duration_seconds (core.py).
DEFAULT_TASK_TIMEOUT_S = 1800
# Margin kept under the outer cap so the executor can finish and record a stop itself.
OUTER_CAP_MARGIN_S = 120
DEFAULT_EXTENSION_S = 300
DEFAULT_MAX_EXTENSIONS = 3
RECENT_ITERATIONS = 4


@dataclass
class ReviewDecision:
    extend: bool
    seconds: float
    reason: str
    source: str  # "rule" (code decided) or "model"


def gather_evidence(iteration_log: List[Dict[str, Any]], elapsed_s: float, max_duration_s: float,
                    extensions_used: int) -> Dict[str, Any]:
    """Facts about the run so far; no judgment."""
    recent = iteration_log[-RECENT_ITERATIONS:]
    tool_iterations = [e for e in iteration_log if e.get("tool_calls")]
    sigs = [tuple(e.get("tool_calls") or ()) for e in recent]
    looping = len(sigs) >= 3 and len(set(sigs)) == 1 and bool(sigs[0])
    return {
        "elapsed_s": round(elapsed_s),
        "budget_s": round(max_duration_s),
        "extensions_used": extensions_used,
        "iterations": len(iteration_log),
        "iterations_with_tools": len(tool_iterations),
        "errors_in_recent": sum(1 for e in recent if e.get("status") in ("error", "empty_response", "no_resource")),
        "same_tool_calls_repeating": looping,
        "recent": [
            {"iteration": e.get("iteration"), "status": e.get("status"), "resource": e.get("resource"),
             "tools": e.get("tool_calls") or [], "took_s": e.get("elapsed_s")}
            for e in recent
        ],
    }


def rule_decision(evidence: Dict[str, Any], hard_cap_s: float, max_extensions: int,
                  extension_s: float) -> Optional[ReviewDecision]:
    """Stops that need no judgment. None means the model may decide."""
    if evidence["extensions_used"] >= max_extensions:
        return ReviewDecision(False, 0, f"extension limit reached ({max_extensions})", "rule")
    room = hard_cap_s - evidence["budget_s"]
    if room <= 0:
        return ReviewDecision(False, 0, f"hard cap reached ({hard_cap_s:.0f}s)", "rule")
    if evidence["iterations_with_tools"] == 0 and evidence["iterations"] > 0:
        return ReviewDecision(False, 0, "no tool activity yet; more time would not change that", "rule")
    if evidence["same_tool_calls_repeating"]:
        return ReviewDecision(False, 0, "the same tool calls are repeating (loop)", "rule")
    return None


def build_prompt(task_goal: str, evidence: Dict[str, Any], max_grant_s: float) -> str:
    return (
        "A scheduled task has reached its time budget. Decide whether it is still making real progress "
        "toward its goal and should get more time, or is stuck/hung and should be stopped.\n\n"
        f"Goal: {task_goal[:600]}\n\nEvidence (facts from the run):\n{json.dumps(evidence, indent=1)}\n\n"
        f"You may grant between 60 and {max_grant_s:.0f} seconds. Extend only if the recent iterations show "
        "new work being done (different tool calls, successful results) and the goal looks reachable in the "
        "extra time. Stop if recent iterations are errors, repeats, or empty.\n"
        'Answer with ONLY a JSON object: {"decision": "extend" or "stop", "seconds": <int>, "reason": "<one sentence>"}'
    )


def parse_model_decision(text: str, max_grant_s: float) -> ReviewDecision:
    """Strict parse. Raises ValueError on anything unexpected -- the caller stops the task."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("deadline review: no JSON object in the model reply")
    obj = json.loads(m.group(0))
    decision = obj.get("decision")
    reason = str(obj.get("reason") or "").strip()
    if decision not in ("extend", "stop"):
        raise ValueError(f"deadline review: decision must be 'extend' or 'stop', got {decision!r}")
    if not reason:
        raise ValueError("deadline review: the model gave no reason")
    if decision == "stop":
        return ReviewDecision(False, 0, reason, "model")
    seconds = float(obj.get("seconds") or 0)
    if seconds < 60:
        raise ValueError(f"deadline review: extension of {seconds}s is below the 60s minimum")
    return ReviewDecision(True, min(seconds, max_grant_s), reason, "model")


def compute_limits(config: Dict[str, Any], outer_cap_s: float):
    """(hard_cap_s, max_extensions, extension_s). The hard cap always stays under the scheduler's outer cap."""
    ceiling = outer_cap_s - OUTER_CAP_MARGIN_S
    hard_cap = min(float(config.get("deadline_hard_max_seconds", ceiling)), ceiling)
    return (hard_cap,
            int(config.get("deadline_max_extensions", DEFAULT_MAX_EXTENSIONS)),
            float(config.get("deadline_extension_seconds", DEFAULT_EXTENSION_S)))
