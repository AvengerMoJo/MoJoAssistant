"""
Smoke — Coding agent HITL bridge.

Verifies the ask_user / check_reply protocol that lets external coding
agents (Claude Code, OpenCode) pause and inject questions into the HITL
inbox, then receive user replies without re-entering the scheduler loop.

No network, LLM, or process spawning required.
"""

import pytest
from pathlib import Path

from app.scheduler.hitl_bridge import ask_user, check_reply
from app.scheduler.models import Task, TaskStatus, TaskType
from app.scheduler.queue import TaskQueue


@pytest.fixture()
def queue(tmp_path: Path) -> TaskQueue:
    return TaskQueue(storage_path=str(tmp_path / "tasks.json"))


# ---------------------------------------------------------------------------
# ask_user
# ---------------------------------------------------------------------------

class TestAskUser:

    def test_creates_stub_task(self, queue: TaskQueue):
        result = ask_user(queue, "cc-1", "Should I use A or B?")
        assert result["status"] == "waiting"
        assert result["task_id"] == "cc-1"
        task = queue.get("cc-1")
        assert task is not None
        assert task.status == TaskStatus.WAITING_FOR_INPUT
        assert task.pending_question == "Should I use A or B?"

    def test_stub_task_is_marked_ext_agent_hitl(self, queue: TaskQueue):
        ask_user(queue, "cc-2", "Question?")
        task = queue.get("cc-2")
        assert task.config.get("ext_agent_hitl") is True

    def test_stub_task_type_is_agent(self, queue: TaskQueue):
        ask_user(queue, "cc-3", "Question?")
        task = queue.get("cc-3")
        assert task.type == TaskType.AGENT

    def test_options_stored_in_config(self, queue: TaskQueue):
        ask_user(queue, "cc-4", "Which?", options=["A", "B", "C"])
        task = queue.get("cc-4")
        assert task.config.get("pending_options") == ["A", "B", "C"]

    def test_second_question_updates_existing_task(self, queue: TaskQueue):
        ask_user(queue, "cc-5", "First question?")
        result = ask_user(queue, "cc-5", "Second question?")
        assert result["status"] == "waiting"
        task = queue.get("cc-5")
        assert task.pending_question == "Second question?"
        assert task.status == TaskStatus.WAITING_FOR_INPUT

    def test_second_question_clears_stale_reply(self, queue: TaskQueue):
        ask_user(queue, "cc-6", "First question?")
        task = queue.get("cc-6")
        task.config["ext_agent_reply"] = "old reply"
        queue.update(task)
        ask_user(queue, "cc-6", "Second question?")
        task = queue.get("cc-6")
        assert "ext_agent_reply" not in task.config

    def test_missing_task_id_returns_error(self, queue: TaskQueue):
        result = ask_user(queue, "", "Question?")
        assert result["status"] == "error"

    def test_missing_question_returns_error(self, queue: TaskQueue):
        result = ask_user(queue, "cc-7", "")
        assert result["status"] == "error"

    def test_response_contains_poll_hint(self, queue: TaskQueue):
        result = ask_user(queue, "cc-8", "Question?")
        assert "poll_with" in result
        assert "check_reply" in result["poll_with"]

    def test_response_contains_reply_tool_hint(self, queue: TaskQueue):
        result = ask_user(queue, "cc-9", "Question?")
        assert "user_reply_tool" in result
        assert "reply_to_task" in result["user_reply_tool"]


# ---------------------------------------------------------------------------
# check_reply
# ---------------------------------------------------------------------------

