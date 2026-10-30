"""resource_chat: an agent without keys asks pool models one question. Distinct models are picked by the pool's
ranking, a third-party model needs max_data_scope=third_party, and a failing model is reported, never replaced."""
import asyncio
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.mcp.core.tools import ToolRegistry
from app.scheduler.resource_pool import ResourceManager


def _or(model, prio, **extra):
    return {"type": "api", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "model": model,
            "tier": "free_api", "priority": prio, "enabled": True, "context_limit": 100000, "output_limit": 4096,
            "data_scope": "third_party", **extra}


POOL = {"resources": {
    "or_a_nemotron": _or("nvidia/nemotron:free", 10),
    "or_b_nemotron": _or("nvidia/nemotron:free", 11),   # same model on a second account
    "or_c_dots": _or("dots/dots3:free", 12),
    "or_d_lightning": _or("nvidia/lightning:free", 13),
    "local_x": {"type": "local", "provider": "openai", "base_url": "http://127.0.0.1:1234/v1", "model": "loc",
                "tier": "free", "priority": 1, "enabled": True, "context_limit": 100000, "output_limit": 4096},
}}


class TestResourceChat(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        for name, attr in (("meta.json", "META_FILE"), ("smoke.jsonl", "SMOKE_LOG_FILE"), ("usage.json", "USAGE_FILE")):
            p = patch.object(ResourceManager, attr, d / name)
            p.start()
            self.addCleanup(p.stop)
        for target, kw in (("subprocess.run", {"return_value": subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")}),
                           ("app.config.config_loader.load_layered_json_config", {"return_value": POOL})):
            p = patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)
        (d / "resource_pool.json").write_text(json.dumps(POOL))
        self.rm = ResourceManager(config_path=str(d / "resource_pool.json"))
        for r in self.rm._resources.values():
            r.api_key = "k"
        self.me = type("Me", (), {"_get_resource_manager": lambda s: self.rm})()
        self.calls = []

        async def fake_call(_self, messages, resource_config, model_override=None, tools=None):
            self.calls.append(resource_config["model"])
            if resource_config["model"].startswith("dots"):
                raise ConnectionError("boom")
            return {"choices": [{"message": {"content": "hi from " + resource_config["model"]}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3}}
        p = patch("app.llm.unified_client.UnifiedLLMClient.call_async", fake_call)
        p.start()
        self.addCleanup(p.stop)

    def _chat(self, **a):
        return asyncio.run(ToolRegistry._execute_resource_chat(self.me, a))

    def test_third_party_needs_explicit_scope(self):
        r = self._chat(message="q", provider="openrouter")
        self.assertEqual(r["status"], "error")
        self.assertIn("third_party", r["message"])
        self.assertEqual(self.calls, [])

    def test_three_distinct_models_not_the_same_model_twice(self):
        r = self._chat(message="q", provider="openrouter", models=3, max_data_scope="third_party")
        models = [x["model"] for x in r["results"]]
        self.assertEqual(sorted(models), sorted(set(models)))
        self.assertEqual(len(models), 3)
        self.assertEqual({x["provider"] for x in r["results"]}, {"openrouter"})

    def test_failed_model_is_reported_not_replaced(self):
        r = self._chat(message="q", resource_ids=["or_a_nemotron", "or_c_dots"], max_data_scope="third_party")
        by = {x["resource_id"]: x for x in r["results"]}
        self.assertEqual(by["or_a_nemotron"]["status"], "success")
        self.assertEqual(by["or_c_dots"]["status"], "error")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(r["answered"], 1)

    def test_pinned_resource_outside_scope_is_refused(self):
        r = self._chat(message="q", resource_ids=["or_a_nemotron"])
        self.assertEqual(r["status"], "error")
        self.assertIn("cannot serve", r["message"])

    def test_bad_input(self):
        self.assertEqual(self._chat(message="")["status"], "error")
        self.assertEqual(self._chat(message="q", tier="paid")["status"], "error")
        self.assertEqual(self._chat(message="q", models=99)["status"], "error")


if __name__ == "__main__":
    unittest.main()
