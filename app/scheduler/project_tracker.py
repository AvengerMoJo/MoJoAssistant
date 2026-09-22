"""
Project Tracker — persistent checklist for ongoing, multi-feature work.

A Task (app/scheduler/models.py) is a bounded, one-shot deliverable closed
out by its own "Done when:" clause and watched for liveness by Quality
Monitor. Not all work fits that shape: a dashboard feature, a module
rewrite, an ongoing integration has multiple features/bugs/updates that
land over separate tasks and PRs across days or weeks, with no single
"Done when:" that closes the whole thing.

A Project is that unit. It does not replace Task — any Task may optionally
carry a project_id (see Task.project_id) to roll its work up into one of
these. This module owns the Project's own persistent state (its checklist)
and is deliberately as dumb as Quality Monitor: plain reads/writes, no LLM
judgment. Deciding whether a piece of work is "a task" or "a project", and
deciding when a checklist item's status should change, is a judgment call
made by whichever role/agent is doing the work — this module only stores
what they decide.

Storage: one JSON file per project at ~/.memory/projects/<project_id>.json.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config.paths import get_memory_subpath

ItemKind = str  # "feature" | "bug" | "update"
ItemStatus = str  # "todo" | "in_progress" | "done" | "blocked"
ProjectStatus = str  # "active" | "blocked" | "completed" | "archived"

VALID_ITEM_KINDS = {"feature", "bug", "update"}
VALID_ITEM_STATUSES = {"todo", "in_progress", "done", "blocked"}
VALID_PROJECT_STATUSES = {"active", "blocked", "completed", "archived"}


@dataclass
class ChecklistItem:
    id: str
    kind: ItemKind
    title: str
    status: ItemStatus = "todo"
    notes: Optional[str] = None
    task_ids: List[str] = field(default_factory=list)  # Task.id values rolled up here
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChecklistItem":
        return cls(**data)


@dataclass
class Project:
    id: str
    name: str
    goal: str  # what "done" looks like for the project as a whole
    status: ProjectStatus = "active"
    items: List[ChecklistItem] = field(default_factory=list)
    owner_role_id: Optional[str] = None  # e.g. "paul" — who's accountable for gaps found here
    # Shared resource any role/agent dispatched under this project_id should work in --
    # {"git_url": ..., "project_label": "opencode+..."} for a git-repo-shaped project.
    # None means this project has no linked coding-agent workspace (e.g. pure research/
    # tracking work) -- dispatch falls back to whatever the dispatcher specifies directly.
    workspace: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["items"] = [item.to_dict() for item in self.items]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Project":
        items = [ChecklistItem.from_dict(i) for i in data.get("items", [])]
        rest = {k: v for k, v in data.items() if k != "items"}
        return cls(items=items, **rest)


def _project_path(project_id: str) -> Path:
    return Path(get_memory_subpath("projects", f"{project_id}.json"))


def load_project(project_id: str) -> Optional[Project]:
    path = _project_path(project_id)
    if not path.exists():
        return None
    with open(path) as f:
        return Project.from_dict(json.load(f))


def save_project(project: Project) -> None:
    """Write, then read back and confirm it parses — per BRIDLE, no silent
    partial writes on structured state."""
    project.updated_at = datetime.now().isoformat()
    path = _project_path(project.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(project.to_dict(), f, indent=2)
    tmp_path.replace(path)

    with open(path) as f:
        readback = json.load(f)
    assert readback["id"] == project.id, (
        f"project_tracker: readback verification failed for {project.id} "
        f"— wrote id={project.id!r}, read back id={readback.get('id')!r}"
    )


def list_projects() -> List[Project]:
    projects_dir = Path(get_memory_subpath("projects"))
    if not projects_dir.exists():
        return []
    out = []
    for path in sorted(projects_dir.glob("*.json")):
        with open(path) as f:
            out.append(Project.from_dict(json.load(f)))
    return out


def create_project(
    project_id: str,
    name: str,
    goal: str,
    owner_role_id: Optional[str] = None,
) -> Project:
    if load_project(project_id) is not None:
        raise ValueError(f"project_tracker: project {project_id!r} already exists")
    project = Project(id=project_id, name=name, goal=goal, owner_role_id=owner_role_id)
    save_project(project)
    return project


def add_item(
    project_id: str,
    item_id: str,
    kind: ItemKind,
    title: str,
    status: ItemStatus = "todo",
    notes: Optional[str] = None,
) -> Project:
    if kind not in VALID_ITEM_KINDS:
        raise ValueError(f"project_tracker: invalid kind {kind!r}, must be one of {VALID_ITEM_KINDS}")
    if status not in VALID_ITEM_STATUSES:
        raise ValueError(f"project_tracker: invalid status {status!r}, must be one of {VALID_ITEM_STATUSES}")
    project = load_project(project_id)
    if project is None:
        raise ValueError(f"project_tracker: project {project_id!r} not found")
    if any(i.id == item_id for i in project.items):
        raise ValueError(f"project_tracker: item {item_id!r} already exists on project {project_id!r}")
    project.items.append(ChecklistItem(id=item_id, kind=kind, title=title, status=status, notes=notes))
    save_project(project)
    return project


def set_workspace(
    project_id: str,
    git_url: str,
    project_label: str,
) -> Project:
    """Link a project to the shared coding-agent workspace any role/agent
    dispatched under this project_id should resolve into. Does not bootstrap
    the backend itself -- callers should confirm it's reachable (or bootstrap
    it) separately before relying on auto-resolution working."""
    project = load_project(project_id)
    if project is None:
        raise ValueError(f"project_tracker: project {project_id!r} not found")
    project.workspace = {"git_url": git_url, "project_label": project_label}
    save_project(project)
    return project


def update_item_status(
    project_id: str,
    item_id: str,
    status: ItemStatus,
    notes: Optional[str] = None,
    task_id: Optional[str] = None,
) -> Project:
    if status not in VALID_ITEM_STATUSES:
        raise ValueError(f"project_tracker: invalid status {status!r}, must be one of {VALID_ITEM_STATUSES}")
    project = load_project(project_id)
    if project is None:
        raise ValueError(f"project_tracker: project {project_id!r} not found")
    for item in project.items:
        if item.id == item_id:
            item.status = status
            item.updated_at = datetime.now().isoformat()
            if notes is not None:
                item.notes = notes
            if task_id is not None and task_id not in item.task_ids:
                item.task_ids.append(task_id)
            save_project(project)
            return project
    raise ValueError(f"project_tracker: item {item_id!r} not found on project {project_id!r}")
