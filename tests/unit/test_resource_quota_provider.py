"""Provider-reported quota (MiniMax token plan: percent-metered, console-only figures).

The payload below is the shape returned by
GET /backend/account/token_plan/remains_percent on 2026-10-08 (counts are -1:
the plan exposes percentages only).
"""
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

from app.scheduler import resource_quota as rq
from app.scheduler.resource_pool import ResourceManager, ResourceStatus, ResourceTier


def payload(interval_used="0%", weekly_used="0%", start_ms=None, end_ms=None, code=0):
    now_ms = int(time.time() * 1000)
    start_ms = start_ms if start_ms is not None else now_ms - 3600_000
    end_ms = end_ms if end_ms is not None else now_ms + 3600_000
    return {"model_remains": [
        {"model_name": "general", "start_time": start_ms, "end_time": end_ms, "remains_time": 1,
         "current_interval_total_count": -1, "current_interval_used_count": -1,
         "current_interval_remains_count": -1, "current_interval_used_percent": interval_used,
         "current_interval_total_percent": "100%", "current_interval_status": 1,
         "weekly_start_time": now_ms - 86400_000, "weekly_end_time": now_ms + 6 * 86400_000,
         "current_weekly_total_count": -1, "current_weekly_used_count": -1,
         "current_weekly_remains_count": -1, "current_weekly_used_percent": weekly_used,
         "current_weekly_total_percent": "100%", "current_weekly_status": 3},
        {"model_name": "video", "start_time": start_ms, "end_time": end_ms,
         "current_interval_used_percent": "0%", "weekly_start_time": start_ms, "weekly_end_time": end_ms,
         "current_weekly_used_percent": "0%"},
    ], "base_resp": {"status_code": code, "status_msg": "success" if code == 0 else "not login"}}


class TestParse(unittest.TestCase):
    def test_reads_both_windows_from_percentages(self):
        ws = rq.parse_minimax_token_plan(payload("40%", "10%"), "general", 95)
        self.assertEqual([(w.name, w.used, w.exhausted) for w in ws], [("5h", 40, False), ("weekly", 10, False)])
        self.assertEqual(ws[0].agent_limit, 95)
        self.assertGreater(ws[0].resets_at, ws[0].window_start)

    def test_blocks_at_threshold(self):
        ws = rq.parse_minimax_token_plan(payload("96%"), "general", 95)
        self.assertTrue(ws[0].exhausted)
        self.assertFalse(ws[1].exhausted)

    def test_provider_error_raises(self):
        with self.assertRaises(rq.QuotaSourceError):
            rq.parse_minimax_token_plan(payload(code=1004), "general", 100)

    def test_unknown_model_name_raises_and_names_what_exists(self):
        with self.assertRaises(rq.QuotaSourceError) as cm:
            rq.parse_minimax_token_plan(payload(), "audio", 100)
        self.assertIn("general", str(cm.exception))

    def test_unreadable_percent_raises_not_guessed(self):
        with self.assertRaises(rq.QuotaSourceError):
            rq.parse_minimax_token_plan(payload("n/a"), "general", 100)

    def test_validate_source(self):
        rq.validate_source(None)
        rq.validate_source({"type": "minimax_token_plan", "url": "http://x", "model_name": "general"})
        for bad in ({"type": "nope", "url": "u", "model_name": "m"},
                    {"type": "minimax_token_plan", "model_name": "m"},
                    {"type": "minimax_token_plan", "url": "u", "model_name": "m", "block_at_used_pct": 0}):
            with self.assertRaises(ValueError):
                rq.validate_source(bad)


class _Server:
    def __init__(self):
        self.body, self.status = payload(), 200
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/v1/models"):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"data": []}')
                    return
                self.send_response(outer.status)
                self.end_headers()
                self.wfile.write(json.dumps(outer.body).encode())

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_port}"


