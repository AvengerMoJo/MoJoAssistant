"""
Dreaming - Memory Consolidation System

Thin re-export layer. Actual implementation lives in the
dreaming-memory-pipeline submodule (dreaming-memory-pipeline/src/dreaming/).

File: app/dreaming/__init__.py
"""

import sys
from pathlib import Path

# Add submodule src/ to path so `dreaming.*` imports resolve
_submodule_src = str(Path(__file__).resolve().parent.parent.parent / "dreaming-memory-pipeline" / "src")
if _submodule_src not in sys.path:
    sys.path.insert(0, _submodule_src)

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
