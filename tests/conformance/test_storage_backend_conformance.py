"""Conformance tests for pluggable mojo_memory storage backends."""

from __future__ import annotations

from typing import Any, Dict, List

from mojo_memory.memory.multi_model_storage import MultiModelEmbeddingStorage
from mojo_memory.storage import (
    LocalFileStorageBackend,
    StorageBackend,
    create_storage_backend,
    register_storage_backend,
)


class InMemoryStorageBackend(StorageBackend):
    """Simple backend used to verify backend-agnostic integration."""

    def __init__(self):
        self.data: Dict[str, Any] = {}

    def read_json(self, key: str) -> Any | None:
        return self.data.get(key)

    def write_json(self, key: str, data: Any) -> None:
        self.data[key] = data

    def exists(self, key: str) -> bool:
        return key in self.data

    def delete(self, key: str) -> bool:
        if key not in self.data:
            return False
        del self.data[key]
        return True

    def list_keys(self, prefix: str = "") -> List[str]:
        keys = sorted(self.data.keys())
        if not prefix:
            return keys
        return [k for k in keys if k.startswith(prefix)]

    def health_check(self) -> Dict[str, Any]:
        return {"ok": True, "backend": "memory"}


def test_local_fs_backend_roundtrip(tmp_path):
    backend = LocalFileStorageBackend(base_path=tmp_path)
    backend.write_json("x/test.json", {"a": 1})
    assert backend.exists("x/test.json")
    assert backend.read_json("x/test.json") == {"a": 1}
    assert "x/test.json" in backend.list_keys("x/")
    assert backend.delete("x/test.json") is True
    assert backend.exists("x/test.json") is False


def test_registry_supports_custom_backend():
    register_storage_backend("in_memory_test", InMemoryStorageBackend)
    backend = create_storage_backend("in_memory_test")
    assert isinstance(backend, InMemoryStorageBackend)
    assert backend.health_check()["ok"] is True


def test_multi_model_storage_supports_injected_backend():
    backend = InMemoryStorageBackend()
    store = MultiModelEmbeddingStorage(data_dir="/tmp/unused", storage_backend=backend)
    store._save_data([{"message_id": "m1"}], store.conversations_file)
    store2 = MultiModelEmbeddingStorage(data_dir="/tmp/unused", storage_backend=backend)
    assert len(store2.conversations) == 1
    assert store2.conversations[0]["message_id"] == "m1"
