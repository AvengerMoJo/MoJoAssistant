"""Compatibility shim for NineChapter persona overlays.

Canonical implementation now lives in:
  submodules/agency-agents/src/agency_agents/ninechapter.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_SUBMODULE_SRC = (
    Path(__file__).resolve().parents[2] / "submodules" / "agency-agents" / "src"
)

if _SUBMODULE_SRC.exists():
    _src = str(_SUBMODULE_SRC)
    if _src not in sys.path:
        sys.path.insert(0, _src)

from agency_agents.ninechapter import *  # noqa: F401,F403
