"""A failed LLM call is an error for the caller -- not a retry on another tier, not text saved as the role's answer."""
import asyncio

import pytest

from app.scheduler.interaction_mode import InteractionMode
from app.scheduler.role_chat import RoleChatSession


class NoResource:
    def acquire(self, *a, **k):
        return None

    def selection_order(self, *a, **k):
        return []

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
    assert task.resources.max_iterations == 10 and task.resources.max_duration_seconds == 900


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


def test_routed_tasks_shows_only_what_this_role_routed(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path))
    (tmp_path / "scheduler_tasks.json").write_text(json.dumps({"tasks": {
        "a": {"id": "a", "status": "completed", "created_at": "2026-10-14T10:00:00",
              "config": {"role_id": "paul", "origin": {"channel": "owner_hub", "via": "anna"}},
              "result": {"metrics": {"final_answer": "the plan"}}},
        "b": {"id": "b", "status": "waiting_for_input", "created_at": "2026-10-14T11:00:00", "pending_question": "which repo?",
              "config": {"role_id": "popo", "origin": {"channel": "owner_hub", "via": "anna"}}},
        "c": {"id": "c", "status": "completed", "created_at": "2026-10-14T12:00:00",
              "config": {"role_id": "paul", "origin": {"channel": "owner_hub", "via": "someone_else"}},
              "result": {"metrics": {"final_answer": "not hers"}}},
        "d": {"id": "d", "status": "completed", "created_at": "2026-10-14T13:00:00", "config": {"role_id": "paul"}},
    }}))
    s = RoleChatSession("anna", session_id="t4", mode=InteractionMode.OWNER_HUB)
    out = json.loads(asyncio.run(s._execute_tool("routed_tasks", {})))
    assert [t["task_id"] for t in out["tasks"]] == ["b", "a"]
    assert out["tasks"][0]["waiting_on"] == "which repo?" and out["tasks"][1]["answer"] == "the plan"
    one = json.loads(asyncio.run(s._execute_tool("routed_tasks", {"task_id": "c"})))
    assert one["count"] == 0


def test_forced_final_answer_keeps_system_message_first(tmp_path, monkeypatch):
    """When the tool budget runs out, the 'answer now' instruction must not be a second system message:
    Ornith/Qwen chat templates raise 'System message must be at the beginning' and the turn fails."""
    s = session(tmp_path, monkeypatch)
    seen = []

    async def fake_call_raw(messages, rm, tools=None):
        seen.append([m["role"] for m in messages])
        if tools is None:
            return {"choices": [{"message": {"content": "final answer"}}], "_resource": "r", "_model": "m"}
        return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "list_roles", "arguments": "{}"}}]}}], "_resource": "r", "_model": "m"}

    async def fake_tool(name, args):
        return "{}"

    monkeypatch.setattr(s, "_call_raw", fake_call_raw)
    monkeypatch.setattr(s, "_execute_tool", fake_tool)
    result = asyncio.run(s.exchange("how did it go?", resource_manager=object()))
    assert result.get("response") == "final answer", result
    final_roles = seen[-1]
    assert final_roles[0] == "system" and "system" not in final_roles[1:]
    assert final_roles[-1] == "user"


def test_empty_final_answer_after_tool_budget_is_an_error_and_not_saved(tmp_path, monkeypatch):
    """No text after the tool rounds is an error for the caller, not a substitute reply saved to history."""
    s = session(tmp_path, monkeypatch)

    async def fake_call_raw(messages, rm, tools=None):
        if tools is None:
            return {"choices": [{"message": {"content": ""}}], "_resource": "r", "_model": "m"}
        return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "list_roles", "arguments": "{}"}}]}}], "_resource": "r", "_model": "m"}

    async def fake_tool(name, args):
        return "{}"

    monkeypatch.setattr(s, "_call_raw", fake_call_raw)
    monkeypatch.setattr(s, "_execute_tool", fake_tool)
    result = asyncio.run(s.exchange("how did it go?", resource_manager=object()))
    assert "produced no answer after" in result["error"], result
    assert "response" not in result
    assert not s._session_file.exists()
