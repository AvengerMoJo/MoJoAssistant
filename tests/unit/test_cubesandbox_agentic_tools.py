"""Unit tests for SandboxManager.

Replaces the old cubesandbox_tools.py tests. Verifies the unified
SandboxManager: config loading, should_provision(), acquire() resume
path, and release() modes.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.scheduler.sandbox.base import SandboxHandle
from app.scheduler.sandbox.manager import SandboxManager


@pytest.fixture(autouse=True)
def _reset_singleton():
    SandboxManager.reset()
    yield
    SandboxManager.reset()


class TestSandboxManagerLoad:
    def test_loads_defaults_when_no_config_file(self):
        with patch.object(Path, "exists", return_value=False):
            mgr = SandboxManager.load()
        assert mgr._config["default_backend"] == "docker"
        assert mgr._config["auto_provision"]["on_git_url"] is True

    def test_merges_user_config(self):
        user_cfg = {"default_backend": "host", "backends": {"host": {"workdir": "/tmp/sandboxes"}}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(user_cfg, f)
            tmp = Path(f.name)
        try:
            with patch("app.scheduler.sandbox.manager._CONFIG_PATH", tmp):
                mgr = SandboxManager.load()
            assert mgr._config["default_backend"] == "host"
            assert mgr._config["backends"]["host"]["workdir"] == "/tmp/sandboxes"
            # Docker backend still present from defaults
            assert "docker" in mgr._config["backends"]
        finally:
            tmp.unlink()

    def test_returns_singleton(self):
        mgr1 = SandboxManager.load()
        mgr2 = SandboxManager.load()
        assert mgr1 is mgr2


class TestShouldProvision:
    def _task(self, **cfg):
        t = MagicMock()
        t.config = cfg
        t.type = cfg.get("type", "agentic")
        return t

    def test_true_when_git_url(self):
        mgr = SandboxManager.load()
        assert mgr.should_provision(self._task(git_url="git@github.com:foo/bar.git"))

    def test_true_when_sandbox_required(self):
        mgr = SandboxManager.load()
        assert mgr.should_provision(self._task(sandbox_required=True))

    def test_false_for_plain_research_task(self):
        mgr = SandboxManager.load()
        assert not mgr.should_provision(self._task(goal="summarise this doc"))

    def test_false_when_git_url_rule_disabled(self):
        mgr = SandboxManager.load()
        mgr._config["auto_provision"]["on_git_url"] = False
        assert not mgr.should_provision(self._task(git_url="git@github.com:foo/bar.git"))


class TestSandboxManagerAcquire:
    def test_resumes_existing_paused_handle(self):
        async def _run():
            mgr = SandboxManager.load()
            existing = SandboxHandle(
                task_id="task-xyz",
                backend="docker",
                sandbox_id="old-container",
                state="paused",
            )
            mock_backend = MagicMock()
            mock_backend.health_check.return_value = {"status": "ok"}
            mock_backend.resume.return_value = existing

            with patch("app.scheduler.sandbox.manager.load_handle", return_value=existing), \
                 patch.object(mgr, "_get_backend", return_value=mock_backend):
                handle = await mgr.acquire(task_id="task-xyz")

            mock_backend.resume.assert_called_once_with(existing)
            assert handle is existing

        asyncio.run(_run())

    def test_starts_fresh_when_no_existing(self):
        async def _run():
            mgr = SandboxManager.load()
            new_handle = SandboxHandle(
                task_id="new-task",
                backend="docker",
                sandbox_id="new-container",
                state="running",
            )
            mock_backend = MagicMock()
            mock_backend.start.return_value = new_handle
            mock_backend.health_check.return_value = {"status": "stopped"}

            with patch("app.scheduler.sandbox.manager.load_handle", return_value=None), \
                 patch.object(mgr, "_get_backend", return_value=mock_backend):
                handle = await mgr.acquire(task_id="new-task")

            mock_backend.start.assert_called_once()
            assert handle is new_handle

        asyncio.run(_run())


class TestSandboxManagerRelease:
    def test_pause_mode(self):
        async def _run():
            mgr = SandboxManager.load()
            handle = SandboxHandle(task_id="t1", backend="docker", sandbox_id="cid", state="running")
            mock_backend = MagicMock()

            with patch.object(mgr, "_get_backend", return_value=mock_backend):
                await mgr.release(handle, mode="pause")

            mock_backend.pause.assert_called_once_with(handle)
            mock_backend.kill.assert_not_called()

        asyncio.run(_run())

    def test_kill_mode(self):
        async def _run():
            mgr = SandboxManager.load()
            handle = SandboxHandle(task_id="t1", backend="docker", sandbox_id="cid", state="running")
            mock_backend = MagicMock()

            with patch.object(mgr, "_get_backend", return_value=mock_backend):
                await mgr.release(handle, mode="kill")

            mock_backend.kill.assert_called_once_with(handle)
            mock_backend.pause.assert_not_called()

        asyncio.run(_run())
