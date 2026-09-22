"""Unit tests for the project_* tools on CapabilityRegistry.

These expose app/scheduler/project_tracker.py to roles as real tool calls
(project_list/project_create/project_add_item/project_update_item_status)
instead of requiring bash_exec + ad-hoc python, so any role with the
"orchestration" category can build/maintain a Project Checklist directly.

No existing test_capability_registry.py exists yet -- this file is scoped
to just the new project_* tools, not full CapabilityRegistry coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from app.scheduler.capability_registry import CapabilityRegistry
from app.scheduler import project_tracker as pt


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pt, "get_memory_subpath",
        lambda *parts: str(tmp_path.joinpath(*parts)),
    )


@pytest.fixture
def registry():
    return CapabilityRegistry()


class TestToolsRegistered:
    def test_all_four_tools_present_with_orchestration_category(self, registry):
        for name in ("project_list", "project_create", "project_add_item", "project_update_item_status"):
            tool = registry.get_tool(name)
            assert tool is not None, f"{name} not registered"
            assert tool.category == "orchestration"


class TestProjectCreate:
    @pytest.mark.asyncio
    async def test_create_succeeds(self, registry):
        result = await registry.execute_tool("project_create", {
            "project_id": "p1", "name": "Test", "goal": "Ship it", "owner_role_id": "paul",
        })
        assert result["success"] is True
        assert result["project"]["id"] == "p1"
        assert result["project"]["owner_role_id"] == "paul"

    @pytest.mark.asyncio
    async def test_create_missing_required_field_fails(self, registry):
        result = await registry.execute_tool("project_create", {"project_id": "p1", "name": "Test"})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_duplicate_create_fails(self, registry):
        await registry.execute_tool("project_create", {"project_id": "p1", "name": "Test", "goal": "g"})
        result = await registry.execute_tool("project_create", {"project_id": "p1", "name": "Test2", "goal": "g2"})
        assert result["success"] is False
        assert "already exists" in result["error"]


class TestProjectAddItem:
    @pytest.mark.asyncio
    async def test_add_item_succeeds(self, registry):
        await registry.execute_tool("project_create", {"project_id": "p1", "name": "Test", "goal": "g"})
        result = await registry.execute_tool("project_add_item", {
            "project_id": "p1", "item_id": "i1", "kind": "feature", "title": "Thing",
        })
        assert result["success"] is True
        assert len(result["project"]["items"]) == 1
        assert result["project"]["items"][0]["status"] == "todo"

    @pytest.mark.asyncio
    async def test_add_item_missing_project_fails(self, registry):
        result = await registry.execute_tool("project_add_item", {
            "project_id": "nope", "item_id": "i1", "kind": "feature", "title": "Thing",
        })
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_add_item_invalid_kind_fails(self, registry):
        await registry.execute_tool("project_create", {"project_id": "p1", "name": "Test", "goal": "g"})
        result = await registry.execute_tool("project_add_item", {
            "project_id": "p1", "item_id": "i1", "kind": "not-a-kind", "title": "Thing",
        })
        assert result["success"] is False


class TestProjectUpdateItemStatus:
    @pytest.mark.asyncio
    async def test_update_status_and_link_task(self, registry):
        await registry.execute_tool("project_create", {"project_id": "p1", "name": "Test", "goal": "g"})
        await registry.execute_tool("project_add_item", {
            "project_id": "p1", "item_id": "i1", "kind": "bug", "title": "Fix thing",
        })
        result = await registry.execute_tool("project_update_item_status", {
            "project_id": "p1", "item_id": "i1", "status": "done", "task_id": "t1",
        })
        assert result["success"] is True
        item = result["project"]["items"][0]
        assert item["status"] == "done"
        assert item["task_ids"] == ["t1"]

    @pytest.mark.asyncio
    async def test_update_missing_item_fails(self, registry):
        await registry.execute_tool("project_create", {"project_id": "p1", "name": "Test", "goal": "g"})
        result = await registry.execute_tool("project_update_item_status", {
            "project_id": "p1", "item_id": "nope", "status": "done",
        })
        assert result["success"] is False


class TestProjectList:
    @pytest.mark.asyncio
    async def test_list_empty(self, registry):
        result = await registry.execute_tool("project_list", {})
        assert result["success"] is True
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_list_returns_created_projects(self, registry):
        await registry.execute_tool("project_create", {"project_id": "p1", "name": "First", "goal": "g1"})
        await registry.execute_tool("project_create", {"project_id": "p2", "name": "Second", "goal": "g2"})
        result = await registry.execute_tool("project_list", {})
        assert result["success"] is True
        assert result["count"] == 2


class TestAvailableToolsGating:
    @pytest.mark.asyncio
    async def test_blocked_when_not_in_available_tools(self, registry):
        from app.scheduler.capability_registry import _cv_enabled_tools

        token = _cv_enabled_tools.set(["read_file"])  # project_create deliberately excluded
        try:
            result = await registry.execute_tool("project_create", {
                "project_id": "p1", "name": "Test", "goal": "g",
            })
            assert result["success"] is False
            assert "not in this task's available_tools list" in result["error"]
        finally:
            _cv_enabled_tools.reset(token)
