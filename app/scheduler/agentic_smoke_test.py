"""
Agentic Smoke Test

Profiles:
- fast_gate: deterministic, backend-independent baseline gate
- standard_agentic: stronger multi-step profile on top of fast_gate
"""

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

_SMOKE_SYSTEM = (
    "You are a minimal test agent. "
    "Follow instructions exactly. "
    "Always wrap your final response in <FINAL_ANSWER> tags."
)

_PROFILES = {
    "fast_gate": {
        "max_iterations": 4,
        "max_duration_seconds": 90,
    },
    "standard_agentic": {
        "max_iterations": 8,
        "max_duration_seconds": 120,
    },
    "reasoning_stress": {
        "max_iterations": 12,
        "max_duration_seconds": 300,
    },
}

_FAST_GATE_GOAL = (
    "You MUST use the smoke_lookup tool with query 'alpha'. "
    "After receiving the tool result, provide a <FINAL_ANSWER> with the exact token value."
)

_STANDARD_CHOICE_GOAL = (
    "Use smoke_lookup to look up keys 'alpha', 'beta', 'gamma', and 'delta'. "
    "Find the token for the key whose token contains the letter 'g' and ends with '6'. "
    "Then use write_file to write only that exact token to the requested path. "
    "Finally provide a <FINAL_ANSWER> with the exact token value you wrote."
)

_RETRY_GOAL = (
    "Call the smoke_fail_once tool with key 'test'. "
    "If the tool returns an error and retryable=true, call the same tool again with the same key. "
    "Continue until the tool succeeds. "
    "Then provide a <FINAL_ANSWER> with the exact result value."
)

_REASONING_GOAL = (
    "Use smoke_lookup to look up keys 'plan_red', 'plan_blue', and 'plan_green'. "
    "Choose the cheapest valid plan. "
    "Then use write_file to write only the winning plan key to the requested path. "
    "Provide a <FINAL_ANSWER> explaining which plan wins and why the others fail."
)


@dataclass
class SmokeCheckResult:
    name: str
    status: str
    message: str = ""
    failure_class: Optional[str] = None


@dataclass
class SmokeTestResult:
    resource_id: str
    model: str
    agentic_capable: bool
    smoke_profile: str = "fast_gate"
    checks: Dict[str, SmokeCheckResult] = field(default_factory=dict)
    iterations_used: int = 0
    duration_seconds: float = 0.0
    error: Optional[str] = None
    debug_bundle: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "resource_id": self.resource_id,
            "model": self.model,
            "agentic_capable": self.agentic_capable,
            "smoke_profile": self.smoke_profile,
            "checks": {
                name: {
                    "status": c.status,
                    "message": c.message,
                    "failure_class": c.failure_class,
                }
                for name, c in self.checks.items()
            },
            "iterations_used": self.iterations_used,
            "duration_seconds": round(self.duration_seconds, 2),
            "error": self.error,
        }
        if self.debug_bundle:
            data["debug_bundle"] = self.debug_bundle
        return data


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


