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


class ComplexityLevel(str, Enum):
    """Task complexity bands for routing decisions."""
    L1_BASIC = "L1_basic"
    L2_WORKFLOW = "L2_workflow"
    L3_CONSTRAINED = "L3_constrained"
    L4_NOISY = "L4_noisy"
    L5_LONG_HORIZON = "L5_long_horizon"


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
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__ if k in d})


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
