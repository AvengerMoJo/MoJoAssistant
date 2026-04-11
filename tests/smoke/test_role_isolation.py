"""
Smoke — Role knowledge isolation.

Verifies that knowledge_search is physically scoped to the calling role:
  - Reports tagged with a different role_id are filtered out
  - Reports tagged with the correct role_id are returned
  - Knowledge units are read from the role-scoped path only
  - An empty task_reports directory returns [] without crashing

No network or LLM calls required.
"""

import json
import os
import pytest
from pathlib import Path

from app.scheduler.role_chat import RoleChatSession


@pytest.fixture()
def reports_dir(isolated_memory_path: Path) -> Path:
    d = isolated_memory_path / "task_reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_report(directory: Path, task_id: str, role_id: str, goal: str, content: str) -> None:
    report = {
        "task_id": task_id,
        "role_id": role_id,
        "goal": goal,
        "status": "completed",
        "review_status": "pending_review",
        "created_at": "2026-03-29T10:00:00",
        "content": content,
    }
    (directory / f"{task_id}.json").write_text(
        json.dumps(report), encoding="utf-8"
    )


class TestKnowledgeSearchIsolation:

    def test_own_report_is_returned(self, reports_dir: Path):
        _write_report(reports_dir, "task-rebecca-1", "rebecca", "NineChapter analysis", "Full analysis here.")
        session = RoleChatSession("rebecca")
        results = session._search_knowledge(query="NineChapter")
        assert len(results) == 1
        assert results[0]["task_id"] == "task-rebecca-1"

    def test_other_role_report_is_excluded(self, reports_dir: Path):
        _write_report(reports_dir, "task-ahman-1", "ahman", "Security audit", "Ahman's security findings.")
        session = RoleChatSession("rebecca")
        results = session._search_knowledge(query="security")
        assert len(results) == 0, "rebecca should not see ahman's task reports"

    def test_mixed_reports_only_own_returned(self, reports_dir: Path):
        _write_report(reports_dir, "task-rebecca-2", "rebecca", "Research topic A", "Rebecca findings.")
        _write_report(reports_dir, "task-ahman-2", "ahman", "Research topic A", "Ahman findings.")
        _write_report(reports_dir, "task-popo-1", "popo", "Research topic A", "Popo findings.")

        session = RoleChatSession("rebecca")
        results = session._search_knowledge(query="Research topic A")
        assert len(results) == 1
        # Only rebecca's task should be returned — identified by task_id
        assert results[0].get("task_id") == "task-rebecca-2"

    def test_empty_reports_dir_returns_empty_list(self, isolated_memory_path: Path):
        """No reports at all → empty list, no exception."""
        session = RoleChatSession("rebecca")
        results = session._search_knowledge(query="anything")
        assert results == []

    def test_absent_reports_dir_returns_empty_list(self, isolated_memory_path: Path):
        """task_reports directory doesn't exist yet → empty list, no exception."""
        session = RoleChatSession("nonexistent_role")
        results = session._search_knowledge(query="anything")
        assert results == []

    def test_query_filter_within_own_reports(self, reports_dir: Path):
        _write_report(reports_dir, "task-r-a", "rebecca", "xyzquux-unique-topic", "Chapter findings xyzquux.")
        _write_report(reports_dir, "task-r-b", "rebecca", "Docker setup", "Container config.")
        session = RoleChatSession("rebecca")
        results = session._search_knowledge(query="xyzquux-unique-topic")
        matching = [r for r in results if r.get("task_id") == "task-r-a"]
        non_matching = [r for r in results if r.get("task_id") == "task-r-b"]
        assert len(matching) == 1
        assert len(non_matching) == 0

    def test_empty_query_returns_all_own_reports(self, reports_dir: Path):
        _write_report(reports_dir, "task-r-c", "rebecca", "Goal C", "Content C.")
        _write_report(reports_dir, "task-r-d", "rebecca", "Goal D", "Content D.")
        _write_report(reports_dir, "task-ahman-3", "ahman", "Goal E", "Content E.")
        session = RoleChatSession("rebecca")
        results = session._search_knowledge(query="")
        role_ids = {r["role_id"] for r in results if "role_id" in r}
        task_ids = {r.get("task_id") for r in results if "task_id" in r}
        assert "ahman" not in role_ids
        assert "task-ahman-3" not in task_ids

    def test_limit_is_respected(self, reports_dir: Path):
        for i in range(10):
            _write_report(reports_dir, f"task-r-{i}", "rebecca", f"Goal {i}", f"Content {i}.")
        session = RoleChatSession("rebecca")
        results = session._search_knowledge(query="", limit=3)
        assert len(results) <= 3


class TestKnowledgeUnitIsolation:

    def test_knowledge_units_read_from_role_scoped_path(self, isolated_memory_path: Path):
        """Knowledge units are stored under roles/{role_id}/knowledge_units/ — verify path scoping."""
        # Write a KU archive for 'rebecca'
        ku_dir = isolated_memory_path / "roles" / "rebecca" / "knowledge_units" / "session_001"
        ku_dir.mkdir(parents=True, exist_ok=True)
        archive = {
            "created_at": "2026-03-29T10:00:00",
            "knowledge_units": [
                {
                    "core_meaning": "Rebecca's personal insight about research methodology",
                    "quote": "Evidence must be independent",
                    "source": "session_001",
                }
            ],
        }
        (ku_dir / "archive_v1.json").write_text(json.dumps(archive), encoding="utf-8")

        # Write a KU for 'ahman' — should not appear in rebecca's search
        other_dir = isolated_memory_path / "roles" / "ahman" / "knowledge_units" / "session_002"
        other_dir.mkdir(parents=True, exist_ok=True)
        other_archive = {
            "created_at": "2026-03-29T10:00:00",
            "knowledge_units": [
                {
                    "core_meaning": "Ahman's security insight",
                    "quote": "Threat model first",
                    "source": "session_002",
                }
            ],
        }
        (other_dir / "archive_v1.json").write_text(json.dumps(other_archive), encoding="utf-8")

        session = RoleChatSession("rebecca")
        results = session._search_knowledge(query="insight")

        contents = [r.get("content", "") for r in results]
        assert any("research methodology" in c or "Evidence" in c for c in contents), \
            "Rebecca's KU should be returned"
        assert not any("security" in c or "Threat" in c for c in contents), \
            "Ahman's KU must not appear in Rebecca's search"
