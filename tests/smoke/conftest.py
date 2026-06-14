"""
Smoke suite shared fixtures.

All tests run against a temporary MEMORY_PATH — no real ~/.memory touched.
No external API keys or network connections required.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def pytest_collection_modifyitems(items):
    """Auto-mark all smoke tests as 'stable' unless explicitly marked 'experimental'.

    Every test in tests/smoke/ is designed to run on a clean install with no
    LLM, no API keys, and no network. Tests that ever need external resources
    must be explicitly marked @pytest.mark.experimental.
    """
    for item in items:
        if "experimental" in item.keywords:
            continue
        item.add_marker(pytest.mark.stable)


@pytest.fixture(scope="session", autouse=True)
def isolated_memory_path(tmp_path_factory):
    """Point MEMORY_PATH at a fresh temp directory for the entire smoke run."""
    mem = tmp_path_factory.mktemp("smoke_memory")
    os.environ["MEMORY_PATH"] = str(mem)
    yield mem
    # Cleanup is handled by pytest's tmp_path_factory
