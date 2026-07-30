"""
Tests for the rate_limited_until circuit-breaker path added 2026-07-30.

Incident: zai-coding-plan's 5-hour quota exhaustion was treated identically
to a one-off connection blip by the blind consecutive_errors/300s breaker.
record_usage(error_message=...) now classifies failures via
provider_errors.classify_provider_error() and, for quota_exhausted errors
with a parseable reset time, sets UsageRecord.rate_limited_until — which
_compute_status() checks before falling back to the generic breaker.
"""
import json
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app.scheduler.resource_pool import ResourceManager, ResourceStatus


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


class TestRateLimitedUntil(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.meta_path = self.tmp_path / "resource_pool_meta.json"
        self.log_path = self.tmp_path / "resource_pool_smoke_log.jsonl"
        self.usage_path = self.tmp_path / "resource_pool_usage.json"
        self.config_path = self.tmp_path / "resource_pool.json"

        _write_pool_config(self.config_path, {
            "solo": _local_resource("some-model", priority=1),
        })

    def _make_manager(self):
        patchers = [
            patch.object(ResourceManager, "META_FILE", self.meta_path),
            patch.object(ResourceManager, "SMOKE_LOG_FILE", self.log_path),
            patch.object(ResourceManager, "USAGE_FILE", self.usage_path),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

        mock_result = subprocess.CompletedProcess(
            args=["lms", "ps", "--json"], returncode=1, stdout="", stderr="",
        )
        run_patcher = patch("subprocess.run", return_value=mock_result)
        run_patcher.start()
        self.addCleanup(run_patcher.stop)

        pool_data = json.loads(self.config_path.read_text(encoding="utf-8"))
        loader_patcher = patch(
            "app.config.config_loader.load_layered_json_config",
            return_value=pool_data,
        )
        loader_patcher.start()
        self.addCleanup(loader_patcher.stop)

        return ResourceManager(config_path=str(self.config_path))

    def test_quota_error_with_reset_time_marks_rate_limited_not_unreachable(self):
        rm = self._make_manager()
        reset_at = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        rm.record_usage(
            "solo", success=False,
            error_message=f"AI_APICallError: Usage limit reached for 5 hour. Your limit will reset at {reset_at}",
        )
        # A single quota failure should not need 5 strikes — it's a known fact,
        # not a flaky-connection guess.
        status = rm._compute_status(rm._resources["solo"])
        self.assertEqual(status, ResourceStatus.RATE_LIMITED)

    def test_quota_reset_time_clears_after_it_elapses(self):
        rm = self._make_manager()
        past = (datetime.now() - timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S")
        rm.record_usage(
            "solo", success=False,
            error_message=f"Usage limit reached. Your limit will reset at {past}",
        )
        status = rm._compute_status(rm._resources["solo"])
        self.assertEqual(status, ResourceStatus.AVAILABLE)
        self.assertIsNone(rm._usage["solo"].rate_limited_until)

    def test_generic_connection_error_still_uses_blind_breaker(self):
        rm = self._make_manager()
        for _ in range(4):
            rm.record_usage("solo", success=False, error_message="Connection refused")
        # 4 strikes: not yet UNREACHABLE (threshold is 5), and no
        # rate_limited_until was ever set for a non-quota error.
        self.assertIsNone(rm._usage["solo"].rate_limited_until)
        status = rm._compute_status(rm._resources["solo"])
        self.assertEqual(status, ResourceStatus.AVAILABLE)

        rm.record_usage("solo", success=False, error_message="Connection refused")
        status = rm._compute_status(rm._resources["solo"])
        self.assertEqual(status, ResourceStatus.UNREACHABLE)

    def test_success_clears_rate_limited_until(self):
        rm = self._make_manager()
        reset_at = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        rm.record_usage(
            "solo", success=False,
            error_message=f"Usage limit reached. Your limit will reset at {reset_at}",
        )
        self.assertIsNotNone(rm._usage["solo"].rate_limited_until)
        rm.record_usage("solo", success=True)
        self.assertIsNone(rm._usage["solo"].rate_limited_until)

    def test_rate_limited_until_persists_across_restart(self):
        rm = self._make_manager()
        reset_at = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        rm.record_usage(
            "solo", success=False,
            error_message=f"Usage limit reached. Your limit will reset at {reset_at}",
        )
        expected = rm._usage["solo"].rate_limited_until

        rm2 = self._make_manager()
        self.assertIsNotNone(rm2._usage["solo"].rate_limited_until)
        self.assertAlmostEqual(rm2._usage["solo"].rate_limited_until, expected, delta=1)

    def test_consecutive_errors_still_reset_on_restart_unlike_rate_limited_until(self):
        rm = self._make_manager()
        for _ in range(3):
            rm.record_usage("solo", success=False, error_message="Connection refused")
        self.assertEqual(rm._usage["solo"].consecutive_errors, 3)

        rm2 = self._make_manager()
        self.assertEqual(rm2._usage["solo"].consecutive_errors, 0)
