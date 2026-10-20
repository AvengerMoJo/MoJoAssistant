"""Unit tests for MessengerManager event routing.

The contract that matters here (owner directive 2026-10-19): an event tagged
audience="push_only" must reach push adapters (nty, via the event log) but must
NOT reach messenger adapters (Discord, Telegram). Quality Monitor escalations
carry that tag so a failed task never lands in the owner's Discord -- the
channel reserved for questions they can actually answer.

Without the guard, Scheduler._broadcast hands every event to BOTH the event
log and this manager, and DiscordMessengerAdapter.send_notification would
deliver the failure anyway, making the whole QM change cosmetic.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.mcp.adapters.messenger.manager import MessengerManager


class FakeAdapter:
    def __init__(self, adapter_id="fake"):
        self.adapter_id = adapter_id
        self.notifications = []
        self.hitls = []

    async def set_scheduler(self, scheduler):
        pass

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send_notification(self, title, body, severity="info"):
        self.notifications.append((title, body, severity))

    async def send_hitl(self, task_id, question, choices=None, context=None):
        self.hitls.append(task_id)


def _manager_with(*adapters):
    mgr = MessengerManager()
    for a in adapters:
        mgr._adapters.append(a)
    return mgr


class TestAudienceRouting:
    def test_push_only_event_is_not_delivered_to_messengers(self):
        """The load-bearing assertion of this whole change."""
        adapter = FakeAdapter()
        mgr = _manager_with(adapter)

        asyncio.run(mgr.dispatch({
            "event_type": "task_failed",
            "task_id": "sub_paul_x",
            "classification": "genuinely_failed",
            "severity": "error",
            "audience": "push_only",
            "notify_user": True,
            "title": "Quality Monitor: sub_paul_x (genuinely_failed)",
        }))

        assert adapter.notifications == []
        assert adapter.hitls == []

    def test_push_only_skipped_even_before_notify_user_check(self):
        """Both guards apply; this one only asserts the audience guard runs
        independently so a future refactor can't reorder them into a hole."""
        adapter = FakeAdapter()
        mgr = _manager_with(adapter)

        asyncio.run(mgr.dispatch({
            "event_type": "task_failed",
            "audience": "push_only",
            "notify_user": False,
        }))

        assert adapter.notifications == []

    def test_real_hitl_question_still_reaches_discord(self):
        """Regression guard: the whole point of the split is that genuine
        questions keep working. owner_route_paul_* must not regress."""
        adapter = FakeAdapter()
        mgr = _manager_with(adapter)

        asyncio.run(mgr.dispatch({
            "event_type": "task_waiting_for_input",
            "task_id": "owner_route_paul_20261015_100735",
            "question": "What is Cecilia Clone's primary job?",
            "notify_user": True,
        }))

        assert adapter.hitls == ["owner_route_paul_20261015_100735"]
        assert adapter.notifications == []

    def test_ordinary_notification_still_reaches_messengers(self):
        """A normal task_failed from the executor (core.py:421) has no
        audience tag and must keep behaving as before."""
        adapter = FakeAdapter()
        mgr = _manager_with(adapter)

        asyncio.run(mgr.dispatch({
            "event_type": "task_failed",
            "task_id": "t123",
            "severity": "error",
            "title": "Task t123 died unexpectedly",
            "notify_user": True,
        }))

        assert len(adapter.notifications) == 1
        assert adapter.notifications[0][0] == "Task t123 died unexpectedly"

    def test_silent_events_are_still_skipped(self):
        adapter = FakeAdapter()
        mgr = _manager_with(adapter)

        asyncio.run(mgr.dispatch({"event_type": "scheduler_tick", "notify_user": False}))

        assert adapter.notifications == []

    def test_no_adapters_is_a_noop(self):
        mgr = MessengerManager()
        asyncio.run(mgr.dispatch({
            "event_type": "task_failed",
            "audience": "push_only",
            "notify_user": True,
        }))  # must not raise