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
    load_final_answer,
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


class TestLoadFinalAnswer:
    """Regression for a live incident (28eb4899_qm_restart_1, 2026-09-18):
    a task report stored final_answer as {"raw_text": "..."} rather than a
    plain string. Concatenating that dict into a goal string crashed with
    "unsupported operand type(s) for +: 'dict' and 'str'", silently
    breaking every quality-monitor tick for hours. load_final_answer must
    never return anything but str or None, whatever shape the report uses.
    """

    def _write_report(self, tmp_path, monkeypatch, task_id, data):
        import app.scheduler.quality_monitor as qm

        report_dir = tmp_path / "task_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / f"{task_id}.json").write_text(__import__("json").dumps(data))
        monkeypatch.setattr(
            qm, "get_memory_subpath",
            lambda *parts: str(tmp_path.joinpath(*parts))
        )

    def test_plain_string_final_answer(self, tmp_path, monkeypatch):
        self._write_report(tmp_path, monkeypatch, "t1", {"final_answer": "done"})
        assert load_final_answer("t1") == "done"

    def test_dict_shaped_final_answer_extracts_raw_text(self, tmp_path, monkeypatch):
        self._write_report(tmp_path, monkeypatch, "t2", {"final_answer": {"raw_text": "did the thing"}})
        result = load_final_answer("t2")
        assert result == "did the thing"
        assert isinstance(result, str)

    def test_dict_shaped_final_answer_without_known_key_falls_back_to_json(self, tmp_path, monkeypatch):
        self._write_report(tmp_path, monkeypatch, "t3", {"final_answer": {"weird": "shape"}})
        result = load_final_answer("t3")
        assert isinstance(result, str)
        assert "weird" in result

    def test_missing_report_returns_none(self, tmp_path, monkeypatch):
        import app.scheduler.quality_monitor as qm
        monkeypatch.setattr(qm, "get_memory_subpath", lambda *parts: str(tmp_path.joinpath(*parts)))
        assert load_final_answer("nonexistent") is None

    def test_end_to_end_dict_final_answer_does_not_crash_continuation_build(self, tmp_path, monkeypatch):
        """The actual failure mode: a falsely_completed task whose real
        final_answer is dict-shaped must still build a continuation task
        without raising."""
        self._write_report(tmp_path, monkeypatch, "28eb4899_qm_restart_1",
                            {"final_answer": {"raw_text": "claimed done, wasn't"}})
        task = _completed_task("28eb4899_qm_restart_1", PAUL_GOAL, success=True)
        task.config[QM_RESTART_COUNT_KEY] = 1  # one restart already used, cap is 2

        with tempfile.TemporaryDirectory() as tmp:
            queue = TaskQueue(storage_path=str(Path(tmp) / "tasks.json"))
            queue.add(task)
            finding = classify_task(
                task,
                final_answer_loader=load_final_answer,
                done_when_checker=lambda goal: False,
            )
            result = apply_action(queue, task, finding)  # must not raise

        assert result.action == "restarted"
        continuation = queue.get("28eb4899_qm_restart_1_qm_restart_2")
        assert "claimed done, wasn't" in continuation.config["goal"]


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
        # The ORIGINAL task must also be stamped -- its own status never
        # changes (stays "completed" forever), so without this the next
        # scan of it would read _restart_count()==0 again and restart
        # forever. Found live 2026-09-23: 28eb4899 restarted every ~5min
        # for 1h47m+ straight because this stamp was never written.
        assert queue.get("28eb4899").config[QM_RESTART_COUNT_KEY] == 1

    def test_repeated_scans_of_the_same_original_stop_restarting_at_cap(self, queue):
        """Regression for the real incident: run_quality_check re-finds the
        SAME original task every tick (its status never changes to
        non-completed just because a continuation was dispatched). Calling
        apply_action on it repeatedly -- exactly what happens live -- must
        restart up to the cap, then escalate, not restart forever."""
        task = _completed_task("28eb4899", PAUL_GOAL, success=True)
        queue.add(task)

        def rescan():
            current = queue.get("28eb4899")
            finding = classify_task(
                current, final_answer_loader=lambda tid: "wrote PRD",
                done_when_checker=lambda g: False,
            )
            return apply_action(queue, current, finding)

        first = rescan()
        assert first.action == "restarted"
        assert queue.get("28eb4899_qm_restart_1") is not None

        second = rescan()
        assert second.action == "restarted"
        assert queue.get("28eb4899_qm_restart_2") is not None

        # Cap is 2 -- the third scan of the same original must escalate,
        # not attempt a third restart.
        third = rescan()
        assert third.action == "escalated"
        assert queue.get("28eb4899_qm_restart_3") is None

        # And it must not spawn a fresh alert every subsequent tick either.
        fourth = rescan()
        assert fourth.action == "escalated"
        alerts = [t for t in queue.list_tasks() if t.id.startswith("quality_monitor_alert_")]
        assert len(alerts) == 1

    def test_duplicate_continuation_id_falls_back_to_escalate(self, queue):
        """If a continuation with the computed id already exists (the exact
        collision that silently no-op'd for 1h47m+ live: queue.add()
        returned False, unchecked, while the code still claimed
        action="restarted"), do not claim success -- escalate instead."""
        task = _completed_task("28eb4899", PAUL_GOAL, success=True)
        queue.add(task)
        # Pre-create the id apply_action would compute (prior_count=0 -> _1),
        # simulating the stale leftover from days earlier that caused the
        # real collision.
        queue.add(Task(id="28eb4899_qm_restart_1", type=TaskType.INTERNAL_ASSIGNMENT))

        finding = classify_task(
            task, final_answer_loader=lambda tid: "wrote PRD", done_when_checker=lambda g: False
        )
        result = apply_action(queue, task, finding)

        assert result.action == "escalated"
        assert "already exists" in (result.detail or "")
        alerts = [t for t in queue.list_tasks() if t.status == TaskStatus.WAITING_FOR_INPUT]
        assert len(alerts) == 1

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

    def test_escalation_does_not_duplicate_alert_for_same_subject(self, queue):
        """Regression for the 56-duplicate-alert storm on sub_28eb4899_952400:
        escalating the same terminal failure twice must not raise a second
        alert -- one (task, classification) -> one alert."""
        task = Task(
            id="t10", type=TaskType.INTERNAL_ASSIGNMENT, status=TaskStatus.FAILED,
            retry_count=3, max_retries=3,
        )
        queue.add(task)
        finding = classify_task(task)
        apply_action(queue, task, finding)  # first pass raises the alert

        finding2 = classify_task(task)
        apply_action(queue, task, finding2)  # second pass must be a no-op

        alerts = [t for t in queue.list_tasks() if t.id.startswith("quality_monitor_alert_")]
        assert len(alerts) == 1


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

    def test_run_quality_check_escalates_once_then_stays_silent(self, queue):
        """Regression for the alert storm: a terminal failure should produce
        exactly ONE escalated finding across repeated ticker passes."""
        task = Task(
            id="sub_28eb4899_952400", type=TaskType.INTERNAL_ASSIGNMENT,
            status=TaskStatus.FAILED, retry_count=3, max_retries=3,
            last_error="Backend not found: git@github.com:AvengerMoJo/MoJoAssistant.git",
        )
        queue.add(task)

        first = run_quality_check(queue)
        second = run_quality_check(queue)
        third = run_quality_check(queue)

        assert [f.action for f in first] == ["escalated"]
        assert len(first) == 1
        assert second == []
        assert third == []
        alerts = [t for t in queue.list_tasks() if t.id.startswith("quality_monitor_alert_")]
        assert len(alerts) == 1


