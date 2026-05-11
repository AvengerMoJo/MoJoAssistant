"""Shim: re-exports from submodules/dreaming-memory-pipeline submodule."""
from app.dreaming import _submodule_src  # ensure path setup  # noqa: F401
from dreaming.session_compactor import *  # noqa: F401, F403
from dreaming.session_compactor import build_session_text, compact_session  # noqa: F401
