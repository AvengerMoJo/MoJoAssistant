"""
Agentic Smoke Test

Validates that a given LLM resource can follow the agentic execution flow.
Two mandatory checks:

  1. Tool calling fidelity — model actually emits a tool_call (not a hallucinated result)
  2. Final answer compliance — model produces <FINAL_ANSWER> tags within the iteration limit

If either check fails, the resource is flagged as agentic_incompatible and should
only be used for non-agentic tasks (e.g. dreaming summarisation).

Usage (from code):
    test = AgenticSmokeTest()
    result = await test.run(resource_id="lmstudio")

Usage (via MCP):
    resource_pool_smoke_test(resource_id="lmstudio")
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# Minimal goal that requires exactly one tool call to succeed.
# The word "MUST" forces the model to call the tool rather than answer from context.
_SMOKE_GOAL = (
    "You MUST use the memory_search tool with query 'test'. "
    "After receiving the tool result, provide a <FINAL_ANSWER> with a one-line summary of what you found."
)

_SMOKE_SYSTEM = (
    "You are a minimal test agent. "
    "Follow instructions exactly. "
    "Always wrap your final response in <FINAL_ANSWER> tags."
)


@dataclass
class SmokeCheckResult:
    name: str              # "tool_calling" | "final_answer" | "sandbox_write"
    status: str            # "pass" | "fail" | "skip"
    message: str = ""


@dataclass
class SmokeTestResult:
    resource_id: str
    model: str
    agentic_capable: bool
    checks: Dict[str, SmokeCheckResult] = field(default_factory=dict)
    iterations_used: int = 0
    duration_seconds: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "model": self.model,
            "agentic_capable": self.agentic_capable,
            "checks": {
                name: {"status": c.status, "message": c.message}
                for name, c in self.checks.items()
            },
            "iterations_used": self.iterations_used,
            "duration_seconds": round(self.duration_seconds, 2),
            "error": self.error,
        }


class _SingleResourceManager:
    """
    Minimal resource manager that always returns one specific resource.
    Used to target the smoke test at a specific resource without modifying
    the real ResourceManager's state.
    """

    def __init__(self, resource):
        self._resource = resource

    def acquire(self, **kwargs):
        return self._resource

    def release(self, resource_id: str) -> None:
        pass

    def record_usage(self, resource_id: str, success: bool) -> None:
        pass


class AgenticSmokeTest:
    """
    Runs a minimal agentic task against a specific resource to validate
    tool-calling fidelity and final-answer compliance.
    """

    def __init__(self):
        pass

    async def run(self, resource_id: str, full: bool = False) -> SmokeTestResult:
        """
        Run the smoke test against a named resource.

        Args:
            resource_id: ID of the LLM resource to test (from llm_config.json).
            full: If True, also test write_file sandbox and parallel calls (future).
        """
        start = time.time()

        # Resolve the target resource
        try:
            from app.scheduler.resource_pool import ResourceManager
            rm = ResourceManager()
            resource = rm._resources.get(resource_id)
            if resource is None:
                return SmokeTestResult(
                    resource_id=resource_id,
                    model="?",
                    agentic_capable=False,
                    error=f"Resource '{resource_id}' not found in llm_config",
                )
        except Exception as e:
            return SmokeTestResult(
                resource_id=resource_id,
                model="?",
                agentic_capable=False,
                error=f"Failed to load resource pool: {e}",
            )

        model = resource.model or "?"

        # Build a minimal task
        try:
            from app.scheduler.models import Task, TaskType, TaskPriority, TaskResources
            task = Task(
                id=f"smoke_test_{resource_id}",
                type=TaskType.ASSISTANT,
                priority=TaskPriority.HIGH,
                config={
                    "goal": _SMOKE_GOAL,
                    "system_prompt": _SMOKE_SYSTEM,
                    "available_tools": ["memory_search"],
                    "max_iterations": 4,
                    "max_duration_seconds": 60,
                },
                resources=TaskResources(max_iterations=4, max_duration_seconds=60),
                description="Agentic smoke test",
                created_by="system",
            )
        except Exception as e:
            return SmokeTestResult(
                resource_id=resource_id, model=model,
                agentic_capable=False,
                error=f"Failed to build test task: {e}",
            )

        # Run via executor with a single-resource manager
        try:
            from app.scheduler.agentic_executor import AgenticExecutor
            single_rm = _SingleResourceManager(resource)
            executor = AgenticExecutor(resource_manager=single_rm)
            task_result = await executor.execute(task)
        except Exception as e:
            return SmokeTestResult(
                resource_id=resource_id, model=model,
                agentic_capable=False,
                error=f"Executor failed: {e}",
                duration_seconds=time.time() - start,
            )

        duration = time.time() - start
        metrics = task_result.metrics or {}
        iteration_log = metrics.get("iteration_log", [])
        iterations = len(iteration_log)
        final_answer = metrics.get("final_answer")

        # Check 1: tool calling fidelity
        made_tool_call = any(
            it.get("status") == "tool_use" and "memory_search" in it.get("tool_calls", [])
            for it in iteration_log
        )
        tool_check = SmokeCheckResult(
            name="tool_calling",
            status="pass" if made_tool_call else "fail",
            message=(
                "Model called memory_search as required"
                if made_tool_call
                else "Model did not emit a tool call (hallucinated result or ignored instruction)"
            ),
        )

        # Check 2: final answer compliance
        fa_check = SmokeCheckResult(
            name="final_answer",
            status="pass" if final_answer else "fail",
            message=(
                "Model produced <FINAL_ANSWER> tags within the iteration budget"
                if final_answer
                else "Model did not produce <FINAL_ANSWER> tags within the iteration budget"
            ),
        )

        # Check 3: sandbox_write (full mode only)
        sw_check = SmokeCheckResult(name="sandbox_write", status="skip", message="Not run (full=False)")

        checks = {
            "tool_calling": tool_check,
            "final_answer": fa_check,
            "sandbox_write": sw_check,
        }

        agentic_capable = tool_check.status == "pass" and fa_check.status == "pass"

        return SmokeTestResult(
            resource_id=resource_id,
            model=model,
            agentic_capable=agentic_capable,
            checks=checks,
            iterations_used=iterations,
            duration_seconds=duration,
        )
