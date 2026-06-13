"""
Suite definitions — named collections of scenarios that run together.

Each suite maps to a qualification or characterization goal:
  - qualification_fast:      replace current fast_gate
  - qualification_standard:  replace current standard_agentic
  - qualification_reasoning: replace current reasoning_stress
  - characterization_tool_schema: full vs lean comparison
  - characterization_complexity_ladder: L1–L5 capability classification
"""

from __future__ import annotations

from typing import Dict, List

from app.scheduler.evals.models import EvalSuite, EvalCategory


# ---------------------------------------------------------------------------
# Suite definitions
# ---------------------------------------------------------------------------

QUALIFICATION_FAST = EvalSuite(
    id="qualification_fast",
    display_name="Fast Gate",
    category=EvalCategory.QUALIFICATION,
    default_scenarios=[
        "qualification.fast.lookup_basic",
        "qualification.fast.write_basic",
    ],
    gating_policy={"all_required_must_pass": True},
    summary_metrics=["success_rate", "avg_duration", "failing_checks"],
)

QUALIFICATION_STANDARD = EvalSuite(
    id="qualification_standard",
    display_name="Standard Agentic",
    category=EvalCategory.QUALIFICATION,
    default_scenarios=[
        "qualification.fast.lookup_basic",
        "qualification.fast.write_basic",
        "qualification.standard.lookup_then_write",
        "qualification.standard.retry_once",
    ],
    gating_policy={"all_required_must_pass": True},
    summary_metrics=[
        "success_rate", "avg_duration", "p95_duration",
        "tool_accuracy", "retry_recovery_rate", "failing_checks",
    ],
)

QUALIFICATION_REASONING = EvalSuite(
    id="qualification_reasoning",
    display_name="Reasoning Stress",
    category=EvalCategory.QUALIFICATION,
    default_scenarios=[
        "qualification.fast.lookup_basic",
        "qualification.fast.write_basic",
        "qualification.standard.lookup_then_write",
        "qualification.standard.retry_once",
        "qualification.reasoning.constraint_plan_choice",
    ],
    gating_policy={"all_required_must_pass": True},
    summary_metrics=[
        "success_rate", "avg_duration", "p95_duration",
        "tool_accuracy", "retry_recovery_rate", "constraint_accuracy",
        "failing_checks",
    ],
)

CHARACTERIZATION_TOOL_SCHEMA = EvalSuite(
    id="characterization_tool_schema",
    display_name="Tool Schema Comparison",
    category=EvalCategory.CHARACTERIZATION,
    default_scenarios=[
        "qualification.fast.lookup_basic",
        "qualification.standard.lookup_then_write",
    ],
    gating_policy={"compare_modes": True},
    summary_metrics=["schema_sensitivity", "avg_duration"],
)

CHARACTERIZATION_COMPLEXITY_LADDER = EvalSuite(
    id="characterization_complexity_ladder",
    display_name="Complexity Ladder",
    category=EvalCategory.CHARACTERIZATION,
    default_scenarios=[
        "qualification.fast.lookup_basic",
        "qualification.fast.write_basic",
        "qualification.standard.lookup_then_write",
        "qualification.standard.retry_once",
        "qualification.reasoning.constraint_plan_choice",
        "characterization.ladder.noisy_context_lookup",
        "characterization.ladder.long_horizon_multi_lookup",
    ],
    gating_policy={"max_passing_complexity": True},
    summary_metrics=[
        "max_reliable_complexity", "success_rate", "avg_duration",
        "tool_accuracy", "retry_recovery_rate", "constraint_accuracy",
    ],
)


# ---------------------------------------------------------------------------
# Suite registry
# ---------------------------------------------------------------------------

ALL_SUITES: Dict[str, EvalSuite] = {
    s.id: s for s in [
        QUALIFICATION_FAST,
        QUALIFICATION_STANDARD,
        QUALIFICATION_REASONING,
        CHARACTERIZATION_TOOL_SCHEMA,
        CHARACTERIZATION_COMPLEXITY_LADDER,
    ]
}


def get_suite(suite_id: str) -> EvalSuite:
    """Look up a suite by ID."""
    s = ALL_SUITES.get(suite_id)
    if s is None:
        raise ValueError(f"Unknown suite: {suite_id}. Known: {sorted(ALL_SUITES)}")
    return s


def list_suites(category: str = None) -> List[EvalSuite]:
    """List suites with optional category filter."""
    results = list(ALL_SUITES.values())
    if category:
        results = [s for s in results if s.category.value == category]
    return results
