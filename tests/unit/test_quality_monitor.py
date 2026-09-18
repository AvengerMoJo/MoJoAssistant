"""Unit tests for the Quality Monitor task-health watchdog.

Spec: docs/specs/quality_monitor_spec.md. Acceptance criterion #2 requires
a replay of the actual task-28eb4899 incident (role_id=paul, self-reported
success without meeting its own Done-when condition) to classify correctly
as falsely_completed -- test_falsely_completed_replays_paul_incident below
is that replay, using the task's real goal text.

No live network/gh/git calls -- every checker is injected.
"""

import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from app.scheduler.models import Task, TaskPriority, TaskResources, TaskResult, TaskStatus, TaskType
from app.scheduler.queue import TaskQueue
from app.scheduler.quality_monitor import (
    RESTART_CAP,
    QM_RESTART_COUNT_KEY,
    apply_action,
    check_done_when,
    classify_task,
    run_quality_check,
)

PAUL_GOAL = (
    "Read the spec at docs/specs/agent_workforce_dashboard_spec.md...\n\n"
    "Done when: a PR exists on AvengerMoJo/MoJoAssistant from "
    "wip_agent_workforce_dashboard against main, all acceptance criteria "
    "in the spec are checked off in the PR description, and "
    "tests/unit/test_agent_bridge.py passes with the new tool coverage."
)


@pytest.fixture
def queue():
    with tempfile.TemporaryDirectory() as tmp:
        yield TaskQueue(storage_path=str(Path(tmp) / "tasks.json"))


def _completed_task(task_id: str, goal: str, success: bool = True) -> Task:
    t = Task(
        id=task_id,
        type=TaskType.INTERNAL_ASSIGNMENT,
        status=TaskStatus.COMPLETED,
        config={"goal": goal, "role_id": "paul"},
        created_at=datetime.now() - timedelta(minutes=10),
    )
    t.result = TaskResult(success=success)
    return t


class TestCheckDoneWhen:
    def test_no_done_when_clause_returns_none(self):
        assert check_done_when("Just do the thing.") is None

    def test_pr_pattern_extracts_repo_and_branch(self):
        seen = {}

        def fake_pr_checker(repo, branch):
            seen["repo"] = repo
            seen["branch"] = branch
            return True

        result = check_done_when(PAUL_GOAL, pr_checker=fake_pr_checker)
        assert result is True
        assert seen["repo"] == "AvengerMoJo/MoJoAssistant"
        assert seen["branch"] == "wip_agent_workforce_dashboard"

    def test_pr_checker_false_propagates(self):
        result = check_done_when(PAUL_GOAL, pr_checker=lambda r, b: False)
        assert result is False

    def test_checker_failure_is_none_not_false(self):
        # A checker that couldn't run (gh missing, network down) must never
        # be conflated with "condition verified false".
        result = check_done_when(PAUL_GOAL, pr_checker=lambda r, b: None)
        assert result is None

    def test_file_pattern(self):
        result = check_done_when(
            "Done when: docs/specs/foo.md exists",
            file_checker=lambda p: True,
        )
        assert result is True


class TestClassifyTask:
    def test_falsely_completed_replays_paul_incident(self):
        """Direct replay of task 28eb4899: success=true, Done-when never met."""
        task = _completed_task("28eb4899", PAUL_GOAL, success=True)
        finding = classify_task(
            task,
            final_answer_loader=lambda tid: "Wrote a PRD but did not dispatch implementation or open a PR.",
            done_when_checker=lambda goal: False,
        )
        assert finding is not None
        assert finding.classification == "falsely_completed"
        assert "PRD" in finding.detail

    def test_completed_with_done_when_true_is_healthy(self):
        task = _completed_task("t1", PAUL_GOAL, success=True)
        finding = classify_task(task, done_when_checker=lambda goal: True)
        assert finding is None

    def test_completed_with_unverifiable_done_when_is_healthy(self):
        task = _completed_task("t1", "Done when: it feels right", success=True)
        finding = classify_task(task, done_when_checker=lambda goal: None)
        assert finding is None

    def test_completed_without_done_when_clause_is_healthy(self):
        task = _completed_task("t1", "Just summarize the file.", success=True)
        finding = classify_task(task)
        assert finding is None

    def test_stuck_running_past_max_duration_plus_grace(self):
        task = Task(
            id="t2",
            type=TaskType.INTERNAL_ASSIGNMENT,
            status=TaskStatus.RUNNING,
            resources=TaskResources(max_duration_seconds=60),
            started_at=datetime.now() - timedelta(seconds=600),
        )
        finding = classify_task(task)
        assert finding is not None
        assert finding.classification == "stuck"

    def test_running_within_budget_is_healthy(self):
        task = Task(
            id="t3",
            type=TaskType.INTERNAL_ASSIGNMENT,
            status=TaskStatus.RUNNING,
            resources=TaskResources(max_duration_seconds=600),
            started_at=datetime.now() - timedelta(seconds=30),
        )
        assert classify_task(task) is None

    def test_waiting_too_long(self):
        task = Task(
            id="t4",
            type=TaskType.EXTERNAL_AGENT,
            status=TaskStatus.WAITING_FOR_INPUT,
            started_at=datetime.now() - timedelta(hours=48),
        )
        finding = classify_task(task)
        assert finding is not None
        assert finding.classification == "waiting_for_input_too_long"

    def test_waiting_within_threshold_is_healthy(self):
        task = Task(
            id="t5",
            type=TaskType.EXTERNAL_AGENT,
            status=TaskStatus.WAITING_FOR_INPUT,
            started_at=datetime.now() - timedelta(hours=1),
        )
        assert classify_task(task) is None

    def test_genuinely_failed_retries_exhausted(self):
        task = Task(
            id="t6",
            type=TaskType.INTERNAL_ASSIGNMENT,
            status=TaskStatus.FAILED,
            retry_count=3,
            max_retries=3,
            last_error="boom",
        )
        finding = classify_task(task)
        assert finding is not None
        assert finding.classification == "genuinely_failed"

    def test_failed_with_retries_remaining_is_healthy(self):
        task = Task(
            id="t7",
            type=TaskType.INTERNAL_ASSIGNMENT,
            status=TaskStatus.FAILED,
            retry_count=1,
            max_retries=3,
        )
        assert classify_task(task) is None


