"""Tests for Phase 1 bug fixes in coding_session_opencode handler.

Covers:
  - Bug 4: _get_client must require exact working_dir match or fail loud
  - Bug 5: _cleanup must run on task end (CubeSandbox + per-task sandbox)
  - Bug 11: Per-task logger prefixes task_id
  - Bug 13: Duration warning fires when approaching cap
"""
from __future__ import annotations

import asyncio
import logging
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.scheduler.models import Task, TaskPriority, TaskType, TaskStatus


def _make_task(config=None, status=TaskStatus.RUNNING):
    t = Task(
        id="test_phase1",
        type=TaskType.CODING_SESSION,
        priority=TaskPriority.MEDIUM,
        config=config or {},
        description="phase 1",
        created_by="test",
    )
    t.status = status
    t.started_at = datetime.now(timezone.utc)
    return t


def _make_ctx():
    ctx = MagicMock()
    ctx._scheduler = MagicMock()
    ctx._scheduler.queue = MagicMock()
    ctx.log = MagicMock()
    return ctx


class TestBug4AutoDiscovery(unittest.IsolatedAsyncioTestCase):
    """_get_client must require exact working_dir match or fail loud."""

    async def test_fails_loud_when_working_dir_has_no_match(self):
        """No sandbox with matching working_dir + no start_new → RuntimeError."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({"working_dir": "/home/alex/Development/Personal/new-project"})
        ctx = _make_ctx()

        # Mock SandboxManager with no matches
        mock_mgr = MagicMock()
        mock_mgr.list.return_value = []  # no running sandboxes
        mock_mgr.get.return_value = None

        with patch("app.sandbox.manager.SandboxManager", return_value=mock_mgr):
            with self.assertRaises(RuntimeError) as cm:
                await handler._get_client(task)
            self.assertIn("No running sandbox matches working_dir", str(cm.exception))
            self.assertIn("/home/alex/Development/Personal/new-project", str(cm.exception))
            self.assertIn("start_new=True", str(cm.exception))

    async def test_fails_loud_when_ambiguous_match(self):
        """Multiple sandboxes match working_dir → fail with disambiguation hint."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({"working_dir": "/home/alex/Development/Personal"})
        ctx = _make_ctx()

        match1 = MagicMock(working_dir="/home/alex/Development/Personal",
                           status="running", agent_type="opencode", port=4100, password="x")
        match2 = MagicMock(working_dir="/home/alex/Development/Personal",
                           status="running", agent_type="opencode", port=4101, password="y")

        mock_mgr = MagicMock()
        mock_mgr.list.return_value = [match1, match2]

        with patch("app.sandbox.manager.SandboxManager", return_value=mock_mgr):
            with self.assertRaises(RuntimeError) as cm:
                await handler._get_client(task)
            self.assertIn("Multiple running sandboxes match", str(cm.exception))
            self.assertIn("Specify sandbox_id", str(cm.exception))

    async def test_exact_match_uses_that_sandbox(self):
        """Single sandbox with matching working_dir → use it."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({"working_dir": "/home/alex/Development/Personal"})
        ctx = _make_ctx()

        match = MagicMock(
            working_dir="/home/alex/Development/Personal",
            status="running", agent_type="opencode",
            port=4101, password="MoJo2026!mcp",
        )
        mock_mgr = MagicMock()
        mock_mgr.list.return_value = [match]

        with patch("app.sandbox.manager.SandboxManager", return_value=mock_mgr):
            client = await handler._get_client(task)

        # client stored in cfg for cleanup
        self.assertIn("_opencode_client", task.config)
        self.assertIs(client, task.config["_opencode_client"])


class TestBug5Cleanup(unittest.IsolatedAsyncioTestCase):
    """_cleanup must release owned resources."""

    async def test_cleanup_kills_cubesandbox(self):
        """CubeSandbox VM is killed on cleanup when _owned_cube is set."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({"_owned_cube": True, "working_dir": "/x"})
        ctx = _make_ctx()

        mock_cube = MagicMock()
        task.config["_cube_client"] = mock_cube

        await handler._cleanup(task, ctx)
        mock_cube.kill.assert_called_once()

    async def test_cleanup_does_not_kill_unowned_cubesandbox(self):
        """CubeSandbox not killed if _owned_cube is not set (we didn't start it)."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({"working_dir": "/x"})  # no _owned_cube flag
        ctx = _make_ctx()

        mock_cube = MagicMock()
        task.config["_cube_client"] = mock_cube

        await handler._cleanup(task, ctx)
        mock_cube.kill.assert_not_called()

    async def test_cleanup_stops_per_task_sandbox(self):
        """Per-task sandbox (start_new=True) is stopped on cleanup."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({"_owned_sandbox": "task-test_phase1", "working_dir": "/x"})
        ctx = _make_ctx()

        mock_mgr = MagicMock()
        with patch("app.sandbox.manager.SandboxManager", return_value=mock_mgr):
            await handler._cleanup(task, ctx)
        mock_mgr.stop.assert_called_once_with("task-test_phase1")

    async def test_cleanup_closes_opencode_client(self):
        """OpenCode HTTP client is closed (best-effort)."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({"working_dir": "/x"})
        ctx = _make_ctx()

        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        task.config["_opencode_client"] = mock_client

        await handler._cleanup(task, ctx)
        mock_client.close.assert_awaited_once()

    async def test_cleanup_safe_when_no_resources(self):
        """Cleanup doesn't crash if no resources were created."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({"working_dir": "/x"})
        ctx = _make_ctx()
        # No _owned_cube, no _owned_sandbox, no _opencode_client
        await handler._cleanup(task, ctx)  # should not raise


