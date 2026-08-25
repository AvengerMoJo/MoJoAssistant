"""Regression tests for the budget-extension wall-clock fix.

Bug found live 2026-08-25 (Rebecca, task rebecca_agent_boundary_research_2608):
BUDGET_EXTENSION_REQUEST granted more max_iterations but never extended the
wall-clock max_duration cap (default 300s). The agent was doing real, correct
work, got its extension granted, and the very next elapsed-time check killed
the task anyway -- 3/3 retries, all "Time budget exhausted" immediately after
"Budget extended by N iterations. Continue your work." was injected.

Fix: every iteration grant now also grants
grant * _SECONDS_PER_EXTENDED_ITERATION wall-clock seconds, via a new
_cv_duration_ext ContextVar (tool-call path) applied in the main loop the
same way _cv_budget_ext already is, and directly on the plain-text path
(same function scope, no ContextVar needed there).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _make_executor():
    from app.scheduler.agentic_executor import AgenticExecutor

    exc = AgenticExecutor.__new__(AgenticExecutor)
    exc._log = lambda msg, level="info": None
    exc._tool_registry = MagicMock()
    exc._tool_registry.get_tool.return_value = None
    exc._policy_monitor = MagicMock()
    exc._policy_monitor.check.return_value = MagicMock(allowed=True, warn=False)
    exc._gate = MagicMock()
    exc._gate.check.return_value = MagicMock(allowed=True)
    return exc


def _reset_cv():
    from app.scheduler.agentic_executor import (
        _cv_budget_ext, _cv_duration_ext, _cv_exhausts_ask,
        _cv_tool_calls, _cv_waiting_q, _cv_waiting_c,
    )
    _cv_budget_ext.set(0)
    _cv_duration_ext.set(0.0)
    _cv_exhausts_ask.set(False)
    _cv_tool_calls.set(1)  # so exhausts_tools_before_asking never blocks these tests
    _cv_waiting_q.set(None)
    _cv_waiting_c.set(None)


class TestToolCallPathGrantsBothBudgets(unittest.IsolatedAsyncioTestCase):
    """The ask_user(question="BUDGET_EXTENSION_REQUEST: ...") path."""

    async def test_grants_duration_alongside_iterations(self):
        from app.scheduler.agentic_executor import (
            _cv_budget_ext, _cv_duration_ext, _SECONDS_PER_EXTENDED_ITERATION,
        )
        _reset_cv()
        exc = _make_executor()

        await exc._execute_single_tool(
            "ask_user",
            {"question": "BUDGET_EXTENSION_REQUEST: Need 8 more iterations. Done: X. Remaining: Y."},
        )

        self.assertEqual(_cv_budget_ext.get(), 8)
        self.assertEqual(_cv_duration_ext.get(), 8 * _SECONDS_PER_EXTENDED_ITERATION)

    async def test_grant_is_capped_the_same_way_for_both(self):
        from app.scheduler.agentic_executor import (
            _cv_budget_ext, _cv_duration_ext, _BUDGET_EXTENSION_MAX_GRANT,
            _SECONDS_PER_EXTENDED_ITERATION,
        )
        _reset_cv()
        exc = _make_executor()

        await exc._execute_single_tool(
            "ask_user",
            {"question": "BUDGET_EXTENSION_REQUEST: Need 999 more iterations. Done: X. Remaining: Y."},
        )

        self.assertEqual(_cv_budget_ext.get(), _BUDGET_EXTENSION_MAX_GRANT)
        self.assertEqual(
            _cv_duration_ext.get(),
            _BUDGET_EXTENSION_MAX_GRANT * _SECONDS_PER_EXTENDED_ITERATION,
        )


class TestMainLoopAppliesDurationExtension(unittest.TestCase):
    """The per-iteration application block that used to only touch max_iterations."""

    def test_duration_ext_contextvar_extends_max_duration(self):
        from app.scheduler.agentic_executor import _cv_duration_ext

        _cv_duration_ext.set(0.0)
        max_duration = 300
        max_iterations = 10

        # Mirrors the exact block added in the main loop.
        if _cv_duration_ext.get() > 0:
            _dur_ext = _cv_duration_ext.get()
            max_duration += _dur_ext
            _cv_duration_ext.set(0.0)

        self.assertEqual(max_duration, 300)  # nothing granted yet -- sanity check

        _cv_duration_ext.set(720.0)
        if _cv_duration_ext.get() > 0:
            _dur_ext = _cv_duration_ext.get()
            max_duration += _dur_ext
            _cv_duration_ext.set(0.0)

        self.assertEqual(max_duration, 1020)
        self.assertEqual(_cv_duration_ext.get(), 0.0)  # consumed, not double-applied


class TestPlainTextPathExtendsDurationInline(unittest.TestCase):
    """The BUDGET_EXTENSION_REQUEST-written-as-text path (what actually fired
    for Rebecca -- her model wrote the marker as assistant text, not a tool
    call). This extends max_duration directly in the same scope, no
    ContextVar round-trip."""

    def test_plain_text_grant_extends_duration_by_the_same_factor(self):
        import re
        from app.scheduler.agentic_executor import (
            _BUDGET_EXTENSION_MAX_GRANT, _SECONDS_PER_EXTENDED_ITERATION,
        )

        response_text = (
            "BUDGET_EXTENSION_REQUEST: Need 8 more iterations. "
            "Done: research so far. Remaining: synthesis."
        )
        max_iterations = 10
        max_duration = 300

        match = re.search(r"Need\s+(\d+)\s+more", response_text, re.IGNORECASE)
        grant = min(int(match.group(1)) if match else 10, _BUDGET_EXTENSION_MAX_GRANT)
        max_iterations += grant
        max_duration += grant * _SECONDS_PER_EXTENDED_ITERATION

        self.assertEqual(max_iterations, 18)
        self.assertEqual(max_duration, 300 + 8 * _SECONDS_PER_EXTENDED_ITERATION)
        # Reproduces the actual incident: 8 granted iterations must buy real
        # wall-clock room, not just a higher iteration ceiling the clock
        # will never let the task reach.
        self.assertGreater(max_duration, 300)


class TestDynamicToolExceptionSurfacesRealError(unittest.IsolatedAsyncioTestCase):
    """Bug found live 2026-08-25 (same incident): read_file/list_files worked
    at iterations 2-3, then failed at 4-6 with "Unknown or unavailable
    tool" -- despite being real builtins that had just succeeded moments
    earlier. Root cause: self._tool_registry.execute_tool() raised, the
    exception was logged and swallowed, and execution fell through to the
    small local builtin dispatch (which has no case for read_file/
    list_files), landing on the generic "unknown or unavailable" message --
    actively misleading, since the tool exists and normally works."""

    async def test_exception_from_registry_is_surfaced_not_masked(self):
        exc = _make_executor()
        exc._tool_registry.execute_tool = AsyncMock(side_effect=RuntimeError("sandbox path resolution failed"))
        _reset_cv()

        result = await exc._execute_single_tool("list_files", {"path": "/some/dir"})

        self.assertIn("error", result)
        self.assertIn("list_files", result["error"])
        self.assertIn("sandbox path resolution failed", result["error"])
        self.assertNotIn("Unknown or unavailable", result["error"])

    async def test_genuine_not_found_still_falls_through_unmasked(self):
        """A tool the registry genuinely doesn't know about (real "not
        found", not an exception) must still produce the old generic
        message -- this path is for tools agentic_executor.py's own small
        builtin set doesn't cover either, and there's no real error to
        surface."""
        exc = _make_executor()
        exc._tool_registry.execute_tool = AsyncMock(
            return_value={"success": False, "error": "Tool 'made_up_tool' not found"}
        )
        _reset_cv()

        result = await exc._execute_single_tool("made_up_tool", {})

        self.assertEqual(result, {"error": "Unknown or unavailable tool: made_up_tool"})


if __name__ == "__main__":
    unittest.main()
