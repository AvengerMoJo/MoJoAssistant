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


@pytest.fixture(scope="session", autouse=True)
def isolated_memory_path(tmp_path_factory):
    """Point MEMORY_PATH at a fresh temp directory for the entire smoke run."""
    mem = tmp_path_factory.mktemp("smoke_memory")
    os.environ["MEMORY_PATH"] = str(mem)
    yield mem
    # Cleanup is handled by pytest's tmp_path_factory
