"""
Evaluation data models — shared across runner, store, suites, and doctor surface.

These are the canonical types for the benchmark/evaluation system.  Doctor
actions, the runner, and the store all speak these types so the system stays
decoupled from smoke-specific internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EvalCategory(str, Enum):
    """Top-level evaluation taxonomy."""
    HEALTH = "health"
    QUALIFICATION = "qualification"
    CHARACTERIZATION = "characterization"


class CheckKind(str, Enum):
    """Supported check types for scenario validation."""
    TOOL_CALLED = "tool_called"
    FINAL_ANSWER_PRESENT = "final_answer_present"
    FINAL_ANSWER_CONTAINS = "final_answer_contains"
    FINAL_ANSWER_EFFICIENCY = "final_answer_efficiency"
    FILE_WRITTEN_EXACT = "file_written_exact"
    MIN_TOOL_CALL_COUNT = "min_tool_call_count"
    RETRY_AFTER_FAILURE = "retry_after_failure"
    BACKEND_AVAILABLE = "backend_available"
    DURATION_UNDER = "duration_under"
    TOOL_ARG_CONTAINS = "tool_arg_contains"
    TOOL_ORDER = "tool_order"


class FailureClass(str, Enum):
    """Machine-readable failure categories for routing and doctor output."""
    TOOL_NOT_CALLED = "tool_not_called"
    WRONG_TOOL = "wrong_tool"
    MALFORMED_ARGUMENTS = "malformed_arguments"
    FINAL_ANSWER_MISSING = "final_answer_missing"
    FINAL_ANSWER_SLOW = "final_answer_slow"
    PREMATURE_FINAL_ANSWER = "premature_final_answer"
    TOOL_BACKEND_UNAVAILABLE = "tool_backend_unavailable"
    EXECUTOR_EXCEPTION = "executor_exception"
    TIMEOUT = "timeout"
    XML_TOOL_LEAKAGE = "xml_tool_leakage"
    VERIFICATION_MISMATCH = "verification_mismatch"
    DURATION_EXCEEDED = "duration_exceeded"
    WRONG_TOOL_ARGS = "wrong_tool_args"
    WRONG_ORDER = "wrong_order"


class ComplexityLevel(str, Enum):
    """Task complexity bands for routing decisions (v2 unified ladder).

    Ordered from simplest to most demanding. The order is used by
    ``_compute_max_complexity`` to report the highest rung a resource
    has cleared all runs on.
    """
    L1_SINGLE_CALL = "L1_single_call"
    L2_MULTI_STEP = "L2_multi_step"
    L3_FEEDBACK = "L3_feedback"
    L4_ORCHESTRATION = "L4_orchestration"

    @classmethod
    def _missing_(cls, value):
        # Tolerate legacy v1 labels (e.g. persisted scenario dicts) by mapping
        # them through the v1->v2 table. Keeps direct ComplexityLevel(old)
        # calls and EvalScenario.from_dict from crashing on old data.
        if isinstance(value, str):
            mapped = _LEGACY_LEVEL_MAP.get(value)
            if mapped is not None:
                return mapped
        return None


# Maps the v1 (drifted) 5-level labels used in persisted eval records
# to the v2 unified 4-level ladder. Applied on read so old eval_log.jsonl
# files round-trip without crashing. See llm_routing_benchmark_design.md v2.
_LEGACY_LEVEL_MAP: Dict[str, ComplexityLevel] = {
    "L1_basic":          ComplexityLevel.L1_SINGLE_CALL,
    "L2_workflow":       ComplexityLevel.L2_MULTI_STEP,
    "L3_constrained":    ComplexityLevel.L3_FEEDBACK,
    "L4_noisy":          ComplexityLevel.L2_MULTI_STEP,   # noise is a trait, not a rung (now a tag)
    "L5_long_horizon":   ComplexityLevel.L2_MULTI_STEP,   # L5 abolished; planned multi-step → L2
}


def translate_legacy_level(value: str) -> str:
    """Translate a legacy v1 complexity label to the v2 ladder.

    Returns the v2 enum value. Unknown values pass through unchanged so
    new (already-canonical) strings round-trip cleanly.
    """
    if value in ComplexityLevel.__members__.values():
        return value
    mapped = _LEGACY_LEVEL_MAP.get(value)
    return mapped.value if mapped is not None else value


class ToolSchemaMode(str, Enum):
    """Tool schema presentation modes for characterization."""
    FULL = "full"
    LEAN = "lean"
    EITHER = "either"


# ---------------------------------------------------------------------------
# Check definition
# ---------------------------------------------------------------------------

@dataclass
class EvalCheck:
    """A single pass/fail criterion within a scenario.

    kind:   which CheckKind to evaluate
    params: kind-specific parameters (e.g. tool_name, expected_value, max_seconds)
    required: if True, failing this check fails the whole scenario
    failure_class: FailureClass to assign on failure
    """
    id: str
    kind: CheckKind
    required: bool = True
    failure_class: Optional[FailureClass] = None
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        if self.failure_class:
            d["failure_class"] = self.failure_class.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvalCheck":
        return cls(
            id=d["id"],
            kind=CheckKind(d["kind"]),
            required=d.get("required", True),
            failure_class=FailureClass(d["failure_class"]) if d.get("failure_class") else None,
            params=d.get("params", {}),
        )


# ---------------------------------------------------------------------------
# Scenario definition
# ---------------------------------------------------------------------------

@dataclass
class EvalScenario:
    """A declarative evaluation scenario.

    goal_template:       the goal string sent to the executor (may contain {resource_id} etc.)
    available_tools:     tool names the model may use
    checks:              list of EvalCheck to evaluate after execution
    suite:               which suite this scenario belongs to
    category:            health / qualification / characterization
    task_family:         e.g. "lookup", "write", "retry", "constraint_solving"
    complexity_level:    L1–L5
    tool_schema_mode:    full / lean / either
    max_iterations:      executor iteration cap
    max_duration_seconds: executor wall-clock cap
    requires_backends:   list of backend names that must be available (e.g. ["memory_search"])
    artifact_expectations: expected file paths or artifacts after execution
    tags:                arbitrary tags for filtering
    """
    id: str
    suite: str
    category: EvalCategory
    task_family: str
    complexity_level: ComplexityLevel
    goal_template: str
    available_tools: List[str]
    checks: List[EvalCheck]
    tool_schema_mode: ToolSchemaMode = ToolSchemaMode.EITHER
    max_iterations: int = 4
    max_duration_seconds: int = 90
    requires_backends: List[str] = field(default_factory=list)
    artifact_expectations: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "suite": self.suite,
            "category": self.category.value,
            "task_family": self.task_family,
            "complexity_level": self.complexity_level.value,
            "goal_template": self.goal_template,
            "available_tools": self.available_tools,
            "checks": [c.to_dict() for c in self.checks],
            "tool_schema_mode": self.tool_schema_mode.value,
            "max_iterations": self.max_iterations,
            "max_duration_seconds": self.max_duration_seconds,
            "requires_backends": self.requires_backends,
            "artifact_expectations": self.artifact_expectations,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvalScenario":
        return cls(
            id=d["id"],
            suite=d["suite"],
            category=EvalCategory(d["category"]),
            task_family=d["task_family"],
            complexity_level=ComplexityLevel(d["complexity_level"]),
            goal_template=d["goal_template"],
            available_tools=d["available_tools"],
            checks=[EvalCheck.from_dict(c) for c in d.get("checks", [])],
            tool_schema_mode=ToolSchemaMode(d.get("tool_schema_mode", "either")),
            max_iterations=d.get("max_iterations", 4),
            max_duration_seconds=d.get("max_duration_seconds", 90),
            requires_backends=d.get("requires_backends", []),
            artifact_expectations=d.get("artifact_expectations", []),
            tags=d.get("tags", []),
        )


# ---------------------------------------------------------------------------
# Suite definition
# ---------------------------------------------------------------------------

@dataclass
class EvalSuite:
    """A named collection of scenarios that run together.

    gating_policy:    which checks must pass for the suite to be considered passed
    summary_metrics:  which metrics to include in the suite summary
    """
    id: str
    display_name: str
    category: EvalCategory
    default_scenarios: List[str]  # scenario IDs
    gating_policy: Dict[str, Any] = field(default_factory=dict)
    summary_metrics: List[str] = field(default_factory=lambda: [
        "success_rate", "avg_duration", "p95_duration", "failing_checks",
    ])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "category": self.category.value,
            "default_scenarios": self.default_scenarios,
            "gating_policy": self.gating_policy,
            "summary_metrics": self.summary_metrics,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvalSuite":
        return cls(
            id=d["id"],
            display_name=d["display_name"],
            category=EvalCategory(d["category"]),
            default_scenarios=d["default_scenarios"],
            gating_policy=d.get("gating_policy", {}),
            summary_metrics=d.get("summary_metrics", [
                "success_rate", "avg_duration", "p95_duration", "failing_checks",
            ]),
        )


# ---------------------------------------------------------------------------
# Check result (outcome of evaluating one EvalCheck)
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Outcome of evaluating a single EvalCheck."""
    check_id: str
    kind: CheckKind
    status: str  # "pass" | "fail" | "skip"
    failure_class: Optional[str] = None
    message: str = ""
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CheckResult":
        return cls(
            check_id=d["check_id"],
            kind=CheckKind(d["kind"]),
            status=d["status"],
            failure_class=d.get("failure_class"),
            message=d.get("message", ""),
            params=d.get("params", {}),
        )


