"""Unit tests for handlers/coding_session_opencode.py — OpenCodeSessionHandler.

Covers the full lifecycle:
  1. Run mode — session created, message sent, normal completion
  2. Run mode — permission HITL via SSE (task → WAITING_FOR_INPUT)
  3. Resume mode — user replies "once" → permission responded → re-enters run
  4. Question HITL — OpenCode Question API surfaces arbitrary question
  5. Resume question — user reply posted to /question/{id}/reply → re-enters run
  6. Timeout chaining — send_message times out → chains "continue"
  7. Error handling — backend failures propagate correctly
  8. Session creation failure — no session ID returned
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.scheduler.models import Task, TaskPriority, TaskStatus, TaskType


def _make_task(config=None, status=None):
    t = Task(
        id="test_cs_001",
        type=TaskType.CODING_SESSION,
        priority=TaskPriority.MEDIUM,
        config=config or {},
        description="test coding session",
        created_by="test",
    )
    if status:
        t.status = status
    return t


def _make_ctx():
    ctx = MagicMock()
    ctx._scheduler = None
    ctx.log = MagicMock()
    ctx.queue = MagicMock()
    ctx.queue.update = MagicMock()
    return ctx


def _make_mock_backend():
    """Create a MagicMock that quacks like OpenCodeBackend."""
    backend = AsyncMock()
    backend.create_session = AsyncMock(return_value={"id": "sess_123"})
    backend.send_message = AsyncMock(return_value={
        "parts": [{"type": "text", "text": "Task completed successfully"}]
    })
    backend.respond_to_permission = AsyncMock(return_value={"ok": True})
    backend.reply_to_question = AsyncMock(return_value={"ok": True})
    backend.list_questions = AsyncMock(return_value=[])
    backend.subscribe_permissions = MagicMock()
    backend._client = AsyncMock()
    backend._client.get = AsyncMock(return_value=MagicMock(
        json=lambda: [], raise_for_status=lambda: None
    ))
    backend._client.post = AsyncMock(return_value=MagicMock(
        json=lambda: {"ok": True}, raise_for_status=lambda: None
    ))
    return backend


class TestOpenCodeSessionHandlerRunMode(unittest.IsolatedAsyncioTestCase):
    """Test normal run mode — create session, send message, complete."""

    async def test_successful_completion(self):
        """Message sent and returned → task completes with summary."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({"prompt": "write hello.py", "session_id": "sess_123"})
        ctx = _make_ctx()
        backend = _make_mock_backend()

        with patch.object(handler, "_get_backend", return_value=backend):
            # SSE watcher returns None (no permissions fired)
            backend.subscribe_permissions.return_value = _empty_async_iter()
            result = await handler.execute(task, ctx)

        self.assertTrue(result.success)
        self.assertIn("result", result.metrics)
        self.assertEqual(result.metrics["result"], "Task completed successfully")

    async def test_session_created_if_no_session_id(self):
        """When session_id is empty, handler calls create_session and stores it."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({"prompt": "write hello.py"})  # no session_id
        ctx = _make_ctx()
        backend = _make_mock_backend()

        with patch.object(handler, "_get_backend", return_value=backend):
            backend.subscribe_permissions.return_value = _empty_async_iter()
            await handler.execute(task, ctx)

        backend.create_session.assert_awaited_once()
        self.assertEqual(task.config["session_id"], "sess_123")
        ctx.queue.update.assert_called()

    async def test_session_creation_fails_no_id(self):
        """create_session returns no ID → handler returns error."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({"prompt": "write hello.py"})
        ctx = _make_ctx()
        backend = _make_mock_backend()
        backend.create_session = AsyncMock(return_value={"unexpected": "shape"})

        with patch.object(handler, "_get_backend", return_value=backend):
            result = await handler.execute(task, ctx)

        self.assertFalse(result.success)
        self.assertIn("no ID", result.error_message)

    async def test_send_message_error_propagates(self):
        """Non-timeout error from send_message → failure result."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({"prompt": "write hello.py", "session_id": "sess_123"})
        ctx = _make_ctx()
        backend = _make_mock_backend()
        backend.send_message = AsyncMock(side_effect=ConnectionError("connection refused"))

        with patch.object(handler, "_get_backend", return_value=backend):
            backend.subscribe_permissions.return_value = _empty_async_iter()
            result = await handler.execute(task, ctx)

        self.assertFalse(result.success)
        self.assertIn("connection refused", result.error_message)


class TestOpenCodePermissionHITL(unittest.IsolatedAsyncioTestCase):
    """Test permission HITL via SSE permission stream."""

    async def test_permission_triggers_waiting_for_input(self):
        """SSE fires a permission event before send_message returns → task waits."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({"prompt": "run tests", "session_id": "sess_123"})
        ctx = _make_ctx()
        backend = _make_mock_backend()

        # send_message will hang (we cancel it)
        async def _hang():
            await asyncio.sleep(999)
        backend.send_message = AsyncMock(side_effect=_hang)

        # SSE fires immediately with a permission
        perm_event = {
            "requestID": "perm_001",
            "directory": "/home/alex/project",
            "title": "Execute: npm test",
            "type": "execute",
        }
        backend.subscribe_permissions.return_value = _single_item_async_iter(perm_event)

        with patch.object(handler, "_get_backend", return_value=backend), \
             patch("app.scheduler.handlers.coding_session_opencode._push_hitl_notification",
                   new_callable=AsyncMock):
            result = await handler.execute(task, ctx)

        self.assertTrue(result.success)
        self.assertEqual(result.waiting_for_input, task.pending_question)
        self.assertEqual(result.waiting_for_input_choices, ["once", "always", "reject"])
        self.assertEqual(task.status, TaskStatus.WAITING_FOR_INPUT)
        self.assertEqual(task.config["_mode"], "resume")
        self.assertEqual(task.config["perm_id"], "perm_001")
        self.assertIn("execute", task.pending_question)
        self.assertIn("npm test", task.pending_question)

    async def test_resume_after_permission_reply(self):
        """User replies 'once' → respond_to_permission called → re-enters run."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({
            "_mode": "resume",
            "session_id": "sess_123",
            "perm_id": "perm_001",
            "perm_directory": "/home/alex/project",
            "_user_reply": "once",
        })
        ctx = _make_ctx()
        backend = _make_mock_backend()

        with patch.object(handler, "_get_backend", return_value=backend):
            backend.subscribe_permissions.return_value = _empty_async_iter()
            result = await handler.execute(task, ctx)

        backend.respond_to_permission.assert_awaited_once_with(
            "sess_123", "perm_001", "once", directory="/home/alex/project"
        )
        self.assertTrue(result.success)
        self.assertNotIn("_mode", task.config)
        self.assertNotIn("perm_id", task.config)
        self.assertEqual(task.config["prompt"], "continue")

    async def test_resume_permission_reply_always(self):
        """User replies 'always' → mapped to 'always' permission."""
        from app.scheduler.handlers.coding_session_opencode import (
            OpenCodeSessionHandler, _map_user_reply_to_permission,
        )

        self.assertEqual(_map_user_reply_to_permission("always"), "always")
        self.assertEqual(_map_user_reply_to_permission("yes always"), "always")
        self.assertEqual(_map_user_reply_to_permission("once"), "once")
        self.assertEqual(_map_user_reply_to_permission("reject"), "reject")
        self.assertEqual(_map_user_reply_to_permission("no"), "reject")
        self.assertEqual(_map_user_reply_to_permission("deny"), "reject")

    async def test_resume_permission_respond_fails(self):
        """respond_to_permission raises → failure result."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({
            "_mode": "resume",
            "session_id": "sess_123",
            "perm_id": "perm_001",
            "_user_reply": "once",
        })
        ctx = _make_ctx()
        backend = _make_mock_backend()
        backend.respond_to_permission = AsyncMock(side_effect=RuntimeError("403 Forbidden"))

        with patch.object(handler, "_get_backend", return_value=backend):
            result = await handler.execute(task, ctx)

        self.assertFalse(result.success)
        self.assertIn("403", result.error_message)


