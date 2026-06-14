import re
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.mcp.core.tools import ToolRegistry
from app.scheduler.agentic_executor import AgenticExecutor, BUILTIN_TOOLS, SMOKE_ONLY_TOOLS
from app.scheduler.agentic_smoke_test import AgenticSmokeTest
from app.scheduler.capability_resolver import CapabilityResolver


class TestAgenticSmokeProfiles(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.resource = SimpleNamespace(model="test-model")

    async def test_default_smoke_uses_deterministic_lookup_and_unique_tmp_write_target(self):
        calls = []

        async def fake_run_single_task(*, task_id, goal, available_tools, **kwargs):
            calls.append({
                "task_id": task_id,
                "goal": goal,
                "available_tools": list(available_tools),
                "kwargs": kwargs,
            })
            if task_id.startswith("smoke_test_"):
                return None, [
                    {"status": "tool_use", "tool_calls": ["smoke_lookup"]},
                    {"status": "final"},
                ], "smoke_ok:alpha:a7c3f1"
            if task_id.startswith("smoke_write_"):
                match = re.search(r"path '([^']+)'", goal)
                self.assertIsNotNone(match)
                write_path = match.group(1)
                with open(write_path, "w", encoding="utf-8") as f:
                    f.write("smoke_test_ok")
                return None, [
                    {"status": "tool_use", "tool_calls": ["write_file"]},
                    {"status": "final"},
                ], "write ok"
            raise AssertionError(f"unexpected task_id: {task_id}")

        with patch("app.scheduler.resource_pool.ResourceManager") as rm_cls:
            rm_cls.return_value._resources = {"r1": self.resource}
            tester = AgenticSmokeTest()
            with patch.object(tester, "_run_single_task", side_effect=fake_run_single_task):
                result = await tester.run(resource_id="r1")

        self.assertTrue(result.agentic_capable)
        self.assertEqual(result.smoke_profile, "fast_gate")
        self.assertEqual(calls[0]["available_tools"], ["smoke_lookup"])
        self.assertTrue(calls[0]["kwargs"]["smoke_test"])
        self.assertIn("smoke_lookup tool with query 'alpha'", calls[0]["goal"])
        self.assertEqual(result.checks["write_workflow"].status, "pass")
        self.assertIn("/.memory/tmp/", calls[1]["goal"])
        self.assertIn("/.memory/tmp/", result.debug_bundle["write_target"])

    async def test_write_workflow_exception_fails_fast_gate(self):
        async def fake_run_single_task(*, task_id, goal, available_tools, **kwargs):
            if task_id.startswith("smoke_test_"):
                return None, [
                    {"status": "tool_use", "tool_calls": ["smoke_lookup"]},
                    {"status": "final"},
                ], "smoke_ok:alpha:a7c3f1"
            raise RuntimeError("write check boom")

        with patch("app.scheduler.resource_pool.ResourceManager") as rm_cls:
            rm_cls.return_value._resources = {"r1": self.resource}
            tester = AgenticSmokeTest()
            with patch.object(tester, "_run_single_task", side_effect=fake_run_single_task):
                result = await tester.run(resource_id="r1")

        self.assertFalse(result.agentic_capable)
        self.assertEqual(result.checks["write_workflow"].status, "fail")
        self.assertEqual(result.checks["write_workflow"].failure_class, "executor_exception")

    async def test_standard_agentic_runs_extra_checks_and_reports_profile(self):
        calls = []

        async def fake_run_single_task(*, task_id, goal, available_tools, **kwargs):
            calls.append(task_id)
            if task_id.startswith("smoke_test_"):
                return None, [
                    {"status": "tool_use", "tool_calls": ["smoke_lookup"]},
                    {"status": "final"},
                ], "smoke_ok:alpha:a7c3f1"
            if task_id.startswith("smoke_write_"):
                match = re.search(r"path '([^']+)'", goal)
                write_path = match.group(1)
                with open(write_path, "w", encoding="utf-8") as f:
                    f.write("smoke_test_ok")
                return None, [{"status": "tool_use", "tool_calls": ["write_file"]}], "write ok"
            if task_id.startswith("smoke_choice_"):
                match = re.search(r"path '([^']+)'", goal)
                choice_path = match.group(1)
                with open(choice_path, "w", encoding="utf-8") as f:
                    f.write("smoke_ok:gamma:g1f8a6")
                return None, [
                    {"status": "tool_use", "tool_calls": ["smoke_lookup"]},
                    {"status": "tool_use", "tool_calls": ["write_file"]},
                ], "smoke_ok:gamma:g1f8a6"
            if task_id.startswith("smoke_retry_"):
                return None, [
                    {"status": "tool_use", "tool_calls": ["smoke_fail_once"]},
                    {"status": "tool_use", "tool_calls": ["smoke_fail_once"]},
                ], "smoke_retry_ok:test"
            raise AssertionError(f"unexpected task_id: {task_id}")

        with patch("app.scheduler.resource_pool.ResourceManager") as rm_cls:
            rm_cls.return_value._resources = {"r1": self.resource}
            tester = AgenticSmokeTest()
            with patch.object(tester, "_run_single_task", side_effect=fake_run_single_task):
                result = await tester.run(resource_id="r1", profile="standard_agentic")

        self.assertTrue(result.agentic_capable)
        self.assertEqual(result.smoke_profile, "standard_agentic")
        self.assertEqual(result.checks["tool_choice"].status, "pass")
        self.assertEqual(result.checks["retry_stability"].status, "pass")
        self.assertIn("tool_choice", result.debug_bundle)
        self.assertIn("retry_stability", result.debug_bundle)
        self.assertEqual(calls, [
            "smoke_test_standard_agentic_r1",
            "smoke_write_standard_agentic_r1",
            "smoke_choice_r1",
            "smoke_retry_r1",
        ])


    async def test_reasoning_stress_adds_constraint_check_without_changing_gate_contract(self):
        calls = []

        async def fake_run_single_task(*, task_id, goal, available_tools, **kwargs):
            calls.append(task_id)
            if task_id.startswith("smoke_test_"):
                return None, [
                    {"status": "tool_use", "tool_calls": ["smoke_lookup"]},
                    {"status": "final"},
                ], "smoke_ok:alpha:a7c3f1"
            if task_id.startswith("smoke_write_"):
                match = re.search(r"path '([^']+)'", goal)
                write_path = match.group(1)
                with open(write_path, "w", encoding="utf-8") as f:
                    f.write("smoke_test_ok")
                return None, [{"status": "tool_use", "tool_calls": ["write_file"]}], "write ok"
            if task_id.startswith("smoke_choice_"):
                match = re.search(r"path '([^']+)'", goal)
                choice_path = match.group(1)
                with open(choice_path, "w", encoding="utf-8") as f:
                    f.write("smoke_ok:gamma:g1f8a6")
                return None, [
                    {"status": "tool_use", "tool_calls": ["smoke_lookup"]},
                    {"status": "tool_use", "tool_calls": ["write_file"]},
                ], "smoke_ok:gamma:g1f8a6"
            if task_id.startswith("smoke_retry_"):
                return None, [
                    {"status": "tool_use", "tool_calls": ["smoke_fail_once"]},
                    {"status": "tool_use", "tool_calls": ["smoke_fail_once"]},
                ], "smoke_retry_ok:test"
            if task_id.startswith("smoke_reasoning_"):
                match = re.search(r"path '([^']+)'", goal)
                reasoning_path = match.group(1)
                with open(reasoning_path, "w", encoding="utf-8") as f:
                    f.write("plan_green")
                return None, [
                    {"status": "tool_use", "tool_calls": ["smoke_lookup"]},
                    {"status": "tool_use", "tool_calls": ["smoke_lookup"]},
                    {"status": "tool_use", "tool_calls": ["smoke_lookup"]},
                    {"status": "tool_use", "tool_calls": ["write_file"]},
                ], "plan_green is the cheapest valid plan because plan_red exceeds latency and plan_blue is invalid"
            raise AssertionError(f"unexpected task_id: {task_id}")

        with patch("app.scheduler.resource_pool.ResourceManager") as rm_cls:
            rm_cls.return_value._resources = {"r1": self.resource}
            tester = AgenticSmokeTest()
            with patch.object(tester, "_run_single_task", side_effect=fake_run_single_task):
                result = await tester.run(resource_id="r1", profile="reasoning_stress")

        self.assertTrue(result.agentic_capable)
        self.assertEqual(result.smoke_profile, "reasoning_stress")
        self.assertEqual(result.checks["constraint_reasoning"].status, "pass")
        self.assertIn("constraint_reasoning", result.debug_bundle)
        self.assertEqual(calls, [
            "smoke_test_reasoning_stress_r1",
            "smoke_write_reasoning_stress_r1",
            "smoke_choice_r1",
            "smoke_retry_r1",
            "smoke_reasoning_r1",
        ])


    async def test_reasoning_stress_counts_multiple_lookup_calls_in_one_iteration(self):
        async def fake_run_single_task(*, task_id, goal, available_tools, **kwargs):
            if task_id.startswith("smoke_test_"):
                return None, [{"status": "tool_use", "tool_calls": ["smoke_lookup"]}], "smoke_ok:alpha:a7c3f1"
            if task_id.startswith("smoke_write_"):
                match = re.search(r"path '([^']+)'", goal)
                write_path = match.group(1)
                with open(write_path, "w", encoding="utf-8") as f:
                    f.write("smoke_test_ok")
                return None, [{"status": "tool_use", "tool_calls": ["write_file"]}], "write ok"
            if task_id.startswith("smoke_choice_"):
                match = re.search(r"path '([^']+)'", goal)
                choice_path = match.group(1)
                with open(choice_path, "w", encoding="utf-8") as f:
                    f.write("smoke_ok:gamma:g1f8a6")
                return None, [
                    {"status": "tool_use", "tool_calls": ["smoke_lookup", "smoke_lookup", "smoke_lookup", "smoke_lookup"]},
                    {"status": "tool_use", "tool_calls": ["write_file"]},
                ], "smoke_ok:gamma:g1f8a6"
            if task_id.startswith("smoke_retry_"):
                return None, [
                    {"status": "tool_use", "tool_calls": ["smoke_fail_once"]},
                    {"status": "tool_use", "tool_calls": ["smoke_fail_once"]},
                ], "smoke_retry_ok:test"
            if task_id.startswith("smoke_reasoning_"):
                match = re.search(r"path '([^']+)'", goal)
                reasoning_path = match.group(1)
                with open(reasoning_path, "w", encoding="utf-8") as f:
                    f.write("plan_green")
                return None, [
                    {"status": "tool_use", "tool_calls": ["smoke_lookup", "smoke_lookup", "smoke_lookup"]},
                    {"status": "tool_use", "tool_calls": ["write_file"]},
                ], "plan_green is the cheapest valid plan because plan_red exceeds latency and plan_blue is invalid"
            raise AssertionError(f"unexpected task_id: {task_id}")

        with patch("app.scheduler.resource_pool.ResourceManager") as rm_cls:
            rm_cls.return_value._resources = {"r1": self.resource}
            tester = AgenticSmokeTest()
            with patch.object(tester, "_run_single_task", side_effect=fake_run_single_task):
                result = await tester.run(resource_id="r1", profile="reasoning_stress")

        self.assertEqual(result.checks["constraint_reasoning"].status, "pass")

    async def test_integration_memory_skip_does_not_change_gate(self):
        async def fake_run_single_task(*, task_id, goal, available_tools, **kwargs):
            if task_id.startswith("smoke_test_"):
                return None, [{"status": "tool_use", "tool_calls": ["smoke_lookup"]}], "smoke_ok:alpha:a7c3f1"
            if task_id.startswith("smoke_write_"):
                match = re.search(r"path '([^']+)'", goal)
                write_path = match.group(1)
                with open(write_path, "w", encoding="utf-8") as f:
                    f.write("smoke_test_ok")
                return None, [{"status": "tool_use", "tool_calls": ["write_file"]}], "write ok"
            raise AssertionError(f"unexpected task_id: {task_id}")

        unavailable_memory = SimpleNamespace(is_available=False, reason="memory offline")
        with patch("app.scheduler.resource_pool.ResourceManager") as rm_cls:
            rm_cls.return_value._resources = {"r1": self.resource}
            with patch("app.services.memory_backend.create_hybrid_memory_service", return_value=unavailable_memory):
                tester = AgenticSmokeTest()
                with patch.object(tester, "_run_single_task", side_effect=fake_run_single_task):
                    result = await tester.run(resource_id="r1", integration_checks=["memory_search"])

        self.assertTrue(result.agentic_capable)
        self.assertEqual(result.checks["integration_memory_search"].status, "skip")
        self.assertEqual(result.checks["integration_memory_search"].failure_class, "tool_backend_unavailable")

    async def test_mcp_wrapper_forwards_profile_and_integration_checks(self):
        executor = ToolRegistry.__new__(ToolRegistry)
        fake_result = SimpleNamespace(
            agentic_capable=True,
            to_dict=lambda: {
                "resource_id": "r1",
                "model": "test-model",
                "agentic_capable": True,
                "smoke_profile": "standard_agentic",
            },
        )

        with patch("app.scheduler.agentic_smoke_test.AgenticSmokeTest.run", new=AsyncMock(return_value=fake_result)) as run_mock:
            with patch("app.scheduler.resource_pool.ResourceManager") as rm_cls:
                rm_cls.return_value.record_agentic_smoke_result = lambda *args, **kwargs: None
                result = await executor._execute_resource_pool_smoke_test({
                    "resource_id": "r1",
                    "profile": "standard_agentic",
                    "integration_checks": ["memory_search", "bash_exec"],
                })

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["smoke_profile"], "standard_agentic")
        self.assertEqual(run_mock.await_args.kwargs["profile"], "standard_agentic")
        self.assertEqual(run_mock.await_args.kwargs["integration_checks"], ["memory_search", "bash_exec"])

    async def test_retry_helper_is_isolated_per_executor_instance(self):
        first = AgenticExecutor.__new__(AgenticExecutor)
        second = AgenticExecutor.__new__(AgenticExecutor)

        self.assertIn("error", first._execute_smoke_fail_once({"key": "test"}))
        self.assertEqual(first._execute_smoke_fail_once({"key": "test"})["result"], "smoke_retry_ok:test")
        self.assertIn("error", second._execute_smoke_fail_once({"key": "test"}))

    def test_smoke_tools_are_smoke_only_and_resolver_requires_opt_in(self):
        self.assertIn("smoke_lookup", SMOKE_ONLY_TOOLS)
        self.assertIn("smoke_fail_once", SMOKE_ONLY_TOOLS)
        self.assertNotIn("smoke_lookup", BUILTIN_TOOLS)
        self.assertNotIn("smoke_fail_once", BUILTIN_TOOLS)

        resolver = CapabilityResolver()
        tool_registry = SimpleNamespace(_tools={}, get_tool=lambda name: None)
        self.assertEqual(resolver._expand(["smoke_lookup"], tool_registry), [])
        self.assertCountEqual(
            resolver._expand(["smoke_lookup", "smoke_fail_once"], tool_registry, allow_smoke_tools=True),
            ["smoke_lookup", "smoke_fail_once"],
        )


if __name__ == "__main__":
    unittest.main()
