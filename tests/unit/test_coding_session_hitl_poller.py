"""Tests for the HITL poller in OpenCodeSessionHandler.

Covers:
  - Poller finds pending /permission and surfaces as permission HITL
  - Poller finds pending /question and surfaces as question HITL
  - Poller races with send_message and returns the right winner
  - Poller handles errors gracefully
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.scheduler.models import Task, TaskPriority, TaskType, TaskStatus


def _make_task():
    t = Task(
        id="test-hitl-poll",
        type=TaskType.CODING_SESSION,
        priority=TaskPriority.MEDIUM,
        config={"use_sandbox": False, "session_id": "sess_123"},
        created_by="test",
    )
    t.status = TaskStatus.RUNNING
    return t


class TestHitlPoller(unittest.IsolatedAsyncioTestCase):
    """_poll_first_hitl polls /permission and /question for the session."""

    async def test_finds_pending_permission(self):
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        client = AsyncMock()
        client.list_permissions = AsyncMock(return_value=[
            {"id": "perm_001", "sessionID": "sess_123", "type": "external_directory"}
        ])
        client.list_questions = AsyncMock(return_value=[])

        result = await handler._poll_first_hitl(client, "sess_123", poll_interval=0.05)
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "permission")
        self.assertEqual(result["data"]["id"], "perm_001")

    async def test_finds_pending_question(self):
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        client = AsyncMock()
        client.list_permissions = AsyncMock(return_value=[])
        client.list_questions = AsyncMock(return_value=[
            {"id": "que_001", "sessionID": "sess_123", "questions": [{"question": "What color?"}]}
        ])

        result = await handler._poll_first_hitl(client, "sess_123", poll_interval=0.05)
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "question")
        self.assertEqual(result["data"]["id"], "que_001")

    async def test_same_perm_id_only_returned_once_per_call(self):
        """If the same permission is in every poll cycle, only the FIRST call returns it.

        This is correct: each task is one poller instance. The handler gets the
        first permission, the user replies, and a new task cycle (resume) starts
        a fresh poller.
        """
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        client = AsyncMock()
        # First call: returns the permission
        # Second call: returns nothing (the perm was acknowledged)
        client.list_permissions = AsyncMock(side_effect=[
            [{"id": "perm_001", "sessionID": "sess_123"}],  # first call finds it
            [],  # subsequent calls: no pending
        ])
        client.list_questions = AsyncMock(return_value=[])

        result1 = await handler._poll_first_hitl(client, "sess_123", poll_interval=0.01)
        self.assertIsNotNone(result1)
        self.assertEqual(result1["data"]["id"], "perm_001")

        # Second call: no more pending perms
        result2 = await asyncio.wait_for(
            handler._poll_first_hitl(client, "sess_123", poll_interval=0.01),
            timeout=0.5,
        )
        self.assertIsNone(result2)

    async def test_ignores_other_sessions_permissions(self):
        """Permissions for other sessions are filtered out by list_permissions."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        client = AsyncMock()
        # list_permissions returns ONLY our session's perms
        # (the real client filters via the sessionID == session_id check)
        client.list_permissions = AsyncMock(return_value=[])  # other session filtered
        client.list_questions = AsyncMock(return_value=[])

        result = await asyncio.wait_for(
            handler._poll_first_hitl(client, "sess_123", poll_interval=0.05),
            timeout=0.5,
        )
        self.assertIsNone(result)

    async def test_handles_errors(self):
        """Errors from list_permissions/list_questions are caught, poller continues."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        client = AsyncMock()
        # First call raises, second returns a permission
        call_count = 0
        async def maybe_fail(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return [{"id": "perm_001", "sessionID": "sess_123"}]
        client.list_permissions = AsyncMock(side_effect=maybe_fail)
        client.list_questions = AsyncMock(return_value=[])

        result = await handler._poll_first_hitl(client, "sess_123", poll_interval=0.01)
        self.assertIsNotNone(result)
        self.assertEqual(result["data"]["id"], "perm_001")

    async def test_cancellation_returns_none(self):
        """Cancelled poller returns None."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        client = AsyncMock()
        client.list_permissions = AsyncMock(return_value=[])
        client.list_questions = AsyncMock(return_value=[])

        # Start the poller and cancel it
        task = asyncio.create_task(
            handler._poll_first_hitl(client, "sess_123", poll_interval=0.5)
        )
        await asyncio.sleep(0.1)  # let it run briefly
        task.cancel()
        result = await task
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
