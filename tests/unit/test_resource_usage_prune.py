"""Orphan usage records (resources removed from config) are archived, not left to skew analysis."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.scheduler.resource_pool import ResourceManager


def _res(prio):
    return {"type": "api", "provider": "openai", "base_url": "http://127.0.0.1:1/v1", "model": f"m{prio}",
            "tier": "free_api", "priority": prio, "enabled": True, "context_limit": 1000, "output_limit": 100}


class TestPrune(unittest.TestCase):
    def _setup(self, resources, usage):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        for name, attr in (("meta.json", "META_FILE"), ("smoke.jsonl", "SMOKE_LOG_FILE"),
                           ("known.json", "KNOWN_IDS_FILE"), ("usage.json", "USAGE_FILE")):
            p = patch.object(ResourceManager, attr, self.base / name)
            p.start()
            self.addCleanup(p.stop)
        (self.base / "usage.json").write_text(json.dumps(usage), encoding="utf-8")
        data = {"resources": resources}
        l = patch("app.config.config_loader.load_layered_json_config", return_value=data)
        l.start()
        self.addCleanup(l.stop)
        cfg = self.base / "pool.json"
        cfg.write_text(json.dumps(data), encoding="utf-8")
        return ResourceManager(config_path=str(cfg))

    USAGE = {"live": {"total_calls": 5, "last_call_at": 1.0, "consecutive_errors": 0, "rate_limited_until": None},
             "gone": {"total_calls": 9, "last_call_at": 2.0, "consecutive_errors": 3, "rate_limited_until": None},
             "__quota_pools__": {"p": [1.0]}}

    def test_orphans_are_archived_and_removed_live_ones_kept(self):
        rm = self._setup({"live": _res(1)}, self.USAGE)
        self.assertEqual(set(rm._usage), {"live"})
        persisted = json.loads((self.base / "usage.json").read_text())
        self.assertIn("live", persisted)
        self.assertNotIn("gone", persisted)
        self.assertEqual(persisted["__quota_pools__"], {"p": [1.0]})          # pool history untouched
        archive = json.loads((self.base / "resource_pool_usage_pruned.json").read_text())
        self.assertEqual(archive["gone"][0]["total_calls"], 9)

    def test_nothing_is_pruned_when_no_resources_loaded(self):
        rm = self._setup({}, self.USAGE)
        self.assertIn("gone", rm._usage)                                       # failed/empty config must not wipe history
        self.assertFalse((self.base / "resource_pool_usage_pruned.json").exists())

    def test_recently_active_unconfigured_resource_is_kept(self):
        rm = self._setup({"live": _res(1)}, self.USAGE)
        rm.record_usage("recent_orphan")            # just used: absent from config but not idle
        self.assertEqual(rm.prune_orphan_usage(), [])
        self.assertIn("recent_orphan", rm._usage)

    def test_repeat_prunes_append_to_the_archive(self):
        rm = self._setup({"live": _res(1)}, self.USAGE)
        rm.record_usage("late_orphan")
        rm._usage["late_orphan"].last_call_at = 5.0  # long idle
        self.assertEqual(rm.prune_orphan_usage(), ["late_orphan"])
        archive = json.loads((self.base / "resource_pool_usage_pruned.json").read_text())
        self.assertEqual(set(archive), {"gone", "late_orphan"})

if __name__ == "__main__":
    unittest.main()
