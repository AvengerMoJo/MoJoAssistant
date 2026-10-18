"""A final answer cannot claim success over a state-changing action that failed and was never fixed.

Found 2026-10-19: Paul's write_file was refused by the sandbox, nothing was created, and the answer began
'Completed: Configured Cecilia Clone ...'."""
import asyncio
from unittest.mock import MagicMock

import pytest

from app.scheduler.action_ledger import ActionLedger, MAX_REFUSALS, REFUSAL_MARKER, too_often_error

BLOCKED = {"error": "Security gate blocked: Path '~/memory/roles/cecilia_config.md' not in sandbox."}


def test_failed_write_is_pending_until_the_answer_mentions_it():
    led = ActionLedger()
    led.record("write_file", {"path": "~/memory/roles/cecilia_config.md", "content": "x"}, BLOCKED, "medium")
    answer = "**Completed:** Configured Cecilia Clone as a lean think-role."
    assert [f.tool for f in led.unaddressed(answer)] == ["write_file"]
    assert led.unaddressed("Completed the project, but write_file was refused so the role is not created.") == []
    assert led.unaddressed("The file cecilia_config.md could not be written.") == []


def test_later_success_of_the_same_tool_resolves_the_failure():
    led = ActionLedger()
    led.record("write_file", {"path": "/bad"}, BLOCKED, "medium")
    led.record("write_file", {"path": "/good"}, {"success": True}, "medium")
    assert led.unaddressed("Done.") == []


def test_other_tools_do_not_resolve_it_and_read_only_tools_are_ignored():
    led = ActionLedger()
    led.record("write_file", {"path": "/bad"}, BLOCKED, "medium")
    led.record("project_update", {"id": "x"}, {"success": True}, "low")
    led.record("read_file", {"path": "/nope"}, {"error": "missing"}, "low")
    assert [f.tool for f in led.unaddressed("All done.")] == ["write_file"]


def test_success_false_counts_as_failure():
    led = ActionLedger()
    led.record("bash_exec", {"command": "make deploy"}, {"success": False, "stderr": "boom"}, "high")
    assert len(led.failures) == 1


def test_refusals_run_out_after_the_limit():
    led = ActionLedger()
    assert [led.refuse() for _ in range(MAX_REFUSALS + 1)] == [True] * MAX_REFUSALS + [False]


def test_messages_name_the_failed_action():
    led = ActionLedger()
    led.record("write_file", {"path": "~/memory/roles/a.md"}, BLOCKED, "medium")
    pending = led.unaddressed("Completed.")
    assert led.refusal_message(pending).startswith(REFUSAL_MARKER) and "a.md" in led.refusal_message(pending)
    assert "write_file" in too_often_error(pending)


def make_executor():
    from app.scheduler.agentic_executor import AgenticExecutor
    return AgenticExecutor.__new__(AgenticExecutor)


def validate(exc, answer):
    return exc._validate_final_answer(final_answer=answer, goal="configure it", config={})


def test_validator_refuses_then_fails_the_task_after_repeated_claims():
    from app.scheduler.agentic_executor import _cv_action_ledger, _cv_requires_deliverable, _cv_deliverable_tools_called, _cv_tool_calls
    _cv_requires_deliverable.set(())
    _cv_deliverable_tools_called.set(frozenset())
    _cv_tool_calls.set(1)
    led = ActionLedger()
    led.record("write_file", {"path": "~/memory/roles/cecilia_config.md"}, BLOCKED, "medium")
    _cv_action_ledger.set(led)
    exc = make_executor()
    for _ in range(MAX_REFUSALS):
        ok, err = validate(exc, "**Completed:** Configured Cecilia.")
        assert not ok and err.startswith(REFUSAL_MARKER)
    with pytest.raises(RuntimeError, match="kept claiming completion"):
        validate(exc, "**Completed:** Configured Cecilia.")
    _cv_action_ledger.set(None)


def test_validator_accepts_an_answer_that_owns_the_failure():
    from app.scheduler.agentic_executor import _cv_action_ledger, _cv_requires_deliverable, _cv_deliverable_tools_called, _cv_tool_calls
    _cv_requires_deliverable.set(())
    _cv_deliverable_tools_called.set(frozenset())
    _cv_tool_calls.set(1)
    led = ActionLedger()
    led.record("write_file", {"path": "~/memory/roles/cecilia_config.md"}, BLOCKED, "medium")
    _cv_action_ledger.set(led)
    ok, err = validate(make_executor(), "**Incomplete:** write_file to cecilia_config.md was blocked, the role was NOT created.")
    assert ok, err
    _cv_action_ledger.set(None)
