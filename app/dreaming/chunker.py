"""Shim: re-exports from submodules/dreaming-memory-pipeline submodule."""
from app.dreaming import _submodule_src  # ensure path setup  # noqa: F401
from dreaming.chunker import *  # noqa: F401, F403
from dreaming.chunker import ConversationChunker  # noqa: F401
