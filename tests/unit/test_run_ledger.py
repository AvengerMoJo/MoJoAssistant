"""Run ledger: every scheduler run, any task type, any outcome, leaves one durable record."""
import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from app.mcp.adapters.event_log import EventLog
from app.scheduler.core import Scheduler
from app.scheduler.models import Task, TaskResult, TaskStatus, TaskType
from app.scheduler.run_ledger import RunLedger, classify_error
from app.scheduler.session_storage import SessionMessage, SessionStorage, TaskSession


def _entry(task_id="job", outcome="completed", ended=None, **kw):
    ended = ended or datetime.now()
    return {"task_id": task_id, "outcome": outcome, "ended_at": ended.isoformat(timespec="seconds"),
            "started_at": (ended - timedelta(seconds=5)).isoformat(timespec="seconds"), **kw}


class TestClassify(unittest.TestCase):
    def test_classes(self):
        cases = {
            "No resource available for task x at iteration 7. Rejected: a: disabled": "no_resource",
            "Resource requirements not satisfiable for task x": "no_resource",
            "Task timed out after 1800s": "timeout",
            "Coding agent backend not reachable and auto-start failed": "infra_unreachable",
            "All connection attempts failed": "infra_unreachable",
            "Iteration budget exhausted (1/6) without FINAL_ANSWER.": "iteration_budget",
            "danger budget exhausted: 161/160": "security_gate",
            "Failed to parse synthesis response as JSON": "parse_error",
            "something odd": "other",
        }
        for msg, cls in cases.items():
            self.assertEqual(classify_error(msg), cls, msg)
        self.assertIsNone(classify_error(None))


