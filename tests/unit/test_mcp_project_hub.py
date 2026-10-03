"""Unit tests for the "project" hub tool on app/mcp/core/tools.py's ToolRegistry.

This is the externally-reachable twin of CapabilityRegistry's project_* tools
(tests/unit/test_capability_registry_project_tools.py) — same underlying
app/scheduler/project_tracker.py implementation, but exposed on the MCP
engine's own tool catalog so any MCP client (not just a role dispatched
inside this scheduler's own loop) can reach it. Verifies the hub dispatches
to the same project_tracker functions and produces consistent results.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from app.scheduler import project_tracker as pt


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pt, "get_memory_subpath",
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


class TestProjectHubHelp:
    @pytest.mark.asyncio
    async def test_no_action_returns_help(self, registry):
        result = await registry.execute("project", {})
        assert result["tool"] == "project"
        assert "list" in result["actions"]

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error_with_help(self, registry):
        result = await registry.execute("project", {"action": "not-a-real-action"})
        assert "error" in result
        assert result["tool"] == "project"


class TestProjectHubCreateAndList:
    @pytest.mark.asyncio
    async def test_create_then_list(self, registry):
        created = await registry.execute("project", {
            "action": "create", "project_id": "p1", "name": "Test", "goal": "Ship it",
            "owner_role_id": "paul",
        })
        assert created["id"] == "p1"
        assert created["owner_role_id"] == "paul"

        listed = await registry.execute("project", {"action": "list"})
        assert len(listed["projects"]) == 1
        assert listed["projects"][0]["id"] == "p1"

    @pytest.mark.asyncio
    async def test_create_missing_field_errors(self, registry):
        result = await registry.execute("project", {"action": "create", "project_id": "p1"})
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_duplicate_create_errors(self, registry):
        await registry.execute("project", {"action": "create", "project_id": "p1", "name": "A", "goal": "g"})
        result = await registry.execute("project", {"action": "create", "project_id": "p1", "name": "B", "goal": "g2"})
        assert result["status"] == "error"
        assert "already exists" in result["message"]


class TestProjectHubListIsCompact:
    """2026-10-03: project(action='list') returning full to_dict() per
    project (every item, every note) hit 96-109K chars with just 10 real
    projects, contributing to a calling task choking its own context and
    timing out. list must stay compact; use 'get' for full detail."""

    @pytest.mark.asyncio
    async def test_list_omits_items_and_goal(self, registry):
        await registry.execute("project", {"action": "create", "project_id": "p1", "name": "Test", "goal": "A" * 5000})
        for i in range(20):
            await registry.execute("project", {
                "action": "add_item", "project_id": "p1", "item_id": f"i{i}",
                "kind": "feature", "title": "Thing", "notes": "x" * 2000,
            })
        result = await registry.execute("project", {"action": "list"})
        row = result["projects"][0]
        assert "items" not in row
        assert "goal" not in row
        assert row["items_done"] == "0/20"

    @pytest.mark.asyncio
    async def test_list_includes_current_state_for_quick_scanning(self, registry):
        await registry.execute("project", {"action": "create", "project_id": "p1", "name": "Test", "goal": "g"})
        await registry.execute("project", {"action": "set_current_state", "project_id": "p1", "current_state": "on track"})
        result = await registry.execute("project", {"action": "list"})
        assert result["projects"][0]["current_state"] == "on track"

    @pytest.mark.asyncio
    async def test_get_still_returns_full_detail(self, registry):
        await registry.execute("project", {"action": "create", "project_id": "p1", "name": "Test", "goal": "g"})
        await registry.execute("project", {
            "action": "add_item", "project_id": "p1", "item_id": "i1",
            "kind": "feature", "title": "Thing", "notes": "detail",
        })
        result = await registry.execute("project", {"action": "get", "project_id": "p1"})
        assert result["items"][0]["notes"] == "detail"


class TestProjectHubGet:
    @pytest.mark.asyncio
    async def test_get_returns_full_project(self, registry):
        await registry.execute("project", {"action": "create", "project_id": "p1", "name": "Test", "goal": "g"})
        await registry.execute("project", {
            "action": "add_item", "project_id": "p1", "item_id": "i1", "kind": "feature", "title": "Thing",
        })
        result = await registry.execute("project", {"action": "get", "project_id": "p1"})
        assert result["id"] == "p1"
        assert len(result["items"]) == 1
        assert result["items"][0]["id"] == "i1"

    @pytest.mark.asyncio
    async def test_get_missing_project_errors(self, registry):
        result = await registry.execute("project", {"action": "get", "project_id": "nope"})
        assert result["status"] == "error"


class TestProjectHubCurrentState:
    @pytest.mark.asyncio
    async def test_set_current_state_round_trips_through_get(self, registry):
        await registry.execute("project", {"action": "create", "project_id": "p1", "name": "Test", "goal": "g"})
        result = await registry.execute("project", {
            "action": "set_current_state", "project_id": "p1",
            "current_state": "Local+API resources tracked; vault wiring not started.",
        })
        assert result["current_state"] == "Local+API resources tracked; vault wiring not started."

        fetched = await registry.execute("project", {"action": "get", "project_id": "p1"})
        assert fetched["current_state"] == "Local+API resources tracked; vault wiring not started."

    @pytest.mark.asyncio
    async def test_set_current_state_missing_project_errors(self, registry):
        result = await registry.execute("project", {
            "action": "set_current_state", "project_id": "nope", "current_state": "x",
        })
        assert result["status"] == "error"


class TestProjectHubAddItemAndUpdateStatus:
    @pytest.mark.asyncio
    async def test_add_item_then_update_status(self, registry):
        await registry.execute("project", {"action": "create", "project_id": "p1", "name": "Test", "goal": "g"})
        await registry.execute("project", {
            "action": "add_item", "project_id": "p1", "item_id": "i1", "kind": "bug", "title": "Fix thing",
        })
        result = await registry.execute("project", {
            "action": "update_item_status", "project_id": "p1", "item_id": "i1",
            "status": "done", "task_id": "t1",
        })
        item = result["items"][0]
        assert item["status"] == "done"
        assert item["task_ids"] == ["t1"]


class TestProjectHubMatchesDirectProjectTracker:
    """The hub must be a thin wrapper, not a second implementation — prove
    it produces the same state as calling project_tracker.py directly."""

    @pytest.mark.asyncio
    async def test_hub_create_visible_to_direct_load(self, registry):
        await registry.execute("project", {"action": "create", "project_id": "p1", "name": "Test", "goal": "g"})
        direct = pt.load_project("p1")
        assert direct is not None
        assert direct.name == "Test"

    @pytest.mark.asyncio
    async def test_direct_create_visible_to_hub_get(self, registry):
        pt.create_project("p1", "Direct", "g")
        result = await registry.execute("project", {"action": "get", "project_id": "p1"})
        assert result["name"] == "Direct"
