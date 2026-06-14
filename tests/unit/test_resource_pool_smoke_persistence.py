import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.scheduler.resource_pool import ResourceManager


class TestResourcePoolSmokePersistence(unittest.TestCase):
    def test_record_agentic_smoke_result_persists_latest_metadata_and_appends_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta_path = Path(tmp) / "resource_pool_meta.json"
            log_path = Path(tmp) / "resource_pool_smoke_log.jsonl"
            with patch.object(ResourceManager, "META_FILE", meta_path), patch.object(ResourceManager, "SMOKE_LOG_FILE", log_path):
                rm = ResourceManager(config_path="/nonexistent/resource_pool.json")
                rm.record_agentic_smoke_result(
                    "r1",
                    {
                        "resource_id": "r1",
                        "model": "test-model",
                        "agentic_capable": True,
                        "smoke_profile": "reasoning_stress",
                        "checks": {"constraint_reasoning": {"status": "pass", "failure_class": None}},
                        "iterations_used": 5,
                        "duration_seconds": 12.5,
                        "error": None,
                        "debug_bundle": {
                            "integration_checks": ["memory_search"],
                            "artifact_path": "/tmp/smoke.json",
                        },
                    },
                )

                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                entry = meta["agentic_capable"]["r1"]
                self.assertTrue(entry["value"])
                self.assertEqual(entry["smoke_profile"], "reasoning_stress")
                self.assertEqual(entry["iterations_used"], 5)
                self.assertEqual(entry["integration_checks"], ["memory_search"])
                self.assertEqual(entry["debug_artifact_path"], "/tmp/smoke.json")

                lines = log_path.read_text(encoding="utf-8").strip().splitlines()
                self.assertEqual(len(lines), 1)
                log_entry = json.loads(lines[0])
                self.assertEqual(log_entry["resource_id"], "r1")
                self.assertEqual(log_entry["smoke_profile"], "reasoning_stress")
                self.assertIn("logged_at", log_entry)

    def test_get_agentic_smoke_metadata_marks_stale_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta_path = Path(tmp) / "resource_pool_meta.json"
            log_path = Path(tmp) / "resource_pool_smoke_log.jsonl"
            stale_entry = {
                "agentic_capable": {
                    "r1": {
                        "value": False,
                        "tested_at": "2000-01-01T00:00:00",
                        "smoke_profile": "fast_gate",
                        "checks": {},
                    }
                }
            }
            meta_path.write_text(json.dumps(stale_entry), encoding="utf-8")
            with patch.object(ResourceManager, "META_FILE", meta_path), patch.object(ResourceManager, "SMOKE_LOG_FILE", log_path):
                rm = ResourceManager(config_path="/nonexistent/resource_pool.json")
                self.assertIsNone(rm.get_agentic_capable("r1"))
                meta = rm.get_agentic_smoke_metadata("r1")
                self.assertIsNotNone(meta)
                self.assertTrue(meta["is_stale"])
                self.assertEqual(meta["smoke_profile"], "fast_gate")



    def test_get_agentic_smoke_history_filters_and_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta_path = Path(tmp) / "resource_pool_meta.json"
            log_path = Path(tmp) / "resource_pool_smoke_log.jsonl"
            lines = [
                json.dumps({"resource_id": "r1", "smoke_profile": "fast_gate", "tested_at": "2026-06-11T10:00:00"}),
                json.dumps({"resource_id": "r2", "smoke_profile": "standard_agentic", "tested_at": "2026-06-11T10:05:00"}),
                json.dumps({"resource_id": "r1", "smoke_profile": "reasoning_stress", "tested_at": "2026-06-11T10:10:00"}),
            ]
            log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with patch.object(ResourceManager, "META_FILE", meta_path), patch.object(ResourceManager, "SMOKE_LOG_FILE", log_path):
                rm = ResourceManager(config_path="/nonexistent/resource_pool.json")
                rows = rm.get_agentic_smoke_history(resource_id="r1", limit=1)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["resource_id"], "r1")
                self.assertEqual(rows[0]["smoke_profile"], "reasoning_stress")

if __name__ == "__main__":
    unittest.main()
