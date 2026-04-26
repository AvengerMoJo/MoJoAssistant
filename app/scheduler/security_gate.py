"""
SecurityGate — per-tool-call security checkpoint.

Synchronous gate that sits in the execution path of every tool call,
before any tool is dispatched. Interface is intentionally designed
for a future async swap: emit-event → await-decision rather than
blocking inline check.

Decision values
---------------
ALLOW         — proceed
WARN_ALLOW    — log a warning, then proceed
STOP_ASK_USER — pause execution, surface to ask_user (HITL)
HARD_STOP     — block the call, return error to model (no HITL)

Rule sources (composed in priority order)
------------------------------------------
1. SafetyPolicy   — immutable system rules (blocked names, sandbox paths,
                    minimum danger level for bash_exec, write_file sandbox).
                    A SafetyPolicy DENY always maps to HARD_STOP.

2. Danger budget  — cumulative risk score for this task session.
                    Each tool call consumes its CapabilityDefinition danger_level
                    worth of budget.  When the total exceeds the task cap the gate
                    escalates to STOP_ASK_USER so the user can decide whether to
                    continue.  Budget is per task_id and reset at task start.

3. Plan scope     — optional soft check.  If the executor supplies the set of
                    tools mentioned in the approved plan, a call to an out-of-plan
                    tool triggers WARN_ALLOW (logged, not blocked) so the agent
                    can adapt without being hard-blocked.

Future async upgrade path
--------------------------
Replace check() with:
    async def check(...) -> GateDecision:
        event = GateEvent(...)
        await self._event_bus.emit("gate.check", event)
        return await self._event_bus.wait("gate.decision", event.id)

The GateDecision dataclass is already designed to carry across an event bus.
"""
# [hitl-orchestrator: generic]
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from app.scheduler.safety_policy import SafetyPolicy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Danger score mapping (mirrors SafetyPolicy._danger_to_int but public)
# ---------------------------------------------------------------------------
_DANGER_SCORE: Dict[str, int] = {
    "none": 0,
    "low": 1,
    "medium": 3,
    "high": 8,
    "critical": 20,
}

# Default per-task cumulative danger budget before escalation.
# Override per-task via SecurityGate.reset_task(task_id, budget=...).
# 160 = ~20 high-danger bash calls — enough for typical build/install tasks
# without interrupting every 5 calls.  The gate still fires on genuinely
# runaway sessions (30+ calls) or if SafetyPolicy hard-blocks a specific op.
_DEFAULT_TASK_BUDGET = 160


# ---------------------------------------------------------------------------
# Public API types
# ---------------------------------------------------------------------------

class Decision(str, Enum):
    ALLOW = "allow"
    WARN_ALLOW = "warn_allow"
    STOP_ASK_USER = "stop_ask_user"
    HARD_STOP = "hard_stop"


@dataclass
class GateDecision:
    """
    Result of a SecurityGate.check() call.

    Fields
    ------
    decision       : final verdict
    reason         : human-readable explanation (logged / returned to model on block)
    warn_message   : present on WARN_ALLOW — surfaced as a log warning
    ask_question   : present on STOP_ASK_USER — the question to pose via ask_user
    rule_source    : which rule source triggered the decision ("safety", "budget", "scope")
    danger_consumed: how much budget this call consumed (0 if blocked before execution)
    """
    decision: Decision
    reason: str
    warn_message: str = ""
    ask_question: str = ""
    rule_source: str = ""
    danger_consumed: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Convenience predicates
    @property
    def allowed(self) -> bool:
        return self.decision in (Decision.ALLOW, Decision.WARN_ALLOW)

    @property
    def blocked(self) -> bool:
        return not self.allowed


# ---------------------------------------------------------------------------
# Per-task state (cleared on task start / completion)
# ---------------------------------------------------------------------------

@dataclass
class _TaskState:
    budget: int = _DEFAULT_TASK_BUDGET
    consumed: int = 0
    calls: int = 0          # total gate-checked calls (including blocked)
    blocked: int = 0        # hard-blocked calls
    escalations: int = 0    # stop_ask_user escalations


# ---------------------------------------------------------------------------
# SecurityGate
# ---------------------------------------------------------------------------

