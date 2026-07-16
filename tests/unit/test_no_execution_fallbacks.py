from pathlib import Path


def test_agentic_executor_has_no_completion_fallback_recovery_block():
    p = Path("app/scheduler/agentic_executor.py")
    text = p.read_text(encoding="utf-8")

    banned_markers = [
        "fallback completion recovery",
        "completed_fallback",
        "auto-extracted last response",
    ]

    for marker in banned_markers:
        assert marker not in text, f"Forbidden fallback marker found in {p}: {marker}"


def test_agentic_executor_role_resolution_must_not_continue_without_role():
    p = Path("app/scheduler/agentic_executor.py")
    text = p.read_text(encoding="utf-8")

    assert "continuing without role" not in text


def test_agentic_executor_must_not_pause_on_capability_gap_or_budget_exhaustion():
    p = Path("app/scheduler/agentic_executor.py")
    text = p.read_text(encoding="utf-8")

    banned_markers = [
        "waiting_for_input=gap_result.ask_user_question()",
        "without a final answer. Reply 'yes' to grant more iterations and ",
        "resume, or 'no' to mark the task as failed.",
    ]
    for marker in banned_markers:
        assert marker not in text, f"Forbidden execution stall marker found in {p}: {marker}"


def test_agentic_executor_does_not_block_ask_user_in_execution_flow():
    """ask_user is documented system-wide as the always-available HITL escape
    hatch (capability_defaults.json: "can never be removed"). It used to be
    hard-blocked outside two narrow escalation contexts, which meant a role
    that genuinely needed a human decision mid-task (e.g. "should I generate
    an SSH deploy key and have you add it to GitHub?") got a flat rejection
    instead of a real pause — the question silently vanished: no
    waiting_for_input, no Discord/ntfy notification, task just completed as
    if nothing was blocked. Reversed 2026-07-17 after this fired for real.
    The genuine-pause path (ask_user succeeds -> _cv_waiting_q ->
    TaskResult.waiting_for_input) was never broken; only the gate in front
    of it was."""
    p = Path("app/scheduler/agentic_executor.py")
    text = p.read_text(encoding="utf-8")
    assert "ask_user is blocked for normal execution flow." not in text


def test_agentic_executor_uses_context_local_enabled_tools():
    p = Path("app/scheduler/agentic_executor.py")
    text = p.read_text(encoding="utf-8")
    assert "_cv_enabled_tools" in text
    assert "enabled = _cv_enabled_tools.get()" in text
