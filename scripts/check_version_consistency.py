#!/usr/bin/env python3
"""Enforce version consistency across the repository.

Single source of truth: pyproject.toml [project].version
All other files that declare or display the MoJoAssistant version must match.

Usage:
    python3 scripts/check_version_consistency.py          # check only (CI gate)
    python3 scripts/check_version_consistency.py --fix    # update all files to match

Exit codes:
    0 — all version references are consistent
    1 — mismatch found (check mode) or fix failed
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Canonical source
# ---------------------------------------------------------------------------

def read_canonical_version() -> str:
    """Read version from pyproject.toml [project].version."""
    toml_path = ROOT / "pyproject.toml"
    text = toml_path.read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        print(f"ERROR: cannot read version from {toml_path}")
        sys.exit(1)
    return m.group(1)


# ---------------------------------------------------------------------------
# File checkers — each returns list of (file, line, current, expected) tuples
# ---------------------------------------------------------------------------

def _check_regex(path: Path, pattern: str, expected: str, group: int = 1) -> list[tuple]:
    """Generic regex checker. Returns mismatches."""
    if not path.exists():
        return []
    text = path.read_text()
    results = []
    for m in re.finditer(pattern, text, re.MULTILINE):
        current = m.group(group)
        if current != expected:
            results.append(
                (str(path.relative_to(ROOT)), text[: m.start()].count("\n") + 1, current, expected)
            )
    return results


def check_pyproject(version: str) -> list[tuple]:
    return _check_regex(ROOT / "pyproject.toml", r'^version\s*=\s*"([^"]+)"', version)


def check_readme(version: str) -> list[tuple]:
    # Only check current-release lines, not historical release links.
    # README uses "v" prefix (e.g. v1.4.2-beta); canonical has none.
    expected = "v" + version
    results = []
    results += _check_regex(ROOT / "README.md", r'Current release:\s*`([^`]+)`', expected)
    results += _check_regex(ROOT / "README.md", r'Active beta\s*\(`([^`]+)`\)', expected)
    return results


def check_overview(version: str) -> list[tuple]:
    return _check_regex(
        ROOT / "docs/MOJOASSISTANT_FULL_OVERVIEW.md",
        r'\*\*Version:\*\*\s*(v[0-9A-Za-z.\-]+)',
        "v" + version,
    )


def check_python_init(version: str) -> list[tuple]:
    """Check __version__ in app/*/__init__.py files."""
    targets = [
        ROOT / "app/scheduler/__init__.py",
        ROOT / "app/mcp/__init__.py",
        ROOT / "app/installer/__init__.py",
    ]
    results = []
    for path in targets:
        if path.exists():
            results += _check_regex(path, r'__version__\s*=\s*"([^"]+)"', version)
    return results


def check_scheduler_core(version: str) -> list[tuple]:
    """Check scheduler startup event version string."""
    path = ROOT / "app/scheduler/core.py"
    if not path.exists():
        return []
    text = path.read_text()

    # Preferred dynamic form auto-tracks package version.
    if '"version": f"v{__version__}"' in text:
        return []

    # Fallback static literal must match canonical version.
    return _check_regex(path, r'"version"\s*:\s*"v([^"]+)"', version)


# ---------------------------------------------------------------------------
# Fixers — rewrite files to match expected version
# ---------------------------------------------------------------------------

def _fix_regex(path: Path, pattern: str, replacement_template: str) -> int:
    """Replace version in file using regex. Returns count of replacements."""
    if not path.exists():
        return 0
    text = path.read_text()
    new_text, count = re.subn(pattern, replacement_template, text, flags=re.MULTILINE)
    if count > 0:
        path.write_text(new_text)
    return count


def fix_pyproject(version: str) -> int:
    return _fix_regex(ROOT / "pyproject.toml", r'(^version\s*=\s*)"[^"]+"', rf'\g<1>"{version}"')


def fix_readme(version: str) -> int:
    total = 0
    readme = ROOT / "README.md"
    if not readme.exists():
        return 0
    text = readme.read_text()

    text, n = re.subn(r'(Current release:\s*`)v?[\d.]+(-beta)?`', rf'\g<1>v{version}`', text)
    total += n

    text, n = re.subn(r'(Active beta\s*\(`)v?[\d.]+(-beta)?(`\))', rf'\g<1>v{version}\g<3>', text)
    total += n

    if total > 0:
        readme.write_text(text)
    return total


def fix_overview(version: str) -> int:
    return _fix_regex(
        ROOT / "docs/MOJOASSISTANT_FULL_OVERVIEW.md",
        r'(\*\*Version:\*\*\s*)v?[0-9A-Za-z.\-]+',
        rf'\g<1>v{version}',
    )


def fix_python_init(version: str) -> int:
    targets = [
        ROOT / "app/scheduler/__init__.py",
        ROOT / "app/mcp/__init__.py",
        ROOT / "app/installer/__init__.py",
    ]
    total = 0
    for path in targets:
        if path.exists():
            total += _fix_regex(path, r'(__version__\s*=\s*)"[^"]+"', rf'\g<1>"{version}"')
    return total


def fix_scheduler_core(version: str) -> int:
    """Normalize scheduler version broadcast to dynamic package-linked form."""
    path = ROOT / "app/scheduler/core.py"
    if not path.exists():
        return 0
    text = path.read_text()
    if '"version": f"v{__version__}"' in text:
        return 0
    new_text, count = re.subn(
        r'("version"\s*:\s*)"v[^"]+"',
        r'\1f"v{__version__}"',
        text,
        flags=re.MULTILINE,
    )
    if count > 0:
        path.write_text(new_text)
    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

ALL_CHECKERS = [
    ("pyproject.toml", check_pyproject),
    ("README.md", check_readme),
    ("docs/MOJOASSISTANT_FULL_OVERVIEW.md", check_overview),
    ("app/*/__init__.py", check_python_init),
    ("app/scheduler/core.py", check_scheduler_core),
]

ALL_FIXERS = [
    fix_pyproject,
    fix_readme,
    fix_overview,
    fix_python_init,
    fix_scheduler_core,
]


def main() -> int:
    fix_mode = "--fix" in sys.argv
    version = read_canonical_version()
    print(f"Canonical version (pyproject.toml): {version}\n")

    all_mismatches: list[tuple] = []
    for _label, checker in ALL_CHECKERS:
        mismatches = checker(version)
        if mismatches:
            for f, line, current, expected in mismatches:
                print(f"  MISMATCH  {f}:{line}  found={current!r}  expected={expected!r}")
            all_mismatches.extend(mismatches)

    if not all_mismatches:
        print("  All version references are consistent.")
        return 0

    if not fix_mode:
        print(f"\n{len(all_mismatches)} mismatch(es) found. Run with --fix to auto-correct.")
        return 1

    print(f"\nFixing {len(all_mismatches)} mismatch(es)...")
    fixed = 0
    for fixer in ALL_FIXERS:
        fixed += fixer(version)
    print(f"  Updated {fixed} reference(s).")

    remaining = []
    for _label, checker in ALL_CHECKERS:
        remaining.extend(checker(version))
    if remaining:
        print("\nERROR: some mismatches remain after fix:")
        for f, line, current, expected in remaining:
            print(f"  {f}:{line}  found={current!r}  expected={expected!r}")
        return 1

    print("  All version references are now consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
