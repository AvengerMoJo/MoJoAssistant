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


def test_projects_page_shows_current_state(client):
    pt.create_project("proj1", "Test Project", "Goal")
    pt.set_current_state("proj1", "Phase 1 done, Phase 2 not started")

    resp = client.get("/dashboard/projects")
    assert resp.status_code == 200
    assert "Current state:" in resp.text
    assert "Phase 1 done, Phase 2 not started" in resp.text


def test_projects_page_no_current_state_section_when_unset(client):
    pt.create_project("proj1", "Test Project", "Goal")

    resp = client.get("/dashboard/projects")
    assert resp.status_code == 200
    assert "Current state:" not in resp.text


def test_projects_page_shows_category_badge(client):
    pt.create_project("proj1", "Test Project", "Goal")
    pt.set_category("proj1", "private")

    resp = client.get("/dashboard/projects")
    assert resp.status_code == 200
    assert 'class="badge cat-private"' in resp.text
    assert ">private<" in resp.text


def test_projects_page_no_category_badge_when_unset(client):
    pt.create_project("proj1", "Test Project", "Goal")

    resp = client.get("/dashboard/projects")
    assert resp.status_code == 200
    assert 'class="badge cat-' not in resp.text


def test_projects_page_renders_one_tab_per_project(client):
    pt.create_project("proj1", "First Project", "Goal 1")
    pt.create_project("proj2", "Second Project", "Goal 2")
    pt.add_item("proj2", "i1", "feature", "Thing", status="done")

    resp = client.get("/dashboard/projects")
    assert resp.status_code == 200
    assert resp.text.count('class="tab-btn') == 2
    assert 'data-tab="tab-proj1"' in resp.text
    assert 'data-tab="tab-proj2"' in resp.text
    # Progress count shown on the tab itself
    assert "1/1" in resp.text  # Second Project's done count


def test_projects_page_first_tab_active_by_default(client):
    pt.create_project("proj1", "First Project", "Goal 1")
    pt.create_project("proj2", "Second Project", "Goal 2")

    resp = client.get("/dashboard/projects")
    assert resp.status_code == 200
    assert 'class="tab-panel active" id="tab-proj1"' in resp.text
    assert 'class="tab-panel" id="tab-proj2"' in resp.text


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
    # Both are present as tabs; active project's tab is selected by default,
    # archived project sits under its own "Archived" tab.
    assert "Active Project" in resp.text
    assert "Old Merged Project" in resp.text
    assert 'class="tab-btn active"' in resp.text
    assert "Archived <span" in resp.text


def test_projects_page_all_archived_shows_archived_tab_active(client):
    pt.create_project("old1", "Old Project", "Goal")
    archived = pt.load_project("old1")
    archived.status = "archived"
    pt.save_project(archived)

    resp = client.get("/dashboard/projects")
    assert resp.status_code == 200
    assert "Old Project" in resp.text
    # With no active projects, the Archived tab itself must default to visible.
    assert 'id="tab-archived"' in resp.text
    assert 'class="tab-panel active" id="tab-archived"' in resp.text


def test_projects_page_requires_auth(monkeypatch):
    monkeypatch.setattr(dashboard_router, "verify_token", lambda token: False)
    app = FastAPI()
    app.include_router(dashboard_router.router)
    client = TestClient(app, follow_redirects=False)

    resp = client.get("/dashboard/projects")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/dashboard/login"
