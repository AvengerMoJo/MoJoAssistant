"""The exec-need classifier uses the task's own tiers (or one configured resource), and a reply that is not a
clear YES/NO is an error for the caller -- never an assumed 'no'."""
import asyncio
from types import SimpleNamespace

import pytest

from app.scheduler.agentic_executor import AgenticExecutor, ExecClassifierError
from app.scheduler.resource_pool import ResourceTier


class FakeRM:
    def __init__(self, resource="default", by_id=None):
        self.resource = SimpleNamespace(id="r1") if resource == "default" else resource
        self.by_id = by_id
        self.acquired_tiers, self.usage = None, []

    def acquire(self, tier_preference=None, **k):
        self.acquired_tiers = tier_preference
        return self.resource

    def acquire_by_id(self, rid):
        return self.by_id

    def rejection_summary(self, tiers, **k):
        return "all busy"

    def record_usage(self, rid, **k):
        self.usage.append((rid, k.get("success")))


def run(monkeypatch, reply=None, rm=None, cfg=None, boundary=None, raises=None):
    monkeypatch.setattr("app.config.config_loader.load_layered_json_config", lambda *_a, **_k: cfg or {})

    async def call_llm(resource, messages, **k):
        if raises:
            raise raises
        return {"choices": [{"message": {"content": reply}}]}

    fake = SimpleNamespace(_rm=rm or FakeRM(), _data_boundary=boundary or {}, _call_llm=call_llm,
                           _apply_data_boundary_to_tiers=AgenticExecutor._apply_data_boundary_to_tiers)
    return fake, asyncio.run(AgenticExecutor._classify_needs_exec(fake, "run `ls | wc -l`", [ResourceTier.FREE]))


def test_yes_and_no_are_read_from_the_first_word(monkeypatch):
    assert run(monkeypatch, "YES. It runs a pipeline.")[1][0] is True
    assert run(monkeypatch, "no - it only describes the command")[1][0] is False
    assert run(monkeypatch, "<think>hmm</think>\nYES, needs a shell")[1][0] is True


def test_an_unclear_reply_is_an_error_not_no(monkeypatch):
    with pytest.raises(ExecClassifierError, match="did not answer YES or NO"):
        run(monkeypatch, "Maybe, it depends.")


def test_llm_failure_is_an_error_and_recorded(monkeypatch):
    rm = FakeRM()
    with pytest.raises(ExecClassifierError, match="r1 failed: boom"):
        run(monkeypatch, rm=rm, raises=RuntimeError("boom"))
    assert rm.usage == [("r1", False)]


def test_no_resource_is_an_error(monkeypatch):
    with pytest.raises(ExecClassifierError, match="no resource available"):
        run(monkeypatch, "YES", rm=FakeRM(resource=None))


def test_configured_resource_that_is_unavailable_does_not_fall_back(monkeypatch):
    rm = FakeRM(by_id=None)
    with pytest.raises(ExecClassifierError, match="'tiny_cls' is unavailable"):
        run(monkeypatch, "YES", rm=rm, cfg={"exec_classifier": {"resource_id": "tiny_cls"}})
    assert rm.acquired_tiers is None  # the task's own tiers were not tried instead


def test_configured_resource_is_used_when_available(monkeypatch):
    rm = FakeRM(by_id=SimpleNamespace(id="tiny_cls"))
    fake, (needs, _) = run(monkeypatch, "NO", rm=rm, cfg={"exec_classifier": {"resource_id": "tiny_cls"}})
    assert needs is False and rm.usage == [("tiny_cls", True)]


def test_role_data_boundary_limits_the_tiers_the_goal_may_go_to(monkeypatch):
    rm = FakeRM()
    run(monkeypatch, "NO", rm=rm, boundary={"allowed_tiers": ["free"]})
    assert rm.acquired_tiers == [ResourceTier.FREE]
