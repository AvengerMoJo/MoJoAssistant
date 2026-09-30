"""Regression test: infra-failure results must FAIL the task outright, not
leave it in WAITING_FOR_INPUT.

Found live 2026-09-23: coding_agent_executor.py reports an unreachable
backend via TaskResult(waiting_for_input=...) (app/scheduler/coding_agent_
executor.py), which core.py._execute_task unconditionally turned into
WAITING_FOR_INPUT -- nobody can "reply" to fix a dead backend, so these sat
as permanent orphans that also got broadcast to Discord as if they were
real questions. dispatch_subtask's own poll-loop cleanup (capability_
registry.py) only fires while the polling parent is still alive; once it
dies or times out (exactly what happened live), 7 of these orphans
accumulated. This test proves the fix at the source: core.py now checks the
infra-failure signature before ever setting WAITING_FOR_INPUT.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from app.scheduler.core import Scheduler
from app.scheduler.models import Task, TaskType, TaskPriority, TaskResult, TaskStatus


class TestInfraFailureAutoFail(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.scheduler = Scheduler(
            storage_path=str(Path(self._tmpdir.name) / "tasks.json"),
            tick_interval=60,
        )
        self.scheduler._broadcast = AsyncMock()

    async def asyncTearDown(self):
        self._tmpdir.cleanup()

    def _add_task(self, task_id="infra_fail_1"):
        task = Task(
            id=task_id,
            type=TaskType.INTERNAL_ASSIGNMENT,
            priority=TaskPriority.MEDIUM,
            status=TaskStatus.RUNNING,
            config={"role_id": "popo"},
            created_by="test",
        )
        self.scheduler.queue.add(task)
        return task

    async def test_infra_failure_result_marks_task_failed_not_waiting(self):
        task = self._add_task()
        self.scheduler.executor.execute = AsyncMock(return_value=TaskResult(
            success=False,
            waiting_for_input=(
                "Coding agent backend not reachable and auto-start failed "
                "(server_id='git@github.com:foo/bar.git')."
            ),
        ))

        await self.scheduler._execute_task(task)

        stored = self.scheduler.queue.get(task.id)
        self.assertEqual(stored.status, TaskStatus.FAILED)
        self.assertIsNone(stored.pending_question)
        self.assertIn("not reachable", stored.last_error)

    async def test_infra_failure_broadcasts_task_failed_not_waiting_for_input(self):
        task = self._add_task()
        self.scheduler.executor.execute = AsyncMock(return_value=TaskResult(
            success=False,
            waiting_for_input="Coding agent backend not reachable and auto-start failed",
        ))

        await self.scheduler._execute_task(task)

        event_types = [
            call.args[0]["event_type"]
            for call in self.scheduler._broadcast.call_args_list
        ]
        self.assertIn("task_failed", event_types)
        self.assertNotIn("task_waiting_for_input", event_types)

    async def test_genuine_question_still_goes_to_waiting_for_input(self):
        """Sanity check: the fix must not swallow real questions."""
        task = self._add_task()
        self.scheduler.executor.execute = AsyncMock(return_value=TaskResult(
            success=False,
            waiting_for_input="Which database should I use, postgres or sqlite?",
            waiting_for_input_choices=["postgres", "sqlite"],
        ))

        await self.scheduler._execute_task(task)

        stored = self.scheduler.queue.get(task.id)
        self.assertEqual(stored.status, TaskStatus.WAITING_FOR_INPUT)
        self.assertEqual(stored.pending_question, "Which database should I use, postgres or sqlite?")

        event_types = [
            call.args[0]["event_type"]
            for call in self.scheduler._broadcast.call_args_list
        ]
        self.assertIn("task_waiting_for_input", event_types)
        self.assertNotIn("task_failed", event_types)


if __name__ == "__main__":
    unittest.main()
