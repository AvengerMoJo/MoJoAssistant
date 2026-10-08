"""Per-run bookkeeping must not leak from one scheduled run of a recurring task to the next.

2026-10-08: 6 of 15 recurring jobs carried resume_from_task_id in task.config forever, so each run
resumed the previous session (ahman_weekly_security_review: 437KB / 270 messages) and appended
"The previous attempt ran out of time or failed. Continue..." every time.
"""
import asyncio
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from app.scheduler.core import Scheduler
from tests.unit.sched_test_support import wire_run_tracking
from app.scheduler.models import Task, TaskResult, TaskStatus, TaskType, clear_run_state

STALE = {
    "resume_from_task_id": "old_session", "pending_options": ["a", "b"], "reply_to_question": "yes",
    "_hitl_posted_at": "2026-10-02T10:00:00", "_qm_escalated_at:waiting_for_input_too_long": "2026-10-01T04:00:00",
}


def _task(cron="0 6 * * *", **cfg):
    t = Task(id="job", type=TaskType.INTERNAL_ASSIGNMENT, config={"goal": "g", "role_id": "ahman", **cfg}, cron_expression=cron)
    t.status = TaskStatus.PENDING
    t.schedule = datetime.now() + timedelta(hours=3)
    return t


def _sched(tasks):
    s = Scheduler.__new__(Scheduler)
    wire_run_tracking(s)
    s._log = MagicMock()
    s.queue = MagicMock()
    s.queue.tasks = {t.id: t for t in tasks}
    return s


class TestClearRunState(unittest.TestCase):
    def test_removes_only_run_bookkeeping_and_reports_it(self):
        cfg = {"goal": "g", "role_id": "r", "max_iterations": 9, **STALE}
        removed = clear_run_state(cfg)
        self.assertEqual(set(removed), set(STALE))
        self.assertEqual(cfg, {"goal": "g", "role_id": "r", "max_iterations": 9})

    def test_clean_config_is_untouched(self):
        cfg = {"goal": "g"}
        self.assertEqual(clear_run_state(cfg), [])
        self.assertEqual(cfg, {"goal": "g"})


class TestRescheduleClearsState(unittest.TestCase):
    def test_failure_reschedule_clears_it(self):
        t = _task(**{k: v for k, v in STALE.items() if k != "reply_to_question"})
        t.mark_failed("Task timed out after 1800s")
        _sched([t])._reschedule_recurring_after_failure(t, t.last_error)
        self.assertEqual(t.status, TaskStatus.PENDING)
        self.assertNotIn("resume_from_task_id", t.config)
        self.assertNotIn("_hitl_posted_at", t.config)
        self.assertEqual(t.config["goal"], "g")

    def test_zombie_recovery_clears_it(self):
        t = _task(**STALE)
        t.status = TaskStatus.RUNNING
        _sched([t])._recover_stuck_running_tasks()
        self.assertEqual(t.status, TaskStatus.PENDING)
        self.assertFalse(set(STALE) & set(t.config))

    def test_successful_cron_cycle_clears_it(self):
        async def run():
            s = Scheduler.__new__(Scheduler)
            wire_run_tracking(s)
            s._log = MagicMock()
            s.stats = {"tasks_failed": 0, "tasks_completed": 0, "tasks_executed": 0}
            s.queue = MagicMock()
            s.executor = MagicMock()

            async def ok(task):
                return TaskResult(success=True, metrics={"final_answer": "done"})

            s.executor.execute = ok
            s._broadcast = MagicMock(side_effect=lambda *a, **k: asyncio.sleep(0))
            s.current_task = None
            s._should_notify_completion = MagicMock(return_value=False)
            s._schedule_dreaming_for_agentic_task = MagicMock()
            s._store_agentic_result_to_memory = MagicMock()
            t = _task(**STALE)
            t.mark_started()
            await s._execute_task(t)
            return t
        t = asyncio.run(run())
        self.assertEqual(t.status, TaskStatus.PENDING)
        self.assertFalse(set(STALE) & set(t.config), t.config)


class TestStartupRepair(unittest.TestCase):
    def test_stale_state_on_a_between_runs_cron_task_is_repaired(self):
        t = _task(**{k: v for k, v in STALE.items() if k != "reply_to_question"})
        s = _sched([t])
        s._sanitize_recurring_run_state()
        self.assertFalse(set(STALE) & set(t.config))
        s.queue.update.assert_called_once_with(t)

    def test_mid_retry_task_keeps_its_resume_state(self):
        t = _task(resume_from_task_id="this_run")
        t.retry_count = 1
        _sched([t])._sanitize_recurring_run_state()
        self.assertEqual(t.config["resume_from_task_id"], "this_run")

    def test_task_holding_a_hitl_reply_keeps_its_resume_state(self):
        t = _task(resume_from_task_id="paused", reply_to_question="go ahead")
        _sched([t])._sanitize_recurring_run_state()
        self.assertEqual(t.config["resume_from_task_id"], "paused")

    def test_waiting_for_input_and_one_shot_tasks_are_untouched(self):
        waiting = _task(resume_from_task_id="paused")
        waiting.status = TaskStatus.WAITING_FOR_INPUT
        oneshot = _task(cron=None, resume_from_task_id="x")
        _sched([waiting, oneshot])._sanitize_recurring_run_state()
        self.assertEqual(waiting.config["resume_from_task_id"], "paused")
        self.assertEqual(oneshot.config["resume_from_task_id"], "x")


if __name__ == "__main__":
    unittest.main()