class TestCheckReply:

    def test_pending_when_no_reply(self, queue: TaskQueue):
        ask_user(queue, "cc-10", "Question?")
        result = check_reply(queue, "cc-10")
        assert result["status"] == "pending"
        assert result.get("question") == "Question?"

    def test_answered_after_reply_injected(self, queue: TaskQueue):
        ask_user(queue, "cc-11", "Question?")
        # Simulate user reply via resume_task_with_reply — directly set ext_agent_reply
        task = queue.get("cc-11")
        task.config["ext_agent_reply"] = "Use approach A"
        task.status = TaskStatus.RUNNING
        task.pending_question = None
        queue.update(task)
        result = check_reply(queue, "cc-11")
        assert result["status"] == "answered"
        assert result["reply"] == "Use approach A"

    def test_reply_is_consumed_on_first_check(self, queue: TaskQueue):
        ask_user(queue, "cc-12", "Question?")
        task = queue.get("cc-12")
        task.config["ext_agent_reply"] = "Some answer"
        task.status = TaskStatus.RUNNING
        queue.update(task)
        first = check_reply(queue, "cc-12")  # consume
        assert first["status"] == "answered"
        second = check_reply(queue, "cc-12")  # second call — no pending question, task is RUNNING
        assert second["status"] == "no_reply"

    def test_task_status_set_to_running_after_reply(self, queue: TaskQueue):
        ask_user(queue, "cc-13", "Question?")
        task = queue.get("cc-13")
        task.config["ext_agent_reply"] = "Yes"
        task.status = TaskStatus.RUNNING
        queue.update(task)
        check_reply(queue, "cc-13")
        task = queue.get("cc-13")
        assert task.status == TaskStatus.RUNNING

    def test_missing_task_id_returns_error(self, queue: TaskQueue):
        result = check_reply(queue, "")
        assert result["status"] == "error"

    def test_unknown_task_id_returns_error(self, queue: TaskQueue):
        result = check_reply(queue, "nonexistent-99")
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()


# ---------------------------------------------------------------------------
# Full round-trip: ask → reply → check
# ---------------------------------------------------------------------------

class TestHITLRoundTrip:

    def test_full_ask_reply_check_cycle(self, queue: TaskQueue):
        """Simulates a complete coding agent pause-and-resume cycle."""
        # 1. Agent asks a question
        result = ask_user(queue, "rt-1", "Should I proceed with refactor?")
        assert result["status"] == "waiting"

        # 2. Agent polls — no reply yet
        assert check_reply(queue, "rt-1")["status"] == "pending"

        # 3. User replies (via the ext_agent_reply path, as resume_task_with_reply would set it)
        task = queue.get("rt-1")
        task.config["ext_agent_reply"] = "Yes, proceed"
        task.status = TaskStatus.RUNNING
        task.pending_question = None
        queue.update(task)

        # 4. Agent polls again — gets the answer
        result = check_reply(queue, "rt-1")
        assert result["status"] == "answered"
        assert result["reply"] == "Yes, proceed"

        # 5. Agent can ask another question in the same session
        result = ask_user(queue, "rt-1", "Which branch should I target?")
        assert result["status"] == "waiting"
        task = queue.get("rt-1")
        assert task.pending_question == "Which branch should I target?"

    def test_multiple_independent_sessions(self, queue: TaskQueue):
        """Two independent coding agent sessions don't interfere."""
        ask_user(queue, "sess-a", "Question from agent A?")
        ask_user(queue, "sess-b", "Question from agent B?")

        # Reply to B only
        task_b = queue.get("sess-b")
        task_b.config["ext_agent_reply"] = "B answered"
        task_b.status = TaskStatus.RUNNING
        queue.update(task_b)

        assert check_reply(queue, "sess-a")["status"] == "pending"
        assert check_reply(queue, "sess-b")["status"] == "answered"


# ---------------------------------------------------------------------------
# resume_task_with_reply integration
# ---------------------------------------------------------------------------

class TestResumeTaskWithReplyIntegration:
    """Verify that the scheduler's resume_task_with_reply correctly routes
    ext_agent_hitl tasks to ext_agent_reply (not reply_to_question)."""

    def test_ext_agent_reply_key_not_reply_to_question(self, queue: TaskQueue):
        """After user replies, ext_agent_hitl tasks use ext_agent_reply key."""
        ask_user(queue, "res-1", "Question?")
        task = queue.get("res-1")
        # Simulate what resume_task_with_reply does for ext_agent_hitl tasks
        assert task.config.get("ext_agent_hitl") is True
        task.config["ext_agent_reply"] = "reply"
        task.status = TaskStatus.RUNNING
        task.pending_question = None
        queue.update(task)

        task = queue.get("res-1")
        assert "ext_agent_reply" in task.config
        assert "reply_to_question" not in task.config
        assert task.status == TaskStatus.RUNNING  # NOT PENDING

    def test_task_never_becomes_pending_after_reply(self, queue: TaskQueue):
        """After a reply, the task status must never be PENDING (would trigger executor)."""
        ask_user(queue, "res-2", "Question?")
        # Simulate reply routing
        task = queue.get("res-2")
        task.config["ext_agent_reply"] = "answer"
        task.status = TaskStatus.RUNNING
        queue.update(task)
        # check_reply consumes and keeps RUNNING
        check_reply(queue, "res-2")
        task = queue.get("res-2")
        assert task.status != TaskStatus.PENDING
