"""Shim: re-exports from submodules/dreaming-memory-pipeline submodule."""
from app.dreaming import _submodule_src  # ensure path setup  # noqa: F401
from dreaming.inbox_distillation import *  # noqa: F401, F403
from dreaming.inbox_distillation import build_inbox_text, run_inbox_distillation  # noqa: F401
