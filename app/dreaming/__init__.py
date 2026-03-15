"""
Dreaming - Memory Consolidation System

Thin re-export layer. Actual implementation lives in the
dreaming-memory-pipeline submodule (submodules/dreaming-memory-pipeline/src/dreaming/).

File: app/dreaming/__init__.py
"""

import sys
import warnings
from pathlib import Path

# Try installed package first (Docker / pip install), then fall back to submodule src/.
_submodule_src = str(Path(__file__).resolve().parent.parent.parent / "submodules" / "dreaming-memory-pipeline" / "src")

try:
    import dreaming  # noqa: F401 — already installed as a package
except ModuleNotFoundError:
    _submodule_populated = Path(_submodule_src).joinpath("dreaming").is_dir()
    if _submodule_populated:
        if _submodule_src not in sys.path:
            sys.path.insert(0, _submodule_src)
    else:
        warnings.warn(
            "\n"
            "  [MoJoAssistant] Dreaming (memory consolidation) is NOT available.\n"
            "  The dreaming-memory-pipeline submodule is not initialised.\n"
            "  Dreaming tasks will fail until you fix this.\n\n"
            "  To enable it, run ONE of the following:\n\n"
            "    # Option A — initialise the git submodule (recommended for development)\n"
            "    git submodule update --init --recursive\n\n"
            "    # Option B — install the package directly (recommended for production)\n"
            "    pip install submodules/dreaming-memory-pipeline/\n\n"
            "  To silence this warning without enabling Dreaming, set:\n"
            "    DREAMING_DISABLED=1\n",
            stacklevel=2,
        )

# Re-export public API so existing `from app.dreaming.X import Y` still works
from dreaming.models import BChunk, CCluster, DArchive  # noqa: E402, F401
from dreaming.pipeline import DreamingPipeline  # noqa: E402, F401
from dreaming.chunker import ConversationChunker  # noqa: E402, F401
from dreaming.synthesizer import DreamingSynthesizer  # noqa: E402, F401
from dreaming.storage.base import StorageBackend  # noqa: E402, F401
from dreaming.storage.json_backend import JsonFileBackend  # noqa: E402, F401

__all__ = [
    'BChunk',
    'CCluster',
    'DArchive',
    'DreamingPipeline',
    'ConversationChunker',
    'DreamingSynthesizer',
    'StorageBackend',
    'JsonFileBackend',
]
