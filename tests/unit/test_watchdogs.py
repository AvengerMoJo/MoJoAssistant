"""Deterministic watchdogs (F6): the automation must notice when it has stopped, without an LLM."""
import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.scheduler import watchdogs
from app.scheduler.core import Scheduler
from app.scheduler.models import Task, TaskStatus, TaskType
from app.scheduler.run_ledger import RunLedger
from tests.unit.sched_test_support import wire_run_tracking

NOW = datetime(2026, 10, 9, 12, 0)


def _task(tid, cron="0 4 * * *", last_ok=None, created=None, status=TaskStatus.PENDING):
    t = Task(id=tid, type=TaskType.INTERNAL_ASSIGNMENT, config={"role_id": "r"}, cron_expression=cron)
    t.status = status
    t.last_completed_at = last_ok
    t.created_at = created or NOW - timedelta(days=60)
    return t


class TestStaleWatchers(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ledger = RunLedger(Path(tmp.name) / "runs")

    def test_cron_period(self):
        self.assertAlmostEqual(watchdogs.cron_period_seconds("0 4 * * *", NOW) / 3600, 24)
        self.assertAlmostEqual(watchdogs.cron_period_seconds("0 9 * * 1", NOW) / 3600, 168)

    def test_daily_job_without_a_success_for_days_is_flagged_with_its_last_failure(self):
        self.ledger.append({"task_id": "d", "outcome": "failed", "error": "No resource available", "error_class": "no_resource",
                            "ended_at": (NOW - timedelta(hours=8)).isoformat(timespec="seconds")})
        t = _task("d", last_ok=NOW - timedelta(days=5))
        f = watchdogs.stale_watchers([t], self.ledger, NOW)
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["task_id"], "d")
        self.assertAlmostEqual(f[0]["hours_since_success"], 120, delta=1)
        self.assertEqual(f[0]["last_attempt"]["error_class"], "no_resource")

    def test_recent_success_in_either_source_is_healthy(self):
        self.assertEqual(watchdogs.stale_watchers([_task("a", last_ok=NOW - timedelta(hours=30))], self.ledger, NOW), [])
        self.ledger.append({"task_id": "b", "outcome": "completed", "ended_at": (NOW - timedelta(hours=2)).isoformat(timespec="seconds")})
        self.assertEqual(watchdogs.stale_watchers([_task("b", last_ok=NOW - timedelta(days=9))], self.ledger, NOW), [])

    def test_never_succeeded_job_is_caught_once_overdue(self):
        old = _task("never", last_ok=None, created=NOW - timedelta(days=10))
        f = watchdogs.stale_watchers([old], self.ledger, NOW)
        self.assertEqual((len(f), f[0]["ever_succeeded"]), (1, False))
        new = _task("new", last_ok=None, created=NOW - timedelta(hours=5))
        self.assertEqual(watchdogs.stale_watchers([new], self.ledger, NOW), [])

    def test_weekly_job_gets_a_weekly_allowance_and_running_or_non_cron_tasks_are_skipped(self):
        weekly = _task("w", cron="0 9 * * 1", last_ok=NOW - timedelta(days=9))
        self.assertEqual(watchdogs.stale_watchers([weekly], self.ledger, NOW), [])          # < 2 weeks
        very_old = _task("w2", cron="0 9 * * 1", last_ok=NOW - timedelta(days=20))
        self.assertEqual(len(watchdogs.stale_watchers([very_old], self.ledger, NOW)), 1)
        running = _task("run", last_ok=NOW - timedelta(days=9), status=TaskStatus.RUNNING)
        oneshot = _task("one", cron=None, last_ok=NOW - timedelta(days=9))
        self.assertEqual(watchdogs.stale_watchers([running, oneshot], self.ledger, NOW), [])