# ---------------------------------------------------------------------------
# Eval record (persisted to eval_log.jsonl)
# ---------------------------------------------------------------------------

@dataclass
class EvalRecord:
    """A single evaluation run record — append-only to eval_log.jsonl."""
    ts: str
    resource_id: str
    model: str
    suite: str
    scenario_id: str
    category: str
    task_family: str
    complexity_level: str
    tool_schema_mode: str
    success: bool
    checks: List[Dict[str, Any]]
    iterations_used: int
    duration_seconds: float
    artifacts: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    debug_artifact_path: Optional[str] = None
    skipped: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvalRecord":
        """Build an EvalRecord, translating any v1 complexity label to v2.

        Persisted eval_log.jsonl records from before the v2 ladder rewrite
        may carry labels like ``L2_workflow`` or ``L5_long_horizon``. We
        accept those and normalize them on read rather than crash.
        """
        kwargs = {k: d.get(k) for k in cls.__dataclass_fields__ if k in d}
        if "complexity_level" in kwargs and kwargs["complexity_level"] is not None:
            kwargs["complexity_level"] = translate_legacy_level(kwargs["complexity_level"])
        return cls(**kwargs)


# ---------------------------------------------------------------------------
# Capability summary (derived from eval history)
# ---------------------------------------------------------------------------

