"""Unit tests for the cubesandbox_* agentic tools.

These tools are exposed to agentic LLMs (Popo, Rebecca, etc.) via
config/agentic_tools.json with ``executor.type = "python"``. Each tool
delegates to ``app.scheduler.agentic.cubesandbox_tools`` which wraps
``CubeSandboxClient``. We mock the e2b SDK to avoid touching the real
cluster.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_module_state(monkeypatch):
    """Each test sees a fresh _CLIENT_CACHE and clean module import.

    Also sets inert E2B env vars so CubeSandboxClient.start() passes
    its preflight check (we mock Sandbox.create() anyway, but the
    env check fires first).
    """
    monkeypatch.setenv("E2B_API_URL", "http://test-host.invalid")
    monkeypatch.setenv("E2B_API_KEY", "test-key-not-used")
    monkeypatch.setenv("CUBE_TEMPLATE_ID", "tpl-test")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    if "app.scheduler.agentic.cubesandbox_tools" in sys.modules:
        del sys.modules["app.scheduler.agentic.cubesandbox_tools"]
    yield
    # Cleanup: drop the module after each test to avoid cache leakage
    sys.modules.pop("app.scheduler.agentic.cubesandbox_tools", None)


# ----------------------------------------------------------------------
# cubesandbox_create
# ----------------------------------------------------------------------


class TestCubesandboxCreate:
    def test_create_returns_sandbox_id_and_url(self):
        from app.scheduler.agentic.cubesandbox_tools import cubesandbox_create

        fake_sandbox = MagicMock()
        fake_sandbox.sandbox_id = "fake-vm-001"
        with patch("e2b.Sandbox") as MockSandbox:
            MockSandbox.create.return_value = fake_sandbox
            result = cubesandbox_create({"name": "popo-build-1"})
        assert result["success"] is True
        assert result["name"] == "popo-build-1"
        assert result["sandbox_id"] == "fake-vm-001"
        assert "url" in result
        assert "template_id" in result

    def test_create_requires_name(self):
        from app.scheduler.agentic.cubesandbox_tools import cubesandbox_create

        result = cubesandbox_create({})
        assert result["success"] is False
        assert "name" in result["error"]

    def test_create_is_idempotent(self):
        """Calling create twice with the same name reuses the existing VM."""
        from app.scheduler.agentic.cubesandbox_tools import cubesandbox_create

        fake_sandbox = MagicMock()
        fake_sandbox.sandbox_id = "fake-vm-002"
        with patch("e2b.Sandbox") as MockSandbox:
            MockSandbox.create.return_value = fake_sandbox
            r1 = cubesandbox_create({"name": "popo-build-2"})
            r2 = cubesandbox_create({"name": "popo-build-2"})
        assert r1["success"] and r2["success"]
        assert r1["sandbox_id"] == r2["sandbox_id"]
        # Idempotent return flags the reuse
        assert r2.get("reused") is True
        # Sandbox.create should only be called once
        assert MockSandbox.create.call_count == 1

    def test_create_handles_sdk_exception(self):
        from app.scheduler.agentic.cubesandbox_tools import cubesandbox_create

        with patch("e2b.Sandbox") as MockSandbox:
            MockSandbox.create.side_effect = RuntimeError("cluster unreachable")
            result = cubesandbox_create({"name": "popo-build-3"})
        assert result["success"] is False
        # cubesandbox_client.start() wraps the original in CubeSandboxError
        assert "cluster unreachable" in result["error"]
        assert "CubeSandboxError" in result["error"]

    def test_create_uploads_dir_when_provided(self):
        from app.scheduler.agentic.cubesandbox_tools import cubesandbox_create

        fake_sandbox = MagicMock()
        fake_sandbox.sandbox_id = "fake-vm-004"
        with patch("e2b.Sandbox") as MockSandbox:
            MockSandbox.create.return_value = fake_sandbox
            with patch("pathlib.Path.is_dir", return_value=True):
                result = cubesandbox_create({
                    "name": "popo-build-4",
                    "upload_dir": "/tmp/fake-repo",
                })
        assert result["success"] is True


# ----------------------------------------------------------------------
# cubesandbox_exec
# ----------------------------------------------------------------------


class TestCubesandboxExec:
    def test_exec_requires_existing_vm(self):
        from app.scheduler.agentic.cubesandbox_tools import cubesandbox_exec

        result = cubesandbox_exec({"name": "nonexistent", "command": "ls"})
        assert result["success"] is False
        assert "no running cubesandbox" in result["error"].lower()

    def test_exec_runs_command_and_returns_output(self):
        from app.scheduler.agentic.cubesandbox_tools import (
            cubesandbox_create, cubesandbox_exec,
        )

        # e2b SDK 2.x: client.commands.run(cmd) returns a CommandResult
        # synchronously. Set up the mock to return one.
        fake_sandbox = MagicMock()
        fake_sandbox.sandbox_id = "fake-vm-exec"
        fake_result = MagicMock(stdout="hello\n", stderr="", exit_code=0)
        fake_sandbox.commands.run.return_value = fake_result

        with patch("e2b.Sandbox") as MockSandbox:
            MockSandbox.create.return_value = fake_sandbox
            cr = cubesandbox_create({"name": "exec-test"})
            er = cubesandbox_exec({"name": "exec-test", "command": "echo hello"})
        assert cr["success"]
        assert er["success"]
        assert er["stdout"] == "hello\n"
        assert er["exit_code"] == 0
        fake_sandbox.commands.run.assert_called_once()

    def test_exec_captures_nonzero_exit_code(self):
        from app.scheduler.agentic.cubesandbox_tools import (
            cubesandbox_create, cubesandbox_exec,
        )

        fake_sandbox = MagicMock()
        fake_sandbox.sandbox_id = "fake-vm-fail"
        fake_result = MagicMock(stdout="partial output", stderr="oops", exit_code=2)
        fake_sandbox.commands.run.return_value = fake_result

        with patch("e2b.Sandbox") as MockSandbox:
            MockSandbox.create.return_value = fake_sandbox
            cubesandbox_create({"name": "fail-test"})
            er = cubesandbox_exec({"name": "fail-test", "command": "false"})
        assert er["success"] is True  # success = tool ran, not exit code
        assert er["exit_code"] == 2
        assert "oops" in er["stderr"]

    def test_exec_requires_command(self):
        from app.scheduler.agentic.cubesandbox_tools import (
            cubesandbox_create, cubesandbox_exec,
        )

        fake_sandbox = MagicMock()
        fake_sandbox.sandbox_id = "fake-vm-nocmd"
        with patch("e2b.Sandbox") as MockSandbox:
            MockSandbox.create.return_value = fake_sandbox
            cubesandbox_create({"name": "nocmd-test"})
            er = cubesandbox_exec({"name": "nocmd-test"})
        assert er["success"] is False
        assert "command" in er["error"]


# ----------------------------------------------------------------------
# cubesandbox_list
# ----------------------------------------------------------------------


class TestCubesandboxList:
    def test_list_empty_initially(self):
        from app.scheduler.agentic.cubesandbox_tools import cubesandbox_list

        result = cubesandbox_list({})
        assert result["success"] is True
        assert result["count"] == 0
        assert result["sandboxes"] == []

    def test_list_after_creates(self):
        from app.scheduler.agentic.cubesandbox_tools import (
            cubesandbox_create, cubesandbox_list,
        )

        fake_sandbox = MagicMock()
        fake_sandbox.sandbox_id = "fake-vm-list"
        with patch("e2b.Sandbox") as MockSandbox:
            MockSandbox.create.return_value = fake_sandbox
            cubesandbox_create({"name": "list-1"})
            cubesandbox_create({"name": "list-2"})
            result = cubesandbox_list({})
        assert result["count"] == 2
        names = {s["name"] for s in result["sandboxes"]}
        assert names == {"list-1", "list-2"}


# ----------------------------------------------------------------------
# cubesandbox_destroy
# ----------------------------------------------------------------------


class TestCubesandboxDestroy:
    def test_destroy_known_vm(self):
        from app.scheduler.agentic.cubesandbox_tools import (
            cubesandbox_create, cubesandbox_destroy, cubesandbox_list,
        )

        fake_sandbox = MagicMock()
        fake_sandbox.sandbox_id = "fake-vm-destroy"
        with patch("e2b.Sandbox") as MockSandbox:
            MockSandbox.create.return_value = fake_sandbox
            cubesandbox_create({"name": "destroy-1"})
            r = cubesandbox_destroy({"name": "destroy-1"})
            listing = cubesandbox_list({})
        assert r["success"] is True
        assert r["destroyed"] is True
        assert listing["count"] == 0

    def test_destroy_unknown_vm_is_idempotent(self):
        from app.scheduler.agentic.cubesandbox_tools import cubesandbox_destroy

        r = cubesandbox_destroy({"name": "never-existed"})
        assert r["success"] is True
        assert r.get("already_destroyed") is True

    def test_destroy_requires_name(self):
        from app.scheduler.agentic.cubesandbox_tools import cubesandbox_destroy

        r = cubesandbox_destroy({})
        assert r["success"] is False
        assert "name" in r["error"]


# ----------------------------------------------------------------------
# cubesandbox_upload
# ----------------------------------------------------------------------


class TestCubesandboxUpload:
    def test_upload_requires_existing_vm(self):
        from app.scheduler.agentic.cubesandbox_tools import cubesandbox_upload

        r = cubesandbox_upload({"name": "missing", "local_path": "/tmp/x"})
        assert r["success"] is False

    def test_upload_rejects_nonexistent_path(self):
        from app.scheduler.agentic.cubesandbox_tools import (
            cubesandbox_create, cubesandbox_upload,
        )

        fake_sandbox = MagicMock()
        fake_sandbox.sandbox_id = "fake-vm-upload"
        with patch("e2b.Sandbox") as MockSandbox:
            MockSandbox.create.return_value = fake_sandbox
            cubesandbox_create({"name": "upload-1"})
            r = cubesandbox_upload({
                "name": "upload-1",
                "local_path": "/no/such/dir/anywhere",
            })
        assert r["success"] is False
        assert "not a directory" in r["error"].lower()


# ----------------------------------------------------------------------
# Integration with CapabilityRegistry's python executor path
# ----------------------------------------------------------------------


class TestExecutorWiring:
    """Verify the agentic_tools.json entries resolve through the
    CapabilityRegistry python executor path correctly."""

    def test_all_5_tools_have_python_executor(self):
        cfg = json.load(open("config/agentic_tools.json"))
        cubesandbox = [t for t in cfg["tools"] if t["name"].startswith("cubesandbox_")]
        assert len(cubesandbox) == 5
        for t in cubesandbox:
            assert t["executor"]["type"] == "python"
            assert t["executor"]["module"] == "app.scheduler.agentic.cubesandbox_tools"
            assert t["executor"]["function"] in {
                "cubesandbox_create",
                "cubesandbox_exec",
                "cubesandbox_list",
                "cubesandbox_destroy",
                "cubesandbox_upload",
            }

    def test_all_5_have_required_parameters(self):
        cfg = json.load(open("config/agentic_tools.json"))
        cubesandbox = {t["name"]: t for t in cfg["tools"] if t["name"].startswith("cubesandbox_")}
        # create requires name
        assert "name" in cubesandbox["cubesandbox_create"]["parameters"]["required"]
        # exec requires name and command
        assert set(cubesandbox["cubesandbox_exec"]["parameters"]["required"]) == {"name", "command"}
        # destroy requires name
        assert "name" in cubesandbox["cubesandbox_destroy"]["parameters"]["required"]
        # upload requires name and local_path
        assert set(cubesandbox["cubesandbox_upload"]["parameters"]["required"]) == {"name", "local_path"}
        # list has no required args
        assert cubesandbox["cubesandbox_list"]["parameters"]["required"] == []

    def test_module_imports_cleanly(self):
        """The python module path must resolve to a real importable module."""
        import importlib
        mod = importlib.import_module("app.scheduler.agentic.cubesandbox_tools")
        assert hasattr(mod, "cubesandbox_create")
        assert hasattr(mod, "cubesandbox_exec")
        assert hasattr(mod, "cubesandbox_list")
        assert hasattr(mod, "cubesandbox_destroy")
        assert hasattr(mod, "cubesandbox_upload")
