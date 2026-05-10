"""Pluggable memory backend loader.

Defaults point to submodule-owned `mojo_memory` implementation, but can be
overridden to support alternative memory/dream modules.
"""

from __future__ import annotations

import importlib
import os
from typing import Any, Type


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
    klass = get_memory_service_class()
    return klass(*args, **kwargs)


def create_hybrid_memory_service(*args: Any, **kwargs: Any) -> Any:
    klass = get_hybrid_memory_service_class()
    return klass(*args, **kwargs)
