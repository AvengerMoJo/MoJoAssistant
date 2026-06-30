"""Unit tests for SandboxManager Docker routing.

Replaces the old docker_sandbox_tools.py tests — those tested an in-process
tool shim that has been deleted. These tests verify that SandboxManager
routes bash_exec / read_file / write_file / list_files through the Docker
backend when _cv_sandbox_handle is set.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scheduler.sandbox.base import SandboxHandle
from app.scheduler.sandbox.context import _cv_sandbox_handle


@pytest.fixture
def docker_handle():
    return SandboxHandle(
        task_id="test-001",
        backend="docker",
        sandbox_id="abc123container",
        working_dir="/workspace/repo",
        state="running",
    )


@pytest.fixture
def mock_mgr():
    mgr = MagicMock()
    mgr.exec = AsyncMock(return_value={"success": True, "stdout": "ok", "stderr": "", "returncode": 0})
    mgr.read_file = AsyncMock(return_value="file contents\n")
    mgr.write_file = AsyncMock()
    mgr.list_files = AsyncMock(return_value=["file1.py", "file2.py"])
    return mgr


class TestSandboxContextRouting:
    def test_bash_exec_routes_through_sandbox(self, docker_handle, mock_mgr):
        async def _run():
            from app.scheduler.capability_registry import CapabilityRegistry
            registry = CapabilityRegistry.__new__(CapabilityRegistry)

            token = _cv_sandbox_handle.set(docker_handle)
            try:
                with patch("app.scheduler.sandbox.manager.SandboxManager.load", return_value=mock_mgr):
                    result = await registry._bash_exec({"command": "echo hello"})
            finally:
                _cv_sandbox_handle.reset(token)

            assert result["success"]
            mock_mgr.exec.assert_called_once_with(docker_handle, "echo hello", timeout=60)

        asyncio.run(_run())

    def test_bash_exec_host_when_no_handle(self):
        """Without a sandbox handle, bash_exec falls through to host subprocess."""
        async def _run():
            from app.scheduler.capability_registry import CapabilityRegistry
            registry = CapabilityRegistry.__new__(CapabilityRegistry)
            registry.sandbox = MagicMock()
            registry.sandbox.is_path_allowed = MagicMock(return_value=True)

            assert _cv_sandbox_handle.get() is None
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="host output\n", stderr="")
                result = await registry._bash_exec({"command": "echo host"})

            assert result["success"]
            mock_run.assert_called_once()

        asyncio.run(_run())

    def test_read_file_routes_through_sandbox(self, docker_handle, mock_mgr):
        async def _run():
            from app.scheduler.capability_registry import CapabilityRegistry
            registry = CapabilityRegistry.__new__(CapabilityRegistry)

            token = _cv_sandbox_handle.set(docker_handle)
            try:
                with patch("app.scheduler.sandbox.manager.SandboxManager.load", return_value=mock_mgr):
                    result = await registry._read_file({"path": "/workspace/repo/main.py"})
            finally:
                _cv_sandbox_handle.reset(token)

            assert result["success"]
            assert result["content"] == "file contents\n"
            mock_mgr.read_file.assert_called_once_with(docker_handle, "/workspace/repo/main.py")

        asyncio.run(_run())

    def test_write_file_routes_through_sandbox(self, docker_handle, mock_mgr):
        async def _run():
            from app.scheduler.capability_registry import CapabilityRegistry
            registry = CapabilityRegistry.__new__(CapabilityRegistry)

            token = _cv_sandbox_handle.set(docker_handle)
            try:
                with patch("app.scheduler.sandbox.manager.SandboxManager.load", return_value=mock_mgr):
                    result = await registry._write_file({"path": "/workspace/repo/out.py", "content": "x=1"})
            finally:
                _cv_sandbox_handle.reset(token)

            assert result["success"]
            mock_mgr.write_file.assert_called_once_with(docker_handle, "/workspace/repo/out.py", "x=1")

        asyncio.run(_run())

    def test_context_reset_after_task(self, docker_handle):
        """Context var must be None after reset — no leak between tasks."""
        token = _cv_sandbox_handle.set(docker_handle)
        assert _cv_sandbox_handle.get() is docker_handle
        _cv_sandbox_handle.reset(token)
        assert _cv_sandbox_handle.get() is None
