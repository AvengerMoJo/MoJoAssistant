"""Renewing quota windows (5-hourly / weekly / monthly) for subscription resources.

Context 2026-10-08: MiniMax M3 is a subscription with a free allowance that
renews every 5 hours; the old single-window Budget kept its call history in
memory only, so any restart reset it -- unusable for weekly/monthly limits.
"""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.scheduler import resource_quota as rq
from app.scheduler.resource_pool import ResourceManager, ResourceStatus, ResourceTier

H = 3600
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc).timestamp()


def _w(**kw):
    return rq.parse_windows([kw])[0]


class TestParse(unittest.TestCase):
    def test_valid_windows(self):
        ws = rq.parse_windows([
            {"name": "5h", "kind": "rolling", "seconds": 5 * H, "max_calls": 100, "reserved_for_user_pct": 20},
            {"name": "week", "kind": "fixed", "seconds": 7 * 24 * H, "anchor": NOW, "max_calls": 500},
            {"name": "month", "kind": "monthly", "reset_day": 1, "max_calls": 2000},
        ])
        self.assertEqual([w.name for w in ws], ["5h", "week", "month"])
        self.assertEqual(ws[0].agent_limit, 80)

    def test_bad_entries_raise(self):
        bad = [
            {"max_calls": 5, "seconds": 10},                                    # no name
            {"name": "a", "kind": "weekly", "max_calls": 5},                    # unknown kind
            {"name": "a", "kind": "rolling", "max_calls": 0, "seconds": 5},     # zero cap
            {"name": "a", "kind": "rolling", "max_calls": 5},                    # no seconds
            {"name": "a", "kind": "fixed", "max_calls": 5, "seconds": 5},        # no anchor
            {"name": "a", "kind": "monthly", "max_calls": 5, "reset_day": 31},   # bad day
            {"name": "a", "kind": "rolling", "max_calls": 5, "seconds": 5, "reserved_for_user_pct": 100},
        ]
        for entry in bad:
            with self.assertRaises(ValueError, msg=str(entry)):
                rq.parse_windows([entry])

    def test_duplicate_names_raise(self):
        e = {"name": "a", "kind": "rolling", "max_calls": 5, "seconds": 5}
        with self.assertRaises(ValueError):
            rq.parse_windows([e, dict(e)])


class TestEvaluate(unittest.TestCase):
    def test_rolling_counts_only_window_and_frees_oldest_first(self):
        w = _w(name="5h", kind="rolling", seconds=5 * H, max_calls=3)
        stamps = [NOW - 6 * H, NOW - 4 * H, NOW - 2 * H, NOW - 10]
        st = rq.evaluate([w], stamps, NOW)[0]
        self.assertEqual(st.used, 3)
        self.assertTrue(st.exhausted)
        self.assertEqual(st.resets_at, (NOW - 4 * H) + 5 * H)  # oldest in-window call ages out

    def test_rolling_with_room(self):
        w = _w(name="5h", kind="rolling", seconds=5 * H, max_calls=3)
        st = rq.evaluate([w], [NOW - 6 * H, NOW - 10], NOW)[0]
        self.assertEqual((st.used, st.exhausted), (1, False))

    def test_reserved_share_lowers_the_agent_limit(self):
        w = _w(name="5h", kind="rolling", seconds=5 * H, max_calls=10, reserved_for_user_pct=20)
        st = rq.evaluate([w], [NOW - i for i in range(1, 9)], NOW)[0]
        self.assertEqual((st.used, st.agent_limit, st.exhausted), (8, 8, True))

    def test_fixed_block_edges(self):
        anchor = NOW - 7 * 24 * H - 2 * H  # a reset happened 7 days + 2h ago
        w = _w(name="week", kind="fixed", seconds=7 * 24 * H, anchor=anchor, max_calls=2)
        st = rq.evaluate([w], [anchor + 7 * 24 * H + 60, NOW - 5], NOW)[0]
        self.assertEqual(st.used, 2)
        self.assertEqual(st.window_start, anchor + 7 * 24 * H)
        self.assertEqual(st.resets_at, anchor + 14 * 24 * H)
        # a call from the previous block no longer counts
        self.assertEqual(rq.evaluate([w], [anchor + 3600], NOW)[0].used, 0)

    def test_monthly_resets_on_reset_day(self):
        w = _w(name="month", kind="monthly", reset_day=5, max_calls=2)
        oct5 = datetime(2026, 10, 5, tzinfo=timezone.utc).timestamp()
        sep20 = datetime(2026, 9, 20, tzinfo=timezone.utc).timestamp()
        st = rq.evaluate([w], [sep20, oct5 + 60], NOW)[0]  # NOW is Oct 8: window began Oct 5
        self.assertEqual(st.used, 1)
        self.assertEqual(st.window_start, oct5)
        self.assertEqual(st.resets_at, datetime(2026, 11, 5, tzinfo=timezone.utc).timestamp())

    def test_monthly_before_reset_day_uses_previous_month(self):
        w = _w(name="month", kind="monthly", reset_day=20, max_calls=2)
        st = rq.evaluate([w], [], NOW)[0]  # Oct 8 < Oct 20 -> window began Sep 20
        self.assertEqual(st.window_start, datetime(2026, 9, 20, tzinfo=timezone.utc).timestamp())

    def test_lookback_covers_longest_window(self):
        ws = rq.parse_windows([
            {"name": "5h", "kind": "rolling", "seconds": 5 * H, "max_calls": 1},
            {"name": "month", "kind": "monthly", "max_calls": 1},
        ])
        self.assertEqual(rq.lookback_seconds(ws), 31 * 86400)


