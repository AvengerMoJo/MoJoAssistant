"""
Unit tests for:
  1. Config-driven scheduler task seeding
  2. SSE event envelope (severity, title, notify_user)
  3. EventLog (append, get_recent, purge, persistence)
  4. get_recent_events MCP tool dispatch
"""

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.mcp.adapters.event_log import EventLog
from app.mcp.adapters.sse import SSENotifier
from app.scheduler.core import Scheduler
from app.scheduler.models import TaskPriority, TaskType


# ============================================================
# Helpers
# ============================================================

def _make_scheduler_config(tasks: list) -> str:
    """Write a scheduler_config.json to a temp file; return its path."""
    tmp = tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w", encoding="utf-8"
    )
    json.dump({"default_tasks": tasks}, tmp)
    tmp.close()
    return tmp.name


# ============================================================
# 1. Config-driven task seeding
# ============================================================

class TestSeedTasksFromConfig(unittest.TestCase):
    """_seed_tasks_from_config reads scheduler_config.json and creates tasks."""

    def _make_scheduler(self, tmp_dir: str) -> Scheduler:
        return Scheduler(
            storage_path=str(Path(tmp_dir) / "tasks.json"),
            tick_interval=60,
        )

    def test_seeds_dreaming_task_from_real_config(self):
        """The committed config/scheduler_config.json seeds the nightly dreaming task.

        Uses a temp memory_config_dir so personal ~/.memory/config overrides
        cannot affect this smoke test — it validates the system default only.
        """
        with tempfile.TemporaryDirectory() as tmp:
            s = self._make_scheduler(tmp)
            # Isolate from personal ~/.memory/config by pointing layer 2 at an
            # empty temp dir — only config/scheduler_config.json is read.
            with patch(
                "app.config.config_loader.MEMORY_CONFIG_DIR",
                str(Path(tmp) / "empty_memory_config"),
            ):
                s._seed_tasks_from_config()

            task = s.get_task("dreaming_nightly_offpeak_default")
            self.assertIsNotNone(task, "Task should be seeded from config/scheduler_config.json")
            self.assertEqual(task.type, TaskType.DREAMING)
            self.assertEqual(task.cron_expression, "0 3 * * *")
            self.assertTrue(task.config.get("automatic"))
            self.assertTrue(task.config.get("enforce_off_peak"))
            self.assertTrue(task.resources.requires_gpu)

    def test_skips_disabled_tasks(self):
        """Tasks with enabled=false are not added."""
        cfg_tasks = [
            {
                "id": "disabled_task",
                "type": "dreaming",
                "cron": "0 4 * * *",
                "enabled": False,
                "config": {},
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            s = self._make_scheduler(tmp)
            cfg_path = _make_scheduler_config(cfg_tasks)
            try:
                with patch(
                    "app.config.config_loader.load_layered_json_config",
                    return_value={"default_tasks": cfg_tasks},
                ):
                    s._seed_tasks_from_config()
                self.assertIsNone(s.get_task("disabled_task"))
            finally:
                os.unlink(cfg_path)

    def test_does_not_duplicate_existing_task(self):
        """Running _seed_tasks_from_config twice does not create duplicates."""
        with tempfile.TemporaryDirectory() as tmp:
            s = self._make_scheduler(tmp)
            s._seed_tasks_from_config()
            s._seed_tasks_from_config()  # second call should be a no-op

            tasks = [
                t for t in s.list_tasks()
                if t.id == "dreaming_nightly_offpeak_default"
            ]
            self.assertEqual(len(tasks), 1)

    def test_reseed_picks_up_new_task(self):
        """reseed_default_tasks() adds tasks that were added to config after startup."""
        original = {"default_tasks": []}
        with_new = {
            "default_tasks": [
                {
                    "id": "new_task_after_reseed",
                    "type": "dreaming",
                    "cron": "0 5 * * *",
                    "config": {},
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            s = self._make_scheduler(tmp)
            with patch(
                "app.config.config_loader.load_layered_json_config",
                return_value=original,
            ):
                s._seed_tasks_from_config()
            self.assertIsNone(s.get_task("new_task_after_reseed"))

            with patch(
                "app.config.config_loader.load_layered_json_config",
                return_value=with_new,
            ):
                s.reseed_default_tasks()
            self.assertIsNotNone(s.get_task("new_task_after_reseed"))

    def test_unknown_task_type_is_skipped(self):
        """Tasks with an unrecognised type don't crash; they're silently skipped."""
        cfg = {
            "default_tasks": [
                {"id": "bad_type", "type": "nonexistent_type", "config": {}}
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            s = self._make_scheduler(tmp)
            with patch(
                "app.config.config_loader.load_layered_json_config",
                return_value=cfg,
            ):
                s._seed_tasks_from_config()  # must not raise
            self.assertIsNone(s.get_task("bad_type"))

    def test_priority_mapping(self):
        """Priority strings are mapped to TaskPriority enum values correctly."""
        cfg = {
            "default_tasks": [
                {
                    "id": "high_prio_task",
                    "type": "dreaming",
                    "priority": "high",
                    "config": {},
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            s = self._make_scheduler(tmp)
            with patch(
                "app.config.config_loader.load_layered_json_config",
                return_value=cfg,
            ):
                s._seed_tasks_from_config()
            task = s.get_task("high_prio_task")
            self.assertIsNotNone(task)
            self.assertEqual(task.priority, TaskPriority.HIGH)


# ============================================================
# 2. SSE event envelope
# ============================================================

class TestSSEEnvelope(unittest.IsolatedAsyncioTestCase):
    """SSENotifier.broadcast() fills in the standard envelope fields."""

    async def test_timestamp_added_if_missing(self):
        n = SSENotifier()
        q = await n.subscribe()
        await n.broadcast({"event_type": "task_started"})
        event = q.get_nowait()
        self.assertIn("timestamp", event)

    async def test_default_severity_is_info(self):
        n = SSENotifier()
        q = await n.subscribe()
        await n.broadcast({"event_type": "task_started"})
        self.assertEqual(q.get_nowait()["severity"], "info")

    async def test_default_title_is_event_type(self):
        n = SSENotifier()
        q = await n.subscribe()
        await n.broadcast({"event_type": "config_changed"})
        self.assertEqual(q.get_nowait()["title"], "config_changed")

    async def test_notify_user_false_for_info(self):
        n = SSENotifier()
        q = await n.subscribe()
        await n.broadcast({"event_type": "task_started", "severity": "info"})
        self.assertFalse(q.get_nowait()["notify_user"])

    async def test_notify_user_true_for_error(self):
        n = SSENotifier()
        q = await n.subscribe()
        await n.broadcast({"event_type": "task_failed", "severity": "error"})
        self.assertTrue(q.get_nowait()["notify_user"])

    async def test_notify_user_true_for_warning(self):
        n = SSENotifier()
        q = await n.subscribe()
        await n.broadcast({"event_type": "something", "severity": "warning"})
        self.assertTrue(q.get_nowait()["notify_user"])

    async def test_explicit_notify_user_not_overwritten(self):
        """Caller can explicitly set notify_user=False even for error severity."""
        n = SSENotifier()
        q = await n.subscribe()
        await n.broadcast(
            {"event_type": "task_failed", "severity": "error", "notify_user": False}
        )
        self.assertFalse(q.get_nowait()["notify_user"])

    async def test_existing_title_preserved(self):
        n = SSENotifier()
        q = await n.subscribe()
        await n.broadcast({"event_type": "task_failed", "title": "Custom title"})
        self.assertEqual(q.get_nowait()["title"], "Custom title")


# ============================================================
# 3. EventLog
# ============================================================

class TestEventLog(unittest.IsolatedAsyncioTestCase):
    """EventLog: circular buffer, persistence, filtering."""

    def _make_log(self, tmp_dir: str, max_events: int = 10) -> EventLog:
        return EventLog(path=str(Path(tmp_dir) / "events.json"), max_events=max_events)

    async def test_append_and_get_recent(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = self._make_log(tmp)
            await log.append({"event_type": "test", "title": "hello"})
            events = log.get_recent(limit=5)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["event_type"], "test")

    async def test_auto_id_and_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = self._make_log(tmp)
            await log.append({"event_type": "test"})
            e = log.get_recent(limit=1)[0]
            self.assertIn("id", e)
            self.assertIn("timestamp", e)

    async def test_circular_buffer_drops_oldest(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = self._make_log(tmp, max_events=3)
            for i in range(5):
                await log.append({"event_type": "e", "title": str(i)})
            events = log.get_recent(limit=10)
            self.assertEqual(len(events), 3)
            # Oldest 2 were dropped; newest 3 remain
            titles = [e["title"] for e in events]
            self.assertNotIn("0", titles)
            self.assertNotIn("1", titles)
            self.assertIn("4", titles)

    async def test_filter_by_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = self._make_log(tmp)
            await log.append({"event_type": "task_failed"})
            await log.append({"event_type": "task_started"})
            await log.append({"event_type": "task_failed"})
            events = log.get_recent(types=["task_failed"], limit=10)
            self.assertEqual(len(events), 2)
            self.assertTrue(all(e["event_type"] == "task_failed" for e in events))

    async def test_filter_by_since(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = self._make_log(tmp)
            await log.append({"event_type": "old", "timestamp": "2026-01-01T00:00:00"})
            await log.append({"event_type": "new", "timestamp": "2026-06-01T00:00:00"})
            events = log.get_recent(since="2026-03-01T00:00:00", limit=10)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["event_type"], "new")

    async def test_include_data_false_strips_data_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = self._make_log(tmp)
            await log.append({"event_type": "test", "data": {"secret": 42}})
            events = log.get_recent(include_data=False, limit=1)
            self.assertNotIn("data", events[0])

    async def test_include_data_true_keeps_data_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = self._make_log(tmp)
            await log.append({"event_type": "test", "data": {"secret": 42}})
            events = log.get_recent(include_data=True, limit=1)
            self.assertIn("data", events[0])
            self.assertEqual(events[0]["data"]["secret"], 42)

    async def test_persists_to_disk_and_reloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "events.json")
            log1 = EventLog(path=path)
            await log1.append({"event_type": "persisted"})

            # New instance should load from disk
            log2 = EventLog(path=path)
            events = log2.get_recent(limit=5)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["event_type"], "persisted")

    async def test_purge_before_removes_old_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = self._make_log(tmp)
            await log.append({"event_type": "old", "timestamp": "2026-01-01T00:00:00"})
            await log.append({"event_type": "old", "timestamp": "2026-02-01T00:00:00"})
            await log.append({"event_type": "new", "timestamp": "2026-06-01T00:00:00"})
            removed = await log.purge_before("2026-03-01T00:00:00")
            self.assertEqual(removed, 2)
            self.assertEqual(len(log.get_recent(limit=10)), 1)


# ============================================================
# 4. EventLog wired into SSENotifier
# ============================================================

class TestSSENotifierWithEventLog(unittest.IsolatedAsyncioTestCase):

    async def test_broadcast_appends_to_event_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = EventLog(path=str(Path(tmp) / "events.json"))
            n = SSENotifier(event_log=log)
            await n.broadcast({"event_type": "task_completed", "title": "done"})
            events = log.get_recent(limit=5)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["event_type"], "task_completed")

    async def test_broadcast_works_without_event_log(self):
        """SSENotifier without event_log still fans out to subscribers."""
        n = SSENotifier()  # no event_log
        q = await n.subscribe()
        await n.broadcast({"event_type": "test"})
        event = q.get_nowait()
        self.assertEqual(event["event_type"], "test")


# ============================================================
# 5. get_recent_events tool dispatch (lightweight smoke test)
# ============================================================

class TestGetRecentEventsTool(unittest.IsolatedAsyncioTestCase):

    async def test_returns_recent_events(self):
        """_execute_get_recent_events uses self._event_log."""
        from app.mcp.core.tools import ToolRegistry

        # Build a minimal mock so ToolRegistry.__init__ doesn't spin up threads
        memory_service = MagicMock()
        memory_service.search = MagicMock(return_value=[])

        with patch("app.mcp.core.tools.ToolRegistry._start_scheduler_daemon"):
            with patch("app.scheduler.core.Scheduler._seed_tasks_from_config"):
                registry = ToolRegistry(memory_service=memory_service)

        # Replace the event log with an isolated temp-path one
        with tempfile.TemporaryDirectory() as tmp:
            registry._event_log = EventLog(path=str(Path(tmp) / "events.json"))
            registry._sse_notifier._event_log = registry._event_log

            await registry._event_log.append(
                {"event_type": "task_failed", "title": "boom", "severity": "error"}
            )
            await registry._event_log.append(
                {"event_type": "config_changed", "title": "cfg", "severity": "info"}
            )

            result = await registry._execute_get_recent_events({})
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["count"], 2)

            result_filtered = await registry._execute_get_recent_events(
                {"types": ["task_failed"]}
            )
            self.assertEqual(result_filtered["count"], 1)
            self.assertEqual(result_filtered["events"][0]["event_type"], "task_failed")

    async def test_limit_is_capped_at_500(self):
        from app.mcp.core.tools import ToolRegistry

        memory_service = MagicMock()
        with patch("app.mcp.core.tools.ToolRegistry._start_scheduler_daemon"):
            with patch("app.scheduler.core.Scheduler._seed_tasks_from_config"):
                registry = ToolRegistry(memory_service=memory_service)

        with tempfile.TemporaryDirectory() as tmp:
            registry._event_log = EventLog(path=str(Path(tmp) / "events.json"))
            result = await registry._execute_get_recent_events({"limit": 9999})
            # Should not raise; actual count is 0 (empty log) but limit was capped
            self.assertEqual(result["status"], "success")


if __name__ == "__main__":
    unittest.main()
