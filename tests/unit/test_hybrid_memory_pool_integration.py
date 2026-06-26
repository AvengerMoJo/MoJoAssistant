"""
Tests that HybridMemoryService._setup_embedding and _setup_multi_model
use the pool-aware SimpleEmbedding from app.memory.simplified_embeddings,
NOT the submodule's bare SimpleEmbedding.

These are unit tests — they mock EmbeddingPool and SimpleEmbedding to avoid
loading real HuggingFace models.
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_submodule_src = str(
    Path(__file__).resolve().parents[3]
    / "submodules" / "dreaming-memory-pipeline" / "src"
)
if _submodule_src not in sys.path:
    sys.path.insert(0, _submodule_src)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_embedding(model_name: str = "BAAI/bge-m3", dim: int = 1024):
    """Minimal SimpleEmbedding-like object."""
    m = MagicMock()
    m.model_name = model_name
    m.embedding_dim = dim
    m.get_text_embedding.return_value = [0.0] * dim
    return m


def _make_fake_storage():
    m = MagicMock()
    m.conversations = []
    m.documents = []
    return m


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSetupEmbeddingUsesPool:
    """_setup_embedding should use app.memory.simplified_embeddings.SimpleEmbedding."""

    def test_setup_embedding_calls_pool_aware_class(self, tmp_path):
        """
        When HybridMemoryService is instantiated, the _setup_embedding override
        must call app.memory.simplified_embeddings.SimpleEmbedding — not the
        submodule version.
        """
        fake_embedding = _make_fake_embedding()
        fake_storage = _make_fake_storage()

        with (
            patch("app.memory.simplified_embeddings.SimpleEmbedding", return_value=fake_embedding) as mock_cls,
            patch("mojo_memory.memory.multi_model_storage.MultiModelEmbeddingStorage", return_value=fake_storage),
            patch("mojo_memory.memory.archival_memory.ArchivalMemory"),
            patch("mojo_memory.memory.knowledge_manager.KnowledgeManager"),
            patch("mojo_memory.memory.working_memory.WorkingMemory"),
            patch("mojo_memory.memory.active_memory.ActiveMemory"),
        ):
            from app.services.hybrid_memory_service import HybridMemoryService
            svc = HybridMemoryService(data_dir=str(tmp_path))

        # Our pool-aware SimpleEmbedding must have been called (for primary model)
        assert mock_cls.called, "_setup_embedding did not use app.memory.simplified_embeddings.SimpleEmbedding"
        call_kwargs = mock_cls.call_args.kwargs if mock_cls.call_args.kwargs else {}
        call_args = mock_cls.call_args.args if mock_cls.call_args.args else ()
        # preferred_model must be passed so the pool can look it up
        assert "preferred_model" in call_kwargs or any("BAAI" in str(a) for a in call_args + tuple(call_kwargs.values())), (
            "_setup_embedding did not pass preferred_model to SimpleEmbedding"
        )


class TestSetupMultiModelUsesPool:
    """_setup_multi_model should use pool-aware SimpleEmbedding for each additional model."""

    def test_additional_models_use_pool_aware_class(self, tmp_path):
        """
        When multi_model_enabled=True, each additional model (not reusing self.embedding)
        must be created via app.memory.simplified_embeddings.SimpleEmbedding.
        The submodule's SimpleEmbedding must NOT be called directly.
        """
        primary = _make_fake_embedding("BAAI/bge-m3", 1024)
        gemma_768 = _make_fake_embedding("google/embeddinggemma-300m", 768)
        gemma_256 = _make_fake_embedding("google/embeddinggemma-300m", 256)
        fake_storage = _make_fake_storage()

        call_log = []
        def pool_aware_factory(*args, **kwargs):
            m = _make_fake_embedding(
                kwargs.get("model_name", "unknown"),
                kwargs.get("embedding_dim", 768),
            )
            call_log.append(kwargs.get("model_name"))
            return m

        with (
            patch("app.memory.simplified_embeddings.SimpleEmbedding", side_effect=pool_aware_factory) as mock_cls,
            patch("mojo_memory.memory.multi_model_storage.MultiModelEmbeddingStorage", return_value=fake_storage),
            patch("mojo_memory.memory.archival_memory.ArchivalMemory"),
            patch("mojo_memory.memory.knowledge_manager.KnowledgeManager"),
            patch("mojo_memory.memory.working_memory.WorkingMemory"),
            patch("mojo_memory.memory.active_memory.ActiveMemory"),
        ):
            from app.services.hybrid_memory_service import HybridMemoryService
            svc = HybridMemoryService(
                data_dir=str(tmp_path),
                config={"multi_model_enabled": True},
            )

        # Pool-aware factory should have been called for primary + additional models
        assert mock_cls.called
        # All model creation went through pool-aware class
        for name in call_log:
            assert name in ("BAAI/bge-m3", "google/embeddinggemma-300m"), (
                f"Unexpected model name in pool-aware calls: {name}"
            )

    def test_submodule_simple_embedding_not_called_directly(self, tmp_path):
        """
        The submodule's mojo_memory.memory.simplified_embeddings.SimpleEmbedding
        must NOT be called for model creation when multi_model_enabled=True.
        It may be imported, but not instantiated.
        """
        fake_storage = _make_fake_storage()

        with (
            patch("app.memory.simplified_embeddings.SimpleEmbedding") as pool_cls,
            patch("mojo_memory.memory.simplified_embeddings.SimpleEmbedding") as submodule_cls,
            patch("mojo_memory.memory.multi_model_storage.MultiModelEmbeddingStorage", return_value=fake_storage),
            patch("mojo_memory.memory.archival_memory.ArchivalMemory"),
            patch("mojo_memory.memory.knowledge_manager.KnowledgeManager"),
            patch("mojo_memory.memory.working_memory.WorkingMemory"),
            patch("mojo_memory.memory.active_memory.ActiveMemory"),
        ):
            pool_cls.return_value = _make_fake_embedding()
            submodule_cls.return_value = _make_fake_embedding()

            from app.services.hybrid_memory_service import HybridMemoryService
            svc = HybridMemoryService(
                data_dir=str(tmp_path),
                config={"multi_model_enabled": True},
            )

        assert submodule_cls.call_count == 0, (
            f"Submodule SimpleEmbedding was instantiated {submodule_cls.call_count} times — "
            "should be 0 (all creation must go through pool-aware class)"
        )
        assert pool_cls.call_count > 0, "Pool-aware SimpleEmbedding was never called"


class TestGetHybridMemoryServiceClassDefault:
    """memory_backend.get_hybrid_memory_service_class must return the app-layer override."""

    def test_default_class_is_pool_aware_override(self):
        from app.services.memory_backend import get_hybrid_memory_service_class
        klass = get_hybrid_memory_service_class()
        assert klass.__module__ == "app.services.hybrid_memory_service", (
            f"Expected app.services.hybrid_memory_service, got {klass.__module__}"
        )
        assert klass._setup_embedding.__qualname__.startswith("HybridMemoryService"), (
            "_setup_embedding not overridden by app-layer class"
        )
        assert klass._setup_multi_model.__qualname__.startswith("HybridMemoryService"), (
            "_setup_multi_model not overridden by app-layer class"
        )
