"""Integration test: storage backend swap via factory.

Verifies that:
1. resolve_storage_backend() returns a working StorageBackend
2. The factory can be overridden via MOJO_STORAGE_BACKEND env var
3. The dreaming handler uses the factory (not hardcoded JsonFileBackend)
4. The MCP tools use the factory (not hardcoded JsonFileBackend)
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Stub backend for swap verification
# ---------------------------------------------------------------------------

class _StubStorageBackend:
    """Stub backend that records calls for verification.

    Matches the JsonFileBackend interface (archive-oriented), not the
    StorageBackend ABC (key-value). This is the interface used by the
    dreaming handler and MCP tools.
    """

    def __init__(self, storage_path: Path = None):
        self.storage_path = storage_path
        self.archives: Dict[str, Any] = {}
        self.manifests: Dict[str, Any] = {}
        self.calls: list = []

    def save_archive(self, conversation_id: str, data: Any, version: int = 0) -> str:
        self.calls.append(("save_archive", conversation_id, version))
        key = f"{conversation_id}_v{version}"
        self.archives[key] = data
        return key

    def load_archive(self, conversation_id: str, version: int = None) -> Any:
        self.calls.append(("load_archive", conversation_id, version))
        if version is None:
            # Return latest
            matching = [k for k in self.archives if k.startswith(f"{conversation_id}_v")]
            if matching:
                return self.archives[sorted(matching)[-1]]
            return None
        return self.archives.get(f"{conversation_id}_v{version}")

    def list_archives(self) -> list:
        self.calls.append(("list_archives",))
        return list(self.archives.keys())

    def get_manifest(self, conversation_id: str) -> Any:
        self.calls.append(("get_manifest", conversation_id))
        return self.manifests.get(conversation_id)

    def update_manifest(self, conversation_id: str, data: Any) -> None:
        self.calls.append(("update_manifest", conversation_id))
        self.manifests[conversation_id] = data

    def get_latest_version(self, conversation_id: str) -> int:
        self.calls.append(("get_latest_version", conversation_id))
        matching = [k for k in self.archives if k.startswith(f"{conversation_id}_v")]
        if matching:
            return int(sorted(matching)[-1].split("_v")[-1])
        return 0

    # Interface used by resolve_storage_backend
    def read_json(self, key: str) -> Any:
        self.calls.append(("read_json", key))
        return self.archives.get(key)

    def write_json(self, key: str, data: Any) -> None:
        self.calls.append(("write_json", key))
        self.archives[key] = data

    def exists(self, key: str) -> bool:
        self.calls.append(("exists", key))
        return key in self.archives

    def delete(self, key: str) -> bool:
        self.calls.append(("delete", key))
        if key not in self.archives:
            return False
        del self.archives[key]
        return True

    def list_keys(self, prefix: str = "") -> List[str]:
        self.calls.append(("list_keys", prefix))
        keys = sorted(self.archives.keys())
        if not prefix:
            return keys
        return [k for k in keys if k.startswith(prefix)]

    def health_check(self) -> Dict[str, Any]:
        self.calls.append(("health_check",))
        return {"ok": True, "backend": "stub"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStorageFactory:
    """Test the storage factory resolves backends correctly."""

    def test_resolve_returns_default_backend(self, tmp_path):
        """Default resolution returns a backend with the expected dream archive interface."""
        from app.services.storage_factory import resolve_storage_backend

        # Reset cached backend class
        import app.services.storage_factory as mod
        mod._backend_class = None

        backend = resolve_storage_backend(storage_path=tmp_path / "test")
        assert backend is not None
        # Dream archive backend has these methods (not StorageBackend ABC)
        assert hasattr(backend, "save_archive")
        assert hasattr(backend, "load_archive")
        assert hasattr(backend, "list_archives")

    def test_resolve_caches_backend_class(self, tmp_path):
        """Subsequent calls reuse the cached backend class."""
        from app.services.storage_factory import resolve_storage_backend
        import app.services.storage_factory as mod
        mod._backend_class = None

        b1 = resolve_storage_backend(storage_path=tmp_path / "a")
        b2 = resolve_storage_backend(storage_path=tmp_path / "b")
        # Different instances, same class
        assert type(b1) is type(b2)
        assert b1 is not b2

    def test_resolve_respects_env_override(self, tmp_path):
        """MOJO_STORAGE_BACKEND env var selects a different backend."""
        import app.services.storage_factory as mod
        mod._backend_class = None

        env_val = "tests.integration.test_storage_swap._StubStorageBackend"
        with patch.dict(os.environ, {"MOJO_STORAGE_BACKEND": env_val}):
            from app.services.storage_factory import resolve_storage_backend
            backend = resolve_storage_backend(storage_path=tmp_path / "test")
            assert isinstance(backend, _StubStorageBackend)
            assert backend.storage_path == tmp_path / "test"


class TestDreamingHandlerUsesFactory:
    """Verify the dreaming handler imports from the factory, not JsonFileBackend directly."""

    def test_dreaming_handler_no_direct_json_import(self):
        """dreaming.py should not import JsonFileBackend directly."""
        dreaming_path = Path(__file__).resolve().parents[2] / "app" / "scheduler" / "handlers" / "dreaming.py"
        source = dreaming_path.read_text(encoding="utf-8")
        # Should NOT have direct import of JsonFileBackend
        assert "from dreaming.storage.json_backend import JsonFileBackend" not in source
        # Should import from the factory
        assert "from app.services.storage_factory import resolve_storage_backend" in source

    def test_tools_no_direct_json_import(self):
        """tools.py should not import JsonFileBackend directly."""
        tools_path = Path(__file__).resolve().parents[2] / "app" / "mcp" / "core" / "tools.py"
        source = tools_path.read_text(encoding="utf-8")
        # Should NOT have direct import of JsonFileBackend in business logic
        # (the factory is the only allowed location)
        lines = source.splitlines()
        direct_imports = [
            i for i, line in enumerate(lines, 1)
            if "from dreaming.storage.json_backend import JsonFileBackend" in line
        ]
        assert direct_imports == [], (
            f"tools.py still has direct JsonFileBackend imports at lines {direct_imports}. "
            f"Use app.services.storage_factory.resolve_storage_backend() instead."
        )


class TestStorageSwapEndToEnd:
    """End-to-end: swap storage backend and verify it's used by the system."""

    def test_factory_stub_backend_works_with_dreaming_storage(self, tmp_path):
        """Stub backend can be used in place of JsonFileBackend for dream storage."""
        import app.services.storage_factory as mod
        mod._backend_class = None

        env_val = "tests.integration.test_storage_swap._StubStorageBackend"
        with patch.dict(os.environ, {"MOJO_STORAGE_BACKEND": env_val}):
            from app.services.storage_factory import resolve_storage_backend
            backend = resolve_storage_backend(storage_path=tmp_path / "dreams")

            # Verify the stub is used
            assert isinstance(backend, _StubStorageBackend)

            # Verify basic operations work
            backend.write_json("test_key", {"data": "value"})
            assert backend.read_json("test_key") == {"data": "value"}
            assert backend.exists("test_key")
            assert backend.list_keys() == ["test_key"]
            assert backend.health_check()["ok"] is True

    def test_factory_stub_records_calls(self, tmp_path):
        """Stub backend records all calls for verification."""
        import app.services.storage_factory as mod
        mod._backend_class = None

        env_val = "tests.integration.test_storage_swap._StubStorageBackend"
        with patch.dict(os.environ, {"MOJO_STORAGE_BACKEND": env_val}):
            from app.services.storage_factory import resolve_storage_backend
            backend = resolve_storage_backend(storage_path=tmp_path / "dreams")

            backend.write_json("k1", "v1")
            backend.read_json("k1")
            backend.exists("k1")
            backend.list_keys()

            assert ("write_json", "k1") in backend.calls
            assert ("read_json", "k1") in backend.calls
            assert ("exists", "k1") in backend.calls
            assert ("list_keys", "") in backend.calls

            # Verify manifest round-trip through the swapped backend
            backend.update_manifest("conv1", {"stage": "B", "count": 3})
            result = backend.get_manifest("conv1")
            assert result == {"stage": "B", "count": 3}
            assert ("update_manifest", "conv1") in backend.calls
            assert ("get_manifest", "conv1") in backend.calls
