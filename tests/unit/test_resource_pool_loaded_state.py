"""Tests for loaded-model-aware resource selection.

Incident 2026-07-21: ResourceManager.acquire() sorted candidates by static
`priority` alone, with no signal for whether a local model was actually
resident in VRAM. This routed real tasks to cold models (ConnectTimeout,
400s) while already-loaded models sat idle. See
~/.memory/research/resource_manager_loaded_state_fix_2607.md.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.scheduler.resource_pool import ResourceManager, ResourceTier


def _write_pool_config(path: Path, resources: dict) -> None:
    path.write_text(json.dumps({"resources": resources}), encoding="utf-8")


def _local_resource(model: str, priority: int) -> dict:
    return {
        "type": "local",
        "provider": "openai",
        "base_url": "http://localhost:8080/v1",
        "model": model,
        "tier": "free",
        "priority": priority,
        "enabled": True,
        "context_limit": 32768,
        "output_limit": 8192,
    }


def _lms_ps_json(loaded_identifiers):
    return json.dumps([{"identifier": ident, "status": "idle"} for ident in loaded_identifiers])


class TestLoadedStateAwareAcquire(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.meta_path = self.tmp_path / "resource_pool_meta.json"
        self.log_path = self.tmp_path / "resource_pool_smoke_log.jsonl"
        self.config_path = self.tmp_path / "resource_pool.json"

        _write_pool_config(self.config_path, {
            "cold_high_priority": _local_resource("cold-model", priority=4),
            "warm_low_priority": _local_resource("warm-model", priority=8),
        })

    def _make_manager(self, lms_ps_stdout: str, lms_ps_returncode: int = 0):
        patchers = [
            patch.object(ResourceManager, "META_FILE", self.meta_path),
            patch.object(ResourceManager, "SMOKE_LOG_FILE", self.log_path),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

        mock_result = subprocess.CompletedProcess(
            args=["lms", "ps", "--json"], returncode=lms_ps_returncode,
            stdout=lms_ps_stdout, stderr="",
        )
        run_patcher = patch("subprocess.run", return_value=mock_result)
        run_patcher.start()
        self.addCleanup(run_patcher.stop)

        # _load_config() ignores the constructor's config_path and always
        # resolves the real layered "config/resource_pool.json" — patch the
        # loader itself so tests control exactly what resources exist.
        pool_data = json.loads(self.config_path.read_text(encoding="utf-8"))
        loader_patcher = patch(
            "app.config.config_loader.load_layered_json_config",
            return_value=pool_data,
        )
        loader_patcher.start()
        self.addCleanup(loader_patcher.stop)

        return ResourceManager(config_path=str(self.config_path))

    def test_warm_lower_priority_beats_cold_higher_priority_within_penalty_range(self):
        # warm(8) effective=8 vs cold(4) effective=4+LOAD_PENALTY(10)=14 -> warm wins
        rm = self._make_manager(_lms_ps_json(["warm-model"]))
        best = rm.acquire()
        self.assertEqual(best.id, "warm_low_priority")

    def test_cold_wins_if_priority_gap_exceeds_penalty(self):
        # A cold resource whose raw priority is far enough ahead should still win.
        _write_pool_config(self.config_path, {
            "cold_far_ahead": _local_resource("cold-model", priority=1),
            "warm_far_behind": _local_resource("warm-model", priority=50),
        })
        rm = self._make_manager(_lms_ps_json(["warm-model"]))
        best = rm.acquire()
        self.assertEqual(best.id, "cold_far_ahead")

    def test_nothing_loaded_falls_back_to_plain_priority(self):
        rm = self._make_manager(_lms_ps_json([]))
        best = rm.acquire()
        self.assertEqual(best.id, "cold_high_priority")  # priority 4 < 8, both cold -> unaffected

    def test_lms_failure_fails_open_and_uses_plain_priority(self):
        rm = self._make_manager(lms_ps_stdout="", lms_ps_returncode=1)
        best = rm.acquire()
        self.assertEqual(best.id, "cold_high_priority")  # loaded set stays empty, no crash

    def test_malformed_lms_json_fails_open(self):
        rm = self._make_manager(lms_ps_stdout="not json", lms_ps_returncode=0)
        best = rm.acquire()
        self.assertEqual(best.id, "cold_high_priority")

    def test_api_resources_never_penalized_by_loaded_state(self):
        _write_pool_config(self.config_path, {
            "local_cold": _local_resource("cold-model", priority=1),
            "api_resource": {
                "type": "api", "provider": "openai", "base_url": "https://api.example.com/v1",
                "model": "gpt-x", "tier": "free_api", "priority": 5, "enabled": True,
                "context_limit": 32768, "output_limit": 8192,
            },
        })
        rm = self._make_manager(_lms_ps_json([]))
        best = rm.acquire(tier_preference=[ResourceTier.FREE, ResourceTier.FREE_API])
        # local_cold(1, unloaded local -> +penalty=11) vs api_resource(5, never penalized -> 5)
        self.assertEqual(best.id, "api_resource")

    def test_loaded_state_cached_across_repeated_acquire_calls(self):
        rm = self._make_manager(_lms_ps_json(["warm-model"]))
        rm.acquire()
        rm.acquire()
        # subprocess.run patched at module level; assert it was only invoked once
        # despite two acquire() calls (TTL not expired).
        self.assertEqual(subprocess.run.call_count, 1)

    def test_refresh_loaded_models_now_forces_a_fresh_check(self):
        rm = self._make_manager(_lms_ps_json(["warm-model"]))
        rm.acquire()
        rm.refresh_loaded_models_now()
        self.assertEqual(subprocess.run.call_count, 2)

    def test_loaded_state_persists_to_meta_file(self):
        rm = self._make_manager(_lms_ps_json(["warm-model"]))
        rm.acquire()
        meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        self.assertIn("warm_low_priority", meta["loaded_models"]["resource_ids"])
        self.assertIsNotNone(meta["loaded_models"]["checked_at"])


if __name__ == "__main__":
    unittest.main()
