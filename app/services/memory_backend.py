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
DEFAULT_HYBRID_MEMORY_SERVICE_CLASS = (
    "mojo_memory.services.hybrid_memory_service.HybridMemoryService"
)


def _load_class(class_path: str) -> Type[Any]:
    if "." not in class_path:
        raise ValueError(f"Invalid class path '{class_path}'")
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
    if os.getenv("MOJO_MEMORY_PROVIDER"):
        return get_memory_provider(**kwargs)
    klass = get_memory_service_class()
    return klass(*args, **kwargs)


def create_hybrid_memory_service(*args: Any, **kwargs: Any) -> Any:
    """
    Create a hybrid memory service instance.
    
    If MOJO_MEMORY_PROVIDER is set, uses the provider registry.
    Otherwise falls back to class-path loading.
    """
    if os.getenv("MOJO_MEMORY_PROVIDER"):
        return get_memory_provider(**kwargs)
    klass = get_hybrid_memory_service_class()
    return klass(*args, **kwargs)
