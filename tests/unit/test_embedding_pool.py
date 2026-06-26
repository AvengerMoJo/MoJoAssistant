"""Unit tests for EmbeddingPool."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.memory.embedding_pool import EmbeddingPool, EmbeddingResource, get_embedding_pool


@pytest.fixture
def temp_config(tmp_path):
    """Create a temporary embedding config file."""
    config = {
        "embedding_models": {
            "primary": {
                "backend": "huggingface",
                "model_name": "BAAI/bge-m3",
                "embedding_dim": 1024,
                "priority": 10,
                "enabled": True,
            },
            "fast": {
                "backend": "huggingface",
                "model_name": "BAAI/bge-small-en-v1.5",
                "embedding_dim": 384,
                "priority": 20,
                "enabled": True,
            },
            "disabled": {
                "backend": "huggingface",
                "model_name": "test-model",
                "embedding_dim": 768,
                "priority": 5,
                "enabled": False,
            },
            "api-model": {
                "backend": "api",
                "model_name": "text-embedding-3-small",
                "api_key": "test-key",
                "embedding_dim": 1536,
                "priority": 30,
                "enabled": True,
            },
            "fallback": {
                "backend": "random",
                "embedding_dim": 768,
                "priority": 99,
                "enabled": True,
            },
        }
    }
    config_path = tmp_path / "embedding_config.json"
    config_path.write_text(json.dumps(config))
    return str(config_path)


class TestEmbeddingPool:
    def test_loads_config(self, temp_config):
        pool = EmbeddingPool(config_path=temp_config)
        resources = pool.list_resources()
        assert len(resources) == 5

    def test_acquire_returns_highest_priority(self, temp_config):
        pool = EmbeddingPool(config_path=temp_config)
        resource = pool.acquire()
        assert resource is not None
        # primary has priority 10, disabled has 5 but is disabled
        assert resource.id == "primary"
        assert resource.priority == 10

    def test_acquire_skips_disabled(self, temp_config):
        pool = EmbeddingPool(config_path=temp_config)
        resource = pool.acquire()
        assert resource.id != "disabled"

    def test_acquire_skips_failed(self, temp_config):
        pool = EmbeddingPool(config_path=temp_config)
        pool.mark_failed("primary", "test error")
        resource = pool.acquire()
        assert resource.id == "fast"

    def test_acquire_with_preferred(self, temp_config):
        pool = EmbeddingPool(config_path=temp_config)
        resource = pool.acquire(preferred_id="api-model")
        assert resource.id == "api-model"

    def test_acquire_with_min_dim(self, temp_config):
        pool = EmbeddingPool(config_path=temp_config)
        resource = pool.acquire(min_dim=1000)
        assert resource.embedding_dim >= 1000

    def test_acquire_with_fallback(self, temp_config):
        pool = EmbeddingPool(config_path=temp_config)
        resources = pool.acquire_with_fallback(strict_dim=False)
        assert len(resources) == 4  # disabled excluded
        assert resources[0].id == "primary"
        assert resources[-1].id == "fallback"

    def test_acquire_with_fallback_strict_dim(self, temp_config):
        pool = EmbeddingPool(config_path=temp_config)
        resources = pool.acquire_with_fallback(strict_dim=True)
        # Only resources with dim matching primary (1024) are returned
        assert all(r.embedding_dim == 1024 for r in resources)

    def test_mark_failed_and_recover(self, temp_config):
        pool = EmbeddingPool(config_path=temp_config)
        pool.mark_failed("primary", "test error")
        r = pool.get_resource("primary")
        assert r.status == "failed"
        assert r.last_error == "test error"
        assert r.failed_at > 0

        pool.mark_available("primary")
        r = pool.get_resource("primary")
        assert r.status == "available"
        assert r.last_error is None
        assert r.failed_at == 0

    def test_auto_recovery_after_ttl(self, temp_config):
        pool = EmbeddingPool(config_path=temp_config, recovery_ttl=1)
        pool.mark_failed("primary", "test error")
        r = pool.acquire()
        assert r.id != "primary"  # primary is failed, should skip

        # Wait for TTL to expire
        import time
        time.sleep(1.1)
        r = pool.acquire()
        assert r.id == "primary"  # primary should be recovered

    def test_reload(self, temp_config):
        pool = EmbeddingPool(config_path=temp_config)
        assert len(pool.list_resources()) == 5

        # Modify config
        config = json.loads(Path(temp_config).read_text())
        config["embedding_models"]["new-model"] = {
            "backend": "huggingface",
            "model_name": "test",
            "embedding_dim": 512,
            "priority": 15,
            "enabled": True,
        }
        Path(temp_config).write_text(json.dumps(config))

        pool.reload()
        assert len(pool.list_resources()) == 6

    def test_env_override(self, temp_config, monkeypatch):
        monkeypatch.setenv("EMBEDDING_MODEL", "fast")
        pool = EmbeddingPool(config_path=temp_config)
        resource = pool.acquire()
        # fast should now have priority 0 due to env override
        assert resource.id == "fast"

    def test_empty_config(self, tmp_path):
        config_path = tmp_path / "empty.json"
        config_path.write_text("{}")
        pool = EmbeddingPool(config_path=str(config_path))
        assert pool.acquire() is None
        assert pool.list_resources() == []
