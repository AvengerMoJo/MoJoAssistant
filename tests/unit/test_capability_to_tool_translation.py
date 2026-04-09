import asyncio
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class TestCapabilityToToolTranslation(unittest.TestCase):
    def test_search_in_files_schema_uses_query(self):
        from app.scheduler.dynamic_tool_registry import DynamicToolRegistry

        reg = DynamicToolRegistry()
        tool = reg._tools["search_in_files"].to_openai_function()
        params = tool["function"]["parameters"]

        self.assertIn("query", params["properties"])
        self.assertNotIn("pattern", params["properties"])
        self.assertEqual(params["required"], ["query"])

    def test_search_in_files_runtime_accepts_pattern_alias(self):
        from app.scheduler.dynamic_tool_registry import DynamicToolRegistry

        reg = DynamicToolRegistry()

        result = asyncio.run(
            reg._search_in_files(
                {
                    "pattern": "DynamicToolRegistry",
                    "path": "app/scheduler/dynamic_tool_registry.py",
                }
            )
        )

        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["count"], 1)

    def test_capability_summary_explains_translation(self):
        from app.scheduler.ninechapter import build_capability_summary

        summary = build_capability_summary({"capabilities": ["file", "memory"]})

        self.assertIn("Capabilities are policy/runtime abstractions", summary)
        self.assertIn("translates these capabilities into concrete tool definitions", summary)

    def test_task_session_read_schema_matches_runtime(self):
        from app.scheduler.dynamic_tool_registry import DynamicToolRegistry

        reg = DynamicToolRegistry()
        tool = reg._tools["task_session_read"].to_openai_function()
        params = tool["function"]["parameters"]

        self.assertEqual(params["required"], ["task_id"])
        self.assertIn("task_id", params["properties"])
        self.assertIn("include_metadata", params["properties"])

    def test_task_report_read_schema_matches_runtime(self):
        from app.scheduler.dynamic_tool_registry import DynamicToolRegistry

        reg = DynamicToolRegistry()
        tool = reg._tools["task_report_read"].to_openai_function()
        params = tool["function"]["parameters"]

        self.assertEqual(params["required"], ["task_id"])
        self.assertIn("task_id", params["properties"])

    def test_task_report_read_runtime_loads_report(self):
        from app.scheduler.dynamic_tool_registry import DynamicToolRegistry

        with TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "task_reports"
            report_dir.mkdir(parents=True, exist_ok=True)
            report_path = report_dir / "task-123.json"
            report_path.write_text('{"status":"completed","summary":"ok"}', encoding="utf-8")

            old_memory = os.environ.get("MEMORY_PATH")
            os.environ["MEMORY_PATH"] = tmp
            try:
                reg = DynamicToolRegistry()
                result = asyncio.run(reg._task_report_read({"task_id": "task-123"}))
            finally:
                if old_memory is None:
                    os.environ.pop("MEMORY_PATH", None)
                else:
                    os.environ["MEMORY_PATH"] = old_memory

        self.assertTrue(result["success"])
        self.assertEqual(result["report"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
