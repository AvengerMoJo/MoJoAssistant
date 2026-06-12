import unittest
from unittest.mock import AsyncMock, patch

from app.mcp.core.tools import ToolRegistry
from app.scheduler.agentic_smoke_test import AgenticSmokeTest


class TestMcpSurfaceEval(unittest.IsolatedAsyncioTestCase):
    async def test_doctor_mcp_surface_eval_compares_both_modes(self):
        registry = ToolRegistry.__new__(ToolRegistry)
        fake_result = {
            "resource_id": "r1",
            "model": "test-model",
            "profile": "fast_gate",
            "integration_checks": [],
            "modes": {"full": [{"agentic_capable": True}], "lean": [{"agentic_capable": False}]},
            "summary": {
                "full": {"runs": 1, "pass_rate": 1.0, "avg_duration_seconds": 10.0, "failing_checks": []},
                "lean": {"runs": 1, "pass_rate": 0.0, "avg_duration_seconds": 12.0, "failing_checks": ["tool_choice"]},
            },
        }
        with patch.object(AgenticSmokeTest, 'compare_tool_schema_modes', new=AsyncMock(return_value=fake_result)) as mock_compare:
            result = await registry._execute_config_doctor_mcp_surface_eval({"resource_id": "r1", "profile": "fast_gate", "repeats": 2})

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"]["full"]["runs"], 1)
        self.assertEqual(mock_compare.await_args.kwargs["repeats"], 2)

    async def test_compare_tool_schema_modes_summarizes_runs(self):
        tester = AgenticSmokeTest()

        async def fake_run(*, resource_id, profile='fast_gate', integration_checks=None, tool_schema_mode='full', **kwargs):
            class _R:
                def __init__(self, capable, duration, checks, mode):
                    self.capable = capable
                    self.duration = duration
                    self.checks = checks
                    self.mode = mode
                def to_dict(self):
                    return {
                        'resource_id': resource_id,
                        'model': 'test-model',
                        'agentic_capable': self.capable,
                        'smoke_profile': profile,
                        'tool_schema_mode': self.mode,
                        'checks': self.checks,
                        'duration_seconds': self.duration,
                    }
            if tool_schema_mode == 'full':
                return _R(True, 10.0, {'tool_calling': {'status': 'pass'}}, 'full')
            return _R(False, 12.0, {'tool_choice': {'status': 'fail'}}, 'lean')

        with patch.object(tester, 'run', side_effect=fake_run):
            result = await tester.compare_tool_schema_modes(resource_id='r1', profile='fast_gate', repeats=1)

        self.assertEqual(result['summary']['full']['pass_rate'], 1.0)
        self.assertEqual(result['summary']['lean']['pass_rate'], 0.0)
        self.assertEqual(result['summary']['lean']['failing_checks'], ['tool_choice'])


if __name__ == '__main__':
    unittest.main()
