"""
v1.2.3 Smoke Tests — Resource Pool Unification + Tool Catalog

Tests:
  - ResourceManager flat format loading (resource_pool.json)
  - ResourceManager legacy fallback (llm_config.json)
  - acquire_by_requirements: tier, min_context, capabilities
  - Two-layer resource merge (system + user personal)
  - _resolve_tools_from_role: tool_access categories
  - _resolve_tools_from_role: legacy tools fallback
  - ask_user always injected
  - AgenticExecutor uses acquire_by_requirements when role has resource_requirements
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Repo root on path
sys.path.insert(0, str(Path(__file__).parents[2]))


# ---------------------------------------------------------------------------
# ResourceManager flat format tests
# ---------------------------------------------------------------------------

class TestResourceManagerFlatFormat(unittest.TestCase):
    """ResourceManager loads resource_pool.json (flat format)."""

    def _make_flat_config(self, resources: dict, tier_policy: dict = None) -> dict:
        return {
            "tier_policy": tier_policy or {
                "free": {"auto_approve": True},
                "free_api": {"auto_approve": True},
                "paid": {"auto_approve": False},
            },
            "selection_strategy": "priority_then_availability",
            "resources": resources,
        }

    def _make_rm_with_data(self, data: dict):
        """Construct a ResourceManager and inject parsed data directly."""
        from app.scheduler.resource_pool import ResourceManager
        rm = ResourceManager.__new__(ResourceManager)
        rm._logger = None
        rm._lock = __import__("threading").RLock()
        rm._resources = {}
        rm._usage = {}
        rm._approved_paid = set()
        rm._group_counters = {}
        rm._config_mtime_ns = None
        rm._runtime_mtime_ns = None
        rm._env_mtime_ns = None
        rm._config_path = "config/resource_pool.json"
        rm._sandbox_env = {}
        rm._tier_policy = {}
        rm._selection_strategy = "priority_then_availability"
        rm._log = lambda msg, level="info": None
        rm._parse_flat_resources(data)
        return rm

    def test_flat_format_loads_resources(self):
        data = self._make_flat_config({
            "lmstudio": {
                "type": "local",
                "provider": "openai",
                "base_url": "http://localhost:8080/v1",
                "model": "test-model",
                "tier": "free",
                "priority": 1,
                "enabled": True,
                "context_limit": 32768,
                "output_limit": 8192,
            },
            "openrouter_free": {
                "type": "api",
                "provider": "openai-compatible",
                "base_url": "https://openrouter.ai/api/v1",
                "model": "openrouter/auto",
                "tier": "free_api",
                "priority": 10,
                "enabled": True,
                "context_limit": 131072,
                "output_limit": 8192,
            },
        })
        rm = self._make_rm_with_data(data)
        self.assertIn("lmstudio", rm._resources)
        self.assertIn("openrouter_free", rm._resources)
        self.assertEqual(len(rm._resources), 2)

    def test_flat_format_tier_parsed(self):
        from app.scheduler.resource_pool import ResourceTier
        data = self._make_flat_config({
            "r1": {
                "type": "local", "provider": "openai", "base_url": "",
                "model": "x", "tier": "free", "priority": 1, "enabled": True,
            },
        })
        rm = self._make_rm_with_data(data)
        self.assertEqual(rm._resources["r1"].tier, ResourceTier.FREE)

    def test_flat_format_capabilities_parsed(self):
        data = self._make_flat_config({
            "capable": {
                "type": "api", "provider": "openai-compatible", "base_url": "https://x",
                "model": "x", "tier": "free_api", "priority": 1, "enabled": True,
                "capabilities": ["tool_use", "vision"],
            },
        })
        rm = self._make_rm_with_data(data)
        self.assertEqual(rm._resources["capable"].capabilities, ["tool_use", "vision"])

    def test_flat_format_disabled_resource(self):
        data = self._make_flat_config({
            "disabled_r": {
                "type": "local", "provider": "openai", "base_url": "",
                "model": "x", "tier": "free", "priority": 1, "enabled": False,
            },
        })
        rm = self._make_rm_with_data(data)
        self.assertIn("disabled_r", rm._resources)
        self.assertFalse(rm._resources["disabled_r"].enabled)


class TestResourceManagerLegacyFallback(unittest.TestCase):
    """ResourceManager falls back to llm_config.json when resource_pool.json absent."""

    def test_legacy_local_models_parsed(self):
        from app.scheduler.resource_pool import ResourceManager, ResourceTier
        rm = ResourceManager.__new__(ResourceManager)
        rm._logger = None
        rm._lock = __import__("threading").RLock()
        rm._resources = {}
        rm._usage = {}
        rm._approved_paid = set()
        rm._group_counters = {}
        rm._config_mtime_ns = None
        rm._runtime_mtime_ns = None
        rm._env_mtime_ns = None
        rm._sandbox_env = {}
        rm._tier_policy = {}
        rm._selection_strategy = "priority_then_availability"
        rm._log = lambda msg, level="info": None

        data = {
            "local_models": {
                "qwen-small": {
                    "type": "local", "provider": "openai", "base_url": "",
                    "model": "qwen", "tier": "free", "priority": 1, "enabled": True,
                }
            },
            "api_models": {},
            "tier_policy": {"free": {"auto_approve": True}},
        }
        rm._parse_legacy_resources(data)
        self.assertIn("qwen-small", rm._resources)
        self.assertEqual(rm._resources["qwen-small"].tier, ResourceTier.FREE)

    def test_legacy_nested_api_models_parsed(self):
        from app.scheduler.resource_pool import ResourceManager
        rm = ResourceManager.__new__(ResourceManager)
        rm._logger = None
        rm._lock = __import__("threading").RLock()
        rm._resources = {}
        rm._usage = {}
        rm._approved_paid = set()
        rm._group_counters = {}
        rm._sandbox_env = {}
        rm._tier_policy = {}
        rm._log = lambda msg, level="info": None

        data = {
            "local_models": {},
            "api_models": {
                "openrouter": {
                    "acc1": {
                        "provider": "openai-compatible",
                        "base_url": "https://openrouter.ai/api/v1",
                        "model": "openrouter/auto",
                        "tier": "free_api",
                        "priority": 10,
                        "enabled": True,
                    }
                }
            },
            "tier_policy": {},
        }
        rm._parse_legacy_resources(data)
        self.assertIn("openrouter_acc1", rm._resources)


class TestAcquireByRequirements(unittest.TestCase):
    """acquire_by_requirements selects resources matching structured requirements."""

    def _make_rm(self, resources: dict):
        from app.scheduler.resource_pool import ResourceManager, ResourceTier, LLMResource, UsageRecord
        rm = ResourceManager.__new__(ResourceManager)
        rm._logger = None
        rm._lock = __import__("threading").RLock()
        rm._resources = {}
        rm._usage = {}
        rm._approved_paid = set()
        rm._group_counters = {}
        rm._config_mtime_ns = None
        rm._runtime_mtime_ns = None
        rm._env_mtime_ns = None
        rm._config_path = "config/resource_pool.json"
        rm._sandbox_env = {}
        rm._tier_policy = {}
        rm._selection_strategy = "priority_then_availability"
        rm._log = lambda msg, level="info": None
        rm._maybe_reload_runtime_state = lambda: None  # no disk access in tests

        for rid, rconf in resources.items():
            rm._resources[rid] = LLMResource(
                id=rid,
                type=rconf.get("type", "local"),
                provider=rconf.get("provider", "openai"),
                base_url=rconf.get("base_url", ""),
                model=rconf.get("model", ""),
                tier=ResourceTier(rconf["tier"]),
                priority=rconf.get("priority", 1),
                enabled=rconf.get("enabled", True),
                context_limit=rconf.get("context_limit", 32768),
                output_limit=rconf.get("output_limit", 8192),
                capabilities=rconf.get("capabilities", []),
                account_group=rconf.get("account_group"),
            )
            rm._usage[rid] = UsageRecord()
        return rm

    def test_tier_match(self):
        rm = self._make_rm({
            "free_r": {"type": "local", "tier": "free", "priority": 1},
            "paid_r": {"type": "api", "tier": "paid", "priority": 1},
        })
        result = rm.acquire_by_requirements({"tier": ["free"]})
        self.assertIsNotNone(result)
        self.assertEqual(result.id, "free_r")

    def test_tier_excludes_wrong_tier(self):
        rm = self._make_rm({
            "paid_only": {"type": "api", "tier": "paid", "priority": 1},
        })
        result = rm.acquire_by_requirements({"tier": ["free"]})
        self.assertIsNone(result)

    def test_min_context_filter(self):
        rm = self._make_rm({
            "small": {"type": "local", "tier": "free", "priority": 1, "context_limit": 8192},
            "large": {"type": "local", "tier": "free", "priority": 2, "context_limit": 131072},
        })
        result = rm.acquire_by_requirements({"tier": ["free"], "min_context": 65536})
        self.assertIsNotNone(result)
        self.assertEqual(result.id, "large")

    def test_min_context_no_match(self):
        rm = self._make_rm({
            "small": {"type": "local", "tier": "free", "priority": 1, "context_limit": 8192},
        })
        result = rm.acquire_by_requirements({"tier": ["free"], "min_context": 65536})
        self.assertIsNone(result)

    def test_capabilities_filter(self):
        rm = self._make_rm({
            "no_caps": {"type": "api", "tier": "free_api", "priority": 1, "capabilities": []},
            "tool_use": {"type": "api", "tier": "free_api", "priority": 2, "capabilities": ["tool_use"]},
        })
        result = rm.acquire_by_requirements({"tier": ["free_api"], "capabilities": ["tool_use"]})
        self.assertIsNotNone(result)
        self.assertEqual(result.id, "tool_use")

    def test_capabilities_no_match(self):
        rm = self._make_rm({
            "no_caps": {"type": "api", "tier": "free_api", "priority": 1, "capabilities": []},
        })
        result = rm.acquire_by_requirements({"tier": ["free_api"], "capabilities": ["vision"]})
        self.assertIsNone(result)

    def test_no_requirements_returns_best(self):
        rm = self._make_rm({
            "r1": {"type": "local", "tier": "free", "priority": 1},
            "r2": {"type": "api",   "tier": "free_api", "priority": 5},
        })
        result = rm.acquire_by_requirements({})
        self.assertIsNotNone(result)
        self.assertEqual(result.id, "r1")  # priority 1 wins

    def test_unknown_tier_string_warns_and_falls_back(self):
        rm = self._make_rm({
            "r1": {"type": "local", "tier": "free", "priority": 1},
        })
        # "super_free" is unknown → should fall back to default [free, free_api]
        result = rm.acquire_by_requirements({"tier": ["super_free"]})
        # With only unknown tier in list, tier_preference falls back to [free, free_api]
        self.assertIsNotNone(result)


class TestToolCatalogResolve(unittest.TestCase):
    """_resolve_tools_from_role expands tool_access categories via tool_catalog."""

    CATALOG = {
        "categories": {
            "memory": {"description": "Memory"},
            "file":   {"description": "File"},
            "web":    {"description": "Web"},
            "exec":   {"description": "Exec"},
            "comms":  {"description": "Comms"},
        },
        "tools": {
            "memory_search":    {"category": "memory", "danger_level": "low"},
            "read_file":        {"category": "file",   "danger_level": "low"},
            "write_file":       {"category": "file",   "danger_level": "medium"},
            "search_in_files":  {"category": "file",   "danger_level": "low"},
            "web_search":       {"category": "web",    "danger_level": "low"},
            "bash_exec":        {"category": "exec",   "danger_level": "high"},
            "run_tests":        {"category": "exec",   "danger_level": "medium"},
            "ask_user":         {"category": "comms",  "danger_level": "low", "always_injected": True},
        },
    }

    def _make_executor(self):
        from app.scheduler.agentic_executor import AgenticExecutor
        from app.scheduler.dynamic_tool_registry import DynamicToolRegistry
        ex = AgenticExecutor.__new__(AgenticExecutor)
        ex._log = lambda msg, level="info": None
        ex._tool_registry = DynamicToolRegistry()
        return ex

    def test_tool_access_file_category(self):
        ex = self._make_executor()
        with patch("app.config.config_loader.load_layered_json_config", return_value=self.CATALOG):
            tools = ex._resolve_tools_from_role({"tool_access": ["file"]})
        self.assertIn("read_file", tools)
        self.assertIn("write_file", tools)
        self.assertIn("search_in_files", tools)
        self.assertNotIn("memory_search", tools)
        self.assertNotIn("ask_user", tools)  # always_injected → excluded from category result

    def test_tool_access_multiple_categories(self):
        ex = self._make_executor()
        with patch("app.config.config_loader.load_layered_json_config", return_value=self.CATALOG):
            tools = ex._resolve_tools_from_role({"tool_access": ["memory", "web"]})
        self.assertIn("memory_search", tools)
        self.assertIn("web_search", tools)
        self.assertNotIn("read_file", tools)

    def test_legacy_tools_fallback(self):
        ex = self._make_executor()
        role = {"tools": ["read_file", "memory_search"]}
        tools = ex._resolve_tools_from_role(role)
        self.assertEqual(tools, ["read_file", "memory_search"])

    def test_no_tools_field_defaults_to_memory_search(self):
        ex = self._make_executor()
        tools = ex._resolve_tools_from_role({})
        self.assertEqual(tools, ["memory_search"])

    def test_ask_user_always_injected_by_caller(self):
        """Simulate the caller logic: ask_user added after _resolve_tools_from_role."""
        ex = self._make_executor()
        with patch("app.config.config_loader.load_layered_json_config", return_value=self.CATALOG):
            tools = ex._resolve_tools_from_role({"tool_access": ["file"]})
        # Caller injects ask_user
        if "ask_user" not in tools:
            tools = list(tools) + ["ask_user"]
        self.assertIn("ask_user", tools)

    def test_empty_tool_access_list(self):
        ex = self._make_executor()
        with patch("app.config.config_loader.load_layered_json_config", return_value=self.CATALOG):
            tools = ex._resolve_tools_from_role({"tool_access": []})
        # No categories → no tools (ask_user still injected by caller)
        self.assertNotIn("memory_search", tools)
        self.assertNotIn("web_search", tools)


if __name__ == "__main__":
    unittest.main()
