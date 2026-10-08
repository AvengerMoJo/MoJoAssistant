"""Quota harvesting: spend renewing quota that would expire unspent.

A subscription window that renews in 30 minutes with 80% still unused is waste;
a task already about to be due can use it. Tasks that are not close to due
(e.g. one that already ran this cycle and rescheduled) must never be pulled.
"""
import asyncio
import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.scheduler import resource_quota as rq
from app.scheduler.core import Scheduler
from tests.unit.sched_test_support import wire_run_tracking
from app.scheduler.models import Task, TaskStatus, TaskType
from app.scheduler.resource_pool import ResourceManager


def _window(used, resets_in, limit=95, name="5h"):
    now = time.time()
    return rq.WindowStatus(name=name, kind="provider_percent", used=used, agent_limit=limit, max_calls=100,
                           window_start=now - 3600, resets_at=now + resets_in, exhausted=used >= limit)


class TestHarvestCandidates(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        for name, attr in (("meta.json", "META_FILE"), ("smoke.jsonl", "SMOKE_LOG_FILE"),
                           ("known.json", "KNOWN_IDS_FILE"), ("usage.json", "USAGE_FILE")):
            p = patch.object(ResourceManager, attr, base / name)
            p.start()
            self.addCleanup(p.stop)
        res = {"sub": {"type": "api", "provider": "openai", "base_url": "http://127.0.0.1:1/v1", "model": "m",
                       "tier": "free_api", "priority": 1, "enabled": True, "context_limit": 1000, "output_limit": 100,
                       "quota_source": {"type": "minimax_token_plan", "url": "http://x", "model_name": "general"},
                       "harvest": {"min_headroom_pct": 40, "horizon_seconds": 3000}},
               "plain": {"type": "api", "provider": "openai", "base_url": "http://127.0.0.1:1/v1", "model": "p",
                         "tier": "free_api", "priority": 2, "enabled": True, "context_limit": 1000, "output_limit": 100}}
        data = {"resources": res}
        l = patch("app.config.config_loader.load_layered_json_config", return_value=data)
        l.start()
        self.addCleanup(l.stop)
        cfg = base / "pool.json"
        cfg.write_text(json.dumps(data), encoding="utf-8")
        self.rm = ResourceManager(config_path=str(cfg))

    def _set(self, *windows):
        self.rm._provider_quota["sub"] = {"windows": list(windows), "fetched_at": time.time(), "error": None}

    def test_unspent_quota_close_to_renewal_qualifies(self):
        self._set(_window(used=10, resets_in=1800))
        c = self.rm.harvest_candidates()
        self.assertEqual([x["resource_id"] for x in c], ["sub"])
        self.assertGreater(c[0]["headroom_pct"], 80)

    def test_renewal_too_far_away_does_not_qualify(self):
        self._set(_window(used=10, resets_in=7200))
        self.assertEqual(self.rm.harvest_candidates(), [])

    def test_mostly_spent_does_not_qualify(self):
        self._set(_window(used=80, resets_in=1800))
        self.assertEqual(self.rm.harvest_candidates(), [])

    def test_any_exhausted_window_disqualifies(self):
        self._set(_window(used=10, resets_in=1800), _window(used=96, resets_in=99999, name="weekly"))
        self.assertEqual(self.rm.harvest_candidates(), [])

    def test_resource_without_opt_in_never_qualifies(self):
        self.rm._provider_quota["plain"] = {"windows": [_window(0, 600)], "fetched_at": 0, "error": None}
        self.assertEqual(self.rm.harvest_candidates(), [])


class TestSchedulerHarvest(unittest.TestCase):
    def _sched(self, tasks, candidates, cfg=None):
        s = Scheduler.__new__(Scheduler)
        wire_run_tracking(s)
        s._log = MagicMock()
        s._broadcast = MagicMock(side_effect=lambda *a, **k: asyncio.sleep(0))
        s.queue = MagicMock()
        s.queue.list_tasks.return_value = tasks
        rm = MagicMock()
        rm.harvest_candidates.return_value = candidates
        s.executor = MagicMock()
        s.executor._get_agentic_executor.return_value._rm = rm
        self.cfg = cfg if cfg is not None else {"harvest": {"enabled": True, "task_ids": ["sentinel", "weekly"],
                                                            "pull_forward_seconds": 21600, "cooldown_seconds": 600}}
        patcher = patch("app.config.config_loader.load_layered_json_config", return_value=self.cfg)
        patcher.start()
        self.addCleanup(patcher.stop)
        return s

    @staticmethod
    def _task(tid, due_in_s, status=TaskStatus.PENDING):
        t = Task(id=tid, type=TaskType.INTERNAL_ASSIGNMENT, config={})
        t.status = status
        t.schedule = datetime.now() + timedelta(seconds=due_in_s)
        return t

    CAND = [{"resource_id": "sub", "window": "5h", "headroom_pct": 90.0, "resets_in_s": 1200}]

    def _run(self, s):
        asyncio.run(s._maybe_harvest_quota())

    def test_pulls_forward_the_soonest_eligible_task(self):
        a, b = self._task("sentinel", 3 * 3600), self._task("weekly", 1 * 3600)
        s = self._sched([a, b], self.CAND)
        self._run(s)
        self.assertLess((b.schedule - datetime.now()).total_seconds(), 5)   # weekly pulled to now
        self.assertGreater((a.schedule - datetime.now()).total_seconds(), 3000)
        s.queue.update.assert_called_once_with(b)

    def test_task_not_close_to_due_is_left_alone(self):
        t = self._task("sentinel", 20 * 3600)  # e.g. already ran this cycle, next run tomorrow
        s = self._sched([t], self.CAND)
        self._run(s)
        s.queue.update.assert_not_called()

    def test_unlisted_task_is_never_pulled(self):
        t = self._task("random_task", 600)
        s = self._sched([t], self.CAND)
        self._run(s)
        s.queue.update.assert_not_called()

    def test_nothing_happens_without_a_candidate_or_when_disabled(self):
        t = self._task("sentinel", 600)
        s = self._sched([t], [])
        self._run(s)
        s.queue.update.assert_not_called()
        s2 = self._sched([t], self.CAND, cfg={"harvest": {"enabled": False, "task_ids": ["sentinel"]}})
        self._run(s2)
        s2.queue.update.assert_not_called()

    def test_cooldown_limits_to_one_task_per_period(self):
        a, b = self._task("sentinel", 600), self._task("weekly", 900)
        s = self._sched([a, b], self.CAND)
        self._run(s)
        self._run(s)
        self.assertEqual(s.queue.update.call_count, 1)

    def test_running_or_waiting_task_is_not_pulled(self):
        t = self._task("sentinel", 600, status=TaskStatus.RUNNING)
        s = self._sched([t], self.CAND)
        self._run(s)
        s.queue.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
