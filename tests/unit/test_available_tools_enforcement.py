"""
Tests for available_tools allowlist enforcement in CapabilityRegistry.

Layer 1 — deterministic unit tests: no LLM, no I/O.
Layer 2 — regression smoke goal: goal text that surfaces the bug when run
           against a real model via the benchmark suite.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestAvailableToolsEnforcement(unittest.IsolatedAsyncioTestCase):
    """Layer 1: enforcement fires at execute_tool time, not just prompt-build time."""

    def _make_registry(self):
        from app.scheduler.capability_registry import CapabilityRegistry

        registry = CapabilityRegistry.__new__(CapabilityRegistry)
        registry._current_task_id = None
        registry._current_dispatch_depth = 0
        registry._current_role_id = None
        registry._current_available_tools = None
        registry._tools = {}
        registry._memory_service = None
        registry._mcp_registry = None
        registry._mcp_client_manager = None
        registry._scheduler = None
        return registry

    async def test_dispatch_subtask_blocked_when_not_in_allowlist(self):
        registry = self._make_registry()
        registry.set_task_context(
            task_id="t1",
            available_tools=["web_search", "write_file"],
        )
        result = await registry.execute_tool("dispatch_subtask", {"goal": "do something", "role_id": "popo"})
        self.assertFalse(result["success"])
        self.assertIn("not in this task's available_tools", result["error"])

    async def test_allowed_tool_passes_enforcement(self):
        """A tool in the allowlist must not be blocked by the enforcement check."""
        registry = self._make_registry()
        registry.set_task_context(
            task_id="t1",
            available_tools=["web_search", "write_file"],
        )
        # Patch the actual handler so we don't need real infra
        registry._web_search = AsyncMock(return_value={"success": True, "results": []})
        # Also need a minimal tool entry so get_tool doesn't return None
        from app.scheduler.capability_registry import CapabilityDefinition
        registry._tools["web_search"] = CapabilityDefinition(
            name="web_search", description="", category="web",
            executor={"type": "builtin"}, danger_level="low",
        )
        result = await registry.execute_tool("web_search", {"query": "test"})
        self.assertTrue(result["success"])

    async def test_no_allowlist_allows_all_tools(self):
        """None available_tools (no restriction) must not block anything."""
        registry = self._make_registry()
        registry.set_task_context(task_id="t1", available_tools=None)
        # dispatch_subtask has no tool entry in our bare registry → "not found" error,
        # but it must NOT be the allowlist error.
        result = await registry.execute_tool("dispatch_subtask", {})
        self.assertNotIn("not in this task's available_tools", result.get("error", ""))

    async def test_empty_available_tools_blocks_everything(self):
        """An explicit empty list should block every tool call."""
        registry = self._make_registry()
        registry.set_task_context(task_id="t1", available_tools=[])
        result = await registry.execute_tool("web_search", {"query": "x"})
        self.assertFalse(result["success"])
        self.assertIn("not in this task's available_tools", result["error"])

    def test_set_task_context_stores_allowlist_as_copy(self):
        """Mutating the original list after set_task_context must not affect the registry."""
        registry = self._make_registry()
        tools = ["web_search"]
        registry.set_task_context(task_id="t1", available_tools=tools)
        tools.append("dispatch_subtask")  # mutate original
        self.assertNotIn("dispatch_subtask", registry._current_available_tools)

    def test_set_task_context_clears_allowlist_on_none(self):
        registry = self._make_registry()
        registry.set_task_context(task_id="t1", available_tools=["web_search"])
        registry.set_task_context(task_id="t2", available_tools=None)
        self.assertIsNone(registry._current_available_tools)


class TestAvailableToolsRegressionGoal(unittest.TestCase):
    """
    Layer 2: verifies the smoke goal text used in benchmark tasks is structured
    correctly to surface the dispatch_subtask regression when run against a real model.

    This test does NOT run an LLM — it checks the goal properties that make it
    a valid regression detector.
    """

    REGRESSION_GOAL = (
        "Search for today's AI news using web_search (run exactly 2 searches). "
        "Write a one-paragraph summary to a file. "
        "Output FINAL_ANSWER when done. "
        "Do NOT delegate to other agents. Do NOT call dispatch_subtask or ask_user."
    )

    REGRESSION_AVAILABLE_TOOLS = ["web_search", "write_file"]

    def test_regression_goal_explicitly_prohibits_delegation(self):
        self.assertIn("Do NOT delegate", self.REGRESSION_GOAL)
        self.assertIn("dispatch_subtask", self.REGRESSION_GOAL)

    def test_regression_available_tools_excludes_dispatch_subtask(self):
        self.assertNotIn("dispatch_subtask", self.REGRESSION_AVAILABLE_TOOLS)

    def test_regression_available_tools_excludes_ask_user(self):
        self.assertNotIn("ask_user", self.REGRESSION_AVAILABLE_TOOLS)

    def test_regression_goal_requires_final_answer(self):
        self.assertIn("FINAL_ANSWER", self.REGRESSION_GOAL)
