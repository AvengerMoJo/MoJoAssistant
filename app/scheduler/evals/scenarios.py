"""
Declarative scenario definitions for the evaluation system.

Each scenario is a self-contained description of what to run, what tools to
grant, and what checks to evaluate.  The runner interprets these definitions
without needing scenario-specific branching logic.

Scenario IDs follow the convention:  {category}.{suite}.{task_family}
"""

from __future__ import annotations

from typing import Dict

from app.scheduler.evals.models import (
    EvalScenario, EvalCheck, EvalCategory, CheckKind, FailureClass,
    ComplexityLevel, ToolSchemaMode,
)


# ---------------------------------------------------------------------------
# L1 Basic — deterministic single-tool scenarios
# ---------------------------------------------------------------------------

LOOKUP_BASIC = EvalScenario(
    id="qualification.fast.lookup_basic",
    suite="qualification_fast",
    category=EvalCategory.QUALIFICATION,
    task_family="lookup",
    complexity_level=ComplexityLevel.L1_BASIC,
    goal_template=(
        "Use the smoke_lookup tool with query '{key}'. "
        "Then provide a <FINAL_ANSWER> with the exact token value you received."
    ),
    available_tools=["smoke_lookup"],
    checks=[
        EvalCheck(
            id="tool_called",
            kind=CheckKind.TOOL_CALLED,
            required=True,
            failure_class=FailureClass.TOOL_NOT_CALLED,
            params={"tool_name": "smoke_lookup"},
        ),
        EvalCheck(
            id="final_answer",
            kind=CheckKind.FINAL_ANSWER_PRESENT,
            required=True,
            failure_class=FailureClass.FINAL_ANSWER_MISSING,
        ),
    ],
    max_iterations=4,
    max_duration_seconds=45,
    tags=["deterministic", "fast"],
)

WRITE_BASIC = EvalScenario(
    id="qualification.fast.write_basic",
    suite="qualification_fast",
    category=EvalCategory.QUALIFICATION,
    task_family="write",
    complexity_level=ComplexityLevel.L1_BASIC,
    goal_template=(
        "Call write_file to write 'smoke_test_ok' to '{write_path}'. "
        "Then provide a <FINAL_ANSWER> confirming the write succeeded."
    ),
    available_tools=["write_file"],
    checks=[
        EvalCheck(
            id="tool_called",
            kind=CheckKind.TOOL_CALLED,
            required=True,
            failure_class=FailureClass.TOOL_NOT_CALLED,
            params={"tool_name": "write_file"},
        ),
        EvalCheck(
            id="file_written",
            kind=CheckKind.FILE_WRITTEN_EXACT,
            required=True,
            failure_class=FailureClass.XML_TOOL_LEAKAGE,
            params={"expected_content": "smoke_test_ok"},
        ),
        EvalCheck(
            id="final_answer",
            kind=CheckKind.FINAL_ANSWER_PRESENT,
            required=True,
            failure_class=FailureClass.FINAL_ANSWER_MISSING,
        ),
    ],
    max_iterations=5,
    max_duration_seconds=60,
    tags=["deterministic", "fast", "xml_leakage_detection"],
)


# ---------------------------------------------------------------------------
# L2 Workflow — multi-step read-then-write
# ---------------------------------------------------------------------------

