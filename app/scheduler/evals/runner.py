"""
Generic evaluation runner — executes scenarios and evaluates checks.

This is the engine behind doctor_eval_run.  It interprets EvalScenario
definitions, runs them through the AgenticExecutor, and evaluates the
resulting checks without scenario-specific branching.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.scheduler.evals.models import (
    EvalScenario, EvalCheck, CheckKind, CheckResult, EvalRecord,
    FailureClass, ToolSchemaMode,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Single-resource resource manager (reused from smoke test)
# ---------------------------------------------------------------------------

class _SingleResourceManager:
    def __init__(self, resource):
        self._resource = resource
        self._resources = {resource.id: resource} if resource else {}

    def acquire(self, **kwargs):
        return self._resource

    def release(self, resource_id: str) -> None:
        pass

    def record_usage(self, resource_id: str, success: bool) -> None:
        pass


# ---------------------------------------------------------------------------
# Check evaluator
# ---------------------------------------------------------------------------

def evaluate_checks(
    checks: List[EvalCheck],
    iteration_log: List[Dict],
    final_answer: Optional[str],
    duration_seconds: float,
    artifacts: Dict[str, Any],
) -> List[CheckResult]:
    """Evaluate a list of checks against execution results."""
    results = []

    for check in checks:
        try:
            result = _evaluate_single_check(
                check, iteration_log, final_answer, duration_seconds, artifacts,
            )
            results.append(result)
        except Exception as e:
            results.append(CheckResult(
                check_id=check.id,
                kind=check.kind,
                status="fail",
                failure_class=check.failure_class.value if check.failure_class else None,
                message=f"Check evaluation error: {e}",
            ))

    return results


def _evaluate_single_check(
    check: EvalCheck,
    iteration_log: List[Dict],
    final_answer: Optional[str],
    duration_seconds: float,
    artifacts: Dict[str, Any],
) -> CheckResult:
    """Evaluate a single check."""
    params = check.params

    if check.kind == CheckKind.TOOL_CALLED:
        tool_name = params.get("tool_name", "")
        called = any(
            e.get("status") == "tool_use" and tool_name in e.get("tool_calls", [])
            for e in iteration_log
        )
        return CheckResult(
            check_id=check.id,
            kind=check.kind,
            status="pass" if called else "fail",
            failure_class=check.failure_class.value if check.failure_class and not called else None,
            message=f"Model called {tool_name}" if called else f"Model did not call {tool_name}",
        )

    elif check.kind == CheckKind.FINAL_ANSWER_PRESENT:
        present = bool(final_answer)
        return CheckResult(
            check_id=check.id,
            kind=check.kind,
            status="pass" if present else "fail",
            failure_class=check.failure_class.value if check.failure_class and not present else None,
            message="FINAL_ANSWER present" if present else "FINAL_ANSWER missing",
        )

    elif check.kind == CheckKind.FINAL_ANSWER_CONTAINS:
        expected = params.get("expected", "")
        found = final_answer and expected.lower() in final_answer.lower()
        return CheckResult(
            check_id=check.id,
            kind=check.kind,
            status="pass" if found else "fail",
            failure_class=check.failure_class.value if check.failure_class and not found else None,
            message=f"FINAL_ANSWER contains '{expected}'" if found else f"FINAL_ANSWER missing '{expected}'",
        )

    elif check.kind == CheckKind.FILE_WRITTEN_EXACT:
        expected_content = params.get("expected_content", "")
        artifact_path = artifacts.get("write_path", "")
        actual_content = artifacts.get("file_content", "")
        if not actual_content and artifact_path and os.path.isfile(artifact_path):
            actual_content = open(artifact_path).read().strip()
        match = actual_content == expected_content
        return CheckResult(
            check_id=check.id,
            kind=check.kind,
            status="pass" if match else "fail",
            failure_class=check.failure_class.value if check.failure_class and not match else None,
            message=f"File content matches" if match else f"File content mismatch: got '{actual_content}'",
        )

    elif check.kind == CheckKind.MIN_TOOL_CALL_COUNT:
        min_count = params.get("min_count", 1)
        tool_name = params.get("tool_name")
        count = sum(
            len([t for t in e.get("tool_calls", []) if not tool_name or t == tool_name])
            for e in iteration_log
            if e.get("status") == "tool_use"
        )
        ok = count >= min_count
        return CheckResult(
            check_id=check.id,
            kind=check.kind,
            status="pass" if ok else "fail",
            failure_class=check.failure_class.value if check.failure_class and not ok else None,
            message=f"Tool call count {count} >= {min_count}" if ok else f"Tool call count {count} < {min_count}",
        )

    elif check.kind == CheckKind.RETRY_AFTER_FAILURE:
        tool_name = params.get("tool_name", "")
        min_calls = params.get("min_calls", 2)
        calls = sum(
            1 for e in iteration_log
            if e.get("status") == "tool_use" and tool_name in e.get("tool_calls", [])
        )
        ok = calls >= min_calls
        return CheckResult(
            check_id=check.id,
            kind=check.kind,
            status="pass" if ok else "fail",
            failure_class=check.failure_class.value if check.failure_class and not ok else None,
            message=f"Retried {calls} times (>= {min_calls})" if ok else f"Only {calls} calls (< {min_calls})",
        )

    elif check.kind == CheckKind.BACKEND_AVAILABLE:
        available = artifacts.get("backend_available", True)
        return CheckResult(
            check_id=check.id,
            kind=check.kind,
            status="pass" if available else "skip",
            failure_class=FailureClass.TOOL_BACKEND_UNAVAILABLE.value if not available else None,
            message="Backend available" if available else "Backend unavailable",
        )

    elif check.kind == CheckKind.DURATION_UNDER:
        max_seconds = params.get("max_seconds", 90)
        ok = duration_seconds <= max_seconds
        return CheckResult(
            check_id=check.id,
            kind=check.kind,
            status="pass" if ok else "fail",
            failure_class=FailureClass.DURATION_EXCEEDED.value if not ok else None,
            message=f"Duration {duration_seconds:.1f}s <= {max_seconds}s" if ok else f"Duration {duration_seconds:.1f}s > {max_seconds}s",
        )

    else:
        return CheckResult(
            check_id=check.id,
            kind=check.kind,
            status="fail",
            message=f"Unknown check kind: {check.kind}",
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class EvalRunner:
    """Generic evaluation runner — executes scenarios and evaluates checks."""

    async def run_scenario(
        self,
        resource,
        scenario: EvalScenario,
        resource_id: str = None,
        store_result: bool = True,
    ) -> EvalRecord:
        """Run a single scenario against a resource and return an EvalRecord.

        Args:
            resource:   LLMResource to test
            scenario:   EvalScenario definition
            resource_id: override for resource ID (defaults to resource.id)
            store_result: if True, persist to EvalStore
        """
        rid = resource_id or resource.id
        start = time.time()

        # Prepare goal from template
        goal = scenario.goal_template
        write_path = self._make_write_path(rid, scenario.id)
        goal = goal.replace("{resource_id}", rid)
        goal = goal.replace("{write_path}", write_path)
        goal = goal.replace("{key}", "alpha")  # default lookup key

        # Skip if required backends are unavailable
        required_backends = getattr(scenario, "requires_backends", None) or []
        if required_backends:
            unavailable = [b for b in required_backends if not self._is_backend_available(b)]
            if unavailable:
                return EvalRecord(
                    ts=datetime.utcnow().isoformat(),
                    resource_id=rid,
                    model=resource.model or "",
                    suite=scenario.suite,
                    scenario_id=scenario.id,
                    category=scenario.category.value,
                    task_family=scenario.task_family,
                    complexity_level=scenario.complexity_level.value,
                    tool_schema_mode=scenario.tool_schema_mode.value,
                    success=False,
                    checks=[],
                    iterations_used=0,
                    duration_seconds=0.0,
                    artifacts={},
                    error=f"Backend(s) unavailable: {', '.join(unavailable)}",
                    tags=scenario.tags,
                    skipped=True,
                )

        # Run the task
        iteration_log = []
        final_answer = None
        error = None
        artifacts = {"write_path": write_path}

        try:
            iteration_log, final_answer = await self._execute_task(
                resource=resource,
                task_id=f"eval_{scenario.id.replace('.', '_')}_{rid}",
                goal=goal,
                available_tools=scenario.available_tools,
                max_iterations=scenario.max_iterations,
                max_duration_seconds=scenario.max_duration_seconds,
                tool_schema_mode=scenario.tool_schema_mode.value,
            )
            # Capture file content if a write was expected
            if write_path and os.path.isfile(write_path):
                artifacts["file_content"] = open(write_path).read().strip()
        except Exception as e:
            error = str(e)
            logger.warning(f"EvalRunner: scenario {scenario.id} failed: {e}")

        duration = time.time() - start

        # Evaluate checks
        check_results = evaluate_checks(
            scenario.checks, iteration_log, final_answer, duration, artifacts,
        )

        # Determine overall success
        success = all(
            c.status == "pass"
            for c in check_results
            if c.status != "skip"
        )

        # Build record
        record = EvalRecord(
            ts=datetime.utcnow().isoformat(),
            resource_id=rid,
            model=resource.model or "",
            suite=scenario.suite,
            scenario_id=scenario.id,
            category=scenario.category.value,
            task_family=scenario.task_family,
            complexity_level=scenario.complexity_level.value,
            tool_schema_mode=scenario.tool_schema_mode.value,
            success=success,
            checks=[c.to_dict() for c in check_results],
            iterations_used=len(iteration_log),
            duration_seconds=duration,
            artifacts=artifacts,
            error=error,
            tags=scenario.tags,
        )

        # Persist
        if store_result:
            from app.scheduler.evals.store import EvalStore
            EvalStore().append(record)

        return record

    async def run_suite(
        self,
        resource,
        scenario_ids: List[str],
        resource_id: str = None,
        repeats: int = 1,
        tool_schema_mode: str = None,
        store_result: bool = True,
    ) -> List[EvalRecord]:
        """Run multiple scenarios (optionally repeated) and return all records."""
        from app.scheduler.evals.scenarios import get_scenario
        records = []

        for scenario_id in scenario_ids:
            scenario = get_scenario(scenario_id)

            # Override tool schema mode if requested
            if tool_schema_mode:
                d = scenario.to_dict()
                d["tool_schema_mode"] = tool_schema_mode
                scenario = EvalScenario.from_dict(d)

            for _ in range(repeats):
                record = await self.run_scenario(
                    resource=resource,
                    scenario=scenario,
                    resource_id=resource_id,
                    store_result=store_result,
                )
                records.append(record)

        return records

    def _is_backend_available(self, backend_name: str) -> bool:
        """Return True if the named backend tool is reachable."""
        if backend_name == "bash_exec":
            try:
                import subprocess
                subprocess.run(["echo", "ok"], capture_output=True, timeout=2)
                return True
            except Exception:
                return False
        if backend_name == "memory_search":
            try:
                from app.memory.multi_model_storage import MultiModelStorage
                MultiModelStorage()
                return True
            except Exception:
                return False
        return True

    # ------------------------------------------------------------------
    # Internal task execution
    # ------------------------------------------------------------------

    async def _execute_task(
        self,
        resource,
        task_id: str,
        goal: str,
        available_tools: list,
        max_iterations: int = 4,
        max_duration_seconds: int = 90,
        tool_schema_mode: str = "full",
    ) -> Tuple[List[Dict], Optional[str]]:
        """Execute a task through the AgenticExecutor."""
        from app.scheduler.models import Task, TaskType, TaskPriority, TaskResources
        task = Task(
            id=task_id,
            type=TaskType.INTERNAL_ASSIGNMENT,
            priority=TaskPriority.HIGH,
            config={
                "goal": goal,
                "available_tools": available_tools,
                "max_iterations": max_iterations,
                "max_duration_seconds": max_duration_seconds,
                "system_prompt": (
                    "You are a minimal test agent. "
                    "Follow instructions exactly. "
                    "Always wrap your final response in <FINAL_ANSWER> tags."
                ),
                "_smoke_test": True,
                "_tool_schema_mode": tool_schema_mode if tool_schema_mode != "full" else None,
            },
            resources=TaskResources(
                max_iterations=max_iterations,
                max_duration_seconds=max_duration_seconds,
            ),
            description="Eval scenario",
            created_by="system",
        )
        from app.scheduler.agentic_executor import AgenticExecutor
        from app.scheduler.mcp_client_manager import MCPClientManager
        from contextlib import AsyncExitStack

        single_rm = _SingleResourceManager(resource)
        empty_mcp = MCPClientManager.__new__(MCPClientManager)
        empty_mcp._servers = {}
        empty_mcp._sessions = {}
        empty_mcp._exit_stack = AsyncExitStack()
        empty_mcp._connected = False
        empty_mcp._connect_lock = None

        executor = AgenticExecutor(resource_manager=single_rm, mcp_client_manager=empty_mcp)
        task_result = await executor.execute(task)
        metrics = task_result.metrics or {}
        return metrics.get("iteration_log", []), metrics.get("final_answer")

    def _make_write_path(self, resource_id: str, scenario_id: str) -> str:
        """Generate a unique temp path for write artifacts."""
        import uuid
        slug = scenario_id.replace(".", "_")
        return os.path.expanduser(
            f"~/.memory/tmp/eval_{slug}_{resource_id}_{uuid.uuid4().hex[:8]}.txt"
        )
