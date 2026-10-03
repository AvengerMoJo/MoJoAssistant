"""Regression test: task_session_read must never return an unbounded payload.

Found live 2026-10-03: a call to this tool returned 328,623 chars, choking
the calling task's (Paul's) own context and contributing to an unrelated
1800s timeout with zero checkpointed progress. last_n/max_content_chars
were neither exposed in the published schema nor ceiling-capped -- a model
could only reach a large value by guessing, but nothing stopped it once it
did.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from app.scheduler.session_storage import SessionMessage, SessionStorage, TaskSession


@pytest.fixture(autouse=True)
def _isolate_session_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.scheduler.session_storage.get_memory_subpath",
        lambda *parts: str(tmp_path.joinpath(*parts)),
    )


@pytest.fixture
def registry():
    from app.mcp.core.tools import ToolRegistry

    memory_service = MagicMock()
    memory_service.search = MagicMock(return_value=[])

    with patch("app.mcp.core.tools.ToolRegistry._start_scheduler_daemon"):
        with patch("app.scheduler.core.Scheduler._seed_tasks_from_config"):
            return ToolRegistry(memory_service=memory_service)


def _seed_large_session(task_id: str, n_messages: int = 50, content_size: int = 50_000) -> None:
    storage = SessionStorage()
    session = TaskSession(
        task_id=task_id, status="completed", messages=[], started_at="2026-10-03T00:00:00",
        final_answer="done",
    )
    storage.save_session(session)
    for i in range(n_messages):
        storage.append_message(task_id, SessionMessage(
            role="tool", content="x" * content_size, timestamp="2026-10-03T00:00:00",
            iteration=i, tool_name="some_tool",
        ))


class TestSizeCeiling:
    @pytest.mark.asyncio
    async def test_default_call_stays_small(self, registry):
        _seed_large_session("big-task", n_messages=50, content_size=50_000)
        result = await registry._execute_task_session_read({"task_id": "big-task"})
        import json
        total_size = len(json.dumps(result))
        assert total_size < 100_000  # nowhere near the 328,623 incident size

    @pytest.mark.asyncio
    async def test_requesting_huge_last_n_is_capped(self, registry):
        _seed_large_session("big-task", n_messages=50, content_size=50_000)
        result = await registry._execute_task_session_read({"task_id": "big-task", "last_n": 10_000})
        assert result["messages_returned"] <= 30

    @pytest.mark.asyncio
    async def test_requesting_huge_max_content_chars_is_capped(self, registry):
        _seed_large_session("big-task", n_messages=5, content_size=50_000)
        result = await registry._execute_task_session_read({
            "task_id": "big-task", "max_content_chars": 1_000_000,
        })
        for m in result["messages"]:
            assert len(m["content"]) <= 2001  # 2000 + ellipsis

    @pytest.mark.asyncio
    async def test_explicit_zero_last_n_does_not_mean_unlimited(self, registry):
        """The old hint text claimed last_n=0 means 'all' -- that was never
        actually true (0 silently coerced back to the default via `or`).
        Now explicit: 0 clamps to the safe ceiling, not unlimited."""
        _seed_large_session("big-task", n_messages=50, content_size=50_000)
        result = await registry._execute_task_session_read({"task_id": "big-task", "last_n": 0})
        assert result["messages_returned"] <= 30

    @pytest.mark.asyncio
    async def test_total_payload_never_approaches_incident_size(self, registry):
        """End-to-end: even a maximally-greedy request stays far below the
        328,623-char incident that choked Paul's context."""
        _seed_large_session("big-task", n_messages=100, content_size=100_000)
        result = await registry._execute_task_session_read({
            "task_id": "big-task", "last_n": 999, "max_content_chars": 999_999,
        })
        import json
        total_size = len(json.dumps(result))
        assert total_size < 100_000
