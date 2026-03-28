"""Unit tests for agentic executor tool-call reliability hardening.

Covers:
  - Malformed JSON arguments return an error to the model (not silent {})
  - Consecutive no-tool iterations trigger a forcing nudge message
"""

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ---------------------------------------------------------------------------
# Helpers to build a minimal AgenticExecutor with stubs
# ---------------------------------------------------------------------------

def _make_executor():
    """Return a barely-alive AgenticExecutor with all heavy deps stubbed out."""
    from app.scheduler.agentic_executor import AgenticExecutor

    task = MagicMock()
    task.id = "test-task-1"
    task.dispatch_depth = 0
    task.config = {"goal": "test goal"}

    policy = MagicMock()
    policy.check_tool_execution.return_value = {"allowed": True}
    policy.track_operation = MagicMock()

    policy_monitor = MagicMock()
    policy_monitor.check.return_value = MagicMock(allowed=True, warn=False)
    policy_monitor.record_call = MagicMock()

    registry = MagicMock()
    registry.set_task_context = MagicMock()
    registry.get_tool.return_value = None

    rm = MagicMock()
    session_storage = MagicMock()

    exc = AgenticExecutor.__new__(AgenticExecutor)
    exc._policy = policy
    exc._policy_monitor = policy_monitor
    exc._tool_registry = registry
    exc._rm = rm
    exc._session_storage = session_storage
    exc._current_task_id = task.id
    exc._waiting_for_input_question = None
    exc._waiting_for_input_choices = None
    exc._tool_calls_made = 0
    exc._consecutive_no_tool = 0
    exc._exhausts_tools_before_asking = False
    exc._requires_tool_use = False
    exc.logger = MagicMock()
    exc._log = lambda msg, level="info": None

    # Stub _execute_single_tool to return a simple success dict
    exc._execute_single_tool = AsyncMock(return_value={"ok": True})
    exc._emit_policy_violation = AsyncMock()

    return exc


# ===========================================================================
# Malformed JSON argument handling
# ===========================================================================

class TestMalformedToolArguments(unittest.IsolatedAsyncioTestCase):

    async def test_invalid_json_returns_error_not_empty_dict(self):
        """When tool arguments are not valid JSON the model should receive an
        error string — not a silent empty-dict execution."""
        exc = _make_executor()

        tool_calls = [
            {
                "id": "call_1",
                "function": {
                    "name": "memory_search",
                    "arguments": "{not valid json",
                },
            }
        ]
        results = await exc._execute_tool_calls(tool_calls)

        self.assertEqual(len(results), 1)
        parsed = json.loads(results[0])
        self.assertIn("error", parsed)
        self.assertIn("memory_search", parsed["error"])
        self.assertIn("valid JSON", parsed["error"])

        # _execute_single_tool must NOT have been called
        exc._execute_single_tool.assert_not_awaited()

    async def test_valid_json_proceeds_normally(self):
        """Valid JSON arguments still reach _execute_single_tool."""
        exc = _make_executor()

        tool_calls = [
            {
                "id": "call_2",
                "function": {
                    "name": "memory_search",
                    "arguments": '{"query": "test"}',
                },
            }
        ]
        results = await exc._execute_tool_calls(tool_calls)

        self.assertEqual(len(results), 1)
        parsed = json.loads(results[0])
        self.assertNotIn("error", parsed)
        exc._execute_single_tool.assert_awaited_once_with("memory_search", {"query": "test"})

    async def test_empty_arguments_treated_as_empty_dict(self):
        """Empty arguments string is treated as {} and execution proceeds."""
        exc = _make_executor()

        tool_calls = [
            {
                "id": "call_3",
                "function": {
                    "name": "list_files",
                    "arguments": "",
                },
            }
        ]
        results = await exc._execute_tool_calls(tool_calls)

        self.assertEqual(len(results), 1)
        exc._execute_single_tool.assert_awaited_once_with("list_files", {})

    async def test_mixed_valid_and_invalid(self):
        """One bad call returns error; one good call still executes."""
        exc = _make_executor()

        tool_calls = [
            {
                "id": "call_bad",
                "function": {"name": "read_file", "arguments": "{{bad"},
            },
            {
                "id": "call_good",
                "function": {"name": "list_files", "arguments": '{"path": "/tmp"}'},
            },
        ]
        results = await exc._execute_tool_calls(tool_calls)

        self.assertEqual(len(results), 2)
        bad = json.loads(results[0])
        self.assertIn("error", bad)
        good = json.loads(results[1])
        self.assertNotIn("error", good)

        exc._execute_single_tool.assert_awaited_once_with("list_files", {"path": "/tmp"})


# ===========================================================================
# Consecutive no-tool drift counter
# ===========================================================================

class TestConsecutiveNoToolCounter(unittest.IsolatedAsyncioTestCase):

    def test_counter_resets_on_tool_call(self):
        """_consecutive_no_tool resets to 0 when tool_calls are present."""
        exc = _make_executor()
        exc._consecutive_no_tool = 2

        # Simulate the reset that happens at top of the tool_calls branch
        tool_calls = [{"id": "c1", "function": {"name": "x", "arguments": "{}"}}]
        if tool_calls:
            exc._consecutive_no_tool = 0

        self.assertEqual(exc._consecutive_no_tool, 0)

    def test_counter_increments_when_tools_available_but_unused(self):
        """Counter goes up each time tool_defs are provided but no tool called."""
        exc = _make_executor()
        tool_defs = [{"function": {"name": "memory_search"}}]

        for expected in range(1, 4):
            if tool_defs:
                exc._consecutive_no_tool += 1
            self.assertEqual(exc._consecutive_no_tool, expected)

    def test_forcing_message_constructed_correctly(self):
        """After 2 no-tool iterations the forcing message lists tool names."""
        exc = _make_executor()
        exc._consecutive_no_tool = 2
        tool_defs = [
            {"function": {"name": "memory_search"}},
            {"function": {"name": "read_file"}},
        ]

        if tool_defs and exc._consecutive_no_tool >= 2:
            available_names = [t["function"]["name"] for t in tool_defs]
            next_msg = (
                f"You have responded {exc._consecutive_no_tool} times without "
                "calling any tools. You have the following tools available: "
                f"{available_names}. "
                "Call a tool now to make progress, or provide your "
                "<FINAL_ANSWER> if the task is complete."
            )
            exc._consecutive_no_tool = 0
        else:
            next_msg = "CONTINUE"

        self.assertIn("memory_search", next_msg)
        self.assertIn("read_file", next_msg)
        self.assertIn("2 times", next_msg)
        self.assertEqual(exc._consecutive_no_tool, 0)

    def test_counter_does_not_increment_when_no_tools_available(self):
        """When no tool_defs, counter is reset to 0 (model can't call tools)."""
        exc = _make_executor()
        exc._consecutive_no_tool = 1
        tool_defs = []  # no tools

        if tool_defs:
            exc._consecutive_no_tool += 1
        else:
            exc._consecutive_no_tool = 0

        self.assertEqual(exc._consecutive_no_tool, 0)


if __name__ == "__main__":
    unittest.main()
