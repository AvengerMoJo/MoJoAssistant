"""Global pytest bootstrap for repository tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUBMODULE_SRC = ROOT / "submodules" / "dreaming-memory-pipeline" / "src"

root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

submodule_str = str(SUBMODULE_SRC)
if SUBMODULE_SRC.exists() and submodule_str not in sys.path:
    sys.path.insert(0, submodule_str)
