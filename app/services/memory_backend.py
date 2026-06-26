"""Pluggable memory backend loader.

Routes memory/dream operations through the provider registry.
Defaults point to submodule-owned `mojo_memory` implementation.

Environment variables:
  MOJO_MEMORY_PROVIDER    — provider name (default: "mojo_memory")
  MOJO_DREAM_PROVIDER     — provider name (default: "mojo_dream")
  MOJO_MEMORY_SERVICE_CLASS — class path override (legacy, prefer provider name)
  MOJO_HYBRID_MEMORY_SERVICE_CLASS — class path override (legacy)
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
from pathlib import Path
from typing import Any, Type

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# New provider registry (preferred)
# ---------------------------------------------------------------------------

def get_memory_provider(**kwargs: Any) -> Any:
    """
    Get a MemoryProvider instance via the provider registry.
    
    Resolution order:
    1. MOJO_MEMORY_PROVIDER env var
    2. Default ("mojo_memory")
    """
    from app.services.provider_contracts import get_registry
    registry = get_registry()
    return registry.resolve_memory_provider(**kwargs)


def get_dream_provider(**kwargs: Any) -> Any:
    """
    Get a DreamProvider instance via the provider registry.
    
    Resolution order:
    1. MOJO_DREAM_PROVIDER env var
    2. Default ("mojo_dream")
    """
    from app.services.provider_contracts import get_registry
    registry = get_registry()
    return registry.resolve_dream_provider(**kwargs)


# ---------------------------------------------------------------------------
# Legacy class-path loader (kept for backward compatibility)
# Falls back to provider registry when MOJO_MEMORY_PROVIDER is set
# ---------------------------------------------------------------------------

DEFAULT_MEMORY_SERVICE_CLASS = "mojo_memory.services.memory_service.MemoryService"
# Points to the app-layer override which wires EmbeddingPool into both
# _setup_embedding (primary model) and _setup_multi_model (additional models).
# The submodule path mojo_memory.services.hybrid_memory_service.HybridMemoryService
# bypasses the pool entirely — do not use that path directly.
DEFAULT_HYBRID_MEMORY_SERVICE_CLASS = (
    "app.services.hybrid_memory_service.HybridMemoryService"
)


class _NullWorkingMemory:
    def get_messages(self) -> list[Any]:
        return []


class NullMemoryService:
    """Fallback memory service when provider/plugin cannot be loaded."""

    def __init__(self, reason: str = "Memory provider unavailable") -> None:
        self.reason = reason
        self.is_available = False
        self.working_memory = _NullWorkingMemory()
        self.multi_model_enabled = False

    async def _search_working_memory_async(self, embedding: Any) -> list[dict[str, Any]]:
        return []

    async def _search_active_memory_async(self, embedding: Any) -> list[dict[str, Any]]:
        return []

    async def _search_archival_memory_async(self, query: str, limit: int) -> list[dict[str, Any]]:
        return []

    async def _search_knowledge_base_async(
        self, query: str, limit: int, role_id: str | None = None
    ) -> list[dict[str, Any]]:
        return []

    def get_memory_stats(self) -> dict[str, Any]:
        return {
            "status": "degraded",
            "reason": self.reason,
            "working_memory_messages": 0,
            "active_memory_pages": 0,
            "archival_memory_entries": 0,
            "knowledge_documents": 0,
        }

    def add_user_message(self, msg: str) -> None:
        return None

    def add_assistant_message(self, msg: str) -> None:
        return None

    def add_to_knowledge_base(self, content: str, metadata: dict[str, Any], role_id: str | None = None) -> bool:
        return False

    def end_conversation(self) -> None:
        return None

    def list_recent_conversations(self, limit: int = 10) -> list[dict[str, Any]]:
        return []

    def remove_conversation_message(self, message_id: str) -> bool:
        return False

    def remove_recent_conversations(self, count: int) -> int:
        return 0

    def list_recent_documents(self, limit: int = 10) -> list[dict[str, Any]]:
        return []

    def remove_document(self, document_id: str) -> bool:
        return False


def _ensure_submodule_src_on_path() -> None:
    """Ensure submodule provider packages are importable in service environments."""
    project_root = Path(__file__).resolve().parents[2]
    submodule_src = project_root / "submodules" / "dreaming-memory-pipeline" / "src"
    if submodule_src.exists():
        submodule_src_str = str(submodule_src)
        if submodule_src_str not in sys.path:
            sys.path.insert(0, submodule_src_str)


def _load_class(class_path: str) -> Type[Any]:
    if "." not in class_path:
        raise ValueError(f"Invalid class path '{class_path}'")
    _ensure_submodule_src_on_path()
    module_name, class_name = class_path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def get_memory_service_class() -> Type[Any]:
    class_path = os.getenv("MOJO_MEMORY_SERVICE_CLASS", DEFAULT_MEMORY_SERVICE_CLASS)
    return _load_class(class_path)


def get_hybrid_memory_service_class() -> Type[Any]:
    class_path = os.getenv(
        "MOJO_HYBRID_MEMORY_SERVICE_CLASS",
        DEFAULT_HYBRID_MEMORY_SERVICE_CLASS,
    )
    return _load_class(class_path)


def create_memory_service(*args: Any, **kwargs: Any) -> Any:
    """
    Create a memory service instance.
    
    If MOJO_MEMORY_PROVIDER is set, uses the provider registry.
    Otherwise falls back to class-path loading.
    """
    try:
        if os.getenv("MOJO_MEMORY_PROVIDER"):
            return get_memory_provider(**kwargs)
        klass = get_memory_service_class()
        return klass(*args, **kwargs)
    except Exception as e:
        logger.error("memory_backend: falling back to NullMemoryService: %s", e)
        return NullMemoryService(
            reason=f"Memory provider is not configured or failed to load: {type(e).__name__}: {e}"
        )


def create_hybrid_memory_service(*args: Any, **kwargs: Any) -> Any:
    """
    Create a hybrid memory service instance.
    
    If MOJO_MEMORY_PROVIDER is set, uses the provider registry.
    Otherwise falls back to class-path loading.
    """
    try:
        if os.getenv("MOJO_MEMORY_PROVIDER"):
            return get_memory_provider(**kwargs)
        klass = get_hybrid_memory_service_class()
        return klass(*args, **kwargs)
    except Exception as e:
        logger.error("memory_backend: falling back to NullMemoryService: %s", e)
        return NullMemoryService(
            reason=f"Memory provider is not configured or failed to load: {type(e).__name__}: {e}"
        )
