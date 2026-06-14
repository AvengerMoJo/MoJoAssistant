import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.mcp.core.tools import ToolRegistry
from app.scheduler.resource_pool import ResourceManager


class TestDoctorSmokeHistoryAction(unittest.IsolatedAsyncioTestCase):
    async def test_doctor_smoke_history_reads_filtered_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta_path = Path(tmp) / "resource_pool_meta.json"
            log_path = Path(tmp) / "resource_pool_smoke_log.jsonl"
            log_path.write_text(
                "\n".join([
                    json.dumps({"resource_id": "r1", "smoke_profile": "fast_gate"}),
                    json.dumps({"resource_id": "r2", "smoke_profile": "standard_agentic"}),
                    json.dumps({"resource_id": "r1", "smoke_profile": "reasoning_stress"}),
                ]) + "\n",
                encoding="utf-8",
            )
            with patch.object(ResourceManager, "META_FILE", meta_path), patch.object(ResourceManager, "SMOKE_LOG_FILE", log_path):
                registry = ToolRegistry.__new__(ToolRegistry)
                registry._get_resource_manager = lambda: ResourceManager(config_path="/nonexistent/resource_pool.json")
                result = await registry._execute_config_doctor_smoke_history({"resource_id": "r1", "limit": 5})

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["items"][0]["smoke_profile"], "reasoning_stress")
        self.assertEqual(result["items"][1]["smoke_profile"], "fast_gate")


if __name__ == "__main__":
    unittest.main()
