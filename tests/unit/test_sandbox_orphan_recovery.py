"""Unit tests for sandbox provenance (role/parent/env) + kill-by-id path.

Covers the v1.4.5 patch that:
  1. Extends SandboxHandle with role_id/parent_task_id/environment
  2. Adds find_by_sandbox_id() and list_orphan_sandbox_ids() helpers
  3. Adds CubeSandboxClient.kill_by_id() + list_cubemaster_sandboxes()
  4. Wires the new MCP tools (sandbox_kill_by_id, sandbox_purge_orphans,
     sandbox_find_by_id) in app/mcp/core/tools.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    """Point session store at tmp file; set inert E2B env so client preflight passes."""
    p = tmp_path / "sandbox_sessions.json"
    monkeypatch.setenv("SANDBOX_SESSION_STORE", str(p))
    monkeypatch.setenv("E2B_API_URL", "http://test-host.invalid")
    monkeypatch.setenv("E2B_API_KEY", "test-key-not-used")
    monkeypatch.setenv("CUBE_TEMPLATE_ID", "tpl-test")
    yield p


# ----------------------------------------------------------------------
# SandboxHandle provenance fields
# ----------------------------------------------------------------------


class TestSandboxHandleProvenance:
    """The new optional fields (role_id, parent_task_id, environment) must
    round-trip through to_dict/from_dict and survive JSON serialization."""

    def test_default_provenance_is_none(self):
        from app.scheduler.sandbox.base import SandboxHandle
        h = SandboxHandle(task_id="t1", backend="cube")
        assert h.role_id is None
        assert h.parent_task_id is None
        assert h.environment is None

    def test_provenance_round_trip(self):
        from app.scheduler.sandbox.base import (
            SandboxHandle, store_handle, load_handle,
        )
        h = SandboxHandle(
            task_id="t1", backend="cube", sandbox_id="sb-abc",
            role_id="rebecca", parent_task_id="parent-x", environment="dev",
        )
        store_handle(h)
        loaded = load_handle("t1")
        assert loaded.role_id == "rebecca"
        assert loaded.parent_task_id == "parent-x"
        assert loaded.environment == "dev"
        assert loaded.sandbox_id == "sb-abc"

    def test_provenance_survives_json_serialization(self, _tmp_store):
        from app.scheduler.sandbox.base import SandboxHandle, store_handle, SESSION_STORE_PATH
        # The SESSION_STORE_PATH constant is captured at module import time,
        # so the test env var might not be wired through. Use whatever the
        # active path is — that's the contract that matters.
        h = SandboxHandle(
            task_id="t2", backend="cube", sandbox_id="sb-def",
            role_id="popo", environment="prod",
        )
        store_handle(h)
        raw = json.loads(SESSION_STORE_PATH.read_text())
        assert raw["t2"]["role_id"] == "popo"
        assert raw["t2"]["environment"] == "prod"
        assert raw["t2"].get("parent_task_id") is None


# ----------------------------------------------------------------------
# find_by_sandbox_id / list_orphan_sandbox_ids
# ----------------------------------------------------------------------


class TestSandboxLookup:
    def test_find_by_sandbox_id_returns_handle(self):
        from app.scheduler.sandbox.base import (
            SandboxHandle, store_handle, find_by_sandbox_id,
        )
        store_handle(SandboxHandle(task_id="t1", backend="cube", sandbox_id="sb-1"))
        store_handle(SandboxHandle(task_id="t2", backend="host", sandbox_id="9999"))
        h = find_by_sandbox_id("sb-1")
        assert h is not None
        assert h.task_id == "t1"
        assert h.backend == "cube"

    def test_find_by_sandbox_id_returns_none_for_orphan(self):
        from app.scheduler.sandbox.base import (
            SandboxHandle, store_handle, find_by_sandbox_id,
        )
        store_handle(SandboxHandle(task_id="t1", backend="cube", sandbox_id="sb-1"))
        assert find_by_sandbox_id("unknown-sb-id") is None

    def test_find_by_sandbox_id_empty_input(self):
        from app.scheduler.sandbox.base import find_by_sandbox_id
        assert find_by_sandbox_id("") is None
        assert find_by_sandbox_id(None) is None

    def test_list_orphan_sandbox_ids(self):
        from app.scheduler.sandbox.base import (
            SandboxHandle, store_handle, list_orphan_sandbox_ids,
        )
        store_handle(SandboxHandle(task_id="t1", backend="cube", sandbox_id="known-1"))
        # CubeMaster reports 4 sandboxes; 3 are not in our registry
        orphan_ids = list_orphan_sandbox_ids(
            ["known-1", "orphan-A", "orphan-B", "orphan-C"]
        )
        assert orphan_ids == ["orphan-A", "orphan-B", "orphan-C"]

    def test_list_orphan_sandbox_ids_empty_input(self):
        from app.scheduler.sandbox.base import list_orphan_sandbox_ids
        assert list_orphan_sandbox_ids([]) == []


# ----------------------------------------------------------------------
# CubeSandboxClient.kill_by_id (the recovery path for stranded VMs)
# ----------------------------------------------------------------------


class TestCubeSandboxClientKillById:
    def test_kill_by_id_succeeds_via_e2b_sdk(self):
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient

        fake_attached = MagicMock()
        with patch("e2b.Sandbox") as MockSandbox:
            MockSandbox.connect.return_value = fake_attached
            result = CubeSandboxClient.kill_by_id("orphan-vm-abc")
        assert result["killed"] is True
        assert result["sandbox_id"] == "orphan-vm-abc"
        assert result["error"] is None
        assert result["path"] == "e2b_sdk"
        fake_attached.kill.assert_called_once()

    def test_kill_by_id_succeeds_via_http_fallback(self):
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient

        # No e2b SDK
        import sys
        original = sys.modules.get("e2b")
        sys.modules["e2b"] = None  # forces ImportError
        try:
            fake_resp = MagicMock()
            fake_resp.status_code = 204
            with patch("httpx.delete", return_value=fake_resp) as mock_delete:
                result = CubeSandboxClient.kill_by_id("orphan-vm-http")
            assert result["killed"] is True
            assert result["path"].startswith("http_delete")
            assert mock_delete.called
        finally:
            if original is not None:
                sys.modules["e2b"] = original
            else:
                sys.modules.pop("e2b", None)

    def test_kill_by_id_handles_http_404_as_success(self):
        """A 404 means the sandbox is already gone — treat as success."""
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient

        import sys
        original = sys.modules.get("e2b")
        sys.modules["e2b"] = None
        try:
            fake_resp = MagicMock()
            fake_resp.status_code = 404
            with patch("httpx.delete", return_value=fake_resp):
                result = CubeSandboxClient.kill_by_id("orphan-vm-404")
            assert result["killed"] is True
            assert "404" in result["path"]
        finally:
            if original is not None:
                sys.modules["e2b"] = original
            else:
                sys.modules.pop("e2b", None)

    def test_kill_by_id_handles_sdk_exception(self):
        """When both e2b SDK and HTTP fail, return error from HTTP attempt."""
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient

        with patch("e2b.Sandbox") as MockSandbox:
            MockSandbox.connect.side_effect = RuntimeError("not found")
            # HTTP also fails
            with patch("httpx.delete", side_effect=RuntimeError("network down")):
                result = CubeSandboxClient.kill_by_id("orphan-vm-xyz")
        assert result["killed"] is False
        assert "RuntimeError" in result["error"]
        assert "network down" in result["error"]

    def test_kill_by_id_missing_e2b_url(self, monkeypatch):
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient
        monkeypatch.delenv("E2B_API_URL", raising=False)
        result = CubeSandboxClient.kill_by_id("orphan-vm-abc")
        assert result["killed"] is False
        assert "E2B_API_URL" in result["error"]

    def test_kill_by_id_missing_e2b_key(self, monkeypatch):
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient
        monkeypatch.delenv("E2B_API_KEY", raising=False)
        result = CubeSandboxClient.kill_by_id("orphan-vm-abc")
        assert result["killed"] is False
        assert "E2B_API_KEY" in result["error"]

    def test_kill_by_id_empty_sandbox_id(self):
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient
        result = CubeSandboxClient.kill_by_id("")
        assert result["killed"] is False
        assert "sandbox_id is required" in result["error"]


# ----------------------------------------------------------------------
# CubeSandboxClient.list_cubemaster_sandboxes
# ----------------------------------------------------------------------


class TestCubeSandboxList:
    def test_list_returns_parsed_json(self):
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = [
            {"sandboxID": "vm-1", "clientID": "192.168.2.248"},
            {"sandboxID": "vm-2", "clientID": "192.168.2.248"},
        ]
        with patch("httpx.get", return_value=fake_resp):
            result = CubeSandboxClient.list_cubemaster_sandboxes()
        assert len(result) == 2
        # camelCase keys are normalized to snake_case
        assert result[0]["sandbox_id"] == "vm-1"
        assert result[0]["host_ip"] == "192.168.2.248"

    def test_list_unwraps_data_envelope(self):
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"data": [{"sandbox_id": "vm-x"}]}
        with patch("httpx.get", return_value=fake_resp):
            result = CubeSandboxClient.list_cubemaster_sandboxes()
        assert len(result) == 1
        assert result[0]["sandbox_id"] == "vm-x"

    def test_list_handles_http_error(self):
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient

        fake_resp = MagicMock()
        fake_resp.status_code = 500
        with patch("httpx.get", return_value=fake_resp):
            result = CubeSandboxClient.list_cubemaster_sandboxes()
        assert result == []

    def test_list_handles_no_api_url(self, monkeypatch):
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient
        monkeypatch.delenv("E2B_API_URL", raising=False)
        result = CubeSandboxClient.list_cubemaster_sandboxes()
        assert result == []


class TestSandboxNormalization:
    def test_camelcase_to_snake_case(self):
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient
        out = CubeSandboxClient._normalize_sandbox({
            "sandboxID": "abc",
            "clientID": "192.168.2.248",
            "startedAt": "2026-06-21T14:51:13Z",
            "templateID": "tpl-x",
            "cpuCount": 2,
            "memoryMB": 2048,
        })
        assert out["sandbox_id"] == "abc"
        assert out["host_ip"] == "192.168.2.248"
        assert out["create_at"] == "2026-06-21T14:51:13Z"
        assert out["template_id"] == "tpl-x"
        assert out["cpu_count"] == 2
        assert out["memory_mb"] == 2048

    def test_snake_case_passthrough(self):
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient
        out = CubeSandboxClient._normalize_sandbox({"sandbox_id": "x"})
        assert out["sandbox_id"] == "x"

    def test_handles_missing_keys(self):
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient
        out = CubeSandboxClient._normalize_sandbox({})
        assert out["sandbox_id"] is None
        assert out["host_ip"] is None


# ----------------------------------------------------------------------
# Backends: verify provenance kwargs flow through start()
# ----------------------------------------------------------------------


class TestBackendProvenancePassThrough:
    def test_cube_backend_stores_provenance(self, monkeypatch):
        from app.scheduler.sandbox.cube_backend import CubeSandboxBackend
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient

        # Patch the e2b SDK so the client doesn't try to talk to a real host
        fake_sandbox = MagicMock()
        fake_sandbox.sandbox_id = "fake-vm-123"

        class FakeClient:
            def __init__(self, *a, **kw): pass
            def start(self): return "fake-vm-123"
            def get_opencode_url(self): return "http://127.0.0.1:4173"
            def upload_project(self, path): pass
            def _append_log(self, *a): pass

        monkeypatch.setattr(CubeSandboxClient, "__init__", lambda self, **kw: None)
        monkeypatch.setattr(CubeSandboxClient, "start", lambda self: "fake-vm-123")
        monkeypatch.setattr(
            CubeSandboxClient, "get_opencode_url", lambda self: "http://127.0.0.1:4173"
        )
        monkeypatch.setattr(CubeSandboxClient, "upload_project", lambda self, p: None)

        backend = CubeSandboxBackend()
        h = backend.start(
            task_id="t-cube-1",
            working_dir="/tmp",
            role_id="rebecca",
            parent_task_id="parent-A",
            environment="dev-sandbox",
        )
        assert h.role_id == "rebecca"
        assert h.parent_task_id == "parent-A"
        assert h.environment == "dev-sandbox"
        assert h.sandbox_id == "fake-vm-123"
        assert h.backend == "cube"

    def test_cube_backend_provenance_defaults_to_none(self, monkeypatch):
        from app.scheduler.sandbox.cube_backend import CubeSandboxBackend
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient

        monkeypatch.setattr(CubeSandboxClient, "__init__", lambda self, **kw: None)
        monkeypatch.setattr(CubeSandboxClient, "start", lambda self: "fake-vm-456")
        monkeypatch.setattr(
            CubeSandboxClient, "get_opencode_url", lambda self: "http://127.0.0.1:4173"
        )
        monkeypatch.setattr(CubeSandboxClient, "upload_project", lambda self, p: None)

        backend = CubeSandboxBackend()
        h = backend.start(task_id="t-cube-2", working_dir="/tmp")
        assert h.role_id is None
        assert h.parent_task_id is None
        assert h.environment is None


# ----------------------------------------------------------------------
# MCP tool surface: registry check (no full execute — that requires
# the FastMCP server). Just verify the tool definitions and dispatcher
# branches exist.
# ----------------------------------------------------------------------


class TestMCPToolRegistration:
    def test_new_tool_definitions_present(self):
        from app.mcp.core.tools import ToolRegistry
        # The engine is heavy to construct; instead, just verify the
        # class-level method names exist on the class.
        assert hasattr(ToolRegistry, "_execute_sandbox_kill_by_id")
        assert hasattr(ToolRegistry, "_execute_sandbox_purge_orphans")
        assert hasattr(ToolRegistry, "_execute_sandbox_find_by_id")

    def test_sandbox_package_exports_new_helpers(self):
        import app.scheduler.sandbox as pkg
        assert hasattr(pkg, "find_by_sandbox_id")
        assert hasattr(pkg, "list_orphan_sandbox_ids")
        assert "find_by_sandbox_id" in pkg.__all__
        assert "list_orphan_sandbox_ids" in pkg.__all__


# ----------------------------------------------------------------------
# End-to-end recovery simulation: the actual 5-orphan scenario
# ----------------------------------------------------------------------


class TestOrphanRecoveryE2E:
    """Reproduce the exact failure mode: 5 sandboxes exist on CubeMaster
    but none are in sandbox_sessions.json. Verify purge_orphans + kill_by_id
    can clean them up."""

    def test_purge_orphans_dry_run_identifies_all_5(self):
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient

        # Use a sandbox_id set that is guaranteed not to collide with any
        # real persisted handle (UUIDs that match no real session).
        five_orphans = [
            {"sandbox_id": sid, "sandbox_ip": f"192.168.0.{i+8}"}
            for i, sid in enumerate([
                "deadbeef000000000000000000000001",
                "deadbeef000000000000000000000002",
                "deadbeef000000000000000000000003",
                "deadbeef000000000000000000000004",
                "deadbeef000000000000000000000005",
            ])
        ]
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = five_orphans

        with patch("httpx.get", return_value=fake_resp):
            cubes = CubeSandboxClient.list_cubemaster_sandboxes()
        assert len(cubes) == 5

        # Store has nothing for these UUIDs — all 5 are orphans
        from app.scheduler.sandbox.base import list_orphan_sandbox_ids
        all_ids = [c["sandbox_id"] for c in cubes]
        orphans = list_orphan_sandbox_ids(all_ids)
        assert len(orphans) == 5
        assert "deadbeef000000000000000000000001" in orphans

    def test_kill_all_5_orphans_via_e2b(self):
        """If we set auto_kill=True, all 5 should be killed via e2b SDK."""
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient

        five_ids = [
            "cafef00d000000000000000000000001",
            "cafef00d000000000000000000000002",
            "cafef00d000000000000000000000003",
            "cafef00d000000000000000000000004",
            "cafef00d000000000000000000000005",
        ]
        killed = []
        for sid in five_ids:
            with patch("e2b.Sandbox") as MockSandbox:
                fake = MagicMock()
                MockSandbox.connect.return_value = fake
                r = CubeSandboxClient.kill_by_id(sid)
                if r["killed"]:
                    killed.append(sid)
        assert len(killed) == 5

    def test_partial_orphan_set_when_one_is_known(self):
        """If one of the 5 has a persisted handle, only the other 4 are orphans."""
        from app.scheduler.sandbox.base import (
            SandboxHandle, store_handle, list_orphan_sandbox_ids,
        )

        five_ids = [
            "9c9d049641b04125a08b913cf5554942",
            "734a4c474aee4eb0a00d333fda7c9ffd",
            "7ca7404343d149079de6f24831ebbd99",
            "2d2282cd5a9a4e5d949cc1e5bb3837c2",
            "08b0937a9e234bc893cb989ad8200ab3",
        ]
        # The 2nd one is known
        store_handle(SandboxHandle(
            task_id="t-recovered", backend="cube",
            sandbox_id="734a4c474aee4eb0a00d333fda7c9ffd",
            role_id="rebecca",
        ))
        orphans = list_orphan_sandbox_ids(five_ids)
        assert "734a4c474aee4eb0a00d333fda7c9ffd" not in orphans
        assert len(orphans) == 4
