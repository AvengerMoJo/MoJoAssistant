"""Overflow to the cloud only when the local models are really busy.

Local models are preferred; MiniMax (and other external resources) take work when
every local model is generating or has queued requests, from ANY client of the
local server. Both selection paths must behave the same way.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.scheduler.resource_pool import ResourceManager, ResourceTier

TIERS = [ResourceTier.FREE, ResourceTier.FREE_API]


def _local(model, priority):
    return {"type": "local", "provider": "openai", "base_url": "http://127.0.0.1:1/v1", "model": model,
            "tier": "free", "priority": priority, "enabled": True, "context_limit": 32768, "output_limit": 8192}


def _cloud(priority):
    return {"type": "api", "provider": "openai", "base_url": "http://127.0.0.1:1/v1", "model": "c",
            "tier": "free_api", "priority": priority, "enabled": True, "context_limit": 32768, "output_limit": 8192}


def _ps(**states):
    return json.dumps([{"identifier": k, "status": v[0], "queued": v[1]} for k, v in states.items()])


class TestBusyOverflow(unittest.TestCase):
    def _rm(self, ps_json):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        for name, attr in (("meta.json", "META_FILE"), ("smoke.jsonl", "SMOKE_LOG_FILE"),
                           ("known.json", "KNOWN_IDS_FILE"), ("usage.json", "USAGE_FILE")):
            p = patch.object(ResourceManager, attr, base / name)
            p.start()
            self.addCleanup(p.stop)
        self.ps = ps_json
        p = patch("subprocess.run", side_effect=lambda *a, **k: subprocess.CompletedProcess(a, 0, self.ps, ""))
        p.start()
        self.addCleanup(p.stop)
        data = {"resources": {"big": _local("big-model", 0), "small": _local("small-model", 2), "cloud": _cloud(61)}}
        l = patch("app.config.config_loader.load_layered_json_config", return_value=data)
        l.start()
        self.addCleanup(l.stop)
        cfg = base / "pool.json"
        cfg.write_text(json.dumps(data), encoding="utf-8")
        rm = ResourceManager(config_path=str(cfg))
        rm.BUSY_CACHE_TTL_SECONDS = 0  # tests flip the load between calls
        return rm

    def _both(self, rm):
        return (rm.acquire(tier_preference=TIERS).id, rm.acquire_by_requirements({"tier": ["free", "free_api"]}).id)

    def test_idle_locals_are_preferred(self):
        rm = self._rm(_ps(**{"big-model": ("idle", 0), "small-model": ("idle", 0)}))
        self.assertEqual(self._both(rm), ("big", "big"))

    def test_one_busy_local_sends_work_to_the_idle_local(self):
        rm = self._rm(_ps(**{"big-model": ("generating", 0), "small-model": ("idle", 0)}))
        self.assertEqual(self._both(rm), ("small", "small"))

    def test_all_locals_busy_overflows_to_the_cloud_resource(self):
        rm = self._rm(_ps(**{"big-model": ("generating", 0), "small-model": ("idle", 3)}))  # queued counts as busy
        self.assertEqual(self._both(rm), ("cloud", "cloud"))

    def test_busy_flag_visible_in_selection_order(self):
        rm = self._rm(_ps(**{"big-model": ("generating", 0), "small-model": ("idle", 0)}))
        rows = {r["id"]: r for r in rm.selection_order(TIERS)}
        self.assertTrue(rows["big"]["busy"])
        self.assertFalse(rows["small"]["busy"])
        self.assertEqual(rm.selection_order(TIERS)[0]["id"], "small")

    def test_unreadable_load_state_does_not_block_selection(self):
        rm = self._rm("not json")
        self.assertEqual(rm.acquire(tier_preference=TIERS).id, "big")

    def test_busy_local_still_chosen_when_nothing_else_is_eligible(self):
        rm = self._rm(_ps(**{"big-model": ("generating", 0), "small-model": ("generating", 0)}))
        self.assertEqual(rm.acquire(tier_preference=[ResourceTier.FREE]).id, "big")


if __name__ == "__main__":
    unittest.main()