def _failed_task(task_id="sub_paul_x", error="Agent did not produce a final answer"):
    return Task(
        id=task_id, type=TaskType.INTERNAL_ASSIGNMENT,
        status=TaskStatus.FAILED, retry_count=3, max_retries=3,
        last_error=error,
    )


class TestAlertEventEmission:
    """Owner directive 2026-10-19: failures belong on ntfy (push), not on
    Discord (questions only). _raise_alert emits an event carrying
    audience='push_only'; MessengerManager.dispatch skips messenger adapters
    for those, so the same event reaches ntfy via the event log but never
    Discord."""

    def test_escalation_emits_push_only_event(self, queue):
        task = _failed_task()
        queue.add(task)
        events = []

        run_quality_check(queue, event_sink=events.append)

        assert len(events) == 1
        ev = events[0]
        assert ev["event_type"] == "task_failed"
        assert ev["audience"] == "push_only"
        assert ev["notify_user"] is True
        assert ev["task_id"] == task.id
        assert ev["classification"] == "genuinely_failed"
        assert ev["severity"] == "error"
        assert ev["source"] == "quality_monitor"

    def test_event_carries_reason_for_the_push_body(self, queue):
        """ntfy has no buttons and a short body -- the reason string is the
        only thing the owner actually reads, so it must survive into the
        event rather than being dropped with the legacy task."""
        task = _failed_task(error="coding agent backend unreachable")
        queue.add(task)
        events = []

        run_quality_check(queue, event_sink=events.append)

        assert "coding agent backend unreachable" in events[0]["reason"]
        assert task.id in events[0]["title"]

    def test_waiting_too_long_is_warning_not_error(self, queue):
        task = Task(
            id="stale_q", type=TaskType.INTERNAL_ASSIGNMENT,
            status=TaskStatus.WAITING_FOR_INPUT,
            started_at=datetime.now() - timedelta(hours=48),
        )
        queue.add(task)
        events = []

        run_quality_check(queue, event_sink=events.append)

        assert len(events) == 1
        assert events[0]["classification"] == "waiting_for_input_too_long"
        assert events[0]["severity"] == "warning"

    def test_only_one_event_across_repeated_passes(self, queue):
        """The 56-identical-alert storm regression, now at the event layer."""
        queue.add(_failed_task())
        first, second, third = [], [], []

        run_quality_check(queue, event_sink=first.append)
        run_quality_check(queue, event_sink=second.append)
        run_quality_check(queue, event_sink=third.append)

        assert len(first) == 1
        assert second == [] and third == []

    def test_no_event_without_a_sink(self, queue):
        """Unit tests and any caller that omits event_sink must not explode."""
        queue.add(_failed_task())
        assert len(run_quality_check(queue)) == 1

    def test_sink_exception_does_not_break_the_scan(self, queue):
        """A dead notification channel must never take down the watchdog's
        own tick -- the finding still has to be recorded."""
        queue.add(_failed_task())

        def exploding_sink(event):
            raise RuntimeError("ntfy down")

        findings = run_quality_check(queue, event_sink=exploding_sink)

        assert len(findings) == 1
        assert findings[0].action == "escalated"

    def test_async_sink_is_awaited_not_dropped(self, queue):
        """Regression guard for the coroutine trap: Scheduler._broadcast is
        `async def`. Calling it from this synchronous module and ignoring the
        return value builds a coroutine that never runs -- the owner is never
        notified and nothing logs an error."""
        import asyncio

        seen = []

        async def async_sink(event):
            await asyncio.sleep(0)
            seen.append(event)

        queue.add(_failed_task())
        async def drive():
            run_quality_check(queue, event_sink=async_sink)
            await asyncio.sleep(0.05)  # let the created_task complete

        asyncio.run(drive())

        assert len(seen) == 1
        assert seen[0]["audience"] == "push_only"