class TestApplyAction:
    def test_falsely_completed_restarts_when_under_cap(self, queue):
        task = _completed_task("28eb4899", PAUL_GOAL, success=True)
        queue.add(task)
        finding = classify_task(
            task, final_answer_loader=lambda tid: "wrote PRD", done_when_checker=lambda g: False
        )
        result = apply_action(queue, task, finding)

        assert result.action == "restarted"
        continuation_id = "28eb4899_qm_restart_1"
        continuation = queue.get(continuation_id)
        assert continuation is not None
        assert continuation.status == TaskStatus.PENDING
        assert continuation.config[QM_RESTART_COUNT_KEY] == 1
        assert "wrote PRD" in continuation.config["goal"]

    def test_restart_cap_exhausted_escalates_instead(self, queue):
        task = _completed_task("28eb4899", PAUL_GOAL, success=True)
        task.config[QM_RESTART_COUNT_KEY] = RESTART_CAP  # already at cap
        queue.add(task)
        finding = classify_task(task, done_when_checker=lambda g: False)
        result = apply_action(queue, task, finding)

        assert result.action == "escalated"
        alerts = [t for t in queue.list_tasks() if t.status == TaskStatus.WAITING_FOR_INPUT]
        assert len(alerts) == 1
        assert alerts[0].pending_question is not None
        assert "28eb4899" in alerts[0].pending_question

    def test_waiting_too_long_always_escalates_never_restarts(self, queue):
        task = Task(
            id="t8", type=TaskType.EXTERNAL_AGENT, status=TaskStatus.WAITING_FOR_INPUT,
            started_at=datetime.now() - timedelta(hours=48),
        )
        queue.add(task)
        finding = classify_task(task)
        result = apply_action(queue, task, finding)

        assert result.action == "escalated"

    def test_genuinely_failed_always_escalates(self, queue):
        task = Task(
            id="t9", type=TaskType.INTERNAL_ASSIGNMENT, status=TaskStatus.FAILED,
            retry_count=3, max_retries=3,
        )
        queue.add(task)
        finding = classify_task(task)
        result = apply_action(queue, task, finding)

        assert result.action == "escalated"


class TestRunQualityCheck:
    def test_empty_queue_no_findings(self, queue):
        assert run_quality_check(queue) == []

    def test_ignores_its_own_restarts_and_alerts(self, queue):
        restart = Task(
            id="orig_qm_restart_1", type=TaskType.INTERNAL_ASSIGNMENT,
            status=TaskStatus.FAILED, retry_count=5, max_retries=3,
            created_by="quality_monitor",
        )
        alert = Task(
            id="quality_monitor_alert_orig_123", type=TaskType.CUSTOM,
            status=TaskStatus.WAITING_FOR_INPUT,
            started_at=datetime.now() - timedelta(hours=48),
            created_by="quality_monitor",
        )
        queue.add(restart)
        queue.add(alert)

        assert run_quality_check(queue) == []

    def test_healthy_task_produces_no_finding(self, queue):
        task = _completed_task("healthy1", "Just do a thing, no Done-when clause.", success=True)
        queue.add(task)
        assert run_quality_check(queue) == []

    def test_end_to_end_falsely_completed_creates_continuation(self, queue):
        task = _completed_task("28eb4899", PAUL_GOAL, success=True)
        queue.add(task)

        findings = run_quality_check(
            queue,
            final_answer_loader=lambda tid: "wrote PRD only",
            done_when_checker=lambda goal: False,
        )

        assert len(findings) == 1
        assert findings[0].classification == "falsely_completed"
        assert findings[0].action == "restarted"
        assert queue.get("28eb4899_qm_restart_1") is not None