def _res(quotas=None, priority=1, url="http://127.0.0.1:1/v1"):
    r = {"type": "api", "provider": "openai", "base_url": url, "model": "m", "tier": "free_api",
         "priority": priority, "enabled": True, "context_limit": 32768, "output_limit": 8192}
    if quotas is not None:
        r["quotas"] = quotas
    return r


class TestPoolQuota(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        for name, attr in (("meta.json", "META_FILE"), ("smoke.jsonl", "SMOKE_LOG_FILE"),
                           ("known.json", "KNOWN_IDS_FILE"), ("usage.json", "USAGE_FILE")):
            p = patch.object(ResourceManager, attr, self.base / name)
            p.start()
            self.addCleanup(p.stop)

    def _manager(self, resources):
        data = {"resources": resources}
        l = patch("app.config.config_loader.load_layered_json_config", return_value=data)
        l.start()
        self.addCleanup(l.stop)
        cfg = self.base / "pool.json"
        cfg.write_text(json.dumps(data), encoding="utf-8")
        return ResourceManager(config_path=str(cfg))

    QUOTAS = [{"name": "5h", "kind": "rolling", "seconds": 5 * H, "max_calls": 2},
              {"name": "month", "kind": "monthly", "max_calls": 100}]

    def test_exhausting_any_window_removes_resource_then_falls_through(self):
        rm = self._manager({"sub": _res(self.QUOTAS, priority=1), "other": _res(None, priority=9)})
        self.assertEqual(rm.acquire(tier_preference=[ResourceTier.FREE_API]).id, "sub")
        rm.record_usage("sub")
        rm.record_usage("sub")
        self.assertEqual(rm.acquire(tier_preference=[ResourceTier.FREE_API]).id, "other")
        self.assertEqual(rm._compute_status(rm._resources["sub"]), ResourceStatus.BUDGET_EXHAUSTED)
        self.assertFalse(rm._is_budget_available(rm._resources["sub"]))

    def test_failed_calls_do_not_spend_quota(self):
        rm = self._manager({"sub": _res(self.QUOTAS)})
        for _ in range(5):
            rm.record_usage("sub", success=False, error_message="ConnectError")
        self.assertEqual(rm.quota_status("sub")[0].used, 0)

    def test_usage_survives_restart(self):
        rm = self._manager({"sub": _res(self.QUOTAS)})
        rm.record_usage("sub")
        rm.record_usage("sub")
        rm2 = ResourceManager(config_path=str(self.base / "pool.json"))
        self.assertEqual(rm2.quota_status("sub")[0].used, 2)
        self.assertFalse(rm2._is_budget_available(rm2._resources["sub"]))

    def test_status_reports_windows(self):
        rm = self._manager({"sub": _res(self.QUOTAS)})
        rm.record_usage("sub")
        q = {w["name"]: w for w in rm.get_status()["sub"]["quota"]}
        self.assertEqual((q["5h"]["used"], q["5h"]["agent_limit"]), (1, 2))
        self.assertEqual(q["month"]["used"], 1)

    def test_invalid_quota_config_disables_only_that_resource_loudly(self):
        bad = _res([{"name": "x", "kind": "rolling", "max_calls": 5}])  # no seconds
        rm = self._manager({"broken": bad, "fine": _res(None, priority=9)})
        self.assertFalse(rm._resources["broken"].enabled)
        self.assertIn("seconds", rm._resources["broken"].config_error)
        self.assertEqual(rm.acquire(tier_preference=[ResourceTier.FREE_API]).id, "fine")
        self.assertIn("seconds", rm.get_status()["broken"]["config_error"])


if __name__ == "__main__":
    unittest.main()
