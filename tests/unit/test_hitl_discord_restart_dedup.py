"""Regression test: service restart must not re-post Discord HITL questions.

Found live: every mojoassistant.service restart re-posted a Discord HITL
question for every task still in WAITING_FOR_INPUT. on_ready_hook ->
_catchup_waiting_tasks() only guarded against duplicates via the in-memory
self._pending map, which resets on every restart while the task itself
persists in the queue -- so the owner channel accumulated one duplicate
message per restart per waiting task.

Fix under test: the same durable-stamp pattern Quality Monitor uses for
escalations (QM_ESCALATED_KEY/_mark_escalated/_already_escalated in
app/scheduler/quality_monitor.py) -- a task.config["_hitl_posted_at"] ISO
timestamp written through queue.update() after every successful post, and
a 24h re-post window (matching WAITING_TOO_LONG_HOURS) so a stamp is a
dedupe, not a permanent silence.

discord.py is not a test dependency here, so a minimal stub is injected
into sys.modules -- enough for _send_hitl_impl and the lazy _HITLView /
_HITLButton classes to run the real code path end to end.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from app.mcp.adapters.hitl.discord import (
    HITL_POSTED_KEY,
    HITL_REPOST_AFTER_HOURS,
    DiscordHITLAdapter,
)
from app.scheduler.models import Task, TaskStatus, TaskType


# ----------------------------------------------------------------------
# Minimal discord.py stub (see module docstring)
# ----------------------------------------------------------------------

class _StubColor:
    @staticmethod
    def orange(): return "orange"
    @staticmethod
    def blue(): return "blue"
    @staticmethod
    def yellow(): return "yellow"
    @staticmethod
    def red(): return "red"
    @staticmethod
    def dark_red(): return "dark_red"


class _StubEmbed:
    def __init__(self, title=None, description=None, color=None):
        self.title = title
        self.description = description
        self.color = color
        self.fields = []
        self.footer = None

    def add_field(self, name=None, value=None, inline=False):
        self.fields.append((name, value, inline))

    def set_footer(self, text=None):
        self.footer = text


class _StubButtonStyle:
    success = "success"
    danger = "danger"
    primary = "primary"


class _StubView:
    def __init__(self, timeout=None):
        self.timeout = timeout
        self.items = []

    def add_item(self, item):
        self.items.append(item)


class _StubButton:
    def __init__(self, label=None, style=None, custom_id=None):
        self.label = label
        self.style = style
        self.custom_id = custom_id


def _install_discord_stub(monkeypatch):
    discord = type(sys)("discord")
    ui = type(sys)("discord.ui")
    discord.Color = _StubColor
    discord.Embed = _StubEmbed
    discord.ButtonStyle = _StubButtonStyle
    ui.View = _StubView
    ui.Button = _StubButton
    discord.ui = ui
    monkeypatch.setitem(sys.modules, "discord", discord)
    monkeypatch.setitem(sys.modules, "discord.ui", ui)


# ----------------------------------------------------------------------
# Fakes: channel/client (same-loop, the on_ready/catch-up scenario) and
# scheduler/queue holding real Task objects.
# ----------------------------------------------------------------------

class _FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, **kwargs):
        msg = type("Msg", (), {"id": len(self.sent) + 1})()
        self.sent.append(kwargs)
        return msg


class _FakeClient:
    def __init__(self, channel: _FakeChannel):
        self.loop = asyncio.get_running_loop()  # catch-up runs on the client loop
        self._channel = channel

    def get_channel(self, channel_id):
        return self._channel


class _FakeQueue:
    def __init__(self, tasks):
        self._tasks = {t.id: t for t in tasks}
        self.updates = []

    def list_tasks(self, status=None):
        return [t for t in self._tasks.values() if t.status == status]

    def get(self, task_id):
        return self._tasks.get(task_id)

    def update(self, task):
        self._tasks[task.id] = task
        self.updates.append(task.id)


class _FakeScheduler:
    def __init__(self, tasks):
        self.queue = _FakeQueue(tasks)


def _waiting_task(task_id="task-1", config=None):
    return Task(
        id=task_id,
        type=TaskType.CUSTOM,
        status=TaskStatus.WAITING_FOR_INPUT,
        config=dict(config or {}),
        pending_question="Proceed?",
    )


def _make_adapter(channel, scheduler):
    adapter = DiscordHITLAdapter("discord_owner", {"channel_id": "123"})
    adapter.set_client(_FakeClient(channel))
    adapter._scheduler = scheduler
    return adapter


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_post_stamps_task_durably(monkeypatch):
    """A successful HITL post must stamp task.config[_hitl_posted_at] via
    queue.update() so the marker survives restarts (in-memory _pending
    does not)."""
    _install_discord_stub(monkeypatch)
    channel = _FakeChannel()
    task = _waiting_task(config={"pending_options": ["yes", "no"]})
    scheduler = _FakeScheduler([task])

    adapter = _make_adapter(channel, scheduler)
    await adapter.on_ready_hook()

    assert len(channel.sent) == 1
    assert task.id in scheduler.queue.updates  # persisted, not memory-only
    stamp = task.config.get(HITL_POSTED_KEY)
    assert stamp, "post must write the durable stamp"
    datetime.fromisoformat(stamp)  # raises if not a valid ISO timestamp


@pytest.mark.asyncio
async def test_restart_within_24h_does_not_repost(monkeypatch):
    """The actual bug: a fresh adapter (empty _pending, as after a service
    restart) sharing the same persisted queue must NOT re-post a question
    whose stamp is younger than 24h."""
    _install_discord_stub(monkeypatch)
    channel = _FakeChannel()
    task = _waiting_task()
    scheduler = _FakeScheduler([task])

    first = _make_adapter(channel, scheduler)
    await first.on_ready_hook()
    assert len(channel.sent) == 1

    # Simulate restart: brand-new adapter, same scheduler/queue/task.
    restarted = _make_adapter(channel, scheduler)
    await restarted.on_ready_hook()

    assert len(channel.sent) == 1  # no duplicate
    # the skip happens before send_hitl, so nothing entered _pending
    assert restarted._pending == {}


@pytest.mark.asyncio
async def test_stale_stamp_past_24h_reposts_exactly_once(monkeypatch):
    """A stamp older than 24h means the question sat unanswered for a day
    (Quality Monitor's WAITING_TOO_LONG_HOURS convention): re-post once,
    then the fresh re-stamp suppresses further posts."""
    _install_discord_stub(monkeypatch)
    channel = _FakeChannel()
    task = _waiting_task(config={HITL_POSTED_KEY: (datetime.now() - timedelta(hours=HITL_REPOST_AFTER_HOURS + 1)).isoformat()})
    scheduler = _FakeScheduler([task])

    adapter = _make_adapter(channel, scheduler)
    await adapter.on_ready_hook()
    assert len(channel.sent) == 1  # stale stamp -> one re-post

    fresh_stamp = datetime.fromisoformat(task.config[HITL_POSTED_KEY])
    assert fresh_stamp > datetime.now() - timedelta(minutes=1)

    # Immediately after, neither the same process nor a "restart" re-posts.
    await adapter.on_ready_hook()
    restarted = _make_adapter(channel, scheduler)
    await restarted.on_ready_hook()
    assert len(channel.sent) == 1


@pytest.mark.asyncio
async def test_unparseable_stamp_fails_open_to_posting(monkeypatch):
    """A corrupt stamp must not permanently silence a waiting question."""
    _install_discord_stub(monkeypatch)
    channel = _FakeChannel()
    task = _waiting_task(config={HITL_POSTED_KEY: "not-a-timestamp"})
    scheduler = _FakeScheduler([task])

    adapter = _make_adapter(channel, scheduler)
    await adapter.on_ready_hook()
    assert len(channel.sent) == 1
    # and the post repaired the stamp
    datetime.fromisoformat(task.config[HITL_POSTED_KEY])


@pytest.mark.asyncio
async def test_stamp_is_best_effort_when_task_missing(monkeypatch):
    """A post for a task no longer in the queue (race: answered/resumed
    between send and stamp) must not raise or unwrap the send."""
    _install_discord_stub(monkeypatch)
    channel = _FakeChannel()
    adapter = DiscordHITLAdapter("discord_owner", {"channel_id": "123"})
    adapter.set_client(_FakeClient(channel))
    adapter._scheduler = _FakeScheduler([])  # queue.get -> None

    await adapter.send_hitl("gone-task", "Proceed?", [])
    assert len(channel.sent) == 1  # post still succeeded


class TestHitlRecentlyPosted:
    def adapter(self):
        return DiscordHITLAdapter("discord_owner", {"channel_id": "123"})

    def test_no_stamp_is_not_recent(self):
        assert self.adapter()._hitl_recently_posted(_waiting_task()) is False

    def test_garbage_stamp_is_not_recent(self):
        task = _waiting_task(config={HITL_POSTED_KEY: 12345})
        assert self.adapter()._hitl_recently_posted(task) is False

    def test_fresh_stamp_is_recent(self):
        task = _waiting_task(config={HITL_POSTED_KEY: datetime.now().isoformat()})
        assert self.adapter()._hitl_recently_posted(task) is True

    def test_stale_stamp_is_not_recent(self):
        old = datetime.now() - timedelta(hours=HITL_REPOST_AFTER_HOURS + 1)
        task = _waiting_task(config={HITL_POSTED_KEY: old.isoformat()})
        assert self.adapter()._hitl_recently_posted(task) is False

    def test_boundary_exactly_24h_is_still_recent(self):
        """Suppression window is [0, 24h]: a stamp exactly 24h old still
        suppresses (mirrors QM's strict-> escalation threshold). Controlled
        now so the boundary is exact, not wall-clock racy."""
        now = datetime(2026, 9, 23, 12, 0, 0)
        task = _waiting_task(config={
            HITL_POSTED_KEY: (now - timedelta(hours=HITL_REPOST_AFTER_HOURS)).isoformat()
        })
        assert self.adapter()._hitl_recently_posted(task, now=now) is True

    def test_boundary_one_microsecond_past_24h_is_stale(self):
        now = datetime(2026, 9, 23, 12, 0, 0)
        task = _waiting_task(config={
            HITL_POSTED_KEY: (now - timedelta(hours=HITL_REPOST_AFTER_HOURS, microseconds=1)).isoformat()
        })
        assert self.adapter()._hitl_recently_posted(task, now=now) is False
