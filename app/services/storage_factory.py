"""Storage backend factory — single point of creation for StorageBackend instances.

All code that needs a StorageBackend should use resolve_storage_backend() instead
of importing concrete implementations directly. This ensures the storage backend
can be swapped via config without code changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# Cache the active backend class — resolved once, reused forever.
_backend_class: Optional[type] = None


def resolve_storage_backend(storage_path: Path):
    """Return a StorageBackend instance for the given path.

    Resolution order:
    1. MOJO_STORAGE_BACKEND env var → import that class
    2. Default: JsonFileBackend from dreaming-memory-pipeline submodule
    """
    global _backend_class

    import os

    if _backend_class is None:
        backend_name = os.environ.get("MOJO_STORAGE_BACKEND", "").strip()
        if backend_name:
            # e.g. "dreaming.storage.duckdb_backend.DuckDBStorageBackend"
            module_path, class_name = backend_name.rsplit(".", 1)
            import importlib
            mod = importlib.import_module(module_path)
            _backend_class = getattr(mod, class_name)
        else:
            from dreaming.storage.json_backend import JsonFileBackend
            _backend_class = JsonFileBackend

    return _backend_class(storage_path=storage_path)
