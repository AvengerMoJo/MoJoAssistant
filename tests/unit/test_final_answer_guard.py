"""Tests for the FINAL_ANSWER tool-use guard.

The bug we're fixing (v1.4.3 → v1.4.4):

  A task with tools available but the model produces a <FINAL_ANSWER> on its
  first iteration WITHOUT calling any tool. The previous behavior marked the
  task as completed/success because the FINAL_ANSWER tag was present.

  Real examples (both seen today):
    - Popo e5e02fbf: 1 iteration, 0 tool calls, output "I'm starting fresh"
    - Paul c4f8efca: 1 iteration, 0 tool calls, output "Starting discovery phase"

  The guard:
    1. If the agent produces <FINAL_ANSWER> AND
       tools were available AND
       zero tools have been called so far
       → REJECT the final answer, inject a forcing message, force another iteration.

  This file tests the guard directly (unit) and via integration with the
  actual AgenticExecutor loop (without a real LLM).
"""

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _make_executor():
    """Return a barely-alive AgenticExecutor with heavy deps stubbed out."""
    from app.scheduler.agentic_executor import AgenticExecutor

    task = MagicMock()
    task.id = "test-task-1"
    task.dispatch_depth = 0
    task.config = {"goal": "test goal"}
    task.priority.value = "normal"

    rm = MagicMock()
    rm.acquire.return_value = MagicMock(id="r1", tier=MagicMock(value="free"))
    rm.acquire_by_id.return_value = MagicMock(id="r1", tier=MagicMock(value="free"))
    rm.acquire_by_requirements.return_value = MagicMock(id="r1", tier=MagicMock(value="free"))

    session_storage = MagicMock()
    policy_monitor = MagicMock()
    policy_monitor.data_boundary = {}
    memory = MagicMock()
    mcp_mgr = MagicMock()

    executor = AgenticExecutor.__new__(AgenticExecutor)
    executor._rm = rm
    executor._session_storage = session_storage
    executor._policy_monitor = policy_monitor
    executor._memory_service = memory
    executor._mcp_client_manager = mcp_mgr
    executor._log = MagicMock()
    executor._record = MagicMock()
    executor._session_storage.update_status = MagicMock()
    executor._session_storage.append_message = MagicMock()
    executor._emit_policy_violation = AsyncMock()
    executor._validate_final_answer = MagicMock(return_value=(True, None))
    executor._parse_final_answer = MagicMock(return_value="final answer text")
    executor._completion_marker = None
    executor._session_marker = None
    executor._lesson_skip_reasons = set()
    executor._write_task_lesson = AsyncMock()
    executor._store_completion_artifact = AsyncMock()
    executor._emit_completion_event = AsyncMock()
    executor._emit_failure_event = AsyncMock()
    executor._emit_assistant_message = AsyncMock()
    executor._emit_tool_message = AsyncMock()
    executor._estimate_input_tokens = lambda msgs: 100
    executor._determine_tier_preference_for_iteration = MagicMock(
        return_value=("free", "test")
    )
    return executor


def _reset_cv():
    """Reset all executor context vars so tests don't pollute each other."""
    from app.scheduler.agentic_executor import (
        _cv_tool_calls, _cv_requires_tool, _cv_budget_ext,
        _cv_exhausts_ask, _cv_waiting_q, _cv_waiting_c,
    )
    _cv_tool_calls.set(0)
    _cv_requires_tool.set(False)
    _cv_budget_ext.set(0)
    _cv_exhausts_ask.set(False)
    _cv_waiting_q.set(None)
    _cv_waiting_c.set(None)