class TestProjectStalls(unittest.TestCase):
    def _project(self, status="active", **items):
        its = [SimpleNamespace(id=k, status=st, title=k, updated_at=(NOW - timedelta(days=d)).isoformat())
               for k, (st, d) in items.items()]
        return SimpleNamespace(id="p", owner_role_id="paul", status=status, items=its)

    def test_flags_idle_in_progress_and_long_blocked_but_not_backlog_or_done(self):
        p = self._project(a=("in_progress", 8), b=("in_progress", 2), c=("todo", 90), d=("done", 90),
                          e=("blocked", 15), f=("blocked", 3))
        got = {x["item_id"]: x for x in watchdogs.stalled_project_items([p], NOW)}
        self.assertEqual(set(got), {"a", "e"})
        self.assertEqual((got["a"]["idle_days"], got["e"]["status"]), (8, "blocked"))

    def test_archived_projects_are_ignored(self):
        self.assertEqual(watchdogs.stalled_project_items([self._project(status="archived", a=("in_progress", 99))], NOW), [])


class TestDreamsStale(unittest.TestCase):
    def test_old_newest_archive_is_flagged_fresh_or_missing_is_not(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(watchdogs.dreams_stale(Path(d) / "nope", NOW))
            (Path(d) / "auto_dream_old").mkdir()
            (Path(d) / "test_junk").mkdir()
            old = (NOW - timedelta(days=8)).timestamp()
            os.utime(Path(d) / "auto_dream_old", (old, old))
            self.assertAlmostEqual(watchdogs.dreams_stale(Path(d), NOW)["age_days"], 8, delta=0.1)
            (Path(d) / "auto_dream_new").mkdir()
            fresh = (NOW - timedelta(hours=3)).timestamp()
            os.utime(Path(d) / "auto_dream_new", (fresh, fresh))
            self.assertIsNone(watchdogs.dreams_stale(Path(d), NOW))


class TestSchedulerWatchdogRun(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.s = Scheduler.__new__(Scheduler)
        self.s._log = MagicMock()
        wire_run_tracking(self.s)
        self.s.queue = MagicMock()
        self.s.queue.tasks = {"daily": _task("daily", last_ok=datetime.now() - timedelta(days=6), created=datetime.now() - timedelta(days=60))}
        self.sent = []

        async def broadcast(event):
            self.sent.append(event)
        self.s._broadcast = broadcast
        self.s._watchdog_state_path = lambda: self.dir / "wd.json"
        for target, value in (("app.scheduler.project_tracker.list_projects", []),
                              ("app.scheduler.watchdogs.dreams_stale", None),
                              ("app.config.config_loader.load_layered_json_config", {})):
            p = patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def _run(self):
        asyncio.run(self.s._run_watchdogs())

    def test_alerts_once_then_stays_quiet_then_realerts_after_a_day(self):
        self._run()
        self.assertEqual([e["event_type"] for e in self.sent], ["watcher_stale"])
        self.assertTrue(self.sent[0]["notify_user"])
        self.assertIn("daily", self.sent[0]["title"])
        self._run()
        self.assertEqual(len(self.sent), 1)                          # de-duplicated
        state = json.loads((self.dir / "wd.json").read_text())
        state["watcher_stale:daily"] = (datetime.now() - timedelta(hours=25)).isoformat()
        (self.dir / "wd.json").write_text(json.dumps(state))
        self._run()
        self.assertEqual(len(self.sent), 2)                          # still broken a day later -> remind

    def test_recovery_clears_the_key_so_a_relapse_alerts_again(self):
        self._run()
        self.s.queue.tasks["daily"].last_completed_at = datetime.now() - timedelta(hours=1)
        self._run()
        self.assertEqual(json.loads((self.dir / "wd.json").read_text()), {})
        self.s.queue.tasks["daily"].last_completed_at = datetime.now() - timedelta(days=6)
        self._run()
        self.assertEqual(len(self.sent), 2)

    def test_disabled_watchdogs_do_nothing(self):
        with patch("app.config.config_loader.load_layered_json_config", return_value={"watchdogs": {"enabled": False}}):
            self._run()
        self.assertEqual(self.sent, [])

    def test_a_failing_check_is_logged_not_raised(self):
        with patch("app.scheduler.watchdogs.stale_watchers", side_effect=RuntimeError("boom")):
            self._run()
        self.assertTrue(any("Watchdog check failed" in c.args[0] for c in self.s._log.call_args_list))


if __name__ == "__main__":
    unittest.main()


class TestWaitingForHuman(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ledger = RunLedger(Path(tmp.name) / "runs")

    def _waiting(self, tid, hours, parent=None, **kw):
        t = Task(id=tid, type=TaskType.INTERNAL_ASSIGNMENT, config={"pending_options": ["continue", "cancel"]}, parent_task_id=parent)
        t.status = TaskStatus.WAITING_FOR_INPUT
        t.pending_question = "Should I continue?"
        t.started_at = NOW - timedelta(hours=hours)
        return t

    def test_reminder_and_escalation_levels_oldest_first(self):
        tasks = [self._waiting("new", 2), self._waiting("day", 30), self._waiting("old", 15 * 24)]
        got = watchdogs.waiting_for_human(tasks, self.ledger, NOW)
        self.assertEqual([(g["task_id"], g["level"]) for g in got], [("old", "escalated"), ("day", "reminder")])
        self.assertEqual(got[0]["choices"], ["continue", "cancel"])

    def test_ledger_waiting_entry_defines_when_waiting_began(self):
        t = self._waiting("w", 500)   # started long ago, but only started waiting 3 hours ago
        self.ledger.append({"task_id": "w", "outcome": "waiting_for_input",
                            "ended_at": (NOW - timedelta(hours=3)).isoformat(timespec="seconds")})
        self.assertEqual(watchdogs.waiting_for_human([t], self.ledger, NOW), [])

    def test_restamped_hitl_post_time_does_not_hide_an_old_question(self):
        t = self._waiting("old", 15 * 24)
        t.config["_hitl_posted_at"] = (NOW - timedelta(minutes=45)).isoformat()    # re-posted after a restart
        got = watchdogs.waiting_for_human([t], self.ledger, NOW)
        self.assertEqual((len(got), got[0]["level"]), (1, "escalated"))
        self.assertAlmostEqual(got[0]["hours_waiting"], 360, delta=1)

    def test_sub_task_whose_parent_is_gone_is_orphaned_but_not_cancelled(self):
        parent_done = Task(id="parent", type=TaskType.INTERNAL_ASSIGNMENT, config={})
        parent_done.status = TaskStatus.COMPLETED
        orphan = self._waiting("orphan", 400, parent="parent")
        live_parent = Task(id="p2", type=TaskType.INTERNAL_ASSIGNMENT, config={})
        live_parent.status = TaskStatus.RUNNING
        attached = self._waiting("attached", 400, parent="p2")
        got = {g["task_id"]: g for g in watchdogs.waiting_for_human([parent_done, orphan, live_parent, attached], self.ledger, NOW)}
        self.assertTrue(got["orphan"]["orphaned"])
        self.assertFalse(got["attached"]["orphaned"])
        self.assertEqual(orphan.status, TaskStatus.WAITING_FOR_INPUT)     # nothing auto-cancelled

    def test_non_waiting_tasks_are_ignored(self):
        t = self._waiting("x", 500)
        t.status = TaskStatus.PENDING
        self.assertEqual(watchdogs.waiting_for_human([t], self.ledger, NOW), [])


class TestSchedulerHitlAlert(TestSchedulerWatchdogRun):
    def test_escalated_waiting_questions_raise_one_error_level_event(self):
        w = Task(id="w", type=TaskType.INTERNAL_ASSIGNMENT, config={})
        w.status = TaskStatus.WAITING_FOR_INPUT
        w.pending_question = "Continue?"
        w.started_at = datetime.now() - timedelta(days=5)
        self.s.queue.tasks = {"w": w}
        self._run()
        events = [e for e in self.sent if e["event_type"] == "hitl_waiting"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["severity"], "error")
        self.assertIn("reply_to_task", events[0]["data"]["how_to_reply"])
