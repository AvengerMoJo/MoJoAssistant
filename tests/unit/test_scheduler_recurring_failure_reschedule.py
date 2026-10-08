"""A recurring task must go back on its cron schedule after ANY failure exit.

Incident 2026-10-08: scott_daily_news_0600 timed out on 2026-09-06 and sat in
FAILED for a month, because only the 'failed permanently' exit rescheduled
cron tasks; timeout, infrastructure-failure and exception exits did not.
"""
import asyncio
import unittest
from datetime import datetime
from unittest.mock import MagicMock

from app.scheduler.core import Scheduler
from tests.unit.sched_test_support import wire_run_tracking
from app.scheduler.models import Task, TaskResult, TaskStatus, TaskType


def _task(cron=None):
    t = Task(id="t1", type=TaskType.INTERNAL_ASSIGNMENT, config={"goal": "g"}, cron_expression=cron)
    t.mark_started()
    return t


class TestRescheduleHelper(unittest.TestCase):
    def _sched(self):
        s = Scheduler.__new__(Scheduler)
        wire_run_tracking(s)
        s._log = MagicMock()
        return s

    def test_cron_task_returns_to_pending_with_future_schedule_and_error_kept(self):
        t = _task("0 6 * * *")
        t.mark_failed("Task timed out after 1800s")
        self.assertTrue(self._sched()._reschedule_recurring_after_failure(t, t.last_error))
        self.assertEqual(t.status, TaskStatus.PENDING)
        self.assertGreater(t.schedule, datetime.now())
        self.assertEqual(t.last_error, "Task timed out after 1800s")
        self.assertIsNotNone(t.last_failed_at)
        self.assertIsNone(t.completed_at)
        self.assertEqual(t.retry_count, 0)

    def test_non_recurring_task_is_left_failed(self):
        t = _task(None)
        t.mark_failed("boom")
        self.assertFalse(self._sched()._reschedule_recurring_after_failure(t, "boom"))
        self.assertEqual(t.status, TaskStatus.FAILED)


class TestFailureExitsReschedule(unittest.TestCase):
    def _run(self, task, execute):
        s = Scheduler.__new__(Scheduler)
        wire_run_tracking(s)
        s._log = MagicMock()
        s.stats = {"tasks_failed": 0, "tasks_completed": 0, "tasks_executed": 0}
        s.queue = MagicMock()
        s.executor = MagicMock()
        s.executor.execute = execute
        s._broadcast = MagicMock(side_effect=lambda *a, **k: asyncio.sleep(0))
        s.current_task = None
        s._should_notify_completion = MagicMock(return_value=False)
        asyncio.run(s._execute_task(task))

    def test_exception_exit_reschedules_recurring_task(self):
        async def boom(task):
            raise RuntimeError("executor exploded")
        t = _task("0 6 * * *")
        self._run(t, boom)
        self.assertEqual(t.status, TaskStatus.PENDING)
        self.assertEqual(t.last_error, "executor exploded")

    def test_timeout_exit_reschedules_recurring_task(self):
        async def hang(task):
            await asyncio.sleep(10)
        t = _task("0 6 * * *")
        t.resources.max_duration_seconds = 1
        self._run(t, hang)
        self.assertEqual(t.status, TaskStatus.PENDING)
        self.assertIn("timed out", t.last_error)

    def test_infra_failure_exit_reschedules_recurring_task(self):
        from app.scheduler import core
        async def infra(task):
            return TaskResult(success=False, waiting_for_input="Coding agent backend not reachable and auto-start failed (server_id='x').")
        t = _task("0 6 * * *")
        self._run(t, infra)
        self.assertEqual(t.status, TaskStatus.PENDING)

    def test_one_shot_exception_stays_failed(self):
        async def boom(task):
            raise RuntimeError("x")
        t = _task(None)
        self._run(t, boom)
        self.assertEqual(t.status, TaskStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
