"""Regression test: free-text Discord replies must not land on Quality
Monitor's notification-only alert tasks.

Found live 2026-09-22: a genuine reply ("where are we", meant for a real
pending ask_user task) was routed to a stale Quality Monitor alert instead,
because handle_owner_message always picked the single most-recently-posted
pending message. Quality Monitor alerts are Task(type=CUSTOM, no "command"),
posted to WAITING_FOR_INPUT purely so the existing send_hitl path delivers
them -- never meant to be resumed. Resuming one flips it to PENDING and
dispatches it through CustomHandler, which fails with "Missing 'command' in
task config".
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from app.mcp.adapters.hitl.discord import DiscordHITLAdapter


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content
        self.replies = []
        self.reactions = []

    async def reply(self, text, mention_author=False):
        self.replies.append(text)

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)


class _FakeQueue:
    def __init__(self, tasks: dict):
        self._tasks = tasks

    def get(self, task_id):
        return self._tasks.get(task_id)


class _FakeScheduler:
    def __init__(self, tasks: dict):
        self.queue = _FakeQueue(tasks)
        self.resumed = []

    def resume_task_with_reply(self, task_id, reply):
        self.resumed.append((task_id, reply))


def _task(source=None):
    config = {}
    if source is not None:
        config["source"] = source
    return SimpleNamespace(config=config)


@pytest.fixture
def adapter():
    return DiscordHITLAdapter("discord_owner", {"channel_id": "123"})


class TestSkipsNotificationOnlyAlerts:
    @pytest.mark.asyncio
    async def test_skips_qm_alert_and_routes_to_real_pending_task(self, adapter):
        tasks = {
            "real-task-1": _task(source=None),
            "qm-alert-1": _task(source="quality_monitor"),
        }
        adapter._scheduler = _FakeScheduler(tasks)
        # qm-alert-1 posted most recently (higher msg id) -- must still be skipped
        adapter._pending = {
            100: ("real-task-1", []),
            200: ("qm-alert-1", []),
        }

        msg = _FakeMessage("where are we")
        await adapter.handle_owner_message(msg)

        assert adapter._scheduler.resumed == [("real-task-1", "where are we")]
        assert "✅" in msg.reactions
        # the QM alert must remain untouched/pending, not consumed
        assert 200 in adapter._pending

    @pytest.mark.asyncio
    async def test_no_real_task_reports_nothing_pending(self, adapter):
        tasks = {"qm-alert-1": _task(source="quality_monitor")}
        adapter._scheduler = _FakeScheduler(tasks)
        adapter._pending = {100: ("qm-alert-1", [])}

        msg = _FakeMessage("where are we")
        await adapter.handle_owner_message(msg)

        assert adapter._scheduler.resumed == []
        assert msg.replies == ["No pending HITL task right now."]

    @pytest.mark.asyncio
    async def test_no_pending_at_all_reports_nothing_pending(self, adapter):
        adapter._scheduler = _FakeScheduler({})
        adapter._pending = {}

        msg = _FakeMessage("hello")
        await adapter.handle_owner_message(msg)

        assert msg.replies == ["No pending HITL task right now."]

    @pytest.mark.asyncio
    async def test_real_task_still_routes_when_it_is_most_recent(self, adapter):
        tasks = {
            "qm-alert-1": _task(source="quality_monitor"),
            "real-task-1": _task(source=None),
        }
        adapter._scheduler = _FakeScheduler(tasks)
        adapter._pending = {
            100: ("qm-alert-1", []),
            200: ("real-task-1", []),
        }

        msg = _FakeMessage("yes")
        await adapter.handle_owner_message(msg)

        assert adapter._scheduler.resumed == [("real-task-1", "yes")]

    @pytest.mark.asyncio
    async def test_unknown_task_id_treated_as_real_not_notification_only(self, adapter):
        """If the task can't be looked up (e.g. scheduler race), fail open
        to the original routing behavior rather than silently dropping it."""
        adapter._scheduler = _FakeScheduler({})  # task_id not in queue
        adapter._pending = {100: ("mystery-task", [])}

        msg = _FakeMessage("ok")
        await adapter.handle_owner_message(msg)

        assert adapter._scheduler.resumed == [("mystery-task", "ok")]


class TestIsNotificationOnly:
    def test_true_for_quality_monitor_source(self, adapter):
        adapter._scheduler = _FakeScheduler({"t1": _task(source="quality_monitor")})
        assert adapter._is_notification_only("t1") is True

    def test_false_for_no_source(self, adapter):
        adapter._scheduler = _FakeScheduler({"t1": _task(source=None)})
        assert adapter._is_notification_only("t1") is False

    def test_false_when_no_scheduler_set(self, adapter):
        adapter._scheduler = None
        assert adapter._is_notification_only("t1") is False

    def test_false_when_task_not_found(self, adapter):
        adapter._scheduler = _FakeScheduler({})
        assert adapter._is_notification_only("t1") is False
