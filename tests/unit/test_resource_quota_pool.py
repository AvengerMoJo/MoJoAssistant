"""Shared quota pools: a limit that belongs to the account, not to one model.

OpenRouter allows ~1000 free-model calls/day per account across ALL :free models.
Each model is its own resource (own tools/context/priority) but they spend one budget.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.scheduler.resource_pool import ResourceManager, ResourceTier

FREE_API = [ResourceTier.FREE_API]
POOL = {"openrouter_free": [{"name": "daily", "kind": "fixed", "seconds": 86400, "anchor": 1791417600,
                             "max_calls": 4, "reserved_for_user_pct": 25}]}   # agent limit = 3


def _r(prio, pool="openrouter_free"):
    d = {"type": "api", "provider": "openrouter", "base_url": "http://127.0.0.1:1/v1", "model": f"m{prio}",
         "tier": "free_api", "priority": prio, "enabled": True, "context_limit": 32768, "output_limit": 8192}
    if pool:
        d["quota_pool"] = pool
    return d


class TestQuotaPool(unittest.TestCase):
    def _rm(self, resources, pools=POOL):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        for name, attr in (("meta.json", "META_FILE"), ("smoke.jsonl", "SMOKE_LOG_FILE"),
                           ("known.json", "KNOWN_IDS_FILE"), ("usage.json", "USAGE_FILE")):
            p = patch.object(ResourceManager, attr, self.base / name)
            p.start()
            self.addCleanup(p.stop)
        data = {"resources": resources, "quota_pools": pools}
        l = patch("app.config.config_loader.load_layered_json_config", return_value=data)
        l.start()
        self.addCleanup(l.stop)
        cfg = self.base / "pool.json"
        cfg.write_text(json.dumps(data), encoding="utf-8")
        return ResourceManager(config_path=str(cfg))

    def test_calls_on_different_models_spend_one_budget(self):
        rm = self._rm({"a": _r(1), "b": _r(2), "c": _r(3, pool=None)})
        rm.record_usage("a"); rm.record_usage("b"); rm.record_usage("a")
        self.assertEqual(rm.acquire(tier_preference=FREE_API).id, "c")   # the whole pool is spent
        for rid in ("a", "b"):
            self.assertTrue(rm.quota_status(rid)[0].exhausted)
            self.assertEqual(rm.quota_status(rid)[0].used, 3)

    def test_resource_outside_the_pool_is_unaffected(self):
        rm = self._rm({"a": _r(1), "c": _r(3, pool=None)})
        rm.record_usage("c"); rm.record_usage("c"); rm.record_usage("c"); rm.record_usage("c")
        self.assertEqual(rm.quota_status("c"), [])
        self.assertEqual(rm.acquire(tier_preference=FREE_API).id, "a")

    def test_pool_usage_survives_restart_and_is_not_mistaken_for_a_resource(self):
        rm = self._rm({"a": _r(1), "b": _r(2)})
        rm.record_usage("a"); rm.record_usage("b"); rm.record_usage("a")
        rm2 = ResourceManager(config_path=str(self.base / "pool.json"))
        self.assertEqual(rm2.quota_status("b")[0].used, 3)
        self.assertNotIn("__quota_pools__", rm2._usage)

    def test_failed_calls_do_not_spend_the_pool(self):
        rm = self._rm({"a": _r(1)})
        for _ in range(5):
            rm.record_usage("a", success=False, error_message="HTTP 429")
        self.assertEqual(rm.quota_status("a")[0].used, 0)

    def test_reference_to_undefined_pool_disables_that_resource_loudly(self):
        rm = self._rm({"a": _r(1, pool="nope"), "b": _r(2)})
        self.assertFalse(rm._resources["a"].enabled)
        self.assertIn("nope", rm._resources["a"].config_error)
        self.assertEqual(rm.acquire(tier_preference=FREE_API).id, "b")

    def test_invalid_pool_definition_disables_its_members_only(self):
        rm = self._rm({"a": _r(1), "b": _r(2, pool=None)}, pools={"openrouter_free": [{"name": "x", "max_calls": 5}]})
        self.assertFalse(rm._resources["a"].enabled)
        self.assertTrue(rm._resources["b"].enabled)

    def test_status_names_the_pool_window(self):
        rm = self._rm({"a": _r(1)})
        rm.record_usage("a")
        w = rm.get_status()["a"]["quota"][0]
        self.assertEqual((w["name"], w["used"], w["agent_limit"]), ("openrouter_free/daily", 1, 3))


if __name__ == "__main__":
    unittest.main()
