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


def test_agentic_executor_blocks_non_security_ask_user_in_execution_flow():
    p = Path("app/scheduler/agentic_executor.py")
    text = p.read_text(encoding="utf-8")
    assert "ask_user is blocked for normal execution flow." in text
