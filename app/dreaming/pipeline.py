"""Shim: re-exports from dreaming-memory-pipeline submodule."""
from app.dreaming import _submodule_src  # ensure path setup  # noqa: F401
from dreaming.pipeline import *  # noqa: F401, F403
from dreaming.pipeline import DreamingPipeline  # noqa: F401
