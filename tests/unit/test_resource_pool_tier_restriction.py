"""Tests for ResourceManager.find_tier_restriction_conflict.

Incident 2026-10-07: project_sentinel_nightly was pinned to tier_preference
['free_api'], so acquire() only ever saw the cloud accounts (priority 60-90),
exhausted them, and failed with "No resource available" while the resident
local models (priority 0 and 2) sat idle.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.scheduler.resource_pool import ResourceManager, ResourceTier


def _res(tier: str, priority: int, rtype: str = "api", enabled: bool = True) -> dict:
    return {
        "type": rtype,
        "provider": "openai",
        "base_url": "http://localhost:8080/v1",
        "model": f"m{priority}",
        "tier": tier,
        "priority": priority,
        "enabled": enabled,
        "context_limit": 32768,
        "output_limit": 8192,
    }


class TestTierRestrictionConflict(unittest.TestCase):
    def _manager(self, resources: dict) -> ResourceManager:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        for name, attr in (("meta.json", "META_FILE"), ("smoke.jsonl", "SMOKE_LOG_FILE")):
            p = patch.object(ResourceManager, attr, base / name)
            p.start()
            self.addCleanup(p.stop)
        data = {"resources": resources}
        loader = patch("app.config.config_loader.load_layered_json_config", return_value=data)
        loader.start()
        self.addCleanup(loader.stop)
        lms = patch.object(ResourceManager, "get_loaded_resource_ids", return_value=set())
        lms.start()
        self.addCleanup(lms.stop)
        cfg = base / "resource_pool.json"
        cfg.write_text(json.dumps(data), encoding="utf-8")
        return ResourceManager(config_path=str(cfg))

    def test_pin_hiding_better_local_is_reported(self):
        rm = self._manager({
            "local_top": _res("free", 0, "local"),
            "cloud_low": _res("free_api", 60),
        })
        msg = rm.find_tier_restriction_conflict([ResourceTier.FREE_API])
        self.assertIsNotNone(msg)
        self.assertIn("local_top", msg)
        self.assertIn("priority 0", msg)

    def test_pin_with_no_better_hidden_resource_is_fine(self):
        rm = self._manager({
            "local_low": _res("free", 90, "local"),
            "cloud_low": _res("free_api", 60),
        })
        self.assertIsNone(rm.find_tier_restriction_conflict([ResourceTier.FREE_API]))

    def test_default_tiers_never_conflict(self):
        rm = self._manager({
            "local_top": _res("free", 0, "local"),
            "cloud_low": _res("free_api", 60),
        })
        self.assertIsNone(rm.find_tier_restriction_conflict([ResourceTier.FREE, ResourceTier.FREE_API]))

    def test_disabled_and_paid_resources_are_ignored(self):
        rm = self._manager({
            "off_local": _res("free", 0, "local", enabled=False),
            "paid_top": _res("paid", 1),
            "cloud_low": _res("free_api", 60),
        })
        self.assertIsNone(rm.find_tier_restriction_conflict([ResourceTier.FREE_API]))

    def test_pin_matching_no_enabled_resource_is_reported(self):
        rm = self._manager({"local_top": _res("free", 0, "local")})
        msg = rm.find_tier_restriction_conflict([ResourceTier.FREE_API])
        self.assertIsNotNone(msg)
        self.assertIn("no enabled resource", msg)


if __name__ == "__main__":
    unittest.main()
