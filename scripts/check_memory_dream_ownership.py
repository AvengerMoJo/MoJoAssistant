#!/usr/bin/env python3
"""Enforce memory/dream ownership boundaries.

Policy:
- `app/memory/*.py` and app memory service files must remain compatibility shims.
- `app/dreaming/*.py` must remain compatibility shims.
- Non-doc code must not import legacy `app.memory` / `app.services.memory_service`
  / `app.services.hybrid_memory_service` paths.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Memory shim files
MEMORY_SHIM_FILES = {
    ROOT / "app/memory/active_memory.py",
    ROOT / "app/memory/archival_memory.py",
    ROOT / "app/memory/knowledge_manager.py",
    ROOT / "app/memory/memory_page.py",
    ROOT / "app/memory/multi_model_storage.py",
    ROOT / "app/memory/simplified_embeddings.py",
    ROOT / "app/memory/working_memory.py",
    ROOT / "app/services/memory_service.py",
    ROOT / "app/services/hybrid_memory_service.py",
}

# Dream shim files
DREAM_SHIM_FILES = {
    ROOT / "app/dreaming/__init__.py",
    ROOT / "app/dreaming/pipeline.py",
    ROOT / "app/dreaming/chunker.py",
    ROOT / "app/dreaming/synthesizer.py",
    ROOT / "app/dreaming/models.py",
}

# All shim files (combined)
SHIM_FILES = MEMORY_SHIM_FILES | DREAM_SHIM_FILES

LEGACY_IMPORT_PATTERNS = [
    re.compile(r"\bfrom\s+app\.memory\.[\w_]+\s+import\b"),
    re.compile(r"\bimport\s+app\.memory\.[\w_]+\b"),
    re.compile(r"\bfrom\s+app\.services\.memory_service\s+import\b"),
    re.compile(r"\bfrom\s+app\.services\.hybrid_memory_service\s+import\b"),
]

ALLOWLIST_PATH_PARTS = {
    "docs/",
    "tests/benchmarks/run_locomo.py.bak",
}


def _is_allowlisted(path: Path) -> bool:
    p = str(path.relative_to(ROOT)).replace("\\", "/")
    return any(part in p for part in ALLOWLIST_PATH_PARTS)


def _iter_py_files() -> list[Path]:
    roots = [ROOT / "app", ROOT / "tests", ROOT / "scripts"]
    files: list[Path] = []
    for base in roots:
        if not base.exists():
            continue
        files.extend(base.rglob("*.py"))
    return files


def check_shims() -> list[str]:
    errors: list[str] = []
    memory_required_markers = (
        "Compatibility shim",
        "from mojo_memory.",
    )
    # Dream shims need submodule path and dreaming imports
    dream_required_markers = (
        "dreaming-memory-pipeline",
        "from dreaming.",
    )

    for path in sorted(SHIM_FILES):
        if not path.exists():
            errors.append(f"missing shim file: {path}")
            continue

        text = path.read_text(encoding="utf-8")
        
        # Check memory shims
        if path in MEMORY_SHIM_FILES:
            if not all(marker in text for marker in memory_required_markers):
                errors.append(
                    f"non-shim content detected in {path}: expected compatibility marker and mojo_memory import"
                )
        
        # Check dream shims
        elif path in DREAM_SHIM_FILES:
            if not all(marker in text for marker in dream_required_markers):
                errors.append(
                    f"non-shim content detected in {path}: expected submodule path and dreaming import"
                )

    return errors


def check_legacy_imports() -> list[str]:
    errors: list[str] = []

    for path in _iter_py_files():
        if path in SHIM_FILES or _is_allowlisted(path):
            continue

        text = path.read_text(encoding="utf-8")
        for pattern in LEGACY_IMPORT_PATTERNS:
            if pattern.search(text):
                rel = path.relative_to(ROOT)
                errors.append(f"legacy import found in {rel}: {pattern.pattern}")
                break

    return errors


def main() -> int:
    errors = []
    errors.extend(check_shims())
    errors.extend(check_legacy_imports())

    if errors:
        print("[FAIL] memory/dream ownership check failed")
        for err in errors:
            print(f"- {err}")
        return 1

    print("[OK] memory/dream ownership check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
