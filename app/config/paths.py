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
    """Return the root memory directory as an absolute path.

    Resolves MEMORY_PATH (which may be relative like '.memory') against cwd
    so all downstream paths are always absolute regardless of how the server
    was started.
    """
    raw = os.getenv("MEMORY_PATH", str(Path.home() / ".memory"))
    return str(Path(raw).resolve())


def get_memory_subpath(*parts: str) -> str:
    """Return a path inside the memory directory."""
    return str(Path(get_memory_path()).joinpath(*parts))
