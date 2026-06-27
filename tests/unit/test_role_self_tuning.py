"""Tests for role self-tuning module."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from app.scheduler.role_self_tuning import (
    TUNABLE_PARAM_DEFS,
    IMMUTABLE_FIELDS,
    get_tunable_params,
    propose_param_update,
    reset_tunable_params,
    parse_self_tune_from_answer,
)


@pytest.fixture
def mock_role(tmp_path, monkeypatch):
    """Create a mock role file."""
    role_dir = tmp_path / "roles"
    role_dir.mkdir(parents=True)
    role = {
        "id": "test_role",
        "name": "Test Role",
        "temperature": 0.7,
        "max_iterations": 10,
        "capabilities": ["knowledge"],
    }
    (role_dir / "test_role.json").write_text(json.dumps(role))
    monkeypatch.setattr("app.scheduler.role_self_tuning.get_memory_path", lambda: str(tmp_path))
    return role


class TestGetTunableParams:
    def test_returns_current_values(self, mock_role):
        params = get_tunable_params("test_role")
        assert params["temperature"] == 0.7
        assert params["max_iterations"] == 10

    def test_returns_defaults_for_missing(self, mock_role):
        params = get_tunable_params("test_role")
        assert "top_p" in params  # default value

    def test_nonexistent_role(self, mock_role):
        params = get_tunable_params("nonexistent")
        assert params == {}


class TestProposeParamUpdate:
    def test_valid_update(self, mock_role):
        result = propose_param_update("test_role", "temperature", 0.9, "testing")
        assert result["success"] is True
        assert result["old"] == 0.7
        assert result["new"] == 0.9

    def test_rejects_immutable(self, mock_role):
        result = propose_param_update("test_role", "name", "New Name")
        assert result["success"] is False
        assert "immutable" in result["error"]

    def test_rejects_out_of_bounds(self, mock_role):
        result = propose_param_update("test_role", "temperature", 5.0)
        assert result["success"] is False
        assert "must be <=" in result["error"]

    def test_rejects_below_min(self, mock_role):
        result = propose_param_update("test_role", "temperature", -0.1)
        assert result["success"] is False
        assert "must be >=" in result["error"]

    def test_int_validation(self, mock_role):
        result = propose_param_update("test_role", "max_iterations", 20)
        assert result["success"] is True

    def test_creates_tuning_history(self, mock_role):
        propose_param_update("test_role", "temperature", 0.9, "test reason")
        role = json.loads((Path.home() / ".memory" / "roles" / "test_role.json").read_text()
                          if Path.home().joinpath(".memory", "roles", "test_role.json").exists()
                          else "{}")
        # Check via re-reading
        import app.scheduler.role_self_tuning as mod
        role = mod._load_role("test_role")
        assert "tuning_history" in role
        assert len(role["tuning_history"]) >= 1


class TestResetTunableParams:
    def test_resets_to_defaults(self, mock_role):
        propose_param_update("test_role", "temperature", 0.9)
        changes = reset_tunable_params("test_role")
        assert "temperature" in changes
        assert changes["temperature"]["new"] == 0.7

    def test_no_changes_if_at_default(self, mock_role):
        changes = reset_tunable_params("test_role")
        assert "temperature" not in changes  # already at 0.7


class TestParseSelfTuneFromAnswer:
    def test_parses_directive(self):
        answer = """
Some analysis here.

SELF_TUNE: temperature=0.5; lower temp for accuracy

More text.
"""
        directives = parse_self_tune_from_answer(answer)
        assert len(directives) == 1
        assert directives[0]["param"] == "temperature"
        assert directives[0]["value"] == "0.5"
        assert directives[0]["reason"] == "lower temp for accuracy"

    def test_no_directives(self):
        answer = "Just a normal answer with no tuning."
        directives = parse_self_tune_from_answer(answer)
        assert len(directives) == 0

    def test_multiple_directives(self):
        answer = "SELF_TUNE: temperature=0.5\nSELF_TUNE: max_iterations=20; more iterations needed"
        directives = parse_self_tune_from_answer(answer)
        assert len(directives) == 2