class SecurityGate:
    """
    Composes SafetyPolicy + danger budget + plan scope into a single
    synchronous gate called before every tool dispatch.

    Usage
    -----
        gate = SecurityGate()
        gate.reset_task(task_id)          # call at the start of each task
        decision = gate.check(
            task_id=task_id,
            tool_name=name,
            tool_def=tool.to_dict(),      # CapabilityDefinition.to_dict()
            args=args,
            plan_tool_set=plan_tools,     # optional Set[str] from PLAN phase
        )
        if decision.blocked:
            return {"error": decision.reason}
        if decision.decision == Decision.WARN_ALLOW:
            logger.warning(decision.warn_message)
    """

    def __init__(
        self,
        safety_policy: Optional[SafetyPolicy] = None,
        default_budget: int = _DEFAULT_TASK_BUDGET,
    ) -> None:
        self._policy = safety_policy or SafetyPolicy()
        self._default_budget = default_budget
        self._tasks: Dict[str, _TaskState] = {}

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------

    def reset_task(self, task_id: str, budget: Optional[int] = None) -> None:
        """
        Initialize (or reset) per-task danger budget.
        Call only on fresh task starts — not on resume — so accumulated
        budget carries over across HITL reply cycles.
        """
        self._tasks[task_id] = _TaskState(
            budget=budget if budget is not None else self._default_budget
        )

    def grant_override(self, task_id: str, additional: int = 40) -> None:
        """
        Extend the danger budget for a task by `additional` points.

        Called when the user explicitly says "continue" (or equivalent) in
        response to a STOP_ASK_USER gate escalation.  The user's reply is
        the override authority — this is intentional, not a default bypass.

        Future: replace with a signed token from the client so the override
        authority is cryptographically tied to a specific user action.
        """
        state = self._tasks.setdefault(task_id, _TaskState(budget=self._default_budget))
        state.budget += additional
        logger.info(
            f"Gate override granted for task {task_id}: "
            f"budget extended by {additional} → {state.budget} total"
        )

    def task_summary(self, task_id: str) -> Dict[str, Any]:
        """Return a snapshot of this task's gate activity (for logs/reports)."""
        state = self._tasks.get(task_id)
        if not state:
            return {}
        return {
            "budget_total": state.budget,
            "budget_consumed": state.consumed,
            "budget_remaining": max(0, state.budget - state.consumed),
            "calls_checked": state.calls,
            "calls_blocked": state.blocked,
            "escalations": state.escalations,
        }

    # ------------------------------------------------------------------
    # Core gate
    # ------------------------------------------------------------------

    def check(
        self,
        task_id: str,
        tool_name: str,
        tool_def: Optional[Dict[str, Any]],
        args: Dict[str, Any],
        plan_tool_set: Optional[Set[str]] = None,
    ) -> GateDecision:
        """
        Synchronous gate check.  Returns a GateDecision; never raises.

        Parameters
        ----------
        task_id       : active task identifier (for budget tracking)
        tool_name     : the tool being requested
        tool_def      : CapabilityDefinition.to_dict() or None if unknown
        args          : the arguments passed to the tool call
        plan_tool_set : set of tool names mentioned in the approved plan (optional)
        """
        state = self._tasks.setdefault(task_id, _TaskState(budget=self._default_budget))
        state.calls += 1

        # --- Rule source 1: SafetyPolicy (immutable rules) ---
        policy_result = self._policy.check_tool_execution(tool_name, tool_def, args)
        if not policy_result["allowed"]:
            state.blocked += 1
            self._policy.track_operation(
                operation="gate_block",
                tool_name=tool_name,
                success=False,
                reason=policy_result["reason"],
            )
            return GateDecision(
                decision=Decision.HARD_STOP,
                reason=policy_result["reason"],
                rule_source="safety",
                metadata={"policy_result": policy_result},
            )

        # --- Rule source 2: Danger budget ---
        danger_str = (tool_def or {}).get("danger_level", "low")
        danger_score = _DANGER_SCORE.get(danger_str, 1)
        remaining = state.budget - state.consumed

        if danger_score > 0 and remaining <= 0:
            # Budget exhausted — ask user before proceeding
            state.escalations += 1
            question = (
                f"Task '{task_id}' has accumulated high risk across {state.calls} tool calls "
                f"(danger budget exhausted: {state.consumed}/{state.budget}). "
                f"The next call is '{tool_name}' (danger={danger_str}). "
                "Should I continue, or would you like to review the plan first?"
            )
            return GateDecision(
                decision=Decision.STOP_ASK_USER,
                reason=f"Cumulative danger budget exhausted ({state.consumed}/{state.budget})",
                ask_question=question,
                rule_source="budget",
                metadata={
                    "consumed": state.consumed,
                    "budget": state.budget,
                    "next_tool": tool_name,
                    "next_danger": danger_str,
                },
            )

        if danger_score > 0 and (state.consumed + danger_score) > state.budget:
            # Would exceed budget — warn but allow, user can extend later
            warn_msg = (
                f"Task '{task_id}': tool '{tool_name}' (danger={danger_str}, score={danger_score}) "
                f"would bring cumulative danger to {state.consumed + danger_score}/{state.budget}. "
                "Proceeding, but approaching budget limit."
            )
            state.consumed += danger_score
            return GateDecision(
                decision=Decision.WARN_ALLOW,
                reason="Approaching danger budget limit",
                warn_message=warn_msg,
                rule_source="budget",
                danger_consumed=danger_score,
                metadata={"consumed": state.consumed, "budget": state.budget},
            )

        # --- Rule source 3: Plan scope (soft check) ---
        if plan_tool_set and tool_name not in plan_tool_set:
            warn_msg = (
                f"Tool '{tool_name}' was not mentioned in the approved plan "
                f"(plan tools: {sorted(plan_tool_set)}). "
                "Proceeding — this may indicate the plan needs updating."
            )
            state.consumed += danger_score
            return GateDecision(
                decision=Decision.WARN_ALLOW,
                reason=f"'{tool_name}' is outside the approved plan scope",
                warn_message=warn_msg,
                rule_source="scope",
                danger_consumed=danger_score,
                metadata={"plan_tool_set": sorted(plan_tool_set)},
            )

        # --- ALLOW ---
        state.consumed += danger_score
        return GateDecision(
            decision=Decision.ALLOW,
            reason="ok",
            rule_source="",
            danger_consumed=danger_score,
        )
