"""Unit tests for the docker_sandbox_* agentic tools.

Mirrors test_cubesandbox_agentic_tools.py — mocks the Docker CLI
subprocess calls so no real containers are created.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_module_state(monkeypatch):
    """Fresh module state for each test."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    if "app.scheduler.agentic.docker_sandbox_tools" in sys.modules:
        del sys.modules["app.scheduler.agentic.docker_sandbox_tools"]
    yield
    sys.modules.pop("app.scheduler.agentic.docker_sandbox_tools", None)


def _mock_run(returncode=0, stdout="", stderr=""):
    """Create a mock subprocess.CompletedProcess."""
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# -------------------------------------------------------------------
# docker_sandbox_create
# -------------------------------------------------------------------


class TestDockerSandboxCreate:
    def test_create_returns_container_id_and_url(self):
        from app.scheduler.agentic.docker_sandbox_tools import docker_sandbox_create

        with patch("subprocess.run") as mock_run:
            # ss check (port free) + docker run
            mock_run.side_effect = [
                _mock_run(stdout=""),  # ss - no process on port
                _mock_run(stdout="abc123\n"),  # docker run
            ]
            result = docker_sandbox_create({"name": "test-1"})

        assert result["success"] is True
        assert result["name"] == "test-1"
        assert result["container_id"] == "abc123"
        assert "url" in result

    def test_create_requires_name(self):
        from app.scheduler.agentic.docker_sandbox_tools import docker_sandbox_create

        result = docker_sandbox_create({})
        assert result["success"] is False
        assert "name" in result["error"]

    def test_create_is_idempotent(self):
        from app.scheduler.agentic.docker_sandbox_tools import docker_sandbox_create

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                _mock_run(stdout=""),  # ss
                _mock_run(stdout="abc123\n"),  # docker run
                _mock_run(stdout=json.dumps([{"State": {"Running": True}}])),  # docker inspect
            ]
            r1 = docker_sandbox_create({"name": "test-2"})
            r2 = docker_sandbox_create({"name": "test-2"})

        assert r1["success"] and r2["success"]
        assert r2.get("reused") is True

    def test_create_handles_docker_failure(self):
        from app.scheduler.agentic.docker_sandbox_tools import docker_sandbox_create

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                _mock_run(stdout=""),  # ss
                _mock_run(returncode=1, stderr="image not found"),  # docker run
            ]
            result = docker_sandbox_create({"name": "fail-1"})

        assert result["success"] is False
        assert "image not found" in result["error"]


# -------------------------------------------------------------------
# docker_sandbox_exec
# -------------------------------------------------------------------


class TestDockerSandboxExec:
    def test_exec_requires_existing_container(self):
        from app.scheduler.agentic.docker_sandbox_tools import docker_sandbox_exec

        result = docker_sandbox_exec({"name": "nonexistent", "command": "ls"})
        assert result["success"] is False
        assert "no container" in result["error"].lower()

    def test_exec_runs_command(self):
        from app.scheduler.agentic.docker_sandbox_tools import (
            docker_sandbox_create, docker_sandbox_exec,
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                _mock_run(stdout=""),  # ss
                _mock_run(stdout="cnt-123\n"),  # docker run
                _mock_run(stdout="hello\n", returncode=0),  # docker exec
            ]
            docker_sandbox_create({"name": "exec-1"})
            result = docker_sandbox_exec({"name": "exec-1", "command": "echo hello"})

        assert result["success"] is True
        assert result["stdout"] == "hello\n"
        assert result["exit_code"] == 0

    def test_exec_requires_command(self):
        from app.scheduler.agentic.docker_sandbox_tools import (
            docker_sandbox_create, docker_sandbox_exec,
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                _mock_run(stdout=""),  # ss
                _mock_run(stdout="cnt-456\n"),  # docker run
            ]
            docker_sandbox_create({"name": "nocmd-1"})
            result = docker_sandbox_exec({"name": "nocmd-1"})

        assert result["success"] is False
        assert "command" in result["error"]


