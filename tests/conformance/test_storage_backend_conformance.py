"""Conformance tests for pluggable mojo_memory storage backends."""

from __future__ import annotations

from typing import Any, Dict, List
import pytest

from mojo_memory.memory.multi_model_storage import MultiModelEmbeddingStorage
from mojo_memory.memory.knowledge_manager import KnowledgeManager
from mojo_memory.storage import (
    ConversationRecord,
    DuckDBStorageBackend,
    LocalFileStorageBackend,
    MirrorStorageBackend,
    StorageBackend,
    create_storage_backend,
    register_storage_backend,
    validate_conversation_record,
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


def test_duckdb_backend_roundtrip(tmp_path):
    pytest.importorskip("duckdb")
    db_path = tmp_path / "storage.duckdb"
    backend = DuckDBStorageBackend(db_path=db_path)
    backend.write_json("knowledge/test.json", {"x": 1})
    assert backend.read_json("knowledge/test.json") == {"x": 1}
    assert backend.exists("knowledge/test.json")
    assert "knowledge/test.json" in backend.list_keys("knowledge/")
    assert backend.delete("knowledge/test.json") is True


def test_multi_model_storage_supports_injected_backend():
    backend = InMemoryStorageBackend()
    store = MultiModelEmbeddingStorage(data_dir="/tmp/unused", storage_backend=backend)
    store._save_data([{"message_id": "m1"}], store.conversations_file)
    store2 = MultiModelEmbeddingStorage(data_dir="/tmp/unused", storage_backend=backend)
    assert len(store2.conversations) == 1
    assert store2.conversations[0]["message_id"] == "m1"


def test_knowledge_manager_supports_injected_backend():
    class DummyEmbedding:
        def get_batch_embeddings(self, texts):
            return [[0.1, 0.2] for _ in texts]

        def get_text_embedding(self, text):
            return [0.1, 0.2]

    backend = InMemoryStorageBackend()
    km = KnowledgeManager(
        embedding=DummyEmbedding(),
        collection_name="knowledge",
        data_dir="/tmp/unused",
        storage_backend=backend,
    )
    km.add_documents(["hello world"], [{"source": "test"}])
    km2 = KnowledgeManager(
        embedding=DummyEmbedding(),
        collection_name="knowledge",
        data_dir="/tmp/unused",
        storage_backend=backend,
    )
    assert len(km2.documents) == 1


def test_conversation_record_validation():
    rec = ConversationRecord(
        conversation_id="c1",
        message_id="m1",
        turn_index=0,
        role="user",
        content="hello",
        created_at="2026-05-11T00:00:00",
        status="incomplete",
    ).to_dict()
    ok, reason = validate_conversation_record(rec)
    assert ok, reason


def test_mirror_backend_writes_primary_and_mirror():
    p = InMemoryStorageBackend()
    m = InMemoryStorageBackend()
    mirror = MirrorStorageBackend(primary=p, mirrors=[m], compare_on_read=True)
    mirror.write_json("k1.json", {"v": 1})
    assert p.read_json("k1.json") == {"v": 1}
    assert m.read_json("k1.json") == {"v": 1}


def test_registry_builds_mirror_backend():
    backend = create_storage_backend(
        "mirror",
        primary={"name": "local_fs", "config": {"base_path": "/tmp/mojo-test-primary"}},
        mirrors=[{"name": "local_fs", "config": {"base_path": "/tmp/mojo-test-mirror"}}],
        compare_on_read=False,
    )
    assert isinstance(backend, MirrorStorageBackend)
