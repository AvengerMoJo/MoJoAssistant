"""
App-layer HybridMemoryService — wraps the submodule class with EmbeddingPool support.

WHY THIS FILE EXISTS
─────────────────────
The submodule's HybridMemoryService creates SimpleEmbedding instances directly
(mojo_memory.memory.simplified_embeddings.SimpleEmbedding) in two places:

  1. memory_service.py _setup_embedding()  — the primary single model
  2. hybrid_memory_service.py _setup_multi_model() — the additional models
     for multi-model fusion (bge-m3:1024, gemma:768, gemma:256)

Neither call goes through app.memory.embedding_pool, so:
  - No failover if the embedding backend crashes
  - No latency metrics in list_resources()
  - No auto-recovery after TTL

This subclass overrides both methods to use the pool-aware SimpleEmbedding
from app.memory.simplified_embeddings. Everything else is inherited unchanged.
"""
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Optional

_submodule_src = str(Path(__file__).resolve().parents[2] / "submodules" / "dreaming-memory-pipeline" / "src")
if _submodule_src not in sys.path:
    sys.path.insert(0, _submodule_src)

from mojo_memory.services.hybrid_memory_service import HybridMemoryService as _Base  # noqa: E402

# Re-export everything from the submodule for backward-compatible star imports
from mojo_memory.services.hybrid_memory_service import *  # noqa: F401,F403,E402

# Export provider factory for new code
from app.services.memory_backend import get_memory_provider  # noqa: F401,E402


class HybridMemoryService(_Base):
    """
    Drop-in replacement for the submodule's HybridMemoryService that routes
    all embedding creation through the EmbeddingPool.

    Behaviour is identical to the parent class except:
      - _setup_embedding uses app.memory.simplified_embeddings.SimpleEmbedding
        (pool-aware: failover, latency tracking, auto-recovery)
      - _setup_multi_model uses the same class for each additional model load
    """

    def _setup_embedding(
        self,
        model_name: str,
        backend: str,
        device: Optional[str] = None,
        **backend_kwargs: Any,
    ) -> None:
        """
        Override: creates the primary embedding via the EmbeddingPool.

        The pool-aware SimpleEmbedding checks the pool first (using model_name
        as the preferred_id hint). If no pool resource matches, it falls back
        to direct instantiation with the given backend/model_name — identical
        to the original behaviour.
        """
        from app.memory.simplified_embeddings import SimpleEmbedding as _PoolAware
        self.embedding = _PoolAware(
            backend=backend,
            model_name=model_name,
            device=device or "cpu",
            cache_dir=os.path.join(self.data_dir, "embedding_cache"),
            **backend_kwargs,
        )

    def _setup_multi_model(self) -> None:
        """
        Override: loads additional multi-model embeddings via the EmbeddingPool.

        Logic is identical to the parent class except SimpleEmbedding is
        imported from app.memory.simplified_embeddings (pool-aware) instead
        of the submodule path.

        Each model that is loaded directly (not reused from self.embedding) goes
        through the pool so latency is tracked and failover applies.
        """
        from app.memory.simplified_embeddings import SimpleEmbedding as _PoolAware
        from mojo_memory.memory.multi_model_storage import MultiModelEmbeddingStorage

        try:
            self.logger.info("Setting up multi-model embedding system (pool-aware)...")

            storage_cfg = self.config.get("storage", {}) if isinstance(self.config, dict) else {}
            self.multi_model_storage = MultiModelEmbeddingStorage(
                data_dir=self.data_dir,
                storage_backend_name=storage_cfg.get("backend", "local_fs"),
                storage_backend_config=storage_cfg.get("backend_config", {}),
            )

            priority_models = [
                ("bge-m3:1024", "BAAI/bge-m3", 1024),
                ("gemma:768", "google/embeddinggemma-300m", 768),
                ("gemma:256", "google/embeddinggemma-300m", 256),
            ]

            for model_key, model_name, embedding_dim in priority_models:
                try:
                    if model_name == self.embedding.model_name:
                        self.embedding_models[model_key] = self.embedding
                        self.logger.info(f"Reusing existing model: {model_key}")
                        continue

                    # Check if a different key already loaded this model
                    existing = next(
                        (m for m in self.embedding_models.values()
                         if hasattr(m, "model_name") and m.model_name == model_name),
                        None,
                    )
                    if existing:
                        self.embedding_models[model_key] = existing
                        self.logger.info(f"Reusing existing model {model_name} for {model_key}")
                        continue

                    cache_dir = os.path.join(
                        self.data_dir, "embedding_cache",
                        model_key.replace(":", "_"),
                    )
                    self.embedding_models[model_key] = _PoolAware(
                        backend="huggingface",
                        model_name=model_name,
                        embedding_dim=embedding_dim,
                        cache_dir=cache_dir,
                    )
                    self.logger.info(f"Loaded additional model via pool: {model_key}")

                except Exception as e:
                    self.logger.warning(f"Failed to load {model_key}: {e}")

            self.logger.info(
                f"Multi-model setup complete: {len(self.embedding_models)} models loaded"
            )

        except Exception as e:
            self.logger.error(f"Multi-model setup failed: {e}")
            self.logger.error(traceback.format_exc())
            self.multi_model_enabled = False
