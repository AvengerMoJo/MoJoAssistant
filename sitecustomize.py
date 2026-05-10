"""Repository-local Python path bootstrap.

Ensures submodule-owned memory package imports (`mojo_memory.*`) resolve
without requiring editable install during local script/test runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SUBMODULE_SRC = ROOT / "submodules" / "dreaming-memory-pipeline" / "src"

if SUBMODULE_SRC.exists():
    submodule_src = str(SUBMODULE_SRC)
    if submodule_src not in sys.path:
        sys.path.insert(0, submodule_src)
