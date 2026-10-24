"""A subscription with `pace` is spent evenly: rank 0 while at/behind its pace line, normal rank when ahead,
out of rotation at the agent's share. Uses the provider-quota pool fixture."""
import time

from app.scheduler import resource_quota as rq
from app.scheduler.resource_pool import ResourceTier
from tests.unit.test_resource_quota_provider import TestPoolUsesProviderQuota

DAY = 86400.0


def windows(used_week, elapsed=0.5, used_5h=0):
    now = time.time()
    return {"windows": [rq.WindowStatus("5h", "provider_rolling", used_5h, 85, 100, now - 18000, None, used_5h >= 85),
                        rq.WindowStatus("weekly", "provider_percent", used_week, 85, 100, now - elapsed * 7 * DAY,
                                        now + (1 - elapsed) * 7 * DAY, used_week >= 85)],
            "fetched_at": now, "error": None}


class TestPacedSubscription(TestPoolUsesProviderQuota):
    def _setup(self, used_week, pace=True):
        sub = self.rm._resources["sub"]
        sub.priority, sub.priority_while_quota, sub.pace = 50, 0, rq.parse_pace(pace)
        self.rm._provider_quota["sub"] = windows(used_week)

    def first(self):
        return self.rm.acquire(tier_preference=[ResourceTier.FREE_API]).id

    def test_behind_the_line_it_ranks_first(self):
        self._setup(used_week=30)                       # line is 60 at half a week
        self.assertEqual((self.first(), self.rm._rank_priority(self.rm._resources["sub"])), ("sub", 0))

    def test_ahead_of_the_line_it_waits_its_turn(self):
        self._setup(used_week=70)
        self.assertEqual((self.first(), self.rm._rank_priority(self.rm._resources["sub"])), ("other", 50))

    def test_past_the_agent_share_it_is_out(self):
        self._setup(used_week=86)
        self.assertEqual(self.first(), "other")

    def test_without_pace_the_old_rule_still_applies(self):
        self._setup(used_week=70, pace=None)
        self.assertEqual(self.first(), "sub")

    def test_status_carries_the_budget(self):
        self._setup(used_week=30)
        wk = next(b for b in self.rm.get_status()["sub"]["budget"] if b["window"] == "weekly")
        self.assertEqual((wk["agent_share"], wk["remaining"], wk["ahead_of_pace"]), (85, 55, False))
        self.assertGreater(wk["remaining_per_day"], 0)

    def test_a_bad_pace_setting_disables_that_resource_only(self):
        self.assertIsNotNone(rq.parse_pace(True))
        with self.assertRaises(ValueError):
            rq.parse_pace({"head_start": 2})