class TestOpenCodeQuestionHITL(unittest.IsolatedAsyncioTestCase):
    """Test OpenCode Question API HITL."""

    async def test_question_during_timeout_chain(self):
        """send_message times out + pending question → question HITL surfaces."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({"prompt": "refactor auth", "session_id": "sess_123"})
        ctx = _make_ctx()
        backend = _make_mock_backend()

        # Timeout error
        backend.send_message = AsyncMock(
            side_effect=TimeoutError("ReadTimeout: timed out")
        )

        # Question polling finds a question on first poll, empty on subsequent
        question = {
            "id": "que_001",
            "sessionID": "sess_123",
            "questions": [{
                "question": "Which database should I use?",
                "header": "DB Choice",
                "options": ["postgres", "sqlite"],
                "custom": True,
            }],
        }
        backend.list_questions = AsyncMock(return_value=[question])

        with patch.object(handler, "_get_backend", return_value=backend), \
             patch("app.scheduler.handlers.coding_session_opencode._push_hitl_notification",
                   new_callable=AsyncMock):
            backend.subscribe_permissions.return_value = _empty_async_iter()
            result = await handler.execute(task, ctx)

        self.assertTrue(result.success)
        self.assertEqual(result.waiting_for_input, task.pending_question)
        self.assertIn("database", result.waiting_for_input)
        self.assertEqual(task.status, TaskStatus.WAITING_FOR_INPUT)
        self.assertEqual(task.config["_mode"], "resume_question")
        self.assertIn("database", task.pending_question)
        self.assertEqual(task.config["pending_options"], ["postgres", "sqlite"])

    async def test_resume_question(self):
        """User replies to question → /question/{id}/reply posted → re-enters run."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({
            "_mode": "resume_question",
            "session_id": "sess_123",
            "question_id": "que_001",
            "_user_reply": "postgres",
        })
        ctx = _make_ctx()
        backend = _make_mock_backend()

        with patch.object(handler, "_get_backend", return_value=backend):
            backend.subscribe_permissions.return_value = _empty_async_iter()
            result = await handler.execute(task, ctx)

        backend.reply_to_question.assert_awaited_once_with("que_001", "postgres")

        self.assertTrue(result.success)
        self.assertNotIn("_mode", task.config)
        self.assertNotIn("question_id", task.config)
        self.assertEqual(task.config["prompt"], "continue")

    async def test_resume_question_no_reply(self):
        """Resume question with no user reply → error."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({
            "_mode": "resume_question",
            "session_id": "sess_123",
            "question_id": "que_001",
        })
        ctx = _make_ctx()
        backend = _make_mock_backend()

        with patch.object(handler, "_get_backend", return_value=backend):
            result = await handler.execute(task, ctx)

        self.assertFalse(result.success)
        self.assertIn("no reply", result.error_message)


class TestOpenCodeTimeoutChain(unittest.IsolatedAsyncioTestCase):
    """Test timeout chaining behavior."""

    async def test_timeout_no_question_chains_continue(self):
        """send_message times out, no pending question → chains 'continue' → succeeds on retry."""
        from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler

        handler = OpenCodeSessionHandler()
        task = _make_task({"prompt": "refactor auth", "session_id": "sess_123"})
        ctx = _make_ctx()
        backend = _make_mock_backend()

        # First call times out, second call (after chain) succeeds
        call_count = 0
        original_result = {"parts": [{"type": "text", "text": "Done after continue"}]}

        async def _send_then_succeed(sid, content, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("ReadTimeout: timed out")
            return original_result

        backend.send_message = AsyncMock(side_effect=_send_then_succeed)

        # No pending questions on first poll
        backend.list_questions = AsyncMock(return_value=[])

        with patch.object(handler, "_get_backend", return_value=backend):
            backend.subscribe_permissions.return_value = _empty_async_iter()
            result = await handler.execute(task, ctx)

        self.assertTrue(result.success)
        self.assertEqual(call_count, 2)
        self.assertEqual(task.config["prompt"], "continue where you left off")
        self.assertEqual(result.metrics["result"], "Done after continue")


class TestHelperFunctions(unittest.TestCase):
    """Test module-level helper functions."""

    def test_extract_text_from_parts(self):
        from app.scheduler.handlers.coding_session_opencode import _extract_text

        result = _extract_text({
            "parts": [
                {"type": "text", "text": "Hello world"},
                {"type": "tool_use", "name": "bash"},
            ]
        })
        self.assertEqual(result, "Hello world")

    def test_extract_text_fallback_to_str(self):
        from app.scheduler.handlers.coding_session_opencode import _extract_text

        result = _extract_text({"unexpected": "shape"})
        self.assertIn("unexpected", result)

    def test_extract_text_empty_parts(self):
        from app.scheduler.handlers.coding_session_opencode import _extract_text

        result = _extract_text({"parts": []})
        self.assertIn("parts", result)


# ---------------------------------------------------------------------------
# Async iterator helpers for mocking SSE streams
# ---------------------------------------------------------------------------

async def _empty_async_iter():
    """Empty async iterator — simulates SSE stream that ends without events."""
    return
    yield  # never reached, makes this a generator


async def _single_item_async_iter(item):
    """Async iterator that yields one item then stops."""
    yield item


if __name__ == "__main__":
    unittest.main()
