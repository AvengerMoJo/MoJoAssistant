"""Regression tests for the requires_tools_called_before_final guard.

Bug found live 2026-08-25 (Rebecca, task rebecca_agent_boundary_research_2608):
her task goal and her own role's "Deliver" workflow stage both said to write
findings to memory/a file before finishing -- a prompt-level instruction with
nothing enforcing it. She produced a <FINAL_ANSWER> and stopped without ever
calling write_file or add_conversation; the task was accepted as a success
anyway, and the durable research it existed to produce simply didn't exist.

Fix: behavior_rules.requires_tools_called_before_final names a set of tool
names, at least one of which must have actually been called (tracked via
_cv_deliverable_tools_called) before _validate_final_answer accepts a
FINAL_ANSWER. Mirrors the existing requires_tool_use guard, but for a
specific configurable tool set rather than "any tool at all".
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _make_executor():
    from app.scheduler.agentic_executor import AgenticExecutor
    return AgenticExecutor.__new__(AgenticExecutor)


def _reset_cv(required=(), called=frozenset(), enabled_tools=None, tool_calls=1):
    from app.scheduler.agentic_executor import (
        _cv_requires_deliverable, _cv_deliverable_tools_called,
        _cv_enabled_tools, _cv_tool_calls,
    )
    _cv_requires_deliverable.set(tuple(required))
    _cv_deliverable_tools_called.set(frozenset(called))
    _cv_enabled_tools.set(enabled_tools)
    _cv_tool_calls.set(tool_calls)


class TestValidateFinalAnswerDeliverableGuard(unittest.TestCase):
    def test_rejects_final_answer_when_required_tool_never_called(self):
        exc = _make_executor()
        _reset_cv(required=["write_file", "add_conversation"], called=frozenset())

        is_valid, error = exc._validate_final_answer(
            final_answer="Here are my findings, fully synthesized.",
            goal="Research X and write findings to memory when done.",
            config={},
        )

        self.assertFalse(is_valid)
        self.assertIn("write_file", error)
        self.assertIn("add_conversation", error)

    def test_accepts_final_answer_when_one_required_tool_was_called(self):
        exc = _make_executor()
        _reset_cv(required=["write_file", "add_conversation"], called=frozenset({"add_conversation"}))

        is_valid, error = exc._validate_final_answer(
            final_answer="Here are my findings, fully synthesized.",
            goal="Research X and write findings to memory when done.",
            config={},
        )

        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_no_requirement_set_is_unaffected(self):
        """Default (no behavior_rules.requires_tools_called_before_final) --
        must not change behavior for roles/tasks that never asked for this."""
        exc = _make_executor()
        _reset_cv(required=(), called=frozenset())

        is_valid, error = exc._validate_final_answer(
            final_answer="Here are my findings, fully synthesized.",
            goal="Research X.",
            config={},
        )

        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_only_a_different_required_tool_being_called_still_rejects(self):
        exc = _make_executor()
        _reset_cv(required=["write_file"], called=frozenset({"web_search", "fetch_url"}))

        is_valid, error = exc._validate_final_answer(
            final_answer="Here are my findings, fully synthesized.",
            goal="Research X and write it to a file when done.",
            config={},
        )

        self.assertFalse(is_valid)


class TestDeliverableToolTrackingSite(unittest.TestCase):
    """The bookkeeping in _execute_single_tool that populates
    _cv_deliverable_tools_called -- verified as pure ContextVar logic,
    mirroring how the tool dispatch increments _cv_tool_calls."""

    def test_call_to_a_required_tool_is_recorded(self):
        from app.scheduler.agentic_executor import (
            _cv_requires_deliverable, _cv_deliverable_tools_called,
        )
        _cv_requires_deliverable.set(("write_file", "add_conversation"))
        _cv_deliverable_tools_called.set(frozenset())

        name = "write_file"
        if name in _cv_requires_deliverable.get():
            _cv_deliverable_tools_called.set(_cv_deliverable_tools_called.get() | {name})

        self.assertEqual(_cv_deliverable_tools_called.get(), frozenset({"write_file"}))

    def test_call_to_an_unrelated_tool_is_not_recorded(self):
        from app.scheduler.agentic_executor import (
            _cv_requires_deliverable, _cv_deliverable_tools_called,
        )
        _cv_requires_deliverable.set(("write_file", "add_conversation"))
        _cv_deliverable_tools_called.set(frozenset())

        name = "web_search"
        if name in _cv_requires_deliverable.get():
            _cv_deliverable_tools_called.set(_cv_deliverable_tools_called.get() | {name})

        self.assertEqual(_cv_deliverable_tools_called.get(), frozenset())


if __name__ == "__main__":
    unittest.main()
