"""Regression test for the Discord HITL cross-event-loop bug.

Found live 2026-09-22: every ask_user HITL prompt failed to post to Discord
with aiohttp's "Timeout context manager should be used inside a task",
because the scheduler runs in its own dedicated thread with its own event
loop (app/mcp/core/tools.py run_scheduler), separate from the loop
discord.py's Client (and its aiohttp ClientSession) actually runs on.
DiscordHITLAdapter.send_hitl() was awaiting Discord API calls directly from
whatever loop called it, instead of bridging onto the client's own loop —
so nothing ever reached the owner channel for the user to reply to.

This test reproduces the real cross-thread/cross-loop scenario (two actual
event loops on two actual threads) rather than mocking asyncio away, since
that's exactly the class of bug a mock would hide.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from app.mcp.adapters.hitl.discord import DiscordHITLAdapter


class _FakeChannel:
    """Records which event loop actually executed .send(), the way a real
    discord.py channel's aiohttp-backed .send() would only work correctly
    on the loop its ClientSession was created on."""

    def __init__(self, expected_loop: asyncio.AbstractEventLoop):
        self.expected_loop = expected_loop
        self.sent = []

    async def send(self, **kwargs):
        running_loop = asyncio.get_running_loop()
        if running_loop is not self.expected_loop:
            raise RuntimeError(
                "Timeout context manager should be used inside a task"
            )  # the exact real-world aiohttp failure this test guards against
        msg = type("Msg", (), {"id": len(self.sent) + 1})()
        self.sent.append(kwargs)
        return msg


class _FakeClient:
    def __init__(self, loop: asyncio.AbstractEventLoop, channel: _FakeChannel):
        self.loop = loop
        self._channel = channel

    def get_channel(self, channel_id):
        return self._channel


@pytest.fixture
def background_loop():
    """A real second event loop running on a real second thread — stands in
    for discord.py's Client loop, distinct from whatever loop the test
    itself (standing in for the scheduler thread) runs on."""
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def _run():
        asyncio.set_event_loop(loop)
        ready.set()
        loop.run_forever()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    ready.wait(timeout=5)
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)


@pytest.mark.asyncio
async def test_send_hitl_bridges_to_client_loop_from_a_different_loop(background_loop):
    """The scheduler-thread scenario: send_hitl is awaited from a loop that
    is NOT the Discord client's loop. Before the fix this raised the real
    aiohttp cross-loop error; after the fix it must succeed by bridging."""
    channel = _FakeChannel(expected_loop=background_loop)
    client = _FakeClient(loop=background_loop, channel=channel)

    adapter = DiscordHITLAdapter("discord_owner", {"channel_id": "123"})
    adapter.set_client(client)

    # This test coroutine itself runs on pytest-asyncio's own loop, which is
    # deliberately NOT background_loop -- reproducing the real mismatch.
    assert asyncio.get_running_loop() is not background_loop

    await adapter.send_hitl("task-1", "Proceed?", ["yes", "no"])

    assert len(channel.sent) == 1
    assert any(v[0] == "task-1" for v in adapter._pending.values())


@pytest.mark.asyncio
async def test_send_notification_bridges_to_client_loop(background_loop):
    channel = _FakeChannel(expected_loop=background_loop)
    client = _FakeClient(loop=background_loop, channel=channel)

    adapter = DiscordHITLAdapter("discord_owner", {"channel_id": "123"})
    adapter.set_client(client)

    await adapter.send_notification("Heads up", "Something happened", severity="warning")

    assert len(channel.sent) == 1


@pytest.mark.asyncio
async def test_send_hitl_same_loop_passthrough_no_thread_hop():
    """The on_ready/catch-up scenario: send_hitl is called from the exact
    loop the client itself runs on (e.g. discord_gateway's on_ready_hook).
    Must work as a plain direct await, no cross-thread bridging needed."""
    this_loop = asyncio.get_running_loop()
    channel = _FakeChannel(expected_loop=this_loop)
    client = _FakeClient(loop=this_loop, channel=channel)

    adapter = DiscordHITLAdapter("discord_owner", {"channel_id": "123"})
    adapter.set_client(client)

    await adapter.send_hitl("task-2", "Proceed?", [])

    assert len(channel.sent) == 1


@pytest.mark.asyncio
async def test_send_hitl_without_bridge_reproduces_the_original_bug(background_loop):
    """Sanity check that the test harness actually reproduces the original
    failure when the bridge is bypassed -- proves this isn't a vacuously
    passing test."""
    channel = _FakeChannel(expected_loop=background_loop)

    with pytest.raises(RuntimeError, match="Timeout context manager"):
        await channel.send(embed="anything")
