"""Shadow mode: the engine is asked on the side, every comparison is logged, and nothing it says changes the pick."""
import json
import threading
import time

import pytest

from app.scheduler.engine_shadow import MAX_PENDING, ShadowSelector


class FakeClient:
    def __init__(self, out=None, error=None, gate=None):
        self.out, self.error, self.gate, self.calls = out, error, gate, []

    def select(self, requirements, limit=8):
        self.calls.append(requirements)
        if self.gate:
            self.gate.wait(5)
        if self.error:
            raise self.error
        return self.out


def run(tmp_path, client, mojo, n=1):
    sel = ShadowSelector(lambda: client, tmp_path / "shadow.jsonl")
    for _ in range(n):
        sel.compare("acquire", mojo, {"tiers": ["free"]})
    sel.close()
    return [json.loads(l) for l in (tmp_path / "shadow.jsonl").read_text().splitlines()]


def ranked(*ids, group=None):
    return {"ranked": [{"id": i, "account_group": group, "rank_priority": 0} for i in ids], "excluded": []}


def test_same_pick_is_exact(tmp_path):
    [r] = run(tmp_path, FakeClient(ranked("a", "b")), {"id": "a", "group": None, "tier": "free"})
    assert (r["level"], r["engine"], r["mojo_position_in_engine"]) == ("exact", "a", 1)


def test_a_different_pick_is_a_disagreement_with_the_reason_the_engine_excluded_it(tmp_path):
    out = {**ranked("b", "c"), "excluded": [{"id": "a", "reason": "disabled (no credential configured)"}]}
    [r] = run(tmp_path, FakeClient(out), {"id": "a", "group": None, "tier": "free"})
    assert r["level"] == "differs" and r["engine"] == "b" and r["engine_excluded_mojo"].startswith("disabled")


def test_round_robin_inside_an_account_group_is_not_a_disagreement(tmp_path):
    [r] = run(tmp_path, FakeClient(ranked("g_x", "g_y", group="g")), {"id": "g_y", "group": "g", "tier": "free_api"})
    assert r["level"] == "same_group" and r["mojo_position_in_engine"] == 2


def test_engine_down_is_recorded_not_hidden_and_not_raised(tmp_path):
    [r] = run(tmp_path, FakeClient(error=ConnectionError("refused")), {"id": "a", "group": None, "tier": "free"})
    assert r["level"] == "engine_error" and "refused" in r["engine_error"]


def test_error_rows_are_rate_limited(tmp_path):
    rows = run(tmp_path, FakeClient(error=ConnectionError("x")), {"id": "a", "group": None, "tier": "free"}, n=5)
    assert len(rows) == 1


def test_a_backlog_never_blocks_the_caller_and_the_drop_is_counted(tmp_path):
    gate = threading.Event()
    sel = ShadowSelector(lambda: FakeClient(ranked("a"), gate=gate), tmp_path / "s.jsonl")
    t0 = time.time()
    for _ in range(MAX_PENDING + 10):
        sel.compare("acquire", {"id": "a", "group": None, "tier": "free"}, {})
    assert time.time() - t0 < 1.0            # compare() returned immediately even with the worker stuck
    gate.set()
    sel.close()
    rows = [json.loads(l) for l in (tmp_path / "s.jsonl").read_text().splitlines()]
    assert len(rows) == MAX_PENDING


def test_nothing_from_the_engine_changes_the_pool_pick(tmp_path):
    from app.scheduler.resource_pool import ResourceTier
    from tests.unit.test_resource_quota_provider import TestPoolUsesProviderQuota
    case = TestPoolUsesProviderQuota("test_resource_usable_while_provider_reports_room")
    case.setUp()
    try:
        case.rm.probe_all()
        before = case.rm.acquire(tier_preference=[ResourceTier.FREE_API]).id
        case.rm._shadow = ShadowSelector(lambda: FakeClient(ranked("something_else")), tmp_path / "s.jsonl")
        after = case.rm.acquire(tier_preference=[ResourceTier.FREE_API]).id
        case.rm._shadow.close()
        assert before == after
        [row] = [json.loads(l) for l in (tmp_path / "s.jsonl").read_text().splitlines()]
        assert row["level"] == "differs" and row["mojo"] == after and row["constraints"]["tiers"] == ["free_api"]
    finally:
        case.doCleanups()
