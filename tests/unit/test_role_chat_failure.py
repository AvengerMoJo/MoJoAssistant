"""A failed LLM call is an error for the caller -- not a retry on another tier, not text saved as the role's answer."""
import asyncio

import pytest

from app.scheduler.interaction_mode import InteractionMode
from app.scheduler.role_chat import RoleChatSession


class NoResource:
    def acquire(self, *a, **k):
        return None

    def record_usage(self, *a, **k):
        pass


def session(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path))
    return RoleChatSession("anna", session_id="t_fail", mode=InteractionMode.OWNER_HUB)


def test_no_resource_raises(tmp_path, monkeypatch):
    s = session(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="no LLM resource available"):
        asyncio.run(s._call_raw([{"role": "user", "content": "hi"}], NoResource()))


def test_exchange_returns_error_and_saves_nothing(tmp_path, monkeypatch):
    s = session(tmp_path, monkeypatch)
    result = asyncio.run(s.exchange("hi", resource_manager=NoResource()))
    assert "no LLM resource available" in result["error"]
    assert "response" not in result
    assert not s._session_file.exists()


def test_roster_tool_only_in_owner_hub(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path))
    caps = ["memory", "orchestration", "knowledge"]
    hub = RoleChatSession("anna", session_id="t1", mode=InteractionMode.OWNER_HUB)
    dash = RoleChatSession("anna", session_id="t2", mode=InteractionMode.DASHBOARD_CHAT)
    names = lambda s: {t["function"]["name"] for t in s._get_chat_tools(caps)}
    assert "list_roles" in names(hub)
    assert "list_roles" not in names(dash)
    assert not names(hub) & {"dispatch_subtask", "scheduler_add_task"}


class FakeScheduler:
    def __init__(self, accept=True):
        self.tasks, self.accept = [], accept

    def add_task(self, task):
        self.tasks.append(task)
        return self.accept


def route(tmp_path, monkeypatch, args, scheduler=None, routable=None):
    import json
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path))
    s = RoleChatSession("anna", session_id="t3", mode=InteractionMode.OWNER_HUB,
                        scheduler=scheduler, routable_roles=routable)
    return json.loads(asyncio.run(s._execute_tool("route_to_role", args)))


def test_route_creates_a_scheduler_task_from_the_owner_message(tmp_path, monkeypatch):
    sched = FakeScheduler()
    out = route(tmp_path, monkeypatch, {"role_id": "paul", "message": "Review the Q4 roadmap risks"}, sched)
    assert out["success"] and out["role_id"] == "paul"
    task = sched.tasks[0]
    assert task.id == out["task_id"] and task.config["role_id"] == "paul"
    assert "Review the Q4 roadmap risks" in task.config["goal"]
    assert task.created_by == "user" and task.config["origin"]["channel"] == "owner_hub"


def test_route_without_scheduler_fails_visibly(tmp_path, monkeypatch):
    out = route(tmp_path, monkeypatch, {"role_id": "paul", "message": "hi there"})
    assert not out["success"] and "scheduler is not available" in out["error"]


def test_route_refuses_unknown_self_and_unlisted_roles(tmp_path, monkeypatch):
    sched = FakeScheduler()
    assert not route(tmp_path, monkeypatch, {"role_id": "nobody", "message": "x y z"}, sched)["success"]
    assert not route(tmp_path, monkeypatch, {"role_id": "anna", "message": "x y z"}, sched)["success"]
    assert not route(tmp_path, monkeypatch, {"role_id": "paul", "message": "x y z"}, sched, routable=["rebecca"])["success"]
    assert sched.tasks == []


def test_route_reports_a_scheduler_refusal(tmp_path, monkeypatch):
    out = route(tmp_path, monkeypatch, {"role_id": "paul", "message": "something to do"}, FakeScheduler(accept=False))
    assert not out["success"] and "refused" in out["error"]
