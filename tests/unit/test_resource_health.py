"""Tests for endpoint liveness probing and its effect on resource selection.

Incident 2026-10-08: LM Studio rebound from loopback to the Tailscale address
while every local resource still pointed at localhost; nothing noticed until
tasks failed on it.
"""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

from app.scheduler import resource_health
from app.scheduler.resource_pool import ResourceManager, ResourceStatus, ResourceTier


def _serve(status: int, body: bytes = b'{"data": []}'):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}/v1"


class TestProbeEndpoint(unittest.TestCase):
    def _probe(self, status, body=b'{"data": []}'):
        srv, url = _serve(status, body)
        self.addCleanup(srv.shutdown)
        return resource_health.probe_endpoint(url, "k", timeout=2)

    def test_200_json_is_live(self):
        self.assertEqual(self._probe(200).state, resource_health.LIVE)

    def test_401_is_auth_failed(self):
        self.assertEqual(self._probe(401).state, resource_health.AUTH_FAILED)

    def test_429_is_live_because_quota_is_not_reachability(self):
        self.assertEqual(self._probe(429).state, resource_health.LIVE)

    def test_non_json_200_is_error(self):
        self.assertEqual(self._probe(200, b"<html>").state, resource_health.ERROR)

    def test_refused_connection_is_unreachable(self):
        srv, url = _serve(200)
        srv.shutdown()
        srv.server_close()
        self.assertEqual(resource_health.probe_endpoint(url, timeout=2).state, resource_health.UNREACHABLE)

    def test_empty_base_url_is_error(self):
        self.assertEqual(resource_health.probe_endpoint("").state, resource_health.ERROR)


class TestPoolUsesHealth(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        for name, attr in (("meta.json", "META_FILE"), ("smoke.jsonl", "SMOKE_LOG_FILE"),
                           ("known.json", "KNOWN_IDS_FILE")):
            p = patch.object(ResourceManager, attr, self.base / name)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(ResourceManager, "get_loaded_resource_ids", return_value=set())
        p.start()
        self.addCleanup(p.stop)
        self.live, live_url = _serve(200)
        self.addCleanup(self.live.shutdown)
        dead, dead_url = _serve(200)
        dead.shutdown()
        dead.server_close()
        self.cfg = {"resources": {
            "dead_top": self._res(0, dead_url),
            "live_low": self._res(5, live_url),
        }}
        l = patch("app.config.config_loader.load_layered_json_config", side_effect=lambda *a, **k: self.cfg)
        l.start()
        self.addCleanup(l.stop)
        path = self.base / "pool.json"
        path.write_text(json.dumps(self.cfg), encoding="utf-8")
        self.rm = ResourceManager(config_path=str(path))

    @staticmethod
    def _res(priority, url):
        return {"type": "local", "provider": "openai", "base_url": url, "model": f"m{priority}",
                "tier": "free", "priority": priority, "enabled": True,
                "context_limit": 32768, "output_limit": 8192}

    def test_acquire_skips_unreachable_and_fails_over(self):
        self.rm.probe_all()
        self.assertEqual(self.rm.acquire(tier_preference=[ResourceTier.FREE]).id, "live_low")

    def test_first_failed_probe_gates_routing_but_is_not_reported(self):
        first = {t["resource_id"]: t for t in self.rm.probe_all()}
        self.assertNotIn("dead_top", first)  # one failed probe is not news yet
        self.assertEqual(first["live_low"]["to"], resource_health.LIVE)
        self.assertEqual(self.rm.acquire(tier_preference=[ResourceTier.FREE]).id, "live_low")

    def test_failure_reported_once_after_confirmation(self):
        self.rm.probe_all()
        second = {t["resource_id"]: t for t in self.rm.probe_all()}
        self.assertEqual(second["dead_top"]["to"], resource_health.UNREACHABLE)
        self.assertIsNone(second["dead_top"]["from"])
        self.assertEqual(self.rm.probe_all(), [])

    def test_blip_that_recovers_is_never_reported(self):
        self.rm.probe_all()  # live_low live; dead_top failed once
        live_url = self.cfg["resources"]["live_low"]["base_url"]
        self.cfg["resources"]["dead_top"]["base_url"] = live_url  # dead_top comes back
        self.rm._resources["dead_top"].base_url = live_url
        reported = {t["resource_id"]: t for t in self.rm.probe_all()}
        self.assertEqual(reported["dead_top"]["to"], resource_health.LIVE)

    def test_recovery_reported_after_a_reported_failure(self):
        self.rm.probe_all()
        self.rm.probe_all()  # failure now confirmed and reported
        live_url = self.cfg["resources"]["live_low"]["base_url"]
        self.rm._resources["dead_top"].base_url = live_url
        reported = {t["resource_id"]: t for t in self.rm.probe_all()}
        self.assertEqual(reported["dead_top"]["from"], resource_health.UNREACHABLE)
        self.assertEqual(reported["dead_top"]["to"], resource_health.LIVE)

    def test_live_probe_clears_stale_breaker_errors_after_outage(self):
        from app.scheduler.resource_pool import UsageRecord
        self.rm._usage["live_low"] = UsageRecord(consecutive_errors=5)
        self.rm.probe_all()
        self.assertEqual(self.rm._usage["live_low"].consecutive_errors, 0)
        self.assertEqual(self.rm.acquire(tier_preference=[ResourceTier.FREE]).id, "live_low")

    def test_live_probe_does_not_clear_errors_of_an_already_live_resource(self):
        from app.scheduler.resource_pool import UsageRecord
        self.rm.probe_all()  # live_low is now known live
        self.rm._usage["live_low"] = UsageRecord(consecutive_errors=3)
        self.rm.probe_all()
        self.assertEqual(self.rm._usage["live_low"].consecutive_errors, 3)

    def test_health_check_false_resource_is_never_probed_or_gated(self):
        self.rm._resources["dead_top"].health_check = False
        self.rm.probe_all()
        self.rm.probe_all()
        self.assertNotIn("dead_top", self.rm.get_health())
        self.assertEqual(self.rm.acquire(tier_preference=[ResourceTier.FREE]).id, "dead_top")

    def test_health_path_is_used(self):
        seen = []

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        res = resource_health.probe_endpoint(f"http://127.0.0.1:{srv.server_port}/v1", path="/health")
        self.assertEqual(res.state, resource_health.LIVE)
        self.assertEqual(seen, ["/v1/health"])

    def test_status_reports_unreachable_with_health_detail(self):
        self.rm.probe_all()
        status = self.rm.get_status()
        self.assertEqual(status["dead_top"]["status"], ResourceStatus.UNREACHABLE.value)
        self.assertEqual(status["dead_top"]["health"]["state"], resource_health.UNREACHABLE)

    def test_detect_new_resources_seeds_silently_then_reports_additions(self):
        self.assertEqual(self.rm.detect_new_resources(), [])
        self.cfg["resources"]["added"] = self._res(9, "http://127.0.0.1:1/v1")
        self.rm._resources = {}
        self.rm._load_config()
        self.assertEqual(self.rm.detect_new_resources(), ["added"])
        self.assertEqual(self.rm.detect_new_resources(), [])


if __name__ == "__main__":
    unittest.main()
