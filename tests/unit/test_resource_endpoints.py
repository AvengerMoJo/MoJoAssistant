"""One resource, several routes: "endpoints" maps a network scope to a base_url and the pool's
network_preference picks the first scope the resource has. No match disables the resource."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.scheduler.resource_pool import ResourceManager

EP = {"lan": "http://192.168.2.246:8080/v1", "tailnet": "http://100.65.157.37:8080/v1"}


def _res(**extra) -> dict:
    return {"type": "local", "provider": "openai", "base_url": EP["tailnet"], "model": "m", "tier": "free",
            "priority": 1, "enabled": True, "context_limit": 32768, "output_limit": 8192, **extra}


class TestEndpoints(unittest.TestCase):
    def _manager(self, data: dict) -> ResourceManager:
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
        (d / "resource_pool.json").write_text(json.dumps(data))
        loader = patch("app.config.config_loader.load_layered_json_config", return_value=data)
        loader.start()
        self.addCleanup(loader.stop)
        return ResourceManager(config_path=str(d / "resource_pool.json"))

    def _get(self, data):
        return self._manager(data)._resources["r"]

    def test_default_order_prefers_lan_over_tailnet(self):
        r = self._get({"resources": {"r": _res(endpoints=EP)}})
        self.assertEqual(r.base_url, EP["lan"])
        self.assertTrue(r.enabled)

    def test_pool_preference_can_pick_tailnet(self):
        r = self._get({"network_preference": ["tailnet", "lan"], "resources": {"r": _res(endpoints=EP)}})
        self.assertEqual(r.base_url, EP["tailnet"])

    def test_no_matching_scope_disables_the_resource(self):
        r = self._get({"network_preference": ["local"], "resources": {"r": _res(endpoints=EP)}})
        self.assertFalse(r.enabled)
        self.assertIn("no endpoint", r.config_error)

    def test_bad_endpoints_disable_the_resource(self):
        for bad in ({"mars": "http://x/v1"}, {"lan": "ftp://x"}, {}, "http://x"):
            r = self._get({"resources": {"r": _res(endpoints=bad)}})
            self.assertFalse(r.enabled, bad)
            self.assertIn("endpoints", r.config_error)

    def test_without_endpoints_base_url_is_unchanged(self):
        r = self._get({"resources": {"r": _res()}})
        self.assertEqual(r.base_url, EP["tailnet"])


if __name__ == "__main__":
    unittest.main()


class TestOpenRouterFreeOnly(TestEndpoints):
    def _or(self, model):
        return self._manager({"resources": {"r": _res(type="api", provider="openrouter", base_url="https://openrouter.ai/api/v1",
                                                    model=model, tier="free_api")}})._resources["r"]

    def test_free_models_are_accepted(self):
        for m in ("nvidia/nemotron-3.5-lightning:free", "openrouter/free"):
            self.assertIsNone(self._or(m).config_error, m)

    def test_a_paid_openrouter_model_is_disabled(self):
        r = self._or("anthropic/claude-sonnet-4.5")
        self.assertIn("not a free model", r.config_error)
        self.assertFalse(r.enabled)
