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
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

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

    async def evaluate_consolidation(
        self,
        query_set: list[str],
        role_id: str = "unknown",
        top_k: int = 5,
    ) -> float:
        """Return mean top-k relevance score for query_set.

        Used by ConsolidationEvaluator to measure retrieval quality
        before and after dreaming consolidation.
        """
        scores = []
        for q in query_set:
            try:
                results = await self.get_context_for_query_async(
                    q, max_items=top_k, role_id=role_id
                )
                if results:
                    scores.append(
                        sum(
                            r.get("relevance_score", r.get("relevance", 0.0))
                            for r in results
                        ) / len(results)
                    )
                else:
                    scores.append(0.0)
            except Exception:
                scores.append(0.0)
        return sum(scores) / len(scores) if scores else 0.0

    def add_to_knowledge_base(
        self, document: str, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Override to inject action metadata defaults into every new unit."""
        if metadata is None:
            metadata = {}
        metadata.setdefault("action_history", [])
        metadata.setdefault("confidence_score", 1.0)
        metadata.setdefault("last_validated", datetime.now(timezone.utc).isoformat())
        super().add_to_knowledge_base(document, metadata)

    def execute_action(self, action: Any, role_id: str) -> dict:
        """Execute a single typed MemoryAction.

        Returns result dict with:
        {"success": bool, "action_type": str, "affected_ids": List[str], "error": str}
        """
        from app.memory.memory_action import MemoryActionType

        try:
            action.validate()
        except ValueError as e:
            return {"success": False, "error": str(e), "action_type": action.action_type.value}

        t = action.action_type
        try:
            if t == MemoryActionType.INSERT_UNIT:
                self.add_to_knowledge_base(action.content, metadata={
                    **action.metadata,
                    "proposed_by": action.proposed_by,
                    "action_reason": action.reason,
                })
                return {"success": True, "action_type": t.value, "affected_ids": []}

            elif t == MemoryActionType.UPDATE_FACTS:
                self._retire_unit(action.target_ids[0], role_id)
                self.add_to_knowledge_base(action.content, metadata={
                    **action.metadata,
                    "replaces": action.target_ids[0],
                    "proposed_by": action.proposed_by,
                })
                return {"success": True, "action_type": t.value, "affected_ids": action.target_ids}

            elif t == MemoryActionType.MERGE_UNITS:
                merged_text = action.content or self._merge_unit_texts(action.target_ids, role_id)
                for uid in action.target_ids:
                    self._retire_unit(uid, role_id)
                self.add_to_knowledge_base(merged_text, metadata={
                    **action.metadata,
                    "merged_from": action.target_ids,
                    "proposed_by": action.proposed_by,
                })
                return {"success": True, "action_type": t.value, "affected_ids": action.target_ids}

            elif t == MemoryActionType.RETIRE_STALE:
                for uid in action.target_ids:
                    self._retire_unit(uid, role_id)
                return {"success": True, "action_type": t.value, "affected_ids": action.target_ids}

            return {"success": False, "error": f"Unknown action type: {t}"}
        except Exception as e:
            return {"success": False, "error": str(e), "action_type": action.action_type.value}

    def execute_actions(self, actions: list, role_id: str) -> list:
        """Execute a list of MemoryActions in order. Stops on first failure."""
        results = []
        for action in actions:
            result = self.execute_action(action, role_id)
            results.append(result)
            if not result.get("success"):
                break
        return results

    def _retire_unit(self, unit_id: str, role_id: str) -> None:
        """Remove a knowledge unit and its chunk embeddings (hard-delete from search index).

        The submodule's query() returns (text, score) tuples with no metadata
        filtering, so metadata-only soft-delete leaves the unit searchable.
        We must remove both the document and its chunk embeddings so it no longer
        appears in results. The action_history on the caller's MemoryAction provides
        the audit trail.
        """
        if not hasattr(self, "knowledge_manager") or not self.knowledge_manager:
            return

        before = len(self.knowledge_manager.documents)
        self.knowledge_manager.documents = [
            d for d in self.knowledge_manager.documents if d.get("id") != unit_id
        ]
        if len(self.knowledge_manager.documents) == before:
            logger.warning("_retire_unit: unit %s not found", unit_id)
            return

        self.knowledge_manager.chunk_embeddings = [
            e for e in self.knowledge_manager.chunk_embeddings
            if e.get("doc_id") != unit_id
        ]
        self.knowledge_manager._save_data()

    def _merge_unit_texts(self, target_ids: list, role_id: str) -> str:
        """Auto-generate merged text from two knowledge units."""
        if not hasattr(self, "knowledge_manager") or not self.knowledge_manager:
            return ""
        texts = []
        for doc in self.knowledge_manager.documents:
            if doc.get("id") in target_ids:
                texts.append(doc.get("text", ""))
        return "\n\n---\n\n".join(texts)