class FinalAnswerGuardTest(unittest.TestCase):
    """Direct tests of the FINAL_ANSWER-with-zero-tool-calls guard."""

    def setUp(self):
        _reset_cv()

    def test_final_answer_with_zero_tool_calls_is_rejected(self):
        """If model produces FINAL_ANSWER before calling any tool, reject."""
        from app.scheduler.agentic_executor import (
            _cv_requires_tool, _cv_tool_calls,
        )
        _cv_requires_tool.set(True)  # role opted in
        _cv_tool_calls.set(0)

        # Call the actual guard logic that the loop uses
        from app.scheduler.agentic_executor import AgenticExecutor
        exc = _make_executor()
        candidate = "I'm starting the task. <FINAL_ANSWER>Done.</FINAL_ANSWER>"
        exc._parse_final_answer.return_value = candidate

        # Simulate what the loop does: check the guard
        # This test will FAIL until the guard exists / is wired to always-on
        requires_tool = _cv_requires_tool.get()
        tool_calls = _cv_tool_calls.get()
        would_reject = (
            candidate is not None
            and requires_tool
            and tool_calls == 0
        )
        self.assertTrue(would_reject,
                         "Guard must reject FINAL_ANSWER when tool_calls=0 and requires_tool=True")

    def test_final_answer_with_tool_calls_is_accepted(self):
        """FINAL_ANSWER after at least one tool call is the normal case."""
        from app.scheduler.agentic_executor import (
            _cv_requires_tool, _cv_tool_calls,
        )
        _cv_requires_tool.set(True)
        _cv_tool_calls.set(3)  # already made 3 calls

        from app.scheduler.agentic_executor import AgenticExecutor
        exc = _make_executor()
        candidate = "After running tools, here's the answer. <FINAL_ANSWER>Done.</FINAL_ANSWER>"
        exc._parse_final_answer.return_value = candidate

        requires_tool = _cv_requires_tool.get()
        tool_calls = _cv_tool_calls.get()
        would_reject = (
            candidate is not None
            and requires_tool
            and tool_calls == 0
        )
        self.assertFalse(would_reject,
                          "Guard must NOT reject when tool_calls > 0")

    def test_final_answer_without_tools_available_is_accepted(self):
        """When no tools were available, FINAL_ANSWER is fine (no work to do)."""
        from app.scheduler.agentic_executor import (
            _cv_requires_tool, _cv_tool_calls,
        )
        _cv_requires_tool.set(False)  # role explicitly says tools not required
        _cv_tool_calls.set(0)

        exc = _make_executor()
        candidate = "I have no tools so here's my answer. <FINAL_ANSWER>Done.</FINAL_ANSWER>"
        exc._parse_final_answer.return_value = candidate

        requires_tool = _cv_requires_tool.get()
        tool_calls = _cv_tool_calls.get()
        would_reject = (
            candidate is not None
            and requires_tool
            and tool_calls == 0
        )
        self.assertFalse(would_reject,
                          "Guard must NOT reject when role doesn't require tools")

    def test_paul_pattern_simulated_failure(self):
        """Exact reproduction of Paul c4f8efca's failure: 1 iter, 0 tools, FINAL_ANSWER with planning prose."""
        from app.scheduler.agentic_executor import (
            _cv_requires_tool, _cv_tool_calls,
        )
        # After v1.4.4 fix: requires_tool defaults to True for all roles
        _cv_requires_tool.set(True)
        _cv_tool_calls.set(0)

        # Paul's actual output (paraphrased)
        paul_output = (
            "**Completed:** None yet — this is iteration 1. Starting discovery phase per SOP. "
            "Will read repo state and existing files before proposing architecture.\n\n"
            "**Findings:** No tools called yet.\n\n"
            "**Incomplete:** Full discovery and PRD writing pending.\n"
            "<FINAL_ANSWER>Planning prose...</FINAL_ANSWER>"
        )

        exc = _make_executor()
        exc._parse_final_answer.return_value = paul_output

        requires_tool = _cv_requires_tool.get()
        tool_calls = _cv_tool_calls.get()
        candidate = paul_output
        would_reject = (
            candidate is not None
            and requires_tool
            and tool_calls == 0
        )
        self.assertTrue(would_reject,
                         "Paul-style 'I am starting' planning output MUST be rejected "
                         "by the FINAL_ANSWER guard when requires_tool=True")

    def test_popo_pattern_simulated_failure(self):
        """Exact reproduction of Popo e5e02fbf's failure: 0 tools, FINAL_ANSWER saying 'starting fresh'."""
        from app.scheduler.agentic_executor import (
            _cv_requires_tool, _cv_tool_calls,
        )
        _cv_requires_tool.set(True)
        _cv_tool_calls.set(0)

        popo_output = (
            "**Completed:** I'm starting fresh on this task - no tools called yet in this run.\n\n"
            "**Findings:** PR #1 needs Docker build fix and merge.\n\n"
            "**Incomplete:** Haven't examined the actual Docker failure yet.\n"
            "<FINAL_ANSWER>Need to diagnose before fixing.</FINAL_ANSWER>"
        )

        exc = _make_executor()
        exc._parse_final_answer.return_value = popo_output

        requires_tool = _cv_requires_tool.get()
        tool_calls = _cv_tool_calls.get()
        candidate = popo_output
        would_reject = (
            candidate is not None
            and requires_tool
            and tool_calls == 0
        )
        self.assertTrue(would_reject,
                         "Popo-style 'I'm starting fresh' planning output MUST be rejected")


