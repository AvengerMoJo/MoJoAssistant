import json
import threading

from app.scheduler import profile_demand
from app.scheduler.engine_shadow import ShadowSelector


class FakeClient:
    def __init__(self):
        self.asked = []

    def select(self, requirements, limit=8):
        self.asked.append(requirements)
        if requirements.get("needs_tools"):
            return {"ranked": [{"id": "b"}], "excluded": [{"id": "a", "reason": "profile unknown: tool calls never measured"}]}
        return {"ranked": [{"id": "a", "rank_priority": 1}, {"id": "b"}], "excluded": []}


def test_demand_is_per_task_context_and_validated():
    profile_demand.set_demand({"needs_tools": True})
    seen = {}
    t = threading.Thread(target=lambda: seen.update(v=profile_demand.current()))
    t.start(); t.join()
    assert seen["v"] is None and profile_demand.current() == {"needs_tools": True}   # a new thread/context does not inherit
    profile_demand.set_demand(None)
    assert profile_demand.current() is None
    try:
        profile_demand.set_demand({"magic": 1})
        assert False
    except ValueError:
        pass


def test_shadow_row_says_whether_mojos_pick_could_serve_on_its_profile(tmp_path):
    log = tmp_path / "s.jsonl"
    client = FakeClient()
    sel = ShadowSelector(lambda: client, log)
    sel.compare("acquire", {"id": "a", "group": None, "tier": "free"}, {"tiers": ["free"]}, profile_demand={"needs_tools": True})
    sel.close()
    row = json.loads(log.read_text())
    assert row["level"] == "exact"                                   # the routing comparison is untouched
    assert row["profile_mojo_pick"].startswith("profile unknown") and row["profile_engine_top"] == ["b"]
    assert client.asked[0] == {"tiers": ["free"]} and client.asked[1]["needs_tools"] is True


def test_no_demand_means_no_second_question(tmp_path):
    client = FakeClient()
    sel = ShadowSelector(lambda: client, tmp_path / "s.jsonl")
    sel.compare("acquire", {"id": "a", "group": None, "tier": "free"}, {"tiers": ["free"]})
    sel.close()
    assert len(client.asked) == 1
