"""
Central path resolution for MoJoAssistant.

All runtime paths are derived from MEMORY_PATH (env var).
Nothing else should hardcode '.memory' or Path.home() / '.memory'.

Usage:
    from app.config.paths import get_memory_path, get_memory_subpath

    data_dir = get_memory_path()
    sessions = get_memory_subpath("task_sessions")
"""

import os
from pathlib import Path


def get_memory_path() -> str:
    """Return the root memory directory, resolved once from MEMORY_PATH env var."""
    return os.getenv("MEMORY_PATH", str(Path.home() / ".memory"))


def get_memory_subpath(*parts: str) -> str:
    """Return a path inside the memory directory."""
    return str(Path(get_memory_path()).joinpath(*parts))