class TestBug11PerTaskLogger(unittest.TestCase):
    """TaskLogAdapter prefixes every message with task_id."""

    def test_prefixes_with_task_id(self):
        from app.scheduler.handlers.coding_session_opencode import TaskLogAdapter
        adapter = TaskLogAdapter(logging.getLogger("test"), {"task_id": "cs-123"})
        msg, _ = adapter.process("hello", {})
        self.assertIn("[cs-123]", msg)
        self.assertIn("hello", msg)

    def test_no_prefix_when_no_task_id(self):
        from app.scheduler.handlers.coding_session_opencode import TaskLogAdapter
        adapter = TaskLogAdapter(logging.getLogger("test"), {})
        msg, _ = adapter.process("hello", {})
        self.assertEqual(msg, "hello")


class TestBug13DurationWarning(unittest.TestCase):
    """_check_duration_warn must log when approaching the duration cap."""

    def test_warns_when_close_to_cap(self):
        from app.scheduler.handlers.coding_session_opencode import (
            _check_duration_warn, TASK_DURATION_CAP_S, TASK_DURATION_WARN_S,
        )

        task = _make_task({})
        # Started 1700s ago → 100s remaining, within warn window
        task.started_at = datetime.now(timezone.utc) - timedelta(seconds=1700)
        log = MagicMock()

        _check_duration_warn(task, log)
        log.warning.assert_called_once()
        # Format placeholders haven't been resolved by the mock — the actual
        # logger fills them in. Verify the format string contains the cap.
        msg = log.warning.call_args[0][0]
        self.assertIn("approaching duration cap", msg)
        self.assertIn("cap=%ds", msg)

    def test_does_not_warn_when_far_from_cap(self):
        from app.scheduler.handlers.coding_session_opencode import _check_duration_warn

        task = _make_task({})
        task.started_at = datetime.now(timezone.utc) - timedelta(seconds=60)  # fresh
        log = MagicMock()

        _check_duration_warn(task, log)
        log.warning.assert_not_called()

    def test_warns_when_exceeded(self):
        from app.scheduler.handlers.coding_session_opencode import _check_duration_warn

        task = _make_task({})
        task.started_at = datetime.now(timezone.utc) - timedelta(seconds=2000)  # over cap
        log = MagicMock()

        _check_duration_warn(task, log)
        log.warning.assert_called_once()
        self.assertIn("exceeded duration cap", log.warning.call_args[0][0])

    def test_safe_when_no_started_at(self):
        """No started_at → no warning (task hasn't actually run yet)."""
        from app.scheduler.handlers.coding_session_opencode import _check_duration_warn

        task = _make_task({})
        task.started_at = None
        log = MagicMock()

        _check_duration_warn(task, log)
        log.warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
