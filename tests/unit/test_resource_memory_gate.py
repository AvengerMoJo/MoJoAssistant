"""Memory-ceiling load gate.

Incident 2026-10-03: cumulative memory of several loaded local models crashed the whole
machine. A cold local model may be routed to only if it fits under memory_ceiling_gb
together with what is already resident; an unknown size fails closed.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.scheduler.resource_pool import ResourceManager, ResourceTier

FREE = [ResourceTier.FREE]


def _local(model, prio, vram=None, **kw):
    d = {"type": "local", "provider": "openai", "base_url": "http://127.0.0.1:1/v1", "model": model,
         "tier": "free", "priority": prio, "enabled": True, "context_limit": 32768, "output_limit": 8192}
    if vram is not None:
        d["vram_gb"] = vram
    d.update(kw)
    return d


def _ps(*ids):
    return json.dumps([{"identifier": i, "status": "idle", "queued": 0} for i in ids])


class TestMemoryGate(unittest.TestCase):
    def _rm(self, resources, loaded=("resident-model",), ceiling=40):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        for name, attr in (("meta.json", "META_FILE"), ("smoke.jsonl", "SMOKE_LOG_FILE"),
                           ("known.json", "KNOWN_IDS_FILE"), ("usage.json", "USAGE_FILE")):
            p = patch.object(ResourceManager, attr, base / name)
            p.start()
            self.addCleanup(p.stop)
        self.ps = _ps(*loaded)
        p = patch("subprocess.run", side_effect=lambda *a, **k: subprocess.CompletedProcess(a, 0, self.ps, ""))
        p.start()
        self.addCleanup(p.stop)
        data = {"resources": resources}
        if ceiling is not None:
            data["memory_ceiling_gb"] = ceiling
        l = patch("app.config.config_loader.load_layered_json_config", return_value=data)
        l.start()
        self.addCleanup(l.stop)
        cfg = base / "pool.json"
        cfg.write_text(json.dumps(data), encoding="utf-8")
        return ResourceManager(config_path=str(cfg))

    def test_cold_model_that_would_exceed_the_ceiling_is_not_routable(self):
        rm = self._rm({"resident": _local("resident-model", 5, vram=24), "big": _local("big-model", 0, vram=22)})
        self.assertEqual(rm.acquire(tier_preference=FREE).id, "resident")   # 24 + 22 > 40
        reason = next(r for r in rm.selection_order(FREE) if r["id"] == "big")["excluded_because"]
        self.assertIn("exceed the memory ceiling", reason)
        self.assertIn("24.0 GB resident + 22.0 GB > 40 GB", reason)

    def test_cold_model_that_fits_is_routable(self):
        rm = self._rm({"resident": _local("resident-model", 5, vram=24), "small": _local("small-model", 0, vram=10)})
        row = next(r for r in rm.selection_order(FREE) if r["id"] == "small")
        self.assertTrue(row["eligible"])                                   # 24 + 10 <= 40
        self.assertEqual(rm.acquire(tier_preference=FREE, exclude_ids={"resident"}).id, "small")

    def test_unknown_size_fails_closed_for_a_cold_model(self):
        rm = self._rm({"resident": _local("resident-model", 5, vram=24), "mystery": _local("mystery-model", 0)})
        self.assertIn("vram_gb not set", next(r for r in rm.selection_order(FREE) if r["id"] == "mystery")["excluded_because"])
        self.assertEqual(rm.acquire(tier_preference=FREE).id, "resident")

    def test_resident_model_is_never_gated_even_without_vram(self):
        rm = self._rm({"resident": _local("resident-model", 5)})
        self.assertEqual(rm.acquire(tier_preference=FREE).id, "resident")

    def test_no_ceiling_configured_means_no_gate(self):
        rm = self._rm({"resident": _local("resident-model", 5, vram=24), "big": _local("big-model", 0, vram=90)}, ceiling=None)
        self.assertTrue(next(r for r in rm.selection_order(FREE) if r["id"] == "big")["eligible"])  # would be refused with a ceiling
        self.assertEqual(rm.acquire(tier_preference=FREE, exclude_ids={"resident"}).id, "big")

    def test_non_local_resources_are_not_gated(self):
        cloud = {"type": "api", "provider": "openai", "base_url": "http://127.0.0.1:1/v1", "model": "c",
                 "tier": "free", "priority": 1, "enabled": True, "context_limit": 1000, "output_limit": 100}
        rm = self._rm({"resident": _local("resident-model", 5, vram=24), "cloud": cloud})
        self.assertEqual(rm.acquire(tier_preference=FREE).id, "cloud")

    def test_pinned_acquire_refuses_a_load_that_does_not_fit(self):
        rm = self._rm({"resident": _local("resident-model", 5, vram=24), "big": _local("big-model", 0, vram=22)})
        self.assertIsNone(rm.acquire_by_id("big"))
        self.assertIsNotNone(rm.acquire_by_id("resident"))

    def test_requirements_path_is_gated_too(self):
        rm = self._rm({"resident": _local("resident-model", 5, vram=24), "big": _local("big-model", 0, vram=22)})
        self.assertEqual(rm.acquire_by_requirements({"tier": ["free"]}).id, "resident")

    def test_requirements_failure_names_every_reason(self):
        rm = self._rm({"big": _local("big-model", 0, vram=60), "off": _local("off", 1, vram=1, enabled=False)}, loaded=())
        self.assertIsNone(rm.acquire_by_requirements({"tier": ["free"], "min_context": 65536}))
        msg = rm.requirements_rejection_summary({"tier": ["free"], "min_context": 65536})
        self.assertIn("big: context 32768 < required 65536", msg)
        self.assertIn("off: disabled", msg)


if __name__ == "__main__":
    unittest.main()
