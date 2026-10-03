"""Regression test: the config(action="resource_add"/"resource_edit") MCP tool
must pass through `rate_limit` and `budget` — found live 2026-10-02 that these
were silently dropped (missing from the FIELDS whitelist in
_execute_resource_add_or_edit), even though ResourceManager._parse_resource
has always understood them. This is why every resource in resource_pool.json
had zero budget/rate_limit configured: the only sanctioned tool to set them
couldn't.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr("app.mcp.core.tools.MEMORY_CONFIG_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr("app.config.config_loader.MEMORY_CONFIG_DIR", str(tmp_path))

    from app.mcp.core.tools import ToolRegistry

    memory_service = MagicMock()
    memory_service.search = MagicMock(return_value=[])

    with patch("app.mcp.core.tools.ToolRegistry._start_scheduler_daemon"):
        with patch("app.scheduler.core.Scheduler._seed_tasks_from_config"):
            reg = ToolRegistry(memory_service=memory_service)
    # Avoid touching the real local resource manager during reload
    reg._on_resource_pool_config_change = lambda: None
    return reg, tmp_path


class TestResourceAddWithBudgetAndRateLimit:
    @pytest.mark.asyncio
    async def test_resource_add_persists_rate_limit_and_budget(self, registry):
        reg, tmp_path = registry
        result = await reg.execute("config", {
            "action": "resource_add",
            "resource_id": "test_gemini",
            "type": "api",
            "provider": "google",
            "base_url": "https://example.test",
            "model": "gemini-test",
            "tier": "free_api",
            "priority": 1,
            "enabled": True,
            "context_limit": 100000,
            "output_limit": 8192,
            "rate_limit": {"max_calls_per_window": 60, "window_seconds": 60, "min_interval_seconds": 1.0},
            "budget": {"max_calls_per_window": 1000, "window_seconds": 86400, "reserved_for_user_pct": 20.0},
        })
        assert result["status"] == "success"

        saved = json.loads((tmp_path / "resource_pool.json").read_text())
        entry = saved["resources"]["test_gemini"]
        assert entry["rate_limit"] == {"max_calls_per_window": 60, "window_seconds": 60, "min_interval_seconds": 1.0}
        assert entry["budget"] == {"max_calls_per_window": 1000, "window_seconds": 86400, "reserved_for_user_pct": 20.0}

    @pytest.mark.asyncio
    async def test_resource_edit_sets_budget_on_existing_resource(self, registry):
        reg, tmp_path = registry
        await reg.execute("config", {
            "action": "resource_add",
            "resource_id": "test_gemini",
            "type": "api", "provider": "google", "base_url": "https://example.test",
            "model": "gemini-test", "tier": "free_api", "priority": 1, "enabled": True,
            "context_limit": 100000, "output_limit": 8192,
        })
        result = await reg.execute("config", {
            "action": "resource_edit",
            "resource_id": "test_gemini",
            "budget": {"max_calls_per_window": 500, "window_seconds": 86400, "reserved_for_user_pct": 30.0},
        })
        assert result["status"] == "success"

        saved = json.loads((tmp_path / "resource_pool.json").read_text())
        entry = saved["resources"]["test_gemini"]
        assert entry["budget"]["reserved_for_user_pct"] == 30.0
        # Pre-existing fields untouched
        assert entry["model"] == "gemini-test"

    @pytest.mark.asyncio
    async def test_parsed_resource_actually_enforces_the_set_budget(self, registry):
        """End-to-end: the dict this tool writes round-trips through
        ResourceManager._parse_resource into a real enforced Budget."""
        reg, tmp_path = registry
        await reg.execute("config", {
            "action": "resource_add",
            "resource_id": "test_gemini",
            "type": "api", "provider": "google", "base_url": "https://example.test",
            "model": "gemini-test", "tier": "free_api", "priority": 1, "enabled": True,
            "context_limit": 100000, "output_limit": 8192,
            "budget": {"max_calls_per_window": 10, "window_seconds": 3600, "reserved_for_user_pct": 50.0},
        })

        from app.scheduler.resource_pool import ResourceManager
        rm = ResourceManager.__new__(ResourceManager)
        rm._sandbox_env = {}
        conf = json.loads((tmp_path / "resource_pool.json").read_text())["resources"]["test_gemini"]
        resource = rm._parse_resource("test_gemini", conf)

        assert resource.budget is not None
        assert resource.budget.max_calls_per_window == 10
        assert resource.budget.reserved_for_user_pct == 50.0