LOOKUP_THEN_WRITE = EvalScenario(
    id="qualification.standard.lookup_then_write",
    suite="qualification_standard",
    category=EvalCategory.QUALIFICATION,
    task_family="workflow",
    complexity_level=ComplexityLevel.L2_WORKFLOW,
    goal_template=(
        "You need to find the token for the project that satisfies ALL of these constraints: "
        "contains the letter 'g', has a token ending in '6'. "
        "Use smoke_lookup to look up keys 'alpha', 'beta', 'gamma', 'delta'. "
        "Then use write_file to write the matching token to '{write_path}'. "
        "Provide a <FINAL_ANSWER> with the exact token you wrote."
    ),
    available_tools=["smoke_lookup", "write_file"],
    checks=[
        EvalCheck(
            id="lookup_called",
            kind=CheckKind.TOOL_CALLED,
            required=True,
            failure_class=FailureClass.TOOL_NOT_CALLED,
            params={"tool_name": "smoke_lookup"},
        ),
        EvalCheck(
            id="write_called",
            kind=CheckKind.TOOL_CALLED,
            required=True,
            failure_class=FailureClass.WRONG_TOOL,
            params={"tool_name": "write_file"},
        ),
        EvalCheck(
            id="correct_answer",
            kind=CheckKind.FINAL_ANSWER_CONTAINS,
            required=True,
            failure_class=FailureClass.VERIFICATION_MISMATCH,
            params={"expected": "g1f8a6"},
        ),
        EvalCheck(
            id="file_written",
            kind=CheckKind.FILE_WRITTEN_EXACT,
            required=True,
            failure_class=FailureClass.VERIFICATION_MISMATCH,
            params={"expected_content": "g1f8a6"},
        ),
    ],
    max_iterations=8,
    max_duration_seconds=120,
    tags=["workflow", "multi_step"],
)

RETRY_ONCE = EvalScenario(
    id="qualification.standard.retry_once",
    suite="qualification_standard",
    category=EvalCategory.QUALIFICATION,
    task_family="retry",
    complexity_level=ComplexityLevel.L2_WORKFLOW,
    goal_template=(
        "Call the smoke_fail_once tool with key 'test'. "
        "If it returns an error with retryable=true, call it again with the same key. "
        "Keep retrying until it succeeds. "
        "Then provide a <FINAL_ANSWER> with the result value you received."
    ),
    available_tools=["smoke_fail_once"],
    checks=[
        EvalCheck(
            id="retry_after_failure",
            kind=CheckKind.RETRY_AFTER_FAILURE,
            required=True,
            failure_class=FailureClass.TOOL_NOT_CALLED,
            params={"tool_name": "smoke_fail_once", "min_calls": 2},
        ),
        EvalCheck(
            id="correct_result",
            kind=CheckKind.FINAL_ANSWER_CONTAINS,
            required=True,
            failure_class=FailureClass.VERIFICATION_MISMATCH,
            params={"expected": "smoke_retry_ok"},
        ),
    ],
    max_iterations=6,
    max_duration_seconds=90,
    tags=["retry", "resilience"],
)


# ---------------------------------------------------------------------------
# L3 Constrained reasoning
# ---------------------------------------------------------------------------

CONSTRAINT_PLAN_CHOICE = EvalScenario(
    id="qualification.reasoning.constraint_plan_choice",
    suite="qualification_reasoning",
    category=EvalCategory.QUALIFICATION,
    task_family="constraint_solving",
    complexity_level=ComplexityLevel.L3_CONSTRAINED,
    goal_template=(
        "You have four project options with different properties:\n"
        "- Project A: cost=low, speed=fast, reliability=medium\n"
        "- Project B: cost=high, speed=slow, reliability=high\n"
        "- Project C: cost=medium, speed=fast, reliability=high\n"
        "- Project D: cost=low, speed=slow, reliability=low\n\n"
        "Constraints: must have 'high' reliability AND 'fast' speed.\n"
        "Use smoke_compare to evaluate all options against the constraints. "
        "Then use write_file to write the name of the valid option to '{write_path}'. "
        "Provide a <FINAL_ANSWER> explaining which option satisfies all constraints and why the others fail."
    ),
    available_tools=["smoke_compare", "write_file"],
    checks=[
        EvalCheck(
            id="compare_called",
            kind=CheckKind.TOOL_CALLED,
            required=True,
            failure_class=FailureClass.TOOL_NOT_CALLED,
            params={"tool_name": "smoke_compare"},
        ),
        EvalCheck(
            id="write_called",
            kind=CheckKind.TOOL_CALLED,
            required=True,
            failure_class=FailureClass.WRONG_TOOL,
            params={"tool_name": "write_file"},
        ),
        EvalCheck(
            id="correct_choice",
            kind=CheckKind.FINAL_ANSWER_CONTAINS,
            required=True,
            failure_class=FailureClass.VERIFICATION_MISMATCH,
            params={"expected": "project c"},
        ),
    ],
    max_iterations=12,
    max_duration_seconds=300,
    tags=["reasoning", "constraint_solving"],
)