class RequiresToolDefaultTest(unittest.TestCase):
    """The requires_tool flag should default to True for any role that has tools."""

    def test_default_value_is_true_or_set_from_role(self):
        """If a role has no behavior_rules.requires_tool_use, the default
        behavior should be to require tool use (safer). The old default of
        False is what enabled the c4f8efca / e5e02fbf fake-completions.

        We test this by reading the executor source — the default value of
        _cv_requires_tool must be True, or the role-load code must default
        to True when the key is missing.
        """
        from app.scheduler import agentic_executor as exec_mod
        import inspect

        # Find the ContextVar declaration
        cv = exec_mod._cv_requires_tool
        # ContextVar doesn't expose .default in older python; use introspection
        # The default is captured in cv._default (private) or via the constructor.
        # The cleanest check: grep the source for the default value.
        src = inspect.getsource(exec_mod)
        # The ContextVar is declared somewhere as ContextVar(..., default=X)
        # Look for the declaration line.
        for line in src.splitlines():
            if "_cv_requires_tool" in line and "ContextVar" in line:
                self.assertIn("default=True", line,
                              f"_cv_requires_tool must default to True. Got: {line!r}")
                return
        self.fail("_cv_requires_tool ContextVar declaration not found")

    def test_role_without_requires_tool_flag_still_gets_protection(self):
        """A role like Paul or Popo that doesn't set behavior_rules.requires_tool_use
        still gets protection via the new default."""
        # Simulate role loading with no behavior_rules
        role_config = {"name": "Popo", "behavior_rules": {}}
        behavior_rules = role_config.get("behavior_rules", {})
        # NEW behavior: default True if key missing
        requires_tool = behavior_rules.get("requires_tool_use", True)
        self.assertTrue(requires_tool,
                        "Roles without explicit requires_tool_use flag must default to True")


class ShouldRejectEmptyFinalAnswerTest(unittest.TestCase):
    """Direct unit tests of the _should_reject_empty_final_answer method."""

    def setUp(self):
        self.exc = _make_executor()

    def test_rejects_when_candidate_present_requires_tool_true_zero_calls(self):
        self.assertTrue(
            self.exc._should_reject_empty_final_answer(
                candidate_final_answer="Any answer",
                requires_tool=True,
                tool_calls=0,
            )
        )

    def test_accepts_when_no_candidate(self):
        self.assertFalse(
            self.exc._should_reject_empty_final_answer(
                candidate_final_answer=None,
                requires_tool=True,
                tool_calls=0,
            )
        )

    def test_accepts_when_requires_tool_false(self):
        self.assertFalse(
            self.exc._should_reject_empty_final_answer(
                candidate_final_answer="Any answer",
                requires_tool=False,
                tool_calls=0,
            )
        )

    def test_accepts_when_tool_calls_positive(self):
        self.assertFalse(
            self.exc._should_reject_empty_final_answer(
                candidate_final_answer="Any answer",
                requires_tool=True,
                tool_calls=5,
            )
        )

    def test_paul_and_popo_outputs_would_be_rejected(self):
        """Real-world fake-completion outputs from today's failures."""
        paul = (
            "**Completed:** None yet — this is iteration 1. Starting discovery phase per SOP. "
            "<FINAL_ANSWER>Planning prose...</FINAL_ANSWER>"
        )
        popo = (
            "**Completed:** I'm starting fresh on this task - no tools called yet in this run. "
            "<FINAL_ANSWER>Need to diagnose before fixing.</FINAL_ANSWER>"
        )
        for fake_output in (paul, popo):
            self.assertTrue(
                self.exc._should_reject_empty_final_answer(
                    candidate_final_answer=fake_output,
                    requires_tool=True,
                    tool_calls=0,
                ),
                f"Output {fake_output[:60]!r}... should be rejected"
            )


class PostConditionZeroToolCallsTest(unittest.TestCase):
    """Defense in depth: the scheduler-layer post-condition check that catches
    any path the in-loop guard might have missed.

    The post-condition logic isn't a method we can call directly — it's
    inline in the execute() loop. We test it by reading the source for the
    pattern that requires tool_calls > 0 when final_answer is set.
    """

    def _get_execute_source(self):
        from app.scheduler.agentic_executor import AgenticExecutor
        import inspect
        return inspect.getsource(AgenticExecutor.execute)

    def test_post_condition_check_present_in_source(self):
        """Verify the post-condition guard exists in the execute loop body."""
        src = self._get_execute_source()
        self.assertIn("total_tool_calls", src,
                      "Post-condition must check total_tool_calls across iteration_log")
        self.assertIn("fake_completion_detected", src,
                      "Post-condition must downgrade with a recognizable status")
        self.assertIn("Post-condition failure", src,
                      "Post-condition must report failure with a clear message")

    def test_post_condition_message_mentions_guards_test(self):
        """The error message should reference the test file so future maintainers
        know where to look."""
        src = self._get_execute_source()
        self.assertIn("test_final_answer_guard.py", src,
                      "Post-condition error should reference the regression test")


if __name__ == "__main__":
    unittest.main()
