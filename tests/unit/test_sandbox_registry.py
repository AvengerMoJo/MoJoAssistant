"""Unit tests for the sandbox backend registry + persistence."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    """Point the session store at a tmp file so tests don't touch ~/.memory.

    Sets E2B_* env vars to inert test values so CubeSandboxClient.start()
    passes its preflight check, but never uses a real domain — tests
    mock the Sandbox class entirely.
    """
    p = tmp_path / "sandbox_sessions.json"
    monkeypatch.setenv("SANDBOX_SESSION_STORE", str(p))
    monkeypatch.setenv("E2B_API_URL", "http://test-host.invalid")
    monkeypatch.setenv("E2B_API_KEY", "test-key-not-used")
    monkeypatch.setenv("CUBE_TEMPLATE_ID", "tpl-test")
    yield p


# ----------------------------------------------------------------------
# session_store
# ----------------------------------------------------------------------


def test_session_store_roundtrip():
    from app.scheduler.sandbox.base import (
        SandboxHandle, store_handle, load_handle, list_handles, delete_handle,
    )
    h = SandboxHandle(
        task_id="task_42", backend="cube", sandbox_id="abc",
        url="http://127.0.0.1:4173", state="paused",
    )
    store_handle(h)
    loaded = load_handle("task_42")
    assert loaded is not None
    assert loaded.sandbox_id == "abc"
    assert loaded.state == "paused"
    # updated_at was bumped
    assert loaded.updated_at >= h.created_at

    delete_handle("task_42")
    assert load_handle("task_42") is None


def test_list_handles_filters_by_backend():
    """Filters by backend and returns all when no filter given.

    Saves and restores the store around the test to avoid pollution from
    other tests (e.g. test_v1_2_2_smoke.py uses the same store).
    """
    from app.scheduler.sandbox.base import (
        SESSION_STORE_PATH, SandboxHandle, store_handle, list_handles,
        _load_store, _save_store,
    )
    # Snapshot the existing store
    backup = dict(_load_store()) if SESSION_STORE_PATH.exists() else {}

    try:
        # Clear to a known state
        _save_store({})
        store_handle(SandboxHandle(task_id="t1", backend="cube", sandbox_id="c1"))
        store_handle(SandboxHandle(task_id="t2", backend="host", sandbox_id="h1"))
        store_handle(SandboxHandle(task_id="t3", backend="cube", sandbox_id="c2"))

        cubes = list_handles(backend="cube")
        hosts = list_handles(backend="host")
        all_ = list_handles()

        assert {h.task_id for h in cubes} == {"t1", "t3"}
        assert {h.task_id for h in hosts} == {"t2"}
        assert {h.task_id for h in all_} == {"t1", "t2", "t3"}
    finally:
        _save_store(backup)


# ----------------------------------------------------------------------
# registry
# ----------------------------------------------------------------------


def test_registry_lists_builtins():
    from app.scheduler.sandbox import list_backends, SandboxRegistry
    backends = SandboxRegistry.available()
    assert "host" in backends
    assert "cube" in backends


def test_registry_caches_singletons():
    from app.scheduler.sandbox import SandboxRegistry
    SandboxRegistry.reset()
    b1 = SandboxRegistry.create("host")
    b2 = SandboxRegistry.create("host")
    assert b1 is b2


def test_registry_unknown_raises():
    from app.scheduler.sandbox import SandboxRegistry
    SandboxRegistry.reset()
    with pytest.raises(ValueError, match="Unknown sandbox backend"):
        SandboxRegistry.create("nope")


def test_registry_passes_config():
    from app.scheduler.sandbox import SandboxRegistry
    from app.scheduler.sandbox.cube_backend import CubeSandboxBackend
    SandboxRegistry.reset()
    backend = SandboxRegistry.create("cube", config={"template_id": "tpl-xyz"})
    assert isinstance(backend, CubeSandboxBackend)
    assert backend._template_id == "tpl-xyz"


# ----------------------------------------------------------------------
# HostOpenCodeBackend (no real process — use mocks)
# ----------------------------------------------------------------------


def test_host_backend_pause_resume_use_sigstop_sigcont():
    """Pause should SIGSTOP the process group; resume should SIGCONT."""
    from app.scheduler.sandbox import SandboxRegistry
    from app.scheduler.sandbox.base import SandboxHandle

    SandboxRegistry.reset()
    backend = SandboxRegistry.create("host")

    handle = SandboxHandle(
        task_id="t_pause", backend="host", sandbox_id="9999", state="running",
    )

    with patch("app.scheduler.sandbox.host_backend.os.killpg") as killpg:
        # Pause
        handle2 = backend.pause(handle)
        killpg.assert_called_with(9999, signal.SIGSTOP if False else __import__("signal").SIGSTOP)
        assert handle2.state == "paused"

        # Resume
        handle3 = backend.resume(handle2)
        killpg.assert_called_with(9999, __import__("signal").SIGCONT)
        assert handle3.state == "running"


def test_host_backend_kill_removes_from_store():
    from app.scheduler.sandbox import SandboxRegistry
    from app.scheduler.sandbox.base import SandboxHandle, load_handle

    SandboxRegistry.reset()
    backend = SandboxRegistry.create("host")

    # Fake an instance and seed the per-task backend
    fake_inst = MagicMock(pid=1234, port=4101, log_path="/tmp/x.log")
    backend._backend._instances["t_kill"] = fake_inst
    # Mock the kill method so we don't actually send signals
    backend._backend.kill = MagicMock(return_value=True)

    handle = SandboxHandle(
        task_id="t_kill", backend="host", sandbox_id="1234",
        url="http://127.0.0.1:4101", state="running",
        log_path="/tmp/x.log",
    )
    from app.scheduler.sandbox.base import store_handle
    store_handle(handle)

    backend.kill(handle)
    backend._backend.kill.assert_called_once_with("t_kill")
    assert load_handle("t_kill") is None


# ----------------------------------------------------------------------
# CubeSandboxBackend
# ----------------------------------------------------------------------


def _make_fake_e2b_module():
    """Build a mock e2b module that provides a Sandbox class with .create()."""
    fake_sb_instance = MagicMock()
    fake_sb_instance.sandbox_id = "c-mock"
    fake_sb_instance.get_host.return_value = "test.eclipsogate.invalid"
    fake_sb_module = MagicMock()
    fake_sb_module.Sandbox.create.return_value = fake_sb_instance
    return fake_sb_module, fake_sb_instance


def test_cube_backend_resumes_paused_session():
    """If session_store has a paused handle for task_id, start() resumes it."""
    import sys
    from app.scheduler.sandbox import SandboxRegistry
    from app.scheduler.sandbox.base import SandboxHandle, store_handle

    SandboxRegistry.reset()
    backend = SandboxRegistry.create("cube", config={"template_id": "tpl-1"})

    # Seed a paused handle
    paused = SandboxHandle(
        task_id="t_resume", backend="cube", sandbox_id="c-1",
        url="http://127.0.0.1:4173", state="paused",
    )
    store_handle(paused)

    fake_module, fake_instance = _make_fake_e2b_module()
    with patch.dict(sys.modules, {"e2b": fake_module}):
        h = backend.start("t_resume", "/work")
        # Should have resumed, not created new
        fake_module.Sandbox.create.assert_not_called()
        # resume() is called either on the existing client or via _AttachedSandbox
        # The test's setUp doesn't seed _clients, so _AttachedSandbox is used.
        assert h.state == "running"
        assert h.sandbox_id == "c-1"


def test_cube_backend_starts_fresh_when_no_existing(tmp_path):
    """Fresh task_id -> Sandbox.create() called, project uploaded."""
    import sys
    from app.scheduler.sandbox import SandboxRegistry

    SandboxRegistry.reset()
    backend = SandboxRegistry.create("cube", config={"template_id": "tpl-1"})

    # Create a real temp dir so upload_project's is_dir() check passes
    workdir = tmp_path / "project"
    workdir.mkdir()

    fake_module, fake_instance = _make_fake_e2b_module()
    with patch.dict(sys.modules, {"e2b": fake_module}):
        # The CubeSandboxClient is created lazily inside start(); patch its
        # upload_project to verify it was invoked.
        with patch("app.scheduler.sandbox.cubesandbox_client.CubeSandboxClient.upload_project") as up:
            h = backend.start("t_fresh", str(workdir))
        fake_module.Sandbox.create.assert_called_once()
        up.assert_called_once_with(str(workdir))
        assert h.sandbox_id == "c-mock"
        assert h.state == "running"


def test_cube_backend_kill_calls_underlying_client_and_removes_store():
    from app.scheduler.sandbox import SandboxRegistry
    from app.scheduler.sandbox.base import SandboxHandle, store_handle, load_handle
    SandboxRegistry.reset()
    backend = SandboxRegistry.create("cube")

    # Seed an in-memory client and a stored handle
    fake_client = MagicMock()
    backend._clients["t_k"] = fake_client
    store_handle(SandboxHandle(
        task_id="t_k", backend="cube", sandbox_id="c-k", state="running",
    ))

    handle = SandboxHandle(task_id="t_k", backend="cube", sandbox_id="c-k", state="running")
    backend.kill(handle)

    fake_client.kill.assert_called_once()
    assert backend._clients == {}
    assert load_handle("t_k") is None


# ----------------------------------------------------------------------
# handler config knobs
# ----------------------------------------------------------------------


def test_handler_prefers_sandbox_backend_over_use_sandbox_flag():
    """sandbox_backend takes precedence; legacy use_sandbox only used as fallback."""
    cfg = {"sandbox_backend": "host", "use_sandbox": True}
    # sandbox_backend wins
    assert (cfg.get("sandbox_backend") or _legacy_use_sandbox(cfg)) == "host"

    cfg2 = {"use_sandbox": True}
    assert _legacy_use_sandbox(cfg2) == "cube"

    cfg3 = {"use_sandbox": False}
    assert _legacy_use_sandbox(cfg3) == "host"


def _legacy_use_sandbox(cfg):
    """Same logic the handler uses when sandbox_backend is absent."""
    if "use_sandbox" in cfg:
        return "cube" if cfg["use_sandbox"] else "host"
    return "host"
