"""Unit tests for the dashboard's /dashboard/projects page.

Renders the Project Checklist tracked by app/scheduler/project_tracker.py --
ongoing, multi-feature work distinct from a single bounded scheduler Task,
audited nightly by the project_sentinel role.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dashboard import router as dashboard_router
from app.scheduler import project_tracker as pt


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(dashboard_router, "verify_token", lambda token: True)
    app = FastAPI()
    app.include_router(dashboard_router.router)
    return TestClient(app, cookies={"mojo_dash": "anything"})


@pytest.fixture(autouse=True)
def _isolate_project_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pt, "get_memory_subpath",
        lambda *parts: str(tmp_path.joinpath(*parts)),
    )


def test_projects_page_empty_state(client):
    resp = client.get("/dashboard/projects")
    assert resp.status_code == 200
    assert "No projects tracked yet" in resp.text


def test_projects_page_shows_project_and_items(client):
    pt.create_project("dash_v2", "Agent Workforce Dashboard v2", "Ship the fleet view", owner_role_id="paul")
    pt.add_item("dash_v2", "feat_fleet", "feature", "Fleet status page", status="done")
    pt.add_item("dash_v2", "bug_timeout", "bug", "siliconnode2 timeout not surfaced", status="in_progress")
    pt.update_item_status("dash_v2", "feat_fleet", "done", task_id="28eb4899")

    resp = client.get("/dashboard/projects")
    assert resp.status_code == 200
    assert "Agent Workforce Dashboard v2" in resp.text
    assert "Fleet status page" in resp.text
    assert "siliconnode2 timeout not surfaced" in resp.text
    assert "28eb4899" in resp.text
    assert "owner: <b>paul</b>" in resp.text
    assert "1/2 items done" in resp.text


def test_projects_page_shows_multiple_projects(client):
    pt.create_project("proj1", "First Project", "Goal 1")
    pt.create_project("proj2", "Second Project", "Goal 2")

    resp = client.get("/dashboard/projects")
    assert resp.status_code == 200
    assert "First Project" in resp.text
    assert "Second Project" in resp.text


def test_projects_page_escapes_html_in_names(client):
    pt.create_project("xss1", "<script>alert(1)</script>", "Goal")

    resp = client.get("/dashboard/projects")
    assert resp.status_code == 200
    assert "<script>alert(1)</script>" not in resp.text
    assert "&lt;script&gt;" in resp.text


def test_projects_page_separates_archived_from_active(client):
    pt.create_project("active1", "Active Project", "Goal")
    pt.create_project("old1", "Old Merged Project", "Goal")
    archived = pt.load_project("old1")
    archived.status = "archived"
    pt.save_project(archived)

    resp = client.get("/dashboard/projects")
    assert resp.status_code == 200
    # Active project appears before the <details> archived section.
    active_idx = resp.text.index("Active Project")
    details_idx = resp.text.index("<details")
    archived_idx = resp.text.index("Old Merged Project")
    assert active_idx < details_idx < archived_idx
    assert "Archived (1)" in resp.text


def test_projects_page_all_archived_shows_active_empty_message(client):
    pt.create_project("old1", "Old Project", "Goal")
    archived = pt.load_project("old1")
    archived.status = "archived"
    pt.save_project(archived)

    resp = client.get("/dashboard/projects")
    assert resp.status_code == 200
    assert "No active projects" in resp.text
    assert "Old Project" in resp.text  # still visible under archived


def test_projects_page_requires_auth(monkeypatch):
    monkeypatch.setattr(dashboard_router, "verify_token", lambda token: False)
    app = FastAPI()
    app.include_router(dashboard_router.router)
    client = TestClient(app, follow_redirects=False)

    resp = client.get("/dashboard/projects")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/dashboard/login"