# ---------------------------------------------------------------------------
# L4 Noisy context — model must extract signal from distractors
# ---------------------------------------------------------------------------

NOISY_CONTEXT_LOOKUP = EvalScenario(
    id="characterization.ladder.noisy_context_lookup",
    suite="characterization_complexity_ladder",
    category=EvalCategory.CHARACTERIZATION,
    task_family="noisy_context",
    complexity_level=ComplexityLevel.L4_NOISY,
    goal_template=(
        "You have been given several irrelevant notes about project budgets and timelines.\n"
        "Ignore all of them. Focus only on the task:\n\n"
        "TASK: Use smoke_lookup to find the token for key 'gamma'.\n"
        "Then use write_file to write ONLY the token value to '{write_path}'.\n"
        "Provide a <FINAL_ANSWER> with the exact token.\n\n"
        "IRRELEVANT CONTEXT:\n"
        "- Budget meeting moved to Thursday\n"
        "- Project Alpha deadline extended to Q3\n"
        "- Server migration complete, all green\n"
        "- Lunch order: vegetarian option available\n"
        "- Quarterly report draft attached below"
    ),
    available_tools=["smoke_lookup", "write_file"],
    checks=[
        EvalCheck(
            id="lookup_called",
            kind=CheckKind.TOOL_CALLED,
            required=True,
            failure_class=FailureClass.TOOL_NOT_CALLED,
            params={"tool_name": "smoke_lookup"},
        ),
        EvalCheck(
            id="correct_answer",
            kind=CheckKind.FINAL_ANSWER_CONTAINS,
            required=True,
            failure_class=FailureClass.VERIFICATION_MISMATCH,
            params={"expected": "g1f8a6"},
        ),
    ],
    max_iterations=6,
    max_duration_seconds=90,
    tags=["characterization", "noisy", "ladder"],
)


# ---------------------------------------------------------------------------
# L5 Long-horizon — multi-step planning with intermediate verification
# ---------------------------------------------------------------------------

LONG_HORIZON_MULTI_LOOKUP = EvalScenario(
    id="characterization.ladder.long_horizon_multi_lookup",
    suite="characterization_complexity_ladder",
    category=EvalCategory.CHARACTERIZATION,
    task_family="long_horizon",
    complexity_level=ComplexityLevel.L5_LONG_HORIZON,
    goal_template=(
        "You need to gather tokens from multiple sources and combine them.\n\n"
        "Steps:\n"
        "1. Use smoke_lookup with query 'alpha' — note the token\n"
        "2. Use smoke_lookup with query 'gamma' — note the token\n"
        "3. Use write_file to write BOTH tokens (one per line) to '{write_path}'\n"
        "4. Provide a <FINAL_ANSWER> with both tokens separated by a newline"
    ),
    available_tools=["smoke_lookup", "write_file"],
    checks=[
        EvalCheck(
            id="min_lookups",
            kind=CheckKind.MIN_TOOL_CALL_COUNT,
            required=True,
            failure_class=FailureClass.TOOL_NOT_CALLED,
            params={"tool_name": "smoke_lookup", "min_count": 2},
        ),
        EvalCheck(
            id="write_called",
            kind=CheckKind.TOOL_CALLED,
            required=True,
            failure_class=FailureClass.WRONG_TOOL,
            params={"tool_name": "write_file"},
        ),
        EvalCheck(
            id="contains_alpha_token",
            kind=CheckKind.FINAL_ANSWER_CONTAINS,
            required=True,
            failure_class=FailureClass.VERIFICATION_MISMATCH,
            params={"expected": "a7c3f1"},
        ),
        EvalCheck(
            id="contains_gamma_token",
            kind=CheckKind.FINAL_ANSWER_CONTAINS,
            required=True,
            failure_class=FailureClass.VERIFICATION_MISMATCH,
            params={"expected": "g1f8a6"},
        ),
    ],
    max_iterations=8,
    max_duration_seconds=120,
    tags=["characterization", "long_horizon", "ladder"],
)


