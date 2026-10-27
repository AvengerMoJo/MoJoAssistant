"""A model that reads a big prompt sends nothing until it has read all of it, so a resource can set how long a
call may wait (timeout_seconds); and the clock goes at the END of the system prompt so the model server's saved
read of the role/workflow text is reused between tasks."""
import asyncio
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.scheduler.agentic_executor import AgenticExecutor
from app.scheduler.resource_pool import ResourceManager


def _resource(**extra) -> dict:
    return {"type": "local", "provider": "openai", "base_url": "http://localhost:8080/v1", "model": "m",
            "tier": "free", "priority": 1, "enabled": True, "context_limit": 32768, "output_limit": 8192, **extra}


class TestTimeoutSeconds(unittest.TestCase):
    def _manager(self, resources: dict) -> ResourceManager:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        for name, attr in (("meta.json", "META_FILE"), ("smoke.jsonl", "SMOKE_LOG_FILE"), ("usage.json", "USAGE_FILE")):
            p = patch.object(ResourceManager, attr, d / name)
            p.start()
            self.addCleanup(p.stop)
        run = patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""))
        run.start()
        self.addCleanup(run.stop)
        data = {"resources": resources}
        (d / "resource_pool.json").write_text(json.dumps(data))
        loader = patch("app.config.config_loader.load_layered_json_config", return_value=data)
        loader.start()
        self.addCleanup(loader.stop)
        return ResourceManager(config_path=str(d / "resource_pool.json"))

    def test_timeout_is_read_from_config_and_defaults_to_unset(self):
        rm = self._manager({"slow": _resource(timeout_seconds=840), "plain": _resource()})
        self.assertEqual(rm._resources["slow"].timeout_seconds, 840.0)
        self.assertIsNone(rm._resources["plain"].timeout_seconds)

    def test_bad_timeout_disables_the_resource_with_a_reason(self):
        rm = self._manager({"zero": _resource(timeout_seconds=0), "text": _resource(timeout_seconds="long"),
                            "flag": _resource(timeout_seconds=True)})
        for rid in ("zero", "text", "flag"):
            r = rm._resources[rid]
            self.assertIn("timeout_seconds", r.config_error or "", rid)
            self.assertIsNone(r.timeout_seconds)

    def test_call_llm_passes_the_resources_timeout_to_the_client(self):
        for timeout, expected in ((840.0, 840.0), (None, "absent")):
            ex = AgenticExecutor.__new__(AgenticExecutor)
            ex._rm = MagicMock()
            seen = {}

            class _Slot:
                async def __aenter__(self): return None
                async def __aexit__(self, *a): return False

            ex._rm.slot = lambda *a, **k: _Slot()
            ex._resolve_model_for_resource = AsyncMock(return_value="m")
            res = MagicMock(api_key=None, base_url="http://x/v1", output_limit=100, provider="openai", id="r",
                            timeout_seconds=timeout)

            async def fake_call(self, messages, resource_config, model_override=None, tools=None):
                seen.update(resource_config)
                return {"choices": [{"message": {"content": "ok"}}]}

            with patch("app.llm.unified_client.UnifiedLLMClient.call_async", fake_call):
                asyncio.run(ex._call_llm(res, [{"role": "user", "content": "hi"}]))
            if expected == "absent":
                self.assertNotIn("timeout", seen)
            else:
                self.assertEqual(seen["timeout"], expected)


class TestPromptOrder(unittest.TestCase):
    def test_clock_is_last_and_the_shared_start_does_not_change_with_it(self):
        compose = AgenticExecutor._compose_system_prompt
        a = compose("MODE\n", "CHARACTER\n", "TEMPLATE\n", "WORKFLOW", "## Runtime context\n- time: 10:01\n")
        b = compose("MODE\n", "CHARACTER\n", "TEMPLATE\n", "WORKFLOW", "## Runtime context\n- time: 10:02\n")
        self.assertTrue(a.endswith("- time: 10:01\n"))
        shared = a.index("## Runtime context")
        self.assertEqual(a[:shared], b[:shared])
        self.assertNotEqual(a, b)
        # without a character block too
        c = compose("MODE\n", "", "TEMPLATE\n", "WORKFLOW", "## Runtime context\n- time: 10:01\n")
        self.assertTrue(c.index("WORKFLOW") < c.index("## Runtime context"))


if __name__ == "__main__":
    unittest.main()
