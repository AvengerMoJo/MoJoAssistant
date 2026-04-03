"""
Smoke — Import health

Every core module must import without error on a clean install.
A failure here means a hard dependency is missing from requirements.txt
or an import-time side-effect is broken.
"""

import pytest


CORE_MODULES = [
    "app.config.paths",
    "app.config.doctor",
    "app.scheduler.models",
    "app.scheduler.queue",
    "app.scheduler.resource_pool",
    "app.scheduler.agentic_executor",
    "app.scheduler.policy.monitor",
    "app.scheduler.policy.static",
    "app.scheduler.policy.content",
    "app.scheduler.policy.data_boundary_checker",
    "app.scheduler.dynamic_tool_registry",
    "app.memory.simplified_embeddings",
    "app.mcp.adapters.audit_log",
    "app.mcp.adapters.event_log",
    "app.mcp.adapters.attention_classifier",
    "app.roles.role_manager",
]


@pytest.mark.parametrize("module", CORE_MODULES)
def test_core_module_imports(module):
    """Each core module must be importable with no exceptions."""
    import importlib
    importlib.import_module(module)
