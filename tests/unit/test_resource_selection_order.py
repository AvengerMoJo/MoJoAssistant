"""The displayed selection order must be the order acquire() actually uses.

Bug report 2026-10-08 (resource_routing_config_vs_execution_bug_2610): resource_status
listed resources by raw priority while acquire() ranked by effective priority
(load penalty, quota-aware priority, health), so the top-listed resource was not
the one that ran.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.scheduler.resource_pool import ResourceManager, ResourceTier

FREE_API = [ResourceTier.FREE_API]


def _r(priority, tier="free_api", rtype="api", enabled=True, **extra):
    d = {"type": rtype, "provider": "openai", "base_url": "http://127.0.0.1:1/v1", "model": f"m{priority}",
         "tier": tier, "priority": priority, "enabled": enabled, "context_limit": 32768, "output_limit": 8192}
    d.update(extra)
    return d


class TestSelectionOrder(unittest.TestCase):
    def _rm(self, resources, loaded=()):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        for name, attr in (("meta.json", "META_FILE"), ("smoke.jsonl", "SMOKE_LOG_FILE"),
                           ("known.json", "KNOWN_IDS_FILE"), ("usage.json", "USAGE_FILE")):
            p = patch.object(ResourceManager, attr, base / name)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(ResourceManager, "get_loaded_resource_ids", return_value=set(loaded))
        p.start()
        self.addCleanup(p.stop)
        data = {"resources": resources}
        l = patch("app.config.config_loader.load_layered_json_config", return_value=data)
        l.start()
        self.addCleanup(l.stop)
        cfg = base / "pool.json"
        cfg.write_text(json.dumps(data), encoding="utf-8")
        return ResourceManager(config_path=str(cfg))

    def test_first_listed_is_what_acquire_returns_with_load_penalty(self):
        rm = self._rm({"cold_top": _r(0, "free", "local"), "warm_low": _r(4, "free", "local")}, loaded={"warm_low"})
        order = rm.selection_order([ResourceTier.FREE])
        self.assertEqual(order[0]["id"], rm.acquire(tier_preference=[ResourceTier.FREE]).id)
        self.assertEqual(order[0]["id"], "warm_low")  # raw priority says cold_top; the penalty reorders
        cold = next(r for r in order if r["id"] == "cold_top")
        self.assertTrue(cold["cold_load_penalty"])
        self.assertGreater(cold["effective_priority"], cold["configured_priority"])

    def test_quota_aware_priority_is_reflected(self):
        quotas = [{"name": "5h", "kind": "rolling", "seconds": 18000, "max_calls": 10}]
        rm = self._rm({"sub": _r(50, quotas=quotas, priority_while_quota=-10), "plain": _r(5)})
        self.assertEqual(rm.selection_order(FREE_API)[0]["id"], "sub")
        self.assertEqual(rm.acquire(tier_preference=FREE_API).id, "sub")

    def test_excluded_resources_list_the_reason_and_sort_last(self):
        rm = self._rm({"ok": _r(5), "off": _r(0, enabled=False), "wrong_tier": _r(1, "free"),
                       "small": _r(2, context_limit=10)})
        rows = {r["id"]: r for r in rm.selection_order(FREE_API, min_context=1000)}
        self.assertEqual(rows["off"]["excluded_because"], "disabled")
        self.assertIn("tier free not in", rows["wrong_tier"]["excluded_because"])
        self.assertIn("context 10 < required 1000", rows["small"]["excluded_because"])
        self.assertTrue(rows["ok"]["eligible"])
        self.assertEqual(rm.selection_order(FREE_API, min_context=1000)[0]["id"], "ok")

    def test_exhausted_quota_and_failed_probe_are_named(self):
        quotas = [{"name": "5h", "kind": "rolling", "seconds": 18000, "max_calls": 1}]
        rm = self._rm({"sub": _r(1, quotas=quotas), "dead": _r(2)})
        rm.record_usage("sub")
        rm.probe_all()  # 127.0.0.1:1 refuses connections
        rows = {r["id"]: r for r in rm.selection_order(FREE_API)}
        self.assertEqual(rows["sub"]["excluded_because"], "quota exhausted (5h)")
        self.assertTrue(rows["dead"]["excluded_because"].startswith("unreachable"))

    def test_rejection_summary_names_every_resource(self):
        rm = self._rm({"a": _r(1, enabled=False), "b": _r(2, "free")})
        msg = rm.rejection_summary(FREE_API)
        self.assertIn("a: disabled", msg)
        self.assertIn("b: tier free not in", msg)

    def test_display_never_disagrees_with_acquire_across_exclusions(self):
        rm = self._rm({"x": _r(1), "y": _r(2), "z": _r(3)})
        for ex in (set(), {"x"}, {"x", "y"}):
            listed = next((r["id"] for r in rm.selection_order(FREE_API, exclude_ids=ex) if r["eligible"]), None)
            got = rm.acquire(tier_preference=FREE_API, exclude_ids=ex)
            self.assertEqual(listed, got.id if got else None)


if __name__ == "__main__":
    unittest.main()
