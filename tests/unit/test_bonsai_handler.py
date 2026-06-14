"""Unit tests for handlers/bonsai.py — BonsaiGrowthHandler + BonsaiPinReviewHandler."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def _make_task(config=None, status=None):
    from app.scheduler.models import Task, TaskType, TaskPriority, TaskStatus
    t = Task(
        id="test_bonsai_task",
        type=TaskType.GROWTH,
        priority=TaskPriority.LOW,
        config=config or {},
        description="test",
        created_by="test",
    )
    if status:
        t.status = status
    return t


def _make_ctx(tmp_dir=None):
    ctx = MagicMock()
    ctx._scheduler = None
    ctx.log = MagicMock()
    return ctx


class TestBonsaiGrowthHandler(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._patches = [
            patch("app.scheduler.handlers.bonsai.get_memory_subpath", return_value=self.tmp),
            patch("app.scheduler.bonsai.get_memory_subpath", return_value=self.tmp),
            patch("app.roles.role_manager.RoleManager.get", return_value=None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_session_file(self, role_id, session_id, exchanges=None, session_type="owner_one_on_one"):
        chat_dir = Path(self.tmp) / role_id / "chat_history"
        chat_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "session_id": session_id,
            "role_id": role_id,
            "session_type": session_type,
            "last_active": "2026-06-14T10:00:00",
            "exchanges": exchanges or [],
        }
        (chat_dir / f"{session_id}.json").write_text(json.dumps(data))

    async def test_no_sessions_returns_no_new_sessions(self):
        from app.scheduler.handlers.bonsai import BonsaiGrowthHandler
        handler = BonsaiGrowthHandler()
        task = _make_task({"mode": "growth", "roles": ["test_role"], "notify_owner": False})
        result = await handler.execute(task, _make_ctx())
        summaries = result.metrics["roles"]
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["status"], "no_new_sessions")
        self.assertIsNone(summaries[0]["snapshot_version"])

    async def test_non_owner_sessions_are_ignored(self):
        from app.scheduler.handlers.bonsai import BonsaiGrowthHandler
        self._make_session_file("test_role", "s1", session_type="chat",
                                exchanges=[{"user": "hello", "assistant": "hi"}])
        handler = BonsaiGrowthHandler()
        task = _make_task({"mode": "growth", "roles": ["test_role"], "notify_owner": False})
        result = await handler.execute(task, _make_ctx())
        summaries = result.metrics["roles"]
        self.assertEqual(summaries[0]["status"], "no_new_sessions")

    async def test_owner_session_creates_snapshot(self):
        from app.scheduler.handlers.bonsai import BonsaiGrowthHandler
        self._make_session_file(
            "test_role", "s1",
            exchanges=[{"user": "always lead with growth for investors", "assistant": "ok"}],
        )
        handler = BonsaiGrowthHandler()
        task = _make_task({"mode": "growth", "roles": ["test_role"], "notify_owner": False})
        result = await handler.execute(task, _make_ctx())
        summaries = result.metrics["roles"]
        self.assertEqual(summaries[0]["status"], "snapshot_created")
        self.assertEqual(summaries[0]["snapshot_version"], 1)

        snap_path = Path(self.tmp) / "test_role" / "growth_snapshots" / "v1.json"
        self.assertTrue(snap_path.exists())

    async def test_watermark_written_after_run(self):
        from app.scheduler.handlers.bonsai import BonsaiGrowthHandler, _read_watermark
        self._make_session_file("test_role", "s1",
                                exchanges=[{"user": "great work", "assistant": "thanks"}])
        handler = BonsaiGrowthHandler()
        task = _make_task({"mode": "growth", "roles": ["test_role"], "notify_owner": False})
        await handler.execute(task, _make_ctx())
        wm = _read_watermark("test_role")
        self.assertIn("last_growth_run", wm)
        self.assertEqual(wm["pending_version"], 1)

    async def test_already_processed_sessions_skipped_by_watermark(self):
        from app.scheduler.handlers.bonsai import BonsaiGrowthHandler, _write_watermark
        # Session was indexed before the session's last_active
        _write_watermark("test_role", {"last_growth_run": "2026-06-15T00:00:00"})
        self._make_session_file("test_role", "s1",
                                exchanges=[{"user": "focus on growth", "assistant": "noted"}])
        handler = BonsaiGrowthHandler()
        task = _make_task({"mode": "growth", "roles": ["test_role"], "notify_owner": False})
        result = await handler.execute(task, _make_ctx())
        summaries = result.metrics["roles"]
        self.assertEqual(summaries[0]["status"], "no_new_sessions")

    async def test_role_error_doesnt_abort_other_roles(self):
        from app.scheduler.handlers.bonsai import BonsaiGrowthHandler
        self._make_session_file("role_a", "s1",
                                exchanges=[{"user": "good job", "assistant": "thanks"}])
        handler = BonsaiGrowthHandler()
        task = _make_task({"mode": "growth", "roles": ["role_a", "role_b"], "notify_owner": False})
        result = await handler.execute(task, _make_ctx())
        summaries = result.metrics["roles"]
        self.assertEqual(len(summaries), 2)
        ids = {s["role_id"] for s in summaries}
        self.assertIn("role_a", ids)
        self.assertIn("role_b", ids)

    async def test_pin_review_mode_delegates(self):
        from app.scheduler.handlers.bonsai import BonsaiGrowthHandler, SnapshotManager, GrowthSnapshot
        sm = SnapshotManager("test_role")
        snap = GrowthSnapshot("test_role", 1, {"core_values": {"score": 80}}, "test")
        sm.save_snapshot(snap)

        handler = BonsaiGrowthHandler()
        task = _make_task({
            "mode": "pin_review",
            "role_id": "test_role",
            "pending_version": 1,
            "reply": "accept",
        })
        result = await handler.execute(task, _make_ctx())
        self.assertTrue(result.success)
        pinned = sm.get_pinned()
        self.assertIsNotNone(pinned)
        self.assertEqual(pinned.version, 1)


class TestBonsaiPinReviewHandler(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._patches = [
            patch("app.scheduler.handlers.bonsai.get_memory_subpath", return_value=self.tmp),
            patch("app.scheduler.bonsai.get_memory_subpath", return_value=self.tmp),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _save_candidate(self, role_id, version):
        from app.scheduler.bonsai import SnapshotManager, GrowthSnapshot
        sm = SnapshotManager(role_id)
        snap = GrowthSnapshot(role_id, version, {"core_values": {"score": 80}}, "test")
        sm.save_snapshot(snap)
        return sm

    async def test_accept_pins_snapshot(self):
        from app.scheduler.handlers.bonsai import BonsaiPinReviewHandler
        sm = self._save_candidate("test_role", 2)
        handler = BonsaiPinReviewHandler()
        task = _make_task({
            "mode": "pin_review",
            "role_id": "test_role",
            "pending_version": 2,
            "reply": "accept",
        })
        result = await handler.execute(task, _make_ctx())
        self.assertTrue(result.success)
        self.assertIsNotNone(sm.get_pinned())
        self.assertEqual(sm.get_pinned().version, 2)

    async def test_reject_does_not_pin(self):
        from app.scheduler.handlers.bonsai import BonsaiPinReviewHandler
        sm = self._save_candidate("test_role", 3)
        handler = BonsaiPinReviewHandler()
        task = _make_task({
            "mode": "pin_review",
            "role_id": "test_role",
            "pending_version": 3,
            "reply": "reject",
        })
        result = await handler.execute(task, _make_ctx())
        self.assertTrue(result.success)
        self.assertIsNone(sm.get_pinned())

    async def test_accept_clears_pending_watermark(self):
        from app.scheduler.handlers.bonsai import BonsaiPinReviewHandler, _write_watermark, _read_watermark
        self._save_candidate("test_role", 1)
        _write_watermark("test_role", {"pending_version": 1, "last_growth_run": "2026-06-14"})
        handler = BonsaiPinReviewHandler()
        task = _make_task({
            "mode": "pin_review", "role_id": "test_role",
            "pending_version": 1, "reply": "accept",
        })
        await handler.execute(task, _make_ctx())
        wm = _read_watermark("test_role")
        self.assertNotIn("pending_version", wm)
        self.assertEqual(wm["pinned_version"], 1)

    async def test_reject_clears_pending_watermark(self):
        from app.scheduler.handlers.bonsai import BonsaiPinReviewHandler, _write_watermark, _read_watermark
        self._save_candidate("test_role", 2)
        _write_watermark("test_role", {"pending_version": 2})
        handler = BonsaiPinReviewHandler()
        task = _make_task({
            "mode": "pin_review", "role_id": "test_role",
            "pending_version": 2, "reply": "reject",
        })
        await handler.execute(task, _make_ctx())
        wm = _read_watermark("test_role")
        self.assertNotIn("pending_version", wm)
        self.assertEqual(wm["rejected_version"], 2)

    async def test_unrecognised_reply_stays_waiting(self):
        from app.scheduler.handlers.bonsai import BonsaiPinReviewHandler
        from app.scheduler.models import TaskStatus
        self._save_candidate("test_role", 1)
        handler = BonsaiPinReviewHandler()
        task = _make_task({
            "mode": "pin_review", "role_id": "test_role",
            "pending_version": 1, "reply": "maybe",
        })
        result = await handler.execute(task, _make_ctx())
        self.assertFalse(result.success)
        self.assertEqual(task.status, TaskStatus.WAITING_FOR_INPUT)

    async def test_missing_role_id_returns_error(self):
        from app.scheduler.handlers.bonsai import BonsaiPinReviewHandler
        handler = BonsaiPinReviewHandler()
        task = _make_task({"mode": "pin_review", "pending_version": 1, "reply": "accept"})
        result = await handler.execute(task, _make_ctx())
        self.assertFalse(result.success)

    async def test_accept_alias_yes(self):
        from app.scheduler.handlers.bonsai import BonsaiPinReviewHandler
        sm = self._save_candidate("test_role", 1)
        handler = BonsaiPinReviewHandler()
        task = _make_task({
            "mode": "pin_review", "role_id": "test_role",
            "pending_version": 1, "reply": "yes",
        })
        result = await handler.execute(task, _make_ctx())
        self.assertTrue(result.success)
        self.assertIsNotNone(sm.get_pinned())
