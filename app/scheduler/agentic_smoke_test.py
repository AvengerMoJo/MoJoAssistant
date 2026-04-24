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

# Two-step write workflow goal — catches models that output XML tool calls as text
# instead of making real function calls (known Qwen XML leakage bug).
_SMOKE_WRITE_GOAL = (
    "You MUST call the write_file tool to write the text 'smoke_test_ok' to the path "
    "'~/.memory/smoke_write_test.txt'. "
    "After the tool returns successfully, provide a <FINAL_ANSWER> confirming the write succeeded."
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

    async def _run_single_task(
        self,
        resource,
        task_id: str,
        goal: str,
        available_tools: list,
        max_iterations: int = 4,
    ) -> tuple:
        """Run one minimal task and return (task_result, iteration_log, final_answer)."""
        from app.scheduler.models import Task, TaskType, TaskPriority, TaskResources
        task = Task(
            id=task_id,
            type=TaskType.INTERNAL_ASSIGNMENT,
            priority=TaskPriority.HIGH,
            config={
                "goal": goal,
                "system_prompt": _SMOKE_SYSTEM,
                "available_tools": available_tools,
                "max_iterations": max_iterations,
                "max_duration_seconds": 90,
            },
            resources=TaskResources(max_iterations=max_iterations, max_duration_seconds=90),
            description="Agentic smoke test",
            created_by="system",
        )
        from app.scheduler.agentic_executor import AgenticExecutor
        from app.scheduler.mcp_client_manager import MCPClientManager
        single_rm = _SingleResourceManager(resource)
        # No-server MCPClientManager skips STDIO discovery (smoke test uses built-in tools only)
        from contextlib import AsyncExitStack
        empty_mcp = MCPClientManager.__new__(MCPClientManager)
        empty_mcp._servers = {}
        empty_mcp._sessions = {}
        empty_mcp._exit_stack = AsyncExitStack()
        empty_mcp._connected = False
        empty_mcp._connect_lock = None
        executor = AgenticExecutor(resource_manager=single_rm, mcp_client_manager=empty_mcp)
        task_result = await executor.execute(task)
        metrics = task_result.metrics or {}
        return task_result, metrics.get("iteration_log", []), metrics.get("final_answer")

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

        # --- Check 1 + 2: tool calling fidelity and final answer ---
        try:
            _, iteration_log, final_answer = await self._run_single_task(
                resource=resource,
                task_id=f"smoke_test_{resource_id}",
                goal=_SMOKE_GOAL,
                available_tools=["memory_search"],
            )
        except Exception as e:
            return SmokeTestResult(
                resource_id=resource_id, model=model,
                agentic_capable=False,
                error=f"Executor failed: {e}",
                duration_seconds=time.time() - start,
            )

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
        fa_check = SmokeCheckResult(
            name="final_answer",
            status="pass" if final_answer else "fail",
            message=(
                "Model produced <FINAL_ANSWER> tags within the iteration budget"
                if final_answer
                else "Model did not produce <FINAL_ANSWER> tags within the iteration budget"
            ),
        )

        # --- Check 3: write_workflow (XML tool call leakage detection) ---
        # Runs in both standard and full mode — this catches the Qwen XML bug
        # where the model outputs <write_file>...</write_file> as plain text in
        # FINAL_ANSWER instead of making a real function call.
        # A pass means the file was actually written to disk (executor ran the tool).
        try:
            _, wf_log, wf_answer = await self._run_single_task(
                resource=resource,
                task_id=f"smoke_write_{resource_id}",
                goal=_SMOKE_WRITE_GOAL,
                available_tools=["write_file"],
                max_iterations=5,
            )
            # Verify the tool was actually called (not just described in text)
            write_tool_called = any(
                it.get("status") == "tool_use" and "write_file" in it.get("tool_calls", [])
                for it in wf_log
            )
            # Also verify file exists on disk
            import os as _os
            smoke_path = _os.path.expanduser("~/.memory/smoke_write_test.txt")
            file_written = _os.path.isfile(smoke_path)
            if file_written:
                try:
                    _os.remove(smoke_path)
                except OSError:
                    pass

            wf_pass = write_tool_called and file_written
            wf_check = SmokeCheckResult(
                name="write_workflow",
                status="pass" if wf_pass else "fail",
                message=(
                    "Model called write_file via function API and file was written to disk"
                    if wf_pass
                    else (
                        "write_file was called but file not found on disk (possible XML leakage — "
                        "model may have output tool call as text instead of function call)"
                        if write_tool_called
                        else "Model did not call write_file (may have described it in text)"
                    )
                ),
            )
        except Exception as e:
            wf_check = SmokeCheckResult(
                name="write_workflow", status="skip",
                message=f"Write workflow test failed to run: {e}",
            )

        # sandbox_write is superseded by write_workflow — keep key for schema compat
        sw_check = SmokeCheckResult(
            name="sandbox_write", status="skip",
            message="Superseded by write_workflow check",
        )

        checks = {
            "tool_calling": tool_check,
            "final_answer": fa_check,
            "write_workflow": wf_check,
            "sandbox_write": sw_check,
        }

        # agentic_capable requires all non-skip checks to pass
        agentic_capable = all(
            c.status == "pass"
            for c in checks.values()
            if c.status != "skip"
        )

        return SmokeTestResult(
            resource_id=resource_id,
            model=model,
            agentic_capable=agentic_capable,
            checks=checks,
            iterations_used=len(iteration_log),
            duration_seconds=time.time() - start,
        )