class TestShadowFlag:
    """QM_SHADOW_DISCORD_LEGACY lets the owner compare ntfy against Discord
    before Discord is switched off for good."""

    def test_shadow_on_creates_both_event_and_alert_task(self, queue, monkeypatch):
        import app.scheduler.quality_monitor as qm
        monkeypatch.setattr(qm, "QM_SHADOW_DISCORD_LEGACY", True)
        queue.add(_failed_task())
        events = []

        qm.run_quality_check(queue, event_sink=events.append)

        assert len(events) == 1
        alerts = [t for t in queue.list_tasks() if t.id.startswith("quality_monitor_alert_")]
        assert len(alerts) == 1
        assert alerts[0].status == TaskStatus.WAITING_FOR_INPUT

    def test_shadow_off_creates_event_only(self, queue, monkeypatch):
        """The hard cut: after the owner confirms ntfy carries enough, no
        alert task is created, so the Discord HITL adapter has nothing to
        poll and the failure never touches that channel again."""
        import app.scheduler.quality_monitor as qm
        monkeypatch.setattr(qm, "QM_SHADOW_DISCORD_LEGACY", False)
        queue.add(_failed_task())
        events = []

        qm.run_quality_check(queue, event_sink=events.append)

        assert len(events) == 1
        alerts = [t for t in queue.list_tasks() if t.id.startswith("quality_monitor_alert_")]
        assert alerts == []
        assert [t for t in queue.list_tasks() if t.status == TaskStatus.WAITING_FOR_INPUT] == []