# -------------------------------------------------------------------
# docker_sandbox_list
# -------------------------------------------------------------------


class TestDockerSandboxList:
    def test_list_empty(self):
        from app.scheduler.agentic.docker_sandbox_tools import docker_sandbox_list

        result = docker_sandbox_list({})
        assert result["success"] is True
        assert result["count"] == 0

    def test_list_after_create(self):
        from app.scheduler.agentic.docker_sandbox_tools import (
            docker_sandbox_create, docker_sandbox_list,
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                _mock_run(stdout=""), _mock_run(stdout="c1\n"),
                _mock_run(stdout=""), _mock_run(stdout="c2\n"),
                _mock_run(stdout=json.dumps([{"State": {"Running": True}}])),
                _mock_run(stdout=json.dumps([{"State": {"Running": True}}])),
            ]
            docker_sandbox_create({"name": "list-1"})
            docker_sandbox_create({"name": "list-2"})
            result = docker_sandbox_list({})

        assert result["count"] == 2


# -------------------------------------------------------------------
# docker_sandbox_destroy
# -------------------------------------------------------------------


class TestDockerSandboxDestroy:
    def test_destroy_known_container(self):
        from app.scheduler.agentic.docker_sandbox_tools import (
            docker_sandbox_create, docker_sandbox_destroy,
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                _mock_run(stdout=""), _mock_run(stdout="c1\n"),
                _mock_run(stdout=""),  # docker rm
            ]
            docker_sandbox_create({"name": "del-1"})
            result = docker_sandbox_destroy({"name": "del-1"})

        assert result["success"] is True
        assert result["destroyed"] is True

    def test_destroy_idempotent(self):
        from app.scheduler.agentic.docker_sandbox_tools import docker_sandbox_destroy

        result = docker_sandbox_destroy({"name": "never-existed"})
        assert result["success"] is True
        assert result.get("already_destroyed") is True


# -------------------------------------------------------------------
# docker_sandbox_upload
# -------------------------------------------------------------------


class TestDockerSandboxUpload:
    def test_upload_requires_existing_container(self):
        from app.scheduler.agentic.docker_sandbox_tools import docker_sandbox_upload

        result = docker_sandbox_upload({"name": "missing", "local_path": "/tmp"})
        assert result["success"] is False

    def test_upload_rejects_nonexistent_path(self):
        from app.scheduler.agentic.docker_sandbox_tools import (
            docker_sandbox_create, docker_sandbox_upload,
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                _mock_run(stdout=""), _mock_run(stdout="c1\n"),
            ]
            docker_sandbox_create({"name": "up-1"})
            result = docker_sandbox_upload({
                "name": "up-1",
                "local_path": "/no/such/dir/anywhere",
            })

        assert result["success"] is False
        assert "not a directory" in result["error"].lower()


# -------------------------------------------------------------------
# Executor wiring
# -------------------------------------------------------------------


class TestExecutorWiring:
    def test_all_5_tools_have_python_executor(self):
        cfg = json.load(open("config/dynamic_tools.json"))
        docker = [t for t in cfg["tools"] if t["name"].startswith("docker_sandbox_")]
        assert len(docker) == 5
        for t in docker:
            assert t["executor"]["type"] == "python"
            assert t["executor"]["module"] == "app.scheduler.agentic.docker_sandbox_tools"
            assert t["executor"]["function"] in {
                "docker_sandbox_create",
                "docker_sandbox_exec",
                "docker_sandbox_list",
                "docker_sandbox_destroy",
                "docker_sandbox_upload",
            }

    def test_module_imports_cleanly(self):
        import importlib
        mod = importlib.import_module("app.scheduler.agentic.docker_sandbox_tools")
        assert hasattr(mod, "docker_sandbox_create")
        assert hasattr(mod, "docker_sandbox_exec")
        assert hasattr(mod, "docker_sandbox_list")
        assert hasattr(mod, "docker_sandbox_destroy")
        assert hasattr(mod, "docker_sandbox_upload")