@dataclass
class CapabilitySummary:
    """Derived capability card for a resource — drives routing decisions."""
    resource_id: str
    model: str
    qualified_for_basic_agentic: Optional[bool] = None
    qualified_for_standard_agentic: Optional[bool] = None
    qualified_for_reasoning_tasks: Optional[bool] = None
    max_reliable_complexity: Optional[str] = None
    median_fast_gate_s: Optional[float] = None
    median_standard_agentic_s: Optional[float] = None
    tool_accuracy: Optional[float] = None
    retry_recovery_rate: Optional[float] = None
    constraint_accuracy: Optional[float] = None
    schema_sensitivity: Optional[float] = None
    last_evaluated_at: Optional[str] = None
    total_evals: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Failure classification (A7)
# ---------------------------------------------------------------------------
#
# A pure classifier used by the routing profiler and (in principle) by any
# downstream tool that needs to bucket a per-task result into a FailureClass.
# Kept side-effect-free and import-light so the profiler can call it without
# pulling the scheduler into the test path.

# Cheap heuristic cutoffs. Tuned against observed LM Studio + Qwen/Ornith runs;
# the same constants appear in the A7 unit tests so a flip forces a test flip.
SLOW_DURATION_S = 30.0      # > this on a successful task -> final_answer_slow
TIMEOUT_DURATION_S = 120.0  # > this on any task -> timeout (assumed iteration cap hit)


def classify_failure(
    *,
    success: bool,
    elapsed_s: float,
    error: Optional[str] = None,
    response: str = "",
    iterations: int = 1,
) -> FailureClass:
    """Classify a single profiling-task result into a FailureClass.

    Pure function — no I/O, no logging. Returns ``FailureClass.*``.

    The classifier expresses the routing-relevant question: "what was the
    *kind* of failure (or near-failure)?" so the router can decide between
    route-up (verification mismatch), raise-budget (slow/timeout), or
    hard-disqualify (leakage/malformed).

    For successful tasks the function still returns a class because routing
    needs to know whether a model is *capable but slow* (a budget-hint
    signal) versus capable and clean. Returns ``None`` only when the run is
    successful *and* fast *and* clean — i.e. nothing to signal.
    """
    # Error path — backend / executor surfaced an exception.
    if error:
        e = error.lower()
        if "timeout" in e or "timed out" in e:
            return FailureClass.TIMEOUT
        if "backend" in e or "unavailable" in e or "connection" in e:
            return FailureClass.TOOL_BACKEND_UNAVAILABLE
        if "xml" in e or "<functioncall" in response.lower() or "<|tool_call" in response.lower():
            return FailureClass.XML_TOOL_LEAKAGE
        if "malformed" in e or "invalid arguments" in e:
            return FailureClass.MALFORMED_ARGUMENTS
        return FailureClass.EXECUTOR_EXCEPTION

    # Raw response signals — checked even on success because leakage in the
    # body of an otherwise-correct answer is still a disqualifier.
    resp_lower = (response or "").lower()
    if "<functioncall" in resp_lower or "<|tool_call" in resp_lower:
        return FailureClass.XML_TOOL_LEAKAGE
    if response and not success and ("{" in response and "}" in response and '"' in response):
        # Heuristic: a JSON-ish blob in a failed task hints at malformed tool args.
        if "arguments" in resp_lower or "args" in resp_lower:
            return FailureClass.MALFORMED_ARGUMENTS

    # Duration signals — applies regardless of success.
    if elapsed_s >= TIMEOUT_DURATION_S:
        return FailureClass.TIMEOUT
    if elapsed_s >= SLOW_DURATION_S and success:
        return FailureClass.FINAL_ANSWER_SLOW

    # Success / failure branch.
    if success:
        # Clean pass — no failure class to signal.
        return None  # type: ignore[return-value]
    # Failed but no error string and no signal above -> the verification itself
    # rejected the answer. That's a capability ceiling -> route up.
    return FailureClass.VERIFICATION_MISMATCH
