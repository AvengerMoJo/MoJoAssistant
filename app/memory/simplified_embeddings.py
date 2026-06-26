"""Compatibility shim: delegates to submodule-owned mojo_memory implementation.

Enhanced with EmbeddingPool integration for failover support.
"""
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_submodule_src = str(Path(__file__).resolve().parents[2] / "submodules" / "dreaming-memory-pipeline" / "src")
if _submodule_src not in sys.path:
    sys.path.insert(0, _submodule_src)
from mojo_memory.memory.simplified_embeddings import SimpleEmbedding as _BaseSimpleEmbedding

from app.memory.embedding_pool import EmbeddingResource, get_embedding_pool


class SimpleEmbedding(_BaseSimpleEmbedding):
    """
    Enhanced SimpleEmbedding with pool-based failover.

    If the primary backend fails, automatically falls back to the next
    available backend in the pool.
    """

    def __init__(
        self,
        backend: str = "huggingface",
        model_name: str = "BAAI/bge-m3",
        api_key: str | None = None,
        server_url: str = "http://localhost:8080/embed",
        embedding_dim: int = 768,
        cache_dir: str = ".embedding_cache",
        device: str | None = None,
        preferred_model: str | None = None,
    ):
        self._pool = get_embedding_pool()
        self._preferred_model = preferred_model
        self._fallback_resources: List[EmbeddingResource] = []
        self._current_resource: Optional[EmbeddingResource] = None

        # Try to use pool for initialization
        if self._pool:
            resources = self._pool.acquire_with_fallback(
                preferred_id=preferred_model or "default",
                min_dim=embedding_dim,
            )
            if resources:
                self._fallback_resources = resources
                primary = resources[0]
                self._current_resource = primary
                backend = primary.backend
                model_name = primary.model_name
                embedding_dim = primary.embedding_dim
                api_key = primary.api_key or api_key
                server_url = primary.server_url or server_url
                device = primary.device or device

        # Initialize with resolved config
        super().__init__(
            backend=backend,
            model_name=model_name,
            api_key=api_key,
            server_url=server_url,
            embedding_dim=embedding_dim,
            cache_dir=cache_dir,
            device=device,
        )

    def get_text_embedding(self, text: str, prompt_name: str = "passage") -> List[float]:
        """Get embedding with automatic failover on error."""
        last_error = None

        # Try current backend first
        try:
            t0 = time.monotonic()
            result = super().get_text_embedding(text, prompt_name)
            if result:
                if self._pool and self._current_resource:
                    self._pool.record_call(
                        self._current_resource.id,
                        (time.monotonic() - t0) * 1000,
                    )
                return result
        except Exception as e:
            last_error = e
            self.logger.warning(f"Primary embedding failed: {e}")

        # Try fallback resources
        for resource in self._fallback_resources:
            if resource == self._current_resource:
                continue
            try:
                self.logger.info(f"Falling back to embedding backend: {resource.id}")
                self._switch_backend(resource)
                t0 = time.monotonic()
                result = super().get_text_embedding(text, prompt_name)
                if result:
                    self._current_resource = resource
                    if self._pool:
                        self._pool.mark_available(resource.id)
                        self._pool.record_call(resource.id, (time.monotonic() - t0) * 1000)
                    return result
            except Exception as e:
                self.logger.warning(f"Fallback '{resource.id}' failed: {e}")
                if self._pool:
                    self._pool.mark_failed(resource.id, str(e))

        # All backends failed
        if last_error:
            raise last_error
        return []

    def get_batch_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Get batch embeddings with automatic failover on error."""
        last_error = None

        try:
            t0 = time.monotonic()
            result = super().get_batch_embeddings(texts)
            if result:
                if self._pool and self._current_resource:
                    self._pool.record_call(
                        self._current_resource.id,
                        (time.monotonic() - t0) * 1000,
                    )
                return result
        except Exception as e:
            last_error = e
            self.logger.warning(f"Primary batch embedding failed: {e}")

        for resource in self._fallback_resources:
            if resource == self._current_resource:
                continue
            try:
                self.logger.info(f"Falling back to: {resource.id}")
                self._switch_backend(resource)
                t0 = time.monotonic()
                result = super().get_batch_embeddings(texts)
                if result:
                    self._current_resource = resource
                    if self._pool:
                        self._pool.mark_available(resource.id)
                        self._pool.record_call(resource.id, (time.monotonic() - t0) * 1000)
                    return result
            except Exception as e:
                self.logger.warning(f"Fallback '{resource.id}' failed: {e}")
                if self._pool:
                    self._pool.mark_failed(resource.id, str(e))

        if last_error:
            raise last_error
        return []

    def _switch_backend(self, resource: EmbeddingResource) -> None:
        """Switch to a different embedding backend."""
        from mojo_memory.embeddings.registry import create_backend

        self._backend_impl = create_backend(
            resource.backend,
            model_name=resource.model_name,
            embedding_dim=resource.embedding_dim,
            server_url=resource.server_url or "http://localhost:8080/embed",
            api_key=resource.api_key,
            device=resource.device,
            request_format=resource.request_format,
            api_key_env=resource.api_key_env or "",
        )
        self._sync_from_backend_info()
        self.model_version = f"{resource.backend}:{resource.model_name}:{resource.embedding_dim}"

    def get_info(self) -> Dict[str, Any]:
        """Get current embedding info including pool status."""
        info = super().get_info()
        info["pool_resources"] = len(self._fallback_resources)
        info["current_resource"] = self._current_resource.id if self._current_resource else None
        return info