# ---------------------------------------------------------------------------
# Integration — real backend checks
# ---------------------------------------------------------------------------

INTEGRATION_BASH_EXEC = EvalScenario(
    id="qualification.integration.bash_exec",
    suite="qualification_fast",
    category=EvalCategory.QUALIFICATION,
    task_family="bash_exec",
    complexity_level=ComplexityLevel.L1_BASIC,
    goal_template=(
        "Use bash_exec to run: echo 'smoke_integration_ok'. "
        "Then provide a <FINAL_ANSWER> with the exact output."
    ),
    available_tools=["bash_exec"],
    checks=[
        EvalCheck(
            id="bash_called",
            kind=CheckKind.TOOL_CALLED,
            required=True,
            failure_class=FailureClass.TOOL_NOT_CALLED,
            params={"tool_name": "bash_exec"},
        ),
        EvalCheck(
            id="output_matches",
            kind=CheckKind.FINAL_ANSWER_CONTAINS,
            required=True,
            failure_class=FailureClass.VERIFICATION_MISMATCH,
            params={"expected": "smoke_integration_ok"},
        ),
    ],
    max_iterations=4,
    max_duration_seconds=60,
    requires_backends=["bash_exec"],
    tags=["integration", "backend"],
)

INTEGRATION_MEMORY_SEARCH = EvalScenario(
    id="qualification.integration.memory_search",
    suite="qualification_fast",
    category=EvalCategory.QUALIFICATION,
    task_family="memory_search",
    complexity_level=ComplexityLevel.L1_BASIC,
    goal_template=(
        "Use memory_search with query 'test' to search the knowledge base. "
        "Provide a <FINAL_ANSWER> summarizing what you found, or saying 'no results' if empty."
    ),
    available_tools=["memory_search"],
    checks=[
        EvalCheck(
            id="search_called",
            kind=CheckKind.TOOL_CALLED,
            required=True,
            failure_class=FailureClass.TOOL_NOT_CALLED,
            params={"tool_name": "memory_search"},
        ),
        EvalCheck(
            id="final_answer",
            kind=CheckKind.FINAL_ANSWER_PRESENT,
            required=True,
            failure_class=FailureClass.FINAL_ANSWER_MISSING,
        ),
    ],
    max_iterations=4,
    max_duration_seconds=60,
    requires_backends=["memory_search"],
    tags=["integration", "backend"],
)


# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------

ALL_SCENARIOS: Dict[str, EvalScenario] = {}
for _s in [
    LOOKUP_BASIC, WRITE_BASIC,
    LOOKUP_THEN_WRITE, RETRY_ONCE,
    CONSTRAINT_PLAN_CHOICE,
    NOISY_CONTEXT_LOOKUP, LONG_HORIZON_MULTI_LOOKUP,
    INTEGRATION_BASH_EXEC, INTEGRATION_MEMORY_SEARCH,
]:
    ALL_SCENARIOS[_s.id] = _s


def get_scenario(scenario_id: str) -> EvalScenario:
    """Look up a scenario by ID."""
    s = ALL_SCENARIOS.get(scenario_id)
    if s is None:
        raise ValueError(f"Unknown scenario: {scenario_id}. Known: {sorted(ALL_SCENARIOS)}")
    return s


def list_scenarios(
    category: str = None,
    suite: str = None,
    complexity: str = None,
) -> list:
    """List scenarios with optional filters."""
    results = list(ALL_SCENARIOS.values())
    if category:
        results = [s for s in results if s.category.value == category]
    if suite:
        results = [s for s in results if s.suite == suite]
    if complexity:
        results = [s for s in results if s.complexity_level.value == complexity]
    return results
