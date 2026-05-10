"""Compatibility shim: routes through provider registry.

This shim provides backward-compatible imports while routing
through the provider interface. Prefer using the provider
registry directly for new code.
"""
import sys
from pathlib import Path

_submodule_src = str(Path(__file__).resolve().parents[2] / "submodules" / "dreaming-memory-pipeline" / "src")
if _submodule_src not in sys.path:
    sys.path.insert(0, _submodule_src)

# Re-export for backward compatibility
from mojo_memory.services.hybrid_memory_service import *  # noqa: F401,F403
from mojo_memory.services.hybrid_memory_service import HybridMemoryService  # noqa: F401

# Export provider factory for new code
from app.services.memory_backend import get_memory_provider  # noqa: F401
