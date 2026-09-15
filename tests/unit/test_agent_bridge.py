"""Unit tests for the agent bridge — FastMCP tools backed by OpenCodeClient.

No network: OpenCodeClient calls are mocked at the HTTP layer. The bridge
git_bridge module registers tools on a FastMCP instance; we test the tool
functions by grabbing them off the registered server.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.mcp.agent_bridge.registry import HostRegistry
from app.mcp.agent_bridge.server import _extract_text


@pytest.fixture
def reg():
    return HostRegistry({
        "orgvm": {"base_url": "http://orgvm:4096", "password": "pw1"},
        "worker": {"base_url": "http://worker:4096", "password": "pw2"},
    })


@pytest.fixture
def tools(reg):
    """Register bridge tools against the fixture registry, return {name: fn}."""
    import app.mcp.agent_bridge.server as srv

    mcp, _ = srv._ensure(reg=reg)
    return {
        name: tool.fn
        for name, tool in mcp._tool_manager._tools.items()
    }


# ----------------------------------------------------------------------
# _extract_text
# ----------------------------------------------------------------------


def test_extract_text_joins_text_parts():
    msg = {"parts": [
        {"type": "text", "text": "hello"},
        {"type": "tool_call", "text": "ignored"},
        {"type": "text", "text": "world"},
    ]}
    assert _extract_text(msg) == "hello\nworld"


def test_extract_text_falls_back_to_flat_string():
    assert _extract_text("raw") == "raw"
    assert _extract_text({"text": "flat"}) == "flat"
    assert _extract_text({}) == "{}"


# ----------------------------------------------------------------------
# registry
# ----------------------------------------------------------------------


def test_registry_unknown_host_raises(reg):
    with pytest.raises(ValueError, match="worker2"):
        reg.get_client("worker2")


def test_registry_returns_same_client_for_host(reg):
    assert reg.get_client("orgvm") is reg.get_client("orgvm")


async def test_registry_close_all_clears(reg):
    reg.get_client("orgvm")
    await reg.close_all()
    assert reg._clients == {}


# ----------------------------------------------------------------------
# tools (OpenCodeClient mocked at the transport layer)
# ----------------------------------------------------------------------


async def test_agent_servers_reports_ok_and_unreachable(tools, reg):
    for name in ("orgvm", "worker"):
        c = reg.get_client(name)
        if name == "orgvm":
            c.health = AsyncMock(return_value={"status": "ok", "url": c._base_url})
        else:
            c.health = AsyncMock(side_effect=RuntimeError("connect refused"))

    out = await tools["agent_servers"]()
    assert out["orgvm"]["status"] == "ok"
    assert out["worker"]["status"] == "unreachable"


async def test_agent_status_includes_session(tools, reg):
    c = reg.get_client("orgvm")
    c.health = AsyncMock(return_value={"status": "ok", "url": c._base_url})
    c.get_session = AsyncMock(return_value={"id": "s1"})

    out = await tools["agent_status"]("orgvm", session_id="s1")
    assert out["session"]["id"] == "s1"


async def test_agent_run_creates_session_and_replies(tools, reg):
    c = reg.get_client("orgvm")
    c.create_session = AsyncMock(return_value={"id": "s-123"})
    c.send_message = AsyncMock(return_value={
        "parts": [{"type": "text", "text": "done the task"}],
    })

    out = await tools["agent_run"]("orgvm", "build the thing", working_dir="~/p")
    assert out["session_id"] == "s-123"
    assert out["reply"] == "done the task"
    c.create_session.assert_awaited_once_with(workingDir="~/p")
    c.send_message.assert_awaited_once_with("s-123", "build the thing")


async def test_agent_reply_continues_session(tools, reg):
    c = reg.get_client("orgvm")
    c.send_message = AsyncMock(return_value={"parts": [{"type": "text", "text": "ok"}]})
    out = await tools["agent_reply"]("orgvm", "s-123", "continue")
    assert out["session_id"] == "s-123"
    assert out["reply"] == "ok"


async def test_agent_sessions_lists(tools, reg):
    c = reg.get_client("orgvm")
    c.list_sessions = AsyncMock(return_value=[{"id": "s-1"}, {"id": "s-2"}])
    out = await tools["agent_sessions"]("orgvm")
    assert len(out) == 2


async def test_agent_close_session_deletes(tools, reg):
    c = reg.get_client("orgvm")
    c.delete_session = AsyncMock(return_value={"ok": True})
    out = await tools["agent_close_session"]("orgvm", "s-123")
    assert out["deleted"] == "s-123"
    c.delete_session.assert_awaited_once_with("s-123")