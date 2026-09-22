"""Unit tests for the Project Tracker checklist store.

No live network calls -- pure filesystem, redirected to tmp_path via
monkeypatching get_memory_subpath the same way test_quality_monitor.py does.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from app.scheduler import project_tracker as pt


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pt, "get_memory_subpath",
        lambda *parts: str(tmp_path.joinpath(*parts)),
    )


class TestCreateProject:
    def test_create_and_load_roundtrips(self):
        pt.create_project("proj1", "Test Project", "Ship the thing", owner_role_id="paul")
        loaded = pt.load_project("proj1")
        assert loaded is not None
        assert loaded.name == "Test Project"
        assert loaded.goal == "Ship the thing"
        assert loaded.owner_role_id == "paul"
        assert loaded.status == "active"
        assert loaded.items == []

    def test_create_duplicate_raises(self):
        pt.create_project("proj1", "Test", "Goal")
        with pytest.raises(ValueError, match="already exists"):
            pt.create_project("proj1", "Test", "Goal")

    def test_load_missing_returns_none(self):
        assert pt.load_project("does-not-exist") is None


class TestAddItem:
    def test_add_item_appears_on_project(self):
        pt.create_project("proj1", "Test", "Goal")
        project = pt.add_item("proj1", "item1", "feature", "Add dashboard page")
        assert len(project.items) == 1
        assert project.items[0].id == "item1"
        assert project.items[0].kind == "feature"
        assert project.items[0].status == "todo"

    def test_add_item_invalid_kind_raises(self):
        pt.create_project("proj1", "Test", "Goal")
        with pytest.raises(ValueError, match="invalid kind"):
            pt.add_item("proj1", "item1", "not-a-kind", "Title")

    def test_add_duplicate_item_id_raises(self):
        pt.create_project("proj1", "Test", "Goal")
        pt.add_item("proj1", "item1", "bug", "Fix thing")
        with pytest.raises(ValueError, match="already exists"):
            pt.add_item("proj1", "item1", "bug", "Fix thing again")

    def test_add_item_missing_project_raises(self):
        with pytest.raises(ValueError, match="not found"):
            pt.add_item("nope", "item1", "feature", "Title")


class TestUpdateItemStatus:
    def test_update_status_persists(self):
        pt.create_project("proj1", "Test", "Goal")
        pt.add_item("proj1", "item1", "feature", "Add dashboard page")
        project = pt.update_item_status("proj1", "item1", "done", task_id="task-123")
        assert project.items[0].status == "done"
        assert project.items[0].task_ids == ["task-123"]

        reloaded = pt.load_project("proj1")
        assert reloaded.items[0].status == "done"
        assert reloaded.items[0].task_ids == ["task-123"]

    def test_update_invalid_status_raises(self):
        pt.create_project("proj1", "Test", "Goal")
        pt.add_item("proj1", "item1", "feature", "Title")
        with pytest.raises(ValueError, match="invalid status"):
            pt.update_item_status("proj1", "item1", "not-a-status")

    def test_update_missing_item_raises(self):
        pt.create_project("proj1", "Test", "Goal")
        with pytest.raises(ValueError, match="not found"):
            pt.update_item_status("proj1", "no-such-item", "done")

    def test_multiple_task_ids_accumulate(self):
        pt.create_project("proj1", "Test", "Goal")
        pt.add_item("proj1", "item1", "feature", "Title")
        pt.update_item_status("proj1", "item1", "in_progress", task_id="task-1")
        project = pt.update_item_status("proj1", "item1", "done", task_id="task-2")
        assert project.items[0].task_ids == ["task-1", "task-2"]


class TestWorkspace:
    def test_new_project_has_no_workspace(self):
        pt.create_project("proj1", "Test", "Goal")
        assert pt.load_project("proj1").workspace is None

    def test_set_workspace_persists(self):
        pt.create_project("proj1", "Test", "Goal")
        project = pt.set_workspace("proj1", "git@github.com:Org/repo.git", "opencode+repo")
        assert project.workspace == {"git_url": "git@github.com:Org/repo.git", "project_label": "opencode+repo"}

        reloaded = pt.load_project("proj1")
        assert reloaded.workspace == {"git_url": "git@github.com:Org/repo.git", "project_label": "opencode+repo"}

    def test_set_workspace_missing_project_raises(self):
        with pytest.raises(ValueError, match="not found"):
            pt.set_workspace("nope", "git@github.com:Org/repo.git", "opencode+repo")

    def test_set_workspace_overwrites_existing(self):
        pt.create_project("proj1", "Test", "Goal")
        pt.set_workspace("proj1", "git@github.com:Org/repo.git", "opencode+repo")
        project = pt.set_workspace("proj1", "git@github.com:Org/repo2.git", "opencode+repo2")
        assert project.workspace["git_url"] == "git@github.com:Org/repo2.git"

    def test_loads_pre_workspace_project_dict_without_error(self):
        """Project dicts written before this field existed (the 5 real
        projects created 2026-09-22) must still load cleanly."""
        old_style = {
            "id": "legacy", "name": "Legacy", "goal": "Goal",
            "status": "active", "items": [], "owner_role_id": None,
            "created_at": "2026-09-22T00:00:00", "updated_at": "2026-09-22T00:00:00",
        }
        project = pt.Project.from_dict(old_style)
        assert project.workspace is None


class TestListProjects:
    def test_list_empty_when_no_projects(self):
        assert pt.list_projects() == []

    def test_list_returns_all_created(self):
        pt.create_project("proj1", "First", "Goal 1")
        pt.create_project("proj2", "Second", "Goal 2")
        names = sorted(p.name for p in pt.list_projects())
        assert names == ["First", "Second"]


class TestTaskProjectIdField:
    def test_task_defaults_project_id_none(self):
        from app.scheduler.models import Task, TaskType

        task = Task(id="t1", type=TaskType.INTERNAL_ASSIGNMENT)
        assert task.project_id is None

    def test_task_roundtrips_project_id(self):
        from app.scheduler.models import Task, TaskType

        task = Task(id="t1", type=TaskType.INTERNAL_ASSIGNMENT, project_id="proj1")
        data = task.to_dict()
        assert data["project_id"] == "proj1"
        restored = Task.from_dict(data)
        assert restored.project_id == "proj1"

    def test_task_from_dict_tolerates_missing_project_id(self):
        from app.scheduler.models import Task, TaskType

        task = Task(id="t1", type=TaskType.INTERNAL_ASSIGNMENT)
        data = task.to_dict()
        del data["project_id"]
        restored = Task.from_dict(data)
        assert restored.project_id is None