class TestLedger(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ledger = RunLedger(Path(tmp.name) / "runs")

    def test_append_and_read_back_newest_first(self):
        now = datetime.now()
        self.ledger.append(_entry("a", "failed", now - timedelta(hours=2), error="boom", error_class="other"))
        self.ledger.append(_entry("a", "completed", now - timedelta(hours=1)))
        self.ledger.append(_entry("b", "completed", now))
        self.assertEqual([e["task_id"] for e in self.ledger.recent()], ["b", "a", "a"])
        self.assertEqual([e["outcome"] for e in self.ledger.recent("a")], ["completed", "failed"])

    def test_last_success_and_summary(self):
        now = datetime.now()
        self.ledger.append(_entry("a", "completed", now - timedelta(days=2)))
        self.ledger.append(_entry("a", "failed", now - timedelta(days=1), error="x", error_class="timeout"))
        s = self.ledger.summary(now - timedelta(days=3))["a"]
        self.assertEqual(s["runs"], 2)
        self.assertEqual(s["outcomes"], {"completed": 1, "failed": 1})
        self.assertEqual(s["last_error"]["class"], "timeout")
        self.assertEqual(self.ledger.last_success("a")["outcome"], "completed")
        self.assertIsNone(self.ledger.last_success("never_ran"))

    def test_unknown_outcome_is_rejected_loudly(self):
        with self.assertRaises(ValueError):
            self.ledger.append(_entry(outcome="kinda-worked"))

    def test_damaged_line_does_not_hide_the_rest(self):
        self.ledger.append(_entry("a"))
        path = next(self.ledger._dir.glob("runs_*.jsonl"))
        with open(path, "a") as f:
            f.write("{not json\n")
        self.ledger.append(_entry("b"))
        self.assertEqual({e["task_id"] for e in self.ledger.recent()}, {"a", "b"})


class TestSchedulerWritesLedger(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)

    def _run(self, execute, task, with_session=False):
        s = Scheduler.__new__(Scheduler)
        s._log = MagicMock()
        s.stats = {"tasks_failed": 0, "tasks_succeeded": 0, "tasks_executed": 0, "tasks_completed": 0}
        s.queue = MagicMock()
        s.executor = MagicMock()
        s.executor.execute = execute
        s._broadcast = MagicMock(side_effect=lambda *a, **k: asyncio.sleep(0))
        s.current_task = None
        s._should_notify_completion = MagicMock(return_value=False)
        s._schedule_dreaming_for_agentic_task = MagicMock()
        s._store_agentic_result_to_memory = MagicMock()
        s._benchmark_store = MagicMock()
        s._run_ledger = RunLedger(self.base / "runs")
        s._run_notes = {}
        s._harvested_task_ids = set()
        from unittest.mock import patch
        with patch("app.scheduler.session_storage.SessionStorage._dir", self.base / "sessions", create=True):
            storage = SessionStorage(self.base / "sessions")
            if with_session:
                storage.save_session(TaskSession(task.id, "running", [], datetime.now().isoformat()))
            with patch("app.scheduler.session_storage.SessionStorage.__init__",
                       lambda self_, storage_dir=None: setattr(self_, "_dir", self.base / "sessions")):
                task.mark_started()
                asyncio.run(s._execute_task(task))
        return s, storage

    def _task(self, tid="job", cron=None, ttype=TaskType.INTERNAL_ASSIGNMENT):
        return Task(id=tid, type=ttype, config={"goal": "g", "role_id": "carl"}, cron_expression=cron)

    def test_success_is_recorded_with_resources_and_final_answer(self):
        async def ok(task):
            return TaskResult(success=True, metrics={"final_answer": "done!", "iterations": 2,
                                                     "iteration_log": [{"resource": "r1"}, {"resource": "r1"}, {"resource": "r2"}]})
        s, _ = self._run(ok, self._task(cron="0 6 * * *"))
        e = s._run_ledger.recent()[0]
        self.assertEqual((e["outcome"], e["trigger"], e["resources"], e["iterations"], e["final_answer_chars"]),
                         ("completed", "cron", ["r1", "r2"], 2, 5))

    def test_failure_timeout_and_exception_are_each_recorded_with_error_class(self):
        async def fail(task):
            return TaskResult(success=False, error_message="No resource available for task x at iteration 5")

        async def boom(task):
            raise RuntimeError("executor exploded")

        async def hang(task):
            await asyncio.sleep(10)

        t_fail = self._task("f"); t_fail.max_retries = 0
        s, _ = self._run(fail, t_fail)
        self.assertEqual((s._run_ledger.recent("f")[0]["outcome"], s._run_ledger.recent("f")[0]["error_class"]), ("failed", "no_resource"))
        s, _ = self._run(boom, self._task("e"))
        self.assertEqual((s._run_ledger.recent("e")[0]["outcome"], s._run_ledger.recent("e")[0]["error"]), ("error", "executor exploded"))
        t_to = self._task("t"); t_to.resources.max_duration_seconds = 1
        s, _ = self._run(hang, t_to)
        self.assertEqual((s._run_ledger.recent("t")[0]["outcome"], s._run_ledger.recent("t")[0]["error_class"]), ("timed_out", "timeout"))

    def test_waiting_for_input_and_retry_are_distinct_outcomes(self):
        async def wait(task):
            return TaskResult(success=False, waiting_for_input="Should I continue?")

        async def fail(task):
            return TaskResult(success=False, error_message="boom")

        s, _ = self._run(wait, self._task("w"))
        self.assertEqual(s._run_ledger.recent("w")[0]["outcome"], "waiting_for_input")
        t = self._task("r"); t.max_retries = 3
        s, _ = self._run(fail, t)
        e = s._run_ledger.recent("r")[0]
        self.assertEqual((e["outcome"], e["attempt"]), ("failed_will_retry", 1))

    def test_non_assistant_task_types_are_recorded_too(self):
        async def ok(task):
            return TaskResult(success=True, metrics={"skipped": True})
        s, _ = self._run(ok, self._task("d", ttype=TaskType.DREAMING))
        e = s._run_ledger.recent("d")[0]
        self.assertEqual((e["task_type"], e["outcome"]), ("dreaming", "completed"))

    def test_failed_run_closes_a_session_left_running(self):
        async def boom(task):
            raise RuntimeError("died early")
        s, storage = self._run(boom, self._task("sess"), with_session=True)
        sess = storage.load_session("sess")
        self.assertEqual((sess.status, sess.error_message), ("failed", "died early"))

    def test_harvest_trigger_is_recorded(self):
        async def ok(task):
            return TaskResult(success=True, metrics={})
        t = self._task("h", cron="0 4 * * *")
        s = Scheduler.__new__(Scheduler)
        # reuse _run's wiring, then mark the task as harvested before it runs
        original = Scheduler._execute_task

        async def with_harvest(self_, task):
            self_._harvested_task_ids.add(task.id)
            return await original(self_, task)
        from unittest.mock import patch
        with patch.object(Scheduler, "_execute_task", with_harvest):
            s, _ = self._run(ok, t)
        self.assertEqual(s._run_ledger.recent("h")[0]["trigger"], "harvest")


class TestHeartbeatsNotPersisted(unittest.TestCase):
    def test_scheduler_tick_is_not_stored_but_real_events_are(self):
        with tempfile.TemporaryDirectory() as d:
            log = EventLog(path=str(Path(d) / "events.json"), max_events=50)
            log._events.clear()
            asyncio.run(log.append({"event_type": "scheduler_tick", "tick": 1}))
            asyncio.run(log.append({"event_type": "task_failed", "task_id": "x"}))
            types = [e["event_type"] for e in log._events]
            self.assertEqual(types, ["task_failed"])


if __name__ == "__main__":
    unittest.main()


class TestSchedulerRunsAction(unittest.TestCase):
    """scheduler(action="runs") exposes the ledger through the MCP hub."""

    def _tools(self, ledger):
        from app.mcp.core.tools import ToolRegistry
        t = ToolRegistry.__new__(ToolRegistry)
        t.scheduler = MagicMock()
        t.scheduler._run_ledger = ledger
        return t

    def test_recent_and_summary_views(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = RunLedger(Path(d) / "runs")
            now = datetime.now()
            ledger.append(_entry("a", "failed", now - timedelta(hours=3), error="x", error_class="timeout"))
            ledger.append(_entry("a", "completed", now - timedelta(hours=1)))
            tools = self._tools(ledger)
            recent = asyncio.run(tools._execute_scheduler_runs({"task_id": "a", "limit": 5}))
            self.assertEqual([r["outcome"] for r in recent["runs"]], ["completed", "failed"])
            summary = asyncio.run(tools._execute_scheduler_runs({"summary": True, "hours": 24}))
            self.assertEqual(summary["tasks"]["a"]["runs"], 2)
            self.assertIsNotNone(summary["tasks"]["a"]["last_success"])
