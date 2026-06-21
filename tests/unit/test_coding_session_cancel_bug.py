"""Tests for the bug where poller fires prematurely and cancels send_message.

The bug: asyncio.wait(FIRST_COMPLETED) returns when ANY task completes.
If the poller completes (with or without a hitl result) but no permission
was found, the previous code still called task_send.cancel() in a loop,
causing send_message to fail with CancelledError and the task to be
marked failed.

The fix: only cancel task_send when we have an actual hitl result to
process. Otherwise, let send_message complete normally.
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.scheduler.models import Task, TaskPriority, TaskType


def _make_task():
    t = Task(
        id="test-cancel-bug",
        type=TaskType.CODING_SESSION,
        priority=TaskPriority.MEDIUM,
        config={
            "use_sandbox": False, "start_new": True,
            "working_dir": "/tmp/cancel-bug-test",
        },
        created_by="test",
    )
    return t


def _make_ctx():
    ctx = MagicMock()
    ctx._scheduler = MagicMock()
    ctx._scheduler.queue = MagicMock()
    return ctx


class TestNoPrematureCancel(unittest.IsolatedAsyncioTestCase):
    """When the poller finishes with no hitl, send_message must NOT be cancelled."""

    async def test_poller_no_hitl_does_not_cancel_send(self):
        """The poller returns None (no permission) → send_message runs to completion."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task()
        ctx = _make_ctx()

        # Mock the client so:
        #   - send_message returns normally
        #   - poller returns None (no hitl found)
        mock_client = MagicMock()
        mock_client.create_session = AsyncMock(return_value={"id": "sess_001"})
        mock_client.send_message = AsyncMock(return_value={
            "parts": [{"type": "text", "text": "Done"}]
        })
        # _poll_first_hitl returns None when no permission found
        handler._poll_first_hitl = AsyncMock(return_value=None)
        handler._sse_first_permission = AsyncMock(return_value=None)
        # Mock _get_client to return our mock
        handler._get_client = AsyncMock(return_value=mock_client)

        result = await handler.execute(task, ctx)

        # If the fix is correct, send_message wasn't cancelled prematurely
        # and the result is success
        self.assertTrue(result.success)
        self.assertIn("Done", result.metrics.get("result", ""))

    async def test_poller_with_hitl_cancels_send(self):
        """The poller returns a real hitl → send_message is cancelled and HITL is processed."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task()
        ctx = _make_ctx()

        mock_client = MagicMock()
        mock_client.create_session = AsyncMock(return_value={"id": "sess_001"})
        # send_message will be cancelled — return a coroutine that raises CancelledError
        async def cancelled_send(*args, **kwargs):
            raise asyncio.CancelledError()
        mock_client.send_message = cancelled_send

        # Poller returns a real permission
        permission = {
            "id": "perm_001",
            "sessionID": "sess_001",
            "type": "external_directory",
            "patterns": ["/tmp/*"],
        }
        hitl = {"type": "permission", "data": permission}
        handler._poll_first_hitl = AsyncMock(return_value=hitl)
        handler._sse_first_permission = AsyncMock(return_value=None)
        handler._get_client = AsyncMock(return_value=mock_client)

        # Mock the HITL push so it doesn't actually try to send notifications
        with patch("app.scheduler.handlers.coding_session_opencode._push_hitl_notification",
                   new_callable=AsyncMock):
            result = await handler.execute(task, ctx)

        # With a real hitl, the task should be in WAITING_FOR_INPUT
        self.assertTrue(result.success)
        self.assertIsNotNone(result.waiting_for_input)
        self.assertIn("once", (result.waiting_for_input_choices or []))


if __name__ == "__main__":
    unittest.main()
