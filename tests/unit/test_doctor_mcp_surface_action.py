import unittest

from app.mcp.core.tools import ToolRegistry


class TestDoctorMcpSurfaceAction(unittest.IsolatedAsyncioTestCase):
    async def test_doctor_mcp_surface_reports_size_and_behavior(self):
        registry = ToolRegistry.__new__(ToolRegistry)
        registry.get_tools_lean_json_size = lambda: {
            "full_bytes": 1000,
            "lean_bytes": 600,
            "reduction_pct": 40.0,
            "per_tool": {"foo": 100},
            "per_tool_lean": {"foo": 60},
        }
        result = await registry._execute_config_doctor_mcp_surface({})

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"]["full_bytes"], 1000)
        self.assertEqual(result["summary"]["lean_bytes"], 600)
        self.assertIn("prompt_difference", result["behavior"])
        self.assertIn("not the agentic system prompt", result["behavior"]["prompt_difference"].lower())


if __name__ == "__main__":
    unittest.main()
