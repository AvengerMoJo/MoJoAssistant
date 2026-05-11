"""Conformance check for examples/plugins/sample-memory-plugin."""

from __future__ import annotations

import sys
from pathlib import Path

from tests.conformance.test_provider_conformance import MemoryProviderConformance


class TestSampleMemoryPlugin(MemoryProviderConformance):
    def create_provider(self):
        root = Path("examples/plugins/sample-memory-plugin/src").resolve()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from sample_memory_plugin.provider import PluginProvider

        return PluginProvider()