class AgenticSmokeTest:
    # Profile → eval suite mapping for compatibility wrapper
    _PROFILE_TO_SUITE = {
        "fast_gate": "qualification_fast",
        "standard_agentic": "qualification_standard",
        "reasoning_stress": "qualification_reasoning",
    }

    def __init__(self):
        pass

    async def run_eval(
        self,
        resource_id: str,
        profile: str = "fast_gate",
        resource=None,
    ) -> dict:
        """Compatibility wrapper — delegates to the generic eval runner.

        Maps smoke profiles to eval suites and returns a smoke-compatible result dict.
        This is the new preferred path; use run() for legacy backward compatibility.
        """
        from app.scheduler.evals.runner import EvalRunner
        from app.scheduler.evals.suites import get_suite
        from app.scheduler.evals.store import EvalStore

        suite_id = self._PROFILE_TO_SUITE.get(profile)
        if suite_id is None:
            return {
                "resource_id": resource_id,
                "agentic_capable": False,
                "smoke_profile": profile,
                "error": f"Unknown profile '{profile}'",
            }

        # Resolve resource
        if resource is None:
            from app.scheduler.resource_pool import ResourceManager
            rm = ResourceManager()
            resource = rm._resources.get(resource_id)
            if resource is None:
                return {
                    "resource_id": resource_id,
                    "agentic_capable": False,
                    "smoke_profile": profile,
                    "error": f"Resource '{resource_id}' not found",
                }

        suite = get_suite(suite_id)
        runner = EvalRunner()

        records = await runner.run_suite(
            resource=resource,
            scenario_ids=suite.default_scenarios,
            resource_id=resource_id,
        )

        # Convert eval records to smoke-compatible format
        checks = {}
        for r in records:
            for c in r.checks:
                check_id = c.get("check_id", "")
                checks[check_id] = {
                    "status": c.get("status", "fail"),
                    "failure_class": c.get("failure_class"),
                    "message": c.get("message", ""),
                }

        agentic_capable = all(r.success for r in records)
        total_duration = sum(r.duration_seconds for r in records)

        return {
            "resource_id": resource_id,
            "model": resource.model,
            "agentic_capable": agentic_capable,
            "smoke_profile": profile,
            "checks": checks,
            "iterations_used": sum(r.iterations_used for r in records),
            "duration_seconds": total_duration,
        }

    async def _run_single_task(
        self,
        resource,
        task_id: str,
        goal: str,
        available_tools: list,
        role_id: Optional[str] = None,
        planning_prompt: Optional[str] = None,
        system_prompt_override: Optional[str] = None,
        max_iterations: int = 4,
        max_duration_seconds: int = 90,
        smoke_test: bool = False,
    ) -> tuple:
        from app.scheduler.models import Task, TaskType, TaskPriority, TaskResources
        task_config = {
            "goal": goal,
            "available_tools": available_tools,
            "max_iterations": max_iterations,
            "max_duration_seconds": max_duration_seconds,
        }
        if smoke_test:
            task_config["_smoke_test"] = True
        if role_id:
            task_config["role_id"] = role_id
        if planning_prompt:
            task_config["planning_prompt"] = planning_prompt
        if system_prompt_override:
            task_config["system_prompt"] = system_prompt_override
        elif not role_id:
            task_config["system_prompt"] = _SMOKE_SYSTEM
        task = Task(
            id=task_id,
            type=TaskType.INTERNAL_ASSIGNMENT,
            priority=TaskPriority.HIGH,
            config=task_config,
            resources=TaskResources(
                max_iterations=max_iterations,
                max_duration_seconds=max_duration_seconds,
            ),
            description="Agentic smoke test",
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
        return task_result, metrics.get("iteration_log", []), metrics.get("final_answer")

    def _write_debug_bundle(self, payload: Dict[str, Any]) -> Optional[str]:
        try:
            ts = int(time.time())
            out_path = os.path.join("/tmp", f"mojo_agentic_smoke_debug_{ts}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
            return out_path
        except Exception:
            return None

    def _make_unique_path(self, resource_id: str, prefix: str) -> str:
        from app.config.paths import get_memory_subpath

        basename = f"{prefix}_{resource_id}_{uuid.uuid4().hex[:8]}.txt"
        smoke_dir = get_memory_subpath("tmp")
        os.makedirs(smoke_dir, exist_ok=True)
        return os.path.join(smoke_dir, basename)

    def _build_write_goal(self, path: str) -> str:
        return (
            "You MUST call the write_file tool to write the text 'smoke_test_ok' to the path "
            f"'{path}'. "
            "After the tool returns successfully, provide a <FINAL_ANSWER> confirming the write succeeded."
        )

    def _build_choice_goal(self, path: str) -> str:
        return _STANDARD_CHOICE_GOAL + f" Write the token to the path '{path}'."

    def _check_tool_called(self, iteration_log: list, tool_name: str) -> bool:
        return any(
            it.get("status") == "tool_use" and tool_name in it.get("tool_calls", [])
            for it in iteration_log
        )

    async def run(
        self,
        resource_id: str,
        profile: str = "fast_gate",
        full: bool = False,
        role_id: Optional[str] = None,
        dynamic_goal: Optional[str] = None,
        dynamic_available_tools: Optional[list] = None,
        dynamic_expected_tool: Optional[str] = None,
        dynamic_planning_prompt: Optional[str] = None,
        dynamic_system_prompt: Optional[str] = None,
        integration_checks: Optional[list] = None,
        tool_schema_mode: Optional[str] = None,
        debug_artifact: bool = False,
        issue_note: Optional[str] = None,
    ) -> SmokeTestResult:
        start = time.time()
        profile_cfg = _PROFILES.get(profile)
        if profile_cfg is None:
            return SmokeTestResult(
                resource_id=resource_id,
                model="?",
                agentic_capable=False,
                smoke_profile=profile,
                error=f"Unknown profile '{profile}'. Valid: {sorted(_PROFILES)}",
            )

        try:
            from app.scheduler.resource_pool import ResourceManager
            rm = ResourceManager()
            resource = rm._resources.get(resource_id)
            if resource is None:
                return SmokeTestResult(
                    resource_id=resource_id,
                    model="?",
                    agentic_capable=False,
                    smoke_profile=profile,
                    error=f"Resource '{resource_id}' not found in llm_config",
                )
        except Exception as e:
            return SmokeTestResult(
                resource_id=resource_id,
                model="?",
                agentic_capable=False,
                smoke_profile=profile,
                error=f"Failed to load resource pool: {e}",
            )

        model = resource.model or "?"
        dynamic_mode = bool(dynamic_goal)
        if dynamic_mode and not dynamic_available_tools:
            dynamic_available_tools = ["smoke_lookup"]
        if dynamic_mode and not dynamic_expected_tool and dynamic_available_tools:
            dynamic_expected_tool = dynamic_available_tools[0]

        try:
            primary_goal = dynamic_goal or _FAST_GATE_GOAL
            primary_tools = dynamic_available_tools or ["smoke_lookup"]
            _, iteration_log, final_answer = await self._run_single_task(
                resource=resource,
                task_id=f"smoke_test_{profile}_{resource_id}",
                goal=primary_goal,
                available_tools=primary_tools,
                role_id=role_id,
                planning_prompt=dynamic_planning_prompt,
                system_prompt_override=dynamic_system_prompt,
                max_iterations=profile_cfg["max_iterations"],
                max_duration_seconds=profile_cfg["max_duration_seconds"],
                smoke_test=True,
            )
        except Exception as e:
            return SmokeTestResult(
                resource_id=resource_id,
                model=model,
                agentic_capable=False,
                smoke_profile=profile,
                error=f"Executor failed: {e}",
                duration_seconds=time.time() - start,
            )

        expected_tool = dynamic_expected_tool or "smoke_lookup"
        made_tool_call = self._check_tool_called(iteration_log, expected_tool)
        tool_failure = None
        if not made_tool_call:
            tool_failure = "premature_final_answer" if final_answer else "tool_not_called"
        tool_check = SmokeCheckResult(
            name="tool_calling",
            status="pass" if made_tool_call else "fail",
            failure_class=tool_failure,
            message=(
                f"Model called {expected_tool} as required"
                if made_tool_call
                else f"Model did not call {expected_tool}"
            ),
        )
        fa_check = SmokeCheckResult(
            name="final_answer",
            status="pass" if final_answer else "fail",
            failure_class=None if final_answer else "final_answer_missing",
            message=(
                "Model produced <FINAL_ANSWER> tags within the iteration budget"
                if final_answer
                else "Model did not produce <FINAL_ANSWER> tags within the iteration budget"
            ),
        )

        if dynamic_mode:
            wf_check = SmokeCheckResult(
                name="write_workflow",
                status="skip",
                message="Skipped in dynamic mode (focus is role/persona prompt behavior)",
            )
            write_target = None
        else:
            write_target = self._make_unique_path(resource_id, "mojo_smoke_write")
            if os.path.exists(write_target):
                try:
                    os.remove(write_target)
                except OSError:
                    pass
            try:
                _, wf_log, wf_answer = await self._run_single_task(
                    resource=resource,
                    task_id=f"smoke_write_{profile}_{resource_id}",
                    goal=self._build_write_goal(write_target),
                    available_tools=["write_file"],
                    max_iterations=5,
                    max_duration_seconds=60,
                )
                write_tool_called = self._check_tool_called(wf_log, "write_file")
                file_written = os.path.isfile(write_target)
                if file_written:
                    try:
                        os.remove(write_target)
                    except OSError:
                        pass
                wf_pass = write_tool_called and file_written
                if wf_pass:
                    wf_failure = None
                elif write_tool_called and not file_written:
                    wf_failure = "verification_mismatch"
                elif not write_tool_called and wf_answer:
                    wf_failure = "xml_tool_leakage"
                else:
                    wf_failure = "tool_not_called"
                wf_check = SmokeCheckResult(
                    name="write_workflow",
                    status="pass" if wf_pass else "fail",
                    failure_class=wf_failure,
                    message=(
                        "Model called write_file via function API and file was written to disk"
                        if wf_pass else "write_file verification failed"
                    ),
                )
            except Exception as e:
                wf_check = SmokeCheckResult(
                    name="write_workflow",
                    status="fail",
                    failure_class="executor_exception",
                    message=f"Write workflow test failed to run: {e}",
                )

        sw_check = SmokeCheckResult(
            name="sandbox_write",
            status="skip",
            message="Superseded by write_workflow check",
        )

        checks = {
            "tool_calling": tool_check,
            "final_answer": fa_check,
            "write_workflow": wf_check,
            "sandbox_write": sw_check,
        }

        extra_debug: Dict[str, Any] = {}
        if profile in ("standard_agentic", "reasoning_stress") and not dynamic_mode:
            choice_target = self._make_unique_path(resource_id, "mojo_smoke_choice")
            try:
                _, tc_log, tc_answer = await self._run_single_task(
                    resource=resource,
                    task_id=f"smoke_choice_{resource_id}",
                    goal=self._build_choice_goal(choice_target),
                    available_tools=["smoke_lookup", "write_file"],
                    max_iterations=8,
                    max_duration_seconds=120,
                    smoke_test=True,
                )
                lookup_called = self._check_tool_called(tc_log, "smoke_lookup")
                write_called = self._check_tool_called(tc_log, "write_file")
                choice_correct = False
                if os.path.isfile(choice_target):
                    with open(choice_target, encoding="utf-8") as f:
                        choice_correct = f.read().strip() == "smoke_ok:gamma:g1f8a6"
                    os.remove(choice_target)
                if lookup_called and write_called and choice_correct:
                    tc_failure = None
                    tc_pass = True
                elif not lookup_called:
                    tc_failure = "tool_not_called"
                    tc_pass = False
                elif not write_called:
                    tc_failure = "wrong_tool"
                    tc_pass = False
                else:
                    tc_failure = "verification_mismatch"
                    tc_pass = False
                checks["tool_choice"] = SmokeCheckResult(
                    name="tool_choice",
                    status="pass" if tc_pass else "fail",
                    failure_class=tc_failure,
                    message=(
                        "Model completed the multi-step lookup and wrote the correct token"
                        if tc_pass else f"Tool choice check failed: {tc_failure}"
                    ),
                )
                extra_debug["tool_choice"] = {
                    "iteration_log": tc_log,
                    "final_answer": tc_answer,
                    "write_target": choice_target,
                }
            except Exception as e:
                checks["tool_choice"] = SmokeCheckResult(
                    name="tool_choice",
                    status="fail",
                    failure_class="executor_exception",
                    message=f"Tool choice test failed to run: {e}",
                )

            try:
                _, rt_log, rt_answer = await self._run_single_task(
                    resource=resource,
                    task_id=f"smoke_retry_{resource_id}",
                    goal=_RETRY_GOAL,
                    available_tools=["smoke_fail_once"],
                    max_iterations=6,
                    max_duration_seconds=90,
                    smoke_test=True,
                )
                retry_calls = sum(
                    1
                    for e in rt_log
                    if e.get("status") == "tool_use" and "smoke_fail_once" in e.get("tool_calls", [])
                )
                retry_success = bool(rt_answer and "smoke_retry_ok:test" in rt_answer)
                if retry_calls >= 2 and retry_success:
                    rt_failure = None
                    rt_pass = True
                elif retry_calls < 2:
                    rt_failure = "did_not_retry"
                    rt_pass = False
                else:
                    rt_failure = "verification_mismatch"
                    rt_pass = False
                checks["retry_stability"] = SmokeCheckResult(
                    name="retry_stability",
                    status="pass" if rt_pass else "fail",
                    failure_class=rt_failure,
                    message=(
                        f"Model retried after transient tool failure ({retry_calls} calls)"
                        if rt_pass else f"Retry stability failed: {rt_failure}"
                    ),
                )
                extra_debug["retry_stability"] = {
                    "iteration_log": rt_log,
                    "final_answer": rt_answer,
                }
            except Exception as e:
                checks["retry_stability"] = SmokeCheckResult(
                    name="retry_stability",
                    status="fail",
                    failure_class="executor_exception",
                    message=f"Retry stability test failed to run: {e}",
                )

        if profile == "reasoning_stress" and not dynamic_mode:
            reasoning_target = self._make_unique_path(resource_id, "mojo_smoke_reasoning")
            try:
                _, rs_log, rs_answer = await self._run_single_task(
                    resource=resource,
                    task_id=f"smoke_reasoning_{resource_id}",
                    goal=_REASONING_GOAL + f" Write the winning plan key to the path '{reasoning_target}'.",
                    available_tools=["smoke_lookup", "write_file"],
                    max_iterations=12,
                    max_duration_seconds=300,
                    smoke_test=True,
                )
                lookup_calls = sum(
                    e.get("tool_calls", []).count("smoke_lookup")
                    for e in rs_log
                    if e.get("status") == "tool_use"
                )
                write_called = self._check_tool_called(rs_log, "write_file")
                reasoning_correct = False
                if os.path.isfile(reasoning_target):
                    with open(reasoning_target, encoding="utf-8") as f:
                        reasoning_correct = f.read().strip() == "plan_green"
                    os.remove(reasoning_target)
                answer_ok = bool(rs_answer and "plan_green" in rs_answer.lower())
                if lookup_calls >= 3 and write_called and reasoning_correct and answer_ok:
                    rs_failure = None
                    rs_pass = True
                elif lookup_calls < 3:
                    rs_failure = "tool_not_called"
                    rs_pass = False
                elif not write_called:
                    rs_failure = "wrong_tool"
                    rs_pass = False
                else:
                    rs_failure = "verification_mismatch"
                    rs_pass = False
                checks["constraint_reasoning"] = SmokeCheckResult(
                    name="constraint_reasoning",
                    status="pass" if rs_pass else "fail",
                    failure_class=rs_failure,
                    message=(
                        "Model gathered evidence and chose the correct plan"
                        if rs_pass else f"Constraint reasoning failed: {rs_failure}"
                    ),
                )
                extra_debug["constraint_reasoning"] = {
                    "iteration_log": rs_log,
                    "final_answer": rs_answer,
                    "write_target": reasoning_target,
                }
            except Exception as e:
                checks["constraint_reasoning"] = SmokeCheckResult(
                    name="constraint_reasoning",
                    status="fail",
                    failure_class="executor_exception",
                    message=f"Constraint reasoning test failed to run: {e}",
                )

        if integration_checks:
            for check_name in integration_checks:
                if check_name == "memory_search":
                    checks["integration_memory_search"] = SmokeCheckResult(
                        name="integration_memory_search",
                        status="skip",
                        failure_class="tool_backend_unavailable",
                        message="Backend unavailable",
                    )
                elif check_name == "bash_exec":
                    checks["integration_bash_exec"] = SmokeCheckResult(
                        name="integration_bash_exec",
                        status="skip",
                        failure_class="tool_backend_unavailable",
                        message="Backend unavailable",
                    )
                else:
                    checks[f"integration_{check_name}"] = SmokeCheckResult(
                        name=f"integration_{check_name}",
                        status="fail",
                        failure_class="verification_mismatch",
                        message=f"Unknown integration check '{check_name}'",
                    )

        mandatory = ["tool_calling", "final_answer", "write_workflow"]
        if profile in ("standard_agentic", "reasoning_stress") and not dynamic_mode:
            mandatory.extend(["tool_choice", "retry_stability"])
        if profile == "reasoning_stress" and not dynamic_mode:
            mandatory.append("constraint_reasoning")
        agentic_capable = all(checks[name].status == "pass" for name in mandatory)

        debug_bundle = {
            "mode": "dynamic" if dynamic_mode else profile,
            "resource_id": resource_id,
            "model": model,
            "role_id": role_id,
            "goal": dynamic_goal or _FAST_GATE_GOAL,
            "available_tools": dynamic_available_tools or ["smoke_lookup"],
            "expected_tool": expected_tool,
            "planning_prompt": dynamic_planning_prompt,
            "checks": {
                k: {
                    "status": v.status,
                    "message": v.message,
                    "failure_class": v.failure_class,
                }
                for k, v in checks.items()
            },
            "iterations_used": len(iteration_log),
            "iteration_log": iteration_log,
            "final_answer": final_answer,
            "write_target": write_target,
            "integration_checks": list(integration_checks or []),
            "issue_note": issue_note or "",
            "captured_at": int(time.time()),
        }
        debug_bundle.update(extra_debug)
        if debug_artifact:
            artifact_path = self._write_debug_bundle(debug_bundle)
            if artifact_path:
                debug_bundle["artifact_path"] = artifact_path

        return SmokeTestResult(
            resource_id=resource_id,
            model=model,
            agentic_capable=agentic_capable,
            smoke_profile=profile,
            checks=checks,
            iterations_used=len(iteration_log),
            duration_seconds=time.time() - start,
            debug_bundle=debug_bundle,
        )


    async def compare_tool_schema_modes(
        self,
        resource_id: str,
        profile: str = "fast_gate",
        integration_checks: Optional[list] = None,
        repeats: int = 1,
    ) -> Dict[str, Any]:
        repeats = max(1, int(repeats or 1))
        modes: Dict[str, list] = {"full": [], "lean": []}

        for mode in ("full", "lean"):
            for _ in range(repeats):
                result = await self.run(
                    resource_id=resource_id,
                    profile=profile,
                    integration_checks=integration_checks,
                    tool_schema_mode=mode,
                )
                data = result.to_dict()
                data["tool_schema_mode"] = mode
                modes[mode].append(data)

        summary: Dict[str, Dict[str, Any]] = {}
        for mode, rows in modes.items():
            pass_rate = (sum(1 for row in rows if row.get("agentic_capable")) / len(rows)) if rows else 0.0
            avg_duration = round(sum(float(row.get("duration_seconds", 0.0)) for row in rows) / len(rows), 2) if rows else 0.0
            failing_checks = sorted({
                check_name
                for row in rows
                for check_name, check_data in (row.get("checks") or {}).items()
                if (check_data or {}).get("status") == "fail"
            })
            summary[mode] = {
                "runs": len(rows),
                "pass_rate": pass_rate,
                "avg_duration_seconds": avg_duration,
                "failing_checks": failing_checks,
            }

        model = ""
        for rows in modes.values():
            if rows:
                model = rows[0].get("model", "")
                break

        return {
            "resource_id": resource_id,
            "model": model,
            "profile": profile,
            "integration_checks": list(integration_checks or []),
            "modes": modes,
            "summary": summary,
        }
