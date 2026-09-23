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
def mixed_reg():
    """Registry with one opencode_serve host (metadata included, per
    docs/specs/agent_workforce_dashboard_spec.md) and one legacy_mcp host
    (different wire protocol -- the pre-AgentBridge Express server, e.g.
    worker-legacy) for testing the fleet tools' backend dispatch."""
    return HostRegistry({
        "worker-gpu": {
            "base_url": "http://worker-gpu:4096", "password": "pw1",
            "location": {"region": "home", "provider": "self-hosted"},
            "profile": {"hardware_accel": ["amd-directml"], "capabilities": ["text", "graphics"]},
            "tier": {"type": "free", "backend": "self-hosted-local"},
        },
        "worker-legacy": {
            "base_url": "http://worker-legacy:4097/mcp", "backend": "legacy_mcp",
            "location": {"region": "home", "provider": "self-hosted"},
            "tier": {"type": "free", "backend": "self-hosted-local"},
        },
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


# ----------------------------------------------------------------------
# HostRegistry metadata (location/profile/tier/backend)
# ----------------------------------------------------------------------


def test_registry_describe_returns_metadata_without_password(mixed_reg):
    entry = mixed_reg.describe("worker-gpu")
    assert entry["name"] == "worker-gpu"
    assert entry["location"]["region"] == "home"
    assert entry["profile"]["hardware_accel"] == ["amd-directml"]
    assert "password" not in entry


def test_registry_backend_of_defaults_to_opencode_serve(mixed_reg):
    assert mixed_reg.backend_of("worker-gpu") == "opencode_serve"
    assert mixed_reg.backend_of("worker-legacy") == "legacy_mcp"


def test_registry_describe_all_covers_every_host(mixed_reg):
    all_hosts = mixed_reg.describe_all()
    assert set(all_hosts) == {"worker-gpu", "worker-legacy"}


# ----------------------------------------------------------------------
# Backend-dispatched availability (_check_legacy_mcp / _check_availability)
# ----------------------------------------------------------------------


async def test_check_legacy_mcp_reachable_on_200(monkeypatch):
    import app.mcp.agent_bridge.server as srv

    class _FakeResp:
        status_code = 200

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            return _FakeResp()

    monkeypatch.setattr(srv.httpx, "AsyncClient", lambda **kw: _FakeClient())
    result = await srv._check_legacy_mcp("http://worker-legacy:4097/mcp")
    assert result == {"status": "ok", "url": "http://worker-legacy:4097/mcp"}


async def test_check_legacy_mcp_unreachable_on_non_200(monkeypatch):
    import app.mcp.agent_bridge.server as srv

    class _FakeResp:
        status_code = 405

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            return _FakeResp()

    monkeypatch.setattr(srv.httpx, "AsyncClient", lambda **kw: _FakeClient())
    result = await srv._check_legacy_mcp("http://worker-legacy:4097/mcp")
    assert result["status"] == "unreachable"
    assert "405" in result["error"]


async def test_check_legacy_mcp_unreachable_on_connection_error(monkeypatch):
    import app.mcp.agent_bridge.server as srv

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            raise ConnectionError("refused")

    monkeypatch.setattr(srv.httpx, "AsyncClient", lambda **kw: _FakeClient())
    result = await srv._check_legacy_mcp("http://worker-legacy:4097/mcp")
    assert result["status"] == "unreachable"
    assert "refused" in result["error"]


# ----------------------------------------------------------------------
# agent_fleet / agent_fleet_summary — the "virtual 3rd agent" dashboard
# ----------------------------------------------------------------------


@pytest.fixture
def mixed_tools(mixed_reg):
    import app.mcp.agent_bridge.server as srv

    mcp, _ = srv._ensure(reg=mixed_reg)
    return {name: tool.fn for name, tool in mcp._tool_manager._tools.items()}


async def test_agent_fleet_merges_metadata_and_live_availability(mixed_tools, mixed_reg, monkeypatch):
    import app.mcp.agent_bridge.server as srv

    c = mixed_reg.get_client("worker-gpu")
    c.health = AsyncMock(return_value={"status": "ok", "url": c._base_url})
    c.list_sessions = AsyncMock(return_value=[{"id": "s-1"}])
    monkeypatch.setattr(srv, "_check_legacy_mcp", AsyncMock(
        return_value={"status": "ok", "url": "http://worker-legacy:4097/mcp"}
    ))

    fleet = await mixed_tools["agent_fleet"]()

    assert fleet["worker-gpu"]["availability"]["status"] == "ok"
    assert fleet["worker-gpu"]["session_count"] == 1
    assert fleet["worker-gpu"]["location"]["region"] == "home"

    # The legacy_mcp host must appear in the SAME fleet with a real status,
    # not silently dropped or falsely marked unreachable just because it
    # doesn't speak the opencode REST API.
    assert fleet["worker-legacy"]["availability"]["status"] == "ok"
    assert fleet["worker-legacy"]["session_count"] is None  # unknown, never guessed as 0


async def test_agent_fleet_legacy_host_unreachable_does_not_break_others(mixed_tools, mixed_reg, monkeypatch):
    import app.mcp.agent_bridge.server as srv

    c = mixed_reg.get_client("worker-gpu")
    c.health = AsyncMock(return_value={"status": "ok", "url": c._base_url})
    c.list_sessions = AsyncMock(return_value=[])
    monkeypatch.setattr(srv, "_check_legacy_mcp", AsyncMock(
        return_value={"status": "unreachable", "url": "http://worker-legacy:4097/mcp", "error": "timeout"}
    ))

    fleet = await mixed_tools["agent_fleet"]()

    assert fleet["worker-gpu"]["availability"]["status"] == "ok"
    assert fleet["worker-legacy"]["availability"]["status"] == "unreachable"


async def test_agent_fleet_summary_groups_by_region_and_tier(mixed_tools, mixed_reg, monkeypatch):
    import app.mcp.agent_bridge.server as srv

    c = mixed_reg.get_client("worker-gpu")
    c.health = AsyncMock(return_value={"status": "ok", "url": c._base_url})
    c.list_sessions = AsyncMock(return_value=[{"id": "s-1"}, {"id": "s-2"}])
    monkeypatch.setattr(srv, "_check_legacy_mcp", AsyncMock(
        return_value={"status": "ok", "url": "http://worker-legacy:4097/mcp"}
    ))

    summary = await mixed_tools["agent_fleet_summary"]()

    key = "home/free"
    assert key in summary
    assert set(summary[key]["hosts"]) == {"worker-gpu", "worker-legacy"}
    assert summary[key]["hosts_ok"] == 2
    # worker-legacy's session_count is None (unknown), must not count as 0
    # sessions in a way that hides worker-gpu's real count -- total should be
    # exactly worker-gpu's 2, not miscounted.
    assert summary[key]["total_sessions"] == 2


# ----------------------------------------------------------------------
# agent_sessions_unified — merged opencode + herdr session view
# ----------------------------------------------------------------------


@pytest.fixture
def unified_reg():
    """Registry shaped for agent_sessions_unified: an opencode_serve host
    with an 'ssh' key (herdr reachable) and a legacy_mcp host without one."""
    return HostRegistry({
        "worker-gpu": {
            "base_url": "http://worker-gpu:4096", "password": "pw1",
            "ssh": "ops@worker-gpu",
            "location": {"region": "home", "provider": "self-hosted"},
            "tier": {"type": "free", "backend": "self-hosted-local"},
        },
        "worker-legacy": {
            "base_url": "http://worker-legacy:4097/mcp", "backend": "legacy_mcp",
        },
    })


@pytest.fixture
def unified_tools(unified_reg):
    import app.mcp.agent_bridge.server as srv

    mcp, _ = srv._ensure(reg=unified_reg)
    return {name: tool.fn for name, tool in mcp._tool_manager._tools.items()}


async def test_agent_sessions_unified_merges_mcp_and_herdr(unified_tools, unified_reg, monkeypatch):
    import app.mcp.agent_bridge.server as srv

    c = unified_reg.get_client("worker-gpu")
    c.list_sessions = AsyncMock(return_value=[
        {"id": "ses_a", "info": {"title": "bugfix review", "time": {"created": 2000}}},
    ])
    monkeypatch.setattr(srv, "list_remote_agents", AsyncMock(return_value={
        "ok": True,
        "agents": [
            {"name": "rev1", "pane": "w1:p1", "state": "working", "time": {"created": 3000}},
            {"name": "rev2", "pane": "w1:p2", "state": "idle"},
        ],
        "ssh_target": "ops@worker-gpu",
    }))

    out = await unified_tools["agent_sessions_unified"]()

    gpu = out["worker-gpu"]
    assert gpu["counts"] == {"mcp": 1, "scheduler": 0, "human": 2}
    # time-descending, herdr agent without a timestamp sorts last
    assert [s["id"] for s in gpu["sessions"]] == ["w1:p1", "ses_a", "w1:p2"]
    assert gpu["sessions"][0]["origin"] == "human"
    assert gpu["sessions"][0]["state"] == "working"
    assert gpu["sessions"][1]["origin"] == "mcp"

    legacy = out["worker-legacy"]
    assert legacy["counts"] == {"mcp": 0, "scheduler": 0, "human": 0}
    assert any("legacy_mcp" in n for n in legacy["notes"])


async def test_agent_sessions_unified_scheduler_heuristic(unified_tools, unified_reg, monkeypatch):
    c = unified_reg.get_client("worker-gpu")
    c.list_sessions = AsyncMock(return_value=[
        {"id": "ses_plain", "info": {"title": "chat about docs", "time": {"created": 3}}},
        {"id": "ses_task", "info": {"title": "task_77 nightly build", "time": {"created": 2}}},
        {"id": "ses_logs", "info": {"title": None}, "directory": "/home/u/.memory/task_logs/t9", "time": {"created": 1}},
    ])

    out = await unified_tools["agent_sessions_unified"]("worker-gpu")

    origins = {s["id"]: s["origin"] for s in out["sessions"]}
    assert origins == {
        "ses_plain": "mcp",
        "ses_task": "scheduler",
        "ses_logs": "scheduler",
    }


async def test_agent_sessions_unified_legacy_host_skips_mcp_side(unified_tools, unified_reg):
    c = unified_reg.get_client("worker-legacy")
    c.list_sessions = AsyncMock(side_effect=AssertionError("must not be called for legacy_mcp"))

    out = await unified_tools["agent_sessions_unified"]("worker-legacy")

    assert out["counts"] == {"mcp": 0, "scheduler": 0, "human": 0}
    assert any("legacy_mcp" in n for n in out["notes"])
    assert any("herdr target not configured" in n for n in out["notes"])
    c.list_sessions.assert_not_awaited()


async def test_agent_sessions_unified_unknown_host_error(unified_tools):
    out = await unified_tools["agent_sessions_unified"]("nope")
    assert "error" in out
    assert "nope" in out["error"]


async def test_agent_sessions_unified_single_host_mode(unified_tools, unified_reg, monkeypatch):
    import app.mcp.agent_bridge.server as srv

    c = unified_reg.get_client("worker-gpu")
    c.list_sessions = AsyncMock(return_value=[{"id": "s1", "info": {"title": "t", "time": {"created": 5}}}])
    monkeypatch.setattr(srv, "list_remote_agents", AsyncMock(return_value={
        "ok": True, "agents": [], "ssh_target": "ops@worker-gpu",
    }))

    out = await unified_tools["agent_sessions_unified"]("worker-gpu")

    # single-host mode returns the host's result directly, not {host: result}
    assert set(out) == {"sessions", "counts", "notes"}
    assert out["counts"] == {"mcp": 1, "scheduler": 0, "human": 0}


async def test_agent_sessions_unified_herdr_failure_degrades(unified_tools, unified_reg, monkeypatch):
    import app.mcp.agent_bridge.server as srv

    c = unified_reg.get_client("worker-gpu")
    c.list_sessions = AsyncMock(return_value=[
        {"id": "s1", "info": {"title": "still visible", "time": {"created": 5}}},
    ])
    monkeypatch.setattr(srv, "list_remote_agents", AsyncMock(return_value={
        "ok": False, "kind": "server_error", "error": "ssh: connect refused",
    }))

    out = await unified_tools["agent_sessions_unified"]("worker-gpu")

    # herdr being down must not blank the MCP-side sessions
    assert out["counts"] == {"mcp": 1, "scheduler": 0, "human": 0}
    assert any("herdr unavailable (server_error)" in n for n in out["notes"])