class TestPoolUsesProviderQuota(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        for name, attr in (("meta.json", "META_FILE"), ("smoke.jsonl", "SMOKE_LOG_FILE"),
                           ("known.json", "KNOWN_IDS_FILE"), ("usage.json", "USAGE_FILE")):
            p = patch.object(ResourceManager, attr, base / name)
            p.start()
            self.addCleanup(p.stop)
        self.server = _Server()
        self.addCleanup(self.server.srv.shutdown)
        res = {"sub": {"type": "api", "provider": "openai", "base_url": self.server.base + "/v1", "model": "m",
                       "tier": "free_api", "priority": 1, "enabled": True, "context_limit": 1000, "output_limit": 100,
                       "quota_source": {"type": "minimax_token_plan", "url": self.server.base + "/quota",
                                        "model_name": "general", "block_at_used_pct": 95}},
               "other": {"type": "api", "provider": "openai", "base_url": self.server.base + "/v1", "model": "o",
                         "tier": "free_api", "priority": 9, "enabled": True, "context_limit": 1000, "output_limit": 100}}
        data = {"resources": res}
        l = patch("app.config.config_loader.load_layered_json_config", return_value=data)
        l.start()
        self.addCleanup(l.stop)
        cfg = base / "pool.json"
        cfg.write_text(json.dumps(data), encoding="utf-8")
        self.rm = ResourceManager(config_path=str(cfg))

    def test_resource_usable_while_provider_reports_room(self):
        self.rm.probe_all()
        self.assertEqual(self.rm.acquire(tier_preference=[ResourceTier.FREE_API]).id, "sub")
        q = {w["name"]: w for w in self.rm.get_status()["sub"]["quota"]}
        self.assertEqual(q["5h"]["used"], 0)

    def test_resource_leaves_rotation_when_provider_reports_exhausted(self):
        self.server.body = payload("97%")
        self.rm.probe_all()
        self.assertEqual(self.rm.acquire(tier_preference=[ResourceTier.FREE_API]).id, "other")
        self.assertEqual(self.rm._compute_status(self.rm._resources["sub"]), ResourceStatus.BUDGET_EXHAUSTED)

    def test_returns_after_reported_window_ends_without_waiting_for_refresh(self):
        past = int((time.time() - 10) * 1000)
        self.server.body = payload("99%", start_ms=past - 5 * 3600_000, end_ms=past)
        self.rm.probe_all()
        self.assertEqual(self.rm.acquire(tier_preference=[ResourceTier.FREE_API]).id, "sub")

    def test_unreadable_quota_is_surfaced_and_last_reading_kept(self):
        self.rm.probe_all()                                   # good reading: 0%
        self.server.body = payload(code=1004)
        self.rm.probe_all()
        st = self.rm.get_status()["sub"]
        self.assertIn("1004", st["quota_source_error"])
        self.assertEqual({w["name"]: w["used"] for w in st["quota"]}["5h"], 0)

    def test_bad_quota_source_config_disables_that_resource(self):
        rm = self.rm
        conf = dict(rm._resources["sub"].quota_source, type="bogus")
        with patch.object(ResourceManager, "_log"):
            r = rm._parse_resource("bad", {"type": "api", "base_url": "http://x/v1", "model": "m",
                                           "tier": "free_api", "quota_source": conf})
        self.assertFalse(r.enabled)
        self.assertIn("quota_source", r.config_error)


if __name__ == "__main__":
    unittest.main()


class TestUseItOrLoseIt(TestPoolUsesProviderQuota):
    """Spend renewing quota first: it is lost if unspent."""

    def _with_boost(self, boost):
        self.rm._resources["sub"].priority = 50          # normally behind 'other' (9)
        self.rm._resources["sub"].priority_while_quota = boost
        self.rm.probe_all()

    def test_subscription_ranks_first_while_it_has_headroom(self):
        self._with_boost(-10)
        self.assertEqual(self.rm.acquire(tier_preference=[ResourceTier.FREE_API]).id, "sub")
        self.assertEqual(self.rm.acquire_by_requirements({"tier": ["free_api"]}).id, "sub")

    def test_falls_back_to_normal_order_when_exhausted(self):
        self.server.body = payload("97%")
        self._with_boost(-10)
        self.assertEqual(self.rm.acquire(tier_preference=[ResourceTier.FREE_API]).id, "other")
        self.assertEqual(self.rm.acquire_by_requirements({"tier": ["free_api"]}).id, "other")

    def test_unset_boost_changes_nothing(self):
        self._with_boost(None)
        self.assertEqual(self.rm.acquire(tier_preference=[ResourceTier.FREE_API]).id, "other")

    def test_boost_ignored_for_resource_without_any_quota(self):
        self.rm._resources["other"].priority_while_quota = -99   # 'other' has no quota config
        self._with_boost(None)
        self.assertEqual(self.rm.acquire(tier_preference=[ResourceTier.FREE_API]).id, "other")
