"""Compatibility shim: delegates to submodule-owned mojo_memory implementation."""
import sys
from pathlib import Path
_submodule_src = str(Path(__file__).resolve().parents[2] / "submodules" / "dreaming-memory-pipeline" / "src")
if _submodule_src not in sys.path:
    sys.path.insert(0, _submodule_src)
from mojo_memory.memory.active_memory import *  # noqa: F401,F403
