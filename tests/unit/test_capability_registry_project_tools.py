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
    def test_all_tools_present_with_orchestration_category(self, registry):
        for name in ("project_list", "project_create", "project_add_item",
                     "project_update_item_status", "project_set_workspace"):
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


class TestProjectSetWorkspace:
    @pytest.mark.asyncio
    async def test_set_workspace_succeeds(self, registry):
        await registry.execute_tool("project_create", {"project_id": "p1", "name": "Test", "goal": "g"})
        result = await registry.execute_tool("project_set_workspace", {
            "project_id": "p1",
            "git_url": "git@github.com:Org/repo.git",
            "project_label": "opencode+repo",
        })
        assert result["success"] is True
        assert result["project"]["workspace"] == {
            "git_url": "git@github.com:Org/repo.git", "project_label": "opencode+repo",
        }

    @pytest.mark.asyncio
    async def test_set_workspace_missing_project_fails(self, registry):
        result = await registry.execute_tool("project_set_workspace", {
            "project_id": "nope", "git_url": "git@github.com:Org/repo.git", "project_label": "opencode+repo",
        })
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_set_workspace_missing_field_fails(self, registry):
        await registry.execute_tool("project_create", {"project_id": "p1", "name": "Test", "goal": "g"})
        result = await registry.execute_tool("project_set_workspace", {"project_id": "p1", "git_url": "x"})
        assert result["success"] is False


class TestDispatchSubtaskProjectIdAutoResolve:
    """dispatch_subtask(project_id=...) must auto-fill project_label/git_url
    from the project's linked workspace, so a dispatcher doesn't have to
    guess a server_id -- guessing wrong is exactly what caused the
    A/B-test/28eb4899 backend-not-found failures (2026-09-22)."""

    @pytest.fixture
    def fake_scheduler(self, monkeypatch):
        from app.scheduler.models import Task, TaskResult, TaskStatus
        import app.scheduler.capability_registry as cr

        monkeypatch.setattr(cr.CapabilityRegistry, "DISPATCH_POLL_INTERVAL_S", 0.001)

        class FakeScheduler:
            def __init__(self):
                self.added_task = None

            def add_task(self, task):
                self.added_task = task
                return True

            def get_task(self, task_id):
                t = self.added_task
                t.status = TaskStatus.COMPLETED
                t.result = TaskResult(success=True, metrics={"final_answer": "done"})
                return t

        return FakeScheduler()

    @pytest.mark.asyncio
    async def test_project_id_fills_label_and_git_url_from_workspace(self, registry, fake_scheduler):
        await registry.execute_tool("project_create", {"project_id": "p1", "name": "Test", "goal": "g"})
        await registry.execute_tool("project_set_workspace", {
            "project_id": "p1",
            "git_url": "git@github.com:Org/repo.git",
            "project_label": "opencode+repo",
        })
        registry._scheduler = fake_scheduler

        result = await registry.execute_tool("dispatch_subtask", {
            "role_id": "popo", "goal": "do the thing please", "force": True, "project_id": "p1",
        })

        assert result["success"] is True
        task = fake_scheduler.added_task
        assert task.config["project_label"] == "opencode+repo"
        assert task.config["git_url"] == "git@github.com:Org/repo.git"
        assert task.project_id == "p1"

    @pytest.mark.asyncio
    async def test_explicit_project_label_wins_over_project_id(self, registry, fake_scheduler):
        await registry.execute_tool("project_create", {"project_id": "p1", "name": "Test", "goal": "g"})
        await registry.execute_tool("project_set_workspace", {
            "project_id": "p1",
            "git_url": "git@github.com:Org/repo.git",
            "project_label": "opencode+repo",
        })
        registry._scheduler = fake_scheduler

        result = await registry.execute_tool("dispatch_subtask", {
            "role_id": "popo", "goal": "do the thing please", "force": True,
            "project_id": "p1", "project_label": "opencode+different",
        })

        assert result["success"] is True
        assert fake_scheduler.added_task.config["project_label"] == "opencode+different"

    @pytest.mark.asyncio
    async def test_project_id_without_workspace_leaves_label_unset(self, registry, fake_scheduler):
        await registry.execute_tool("project_create", {"project_id": "p1", "name": "Test", "goal": "g"})
        registry._scheduler = fake_scheduler

        result = await registry.execute_tool("dispatch_subtask", {
            "role_id": "popo", "goal": "do the thing please", "force": True, "project_id": "p1",
        })

        assert result["success"] is True
        assert "project_label" not in fake_scheduler.added_task.config
        assert fake_scheduler.added_task.project_id == "p1"

    @pytest.mark.asyncio
    async def test_unknown_project_id_does_not_crash(self, registry, fake_scheduler):
        registry._scheduler = fake_scheduler

        result = await registry.execute_tool("dispatch_subtask", {
            "role_id": "popo", "goal": "do the thing please", "force": True, "project_id": "does-not-exist",
        })

        assert result["success"] is True
        assert "project_label" not in fake_scheduler.added_task.config


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
