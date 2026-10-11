"""Deadline review: hard rules are code, the model only chooses within them, and a failed review stops."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.scheduler import deadline_review as dr
from app.scheduler.agentic_executor import AgenticExecutor


def _it(i, tools=("web_search",), status="tool_calls", took=40):
    return {"iteration": i, "status": status, "resource": "r1", "tool_calls": list(tools), "elapsed_s": took}


def ev(log, elapsed=900, budget=900, used=0):
    return dr.gather_evidence(log, elapsed, budget, used)


class TestRules:
    def test_extension_limit_stops(self):
        e = ev([_it(1), _it(2, ("fetch_url",))], used=3)
        assert not dr.rule_decision(e, 1680, 3, 300).extend

    def test_hard_cap_stops(self):
        e = ev([_it(1), _it(2, ("fetch_url",))], budget=1680)
        d = dr.rule_decision(e, 1680, 3, 300)
        assert d and not d.extend and "hard cap" in d.reason

    def test_no_tool_activity_stops(self):
        e = ev([_it(1, tools=(), status="empty_response")])
        assert "no tool activity" in dr.rule_decision(e, 1680, 3, 300).reason

    def test_repeating_calls_stop(self):
        e = ev([_it(i) for i in range(1, 5)])
        assert "loop" in dr.rule_decision(e, 1680, 3, 300).reason

    def test_progress_leaves_decision_to_model(self):
        e = ev([_it(1), _it(2, ("fetch_url",)), _it(3, ("write_file",))])
        assert dr.rule_decision(e, 1680, 3, 300) is None


class TestParse:
    def test_extend_is_clamped_to_max_grant(self):
        d = dr.parse_model_decision('{"decision":"extend","seconds":9999,"reason":"still fetching"}', 300)
        assert d.extend and d.seconds == 300

    def test_stop(self):
        assert not dr.parse_model_decision('ok {"decision":"stop","reason":"hung"}', 300).extend

    @pytest.mark.parametrize("text", [
        "no json", '{"decision":"maybe","reason":"x"}', '{"decision":"extend","seconds":10,"reason":"x"}',
        '{"decision":"extend","seconds":120}', "",
    ])
    def test_bad_reply_raises(self, text):
        with pytest.raises(ValueError):
            dr.parse_model_decision(text, 300)


class TestLimits:
    def test_hard_cap_stays_under_outer_cap(self):
        assert dr.compute_limits({"deadline_hard_max_seconds": 99999}, 1800)[0] == 1800 - dr.OUTER_CAP_MARGIN_S

    def test_config_overrides(self):
        cap, n, s = dr.compute_limits({"deadline_hard_max_seconds": 1200, "deadline_max_extensions": 2, "deadline_extension_seconds": 200}, 1800)
        assert (cap, n, s) == (1200, 2, 200)


def _executor(reply=None, raises=None):
    ex = AgenticExecutor.__new__(AgenticExecutor)
    ex._log = lambda *a, **k: None
    ex._rm = SimpleNamespace(acquire_by_id=lambda rid: SimpleNamespace(id=rid))

    async def fake_call(resource, messages, **kw):
        if raises:
            raise raises
        return {"choices": [{"message": {"content": reply}}]}
    ex._call_llm = fake_call
    return ex


def _review(ex, log, used=0, rid="r1", budget=900):
    task = SimpleNamespace(id="t1", resources=None)
    return asyncio.run(ex._review_deadline(task, {}, "goal", log, budget, budget, used, rid))


PROGRESS = [_it(1), _it(2, ("fetch_url",)), _it(3, ("write_file",))]


class TestExecutorReview:
    def test_model_extends_within_limits(self):
        d = _review(_executor('{"decision":"extend","seconds":250,"reason":"fetching sources"}'), PROGRESS)
        assert d.extend and d.seconds == 250 and d.source == "model"

    def test_model_stop(self):
        assert not _review(_executor('{"decision":"stop","reason":"stuck"}'), PROGRESS).extend

    def test_garbage_reply_stops_not_extends(self):
        d = _review(_executor("sure, take more time"), PROGRESS)
        assert not d.extend and "review failed" in d.reason

    def test_llm_error_stops_not_extends(self):
        d = _review(_executor(raises=RuntimeError("boom")), PROGRESS)
        assert not d.extend and "boom" in d.reason

    def test_no_resource_stops(self):
        d = _review(_executor('{"decision":"extend","seconds":200,"reason":"x"}'), PROGRESS, rid=None)
        assert not d.extend

    def test_rule_wins_over_model(self):
        d = _review(_executor('{"decision":"extend","seconds":200,"reason":"x"}'), PROGRESS, used=3)
        assert not d.extend and d.source == "rule"
