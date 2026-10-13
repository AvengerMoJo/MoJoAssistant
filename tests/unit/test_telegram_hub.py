"""Telegram hub: owner-only, agent switching, daily sessions, errors surfaced in the chat."""
import asyncio

import pytest

from app.mcp.adapters.telegram_hub import TelegramHub, split_message

ROLES = ["anna", "rebecca", "popo"]


def make_hub(tmp_path, config=None, exchange=None):
    calls = []

    async def default_exchange(agent, session_id, text):
        calls.append((agent, session_id, text))
        return {"response": f"{agent} heard {text}"}

    hub = TelegramHub("tok", "42", config or {"default_agent": "anna"}, tmp_path / "state.json",
                      exchange or default_exchange, lambda r: r in ROLES, lambda: ROLES)
    return hub, calls


async def say(hub, text):
    out = []

    async def send(t):
        out.append(t)
    await hub.handle_text(text, send)
    return out


def run(coro):
    return asyncio.run(coro)


def test_plain_text_goes_to_default_agent_in_a_daily_session(tmp_path):
    hub, calls = make_hub(tmp_path)
    assert run(say(hub, "hello")) == ["anna heard hello"]
    agent, sid, _ = calls[0]
    assert agent == "anna" and sid.startswith("hub_anna_")


def test_to_switches_agent_and_keeps_a_session_per_agent(tmp_path):
    hub, calls = make_hub(tmp_path)
    run(say(hub, "one"))
    assert run(say(hub, "/to rebecca")) == ["Now talking with rebecca."]
    run(say(hub, "two"))
    run(say(hub, "/to anna"))
    run(say(hub, "three"))
    assert [c[0] for c in calls] == ["anna", "rebecca", "anna"]
    assert calls[0][1] == calls[2][1]  # anna keeps her session across the detour


def test_unknown_agent_is_refused_and_current_agent_unchanged(tmp_path):
    hub, _ = make_hub(tmp_path)
    out = run(say(hub, "/to nobody"))
    assert "No assistant 'nobody'" in out[0] and hub.agent == "anna"


def test_agent_allow_list_is_enforced(tmp_path):
    hub, _ = make_hub(tmp_path, {"default_agent": "anna", "agents": ["anna"]})
    assert "No assistant 'popo'" in run(say(hub, "/to popo"))[0]


def test_default_agent_must_exist(tmp_path):
    with pytest.raises(ValueError, match="not an available role"):
        make_hub(tmp_path, {"default_agent": "ghost"})


def test_new_starts_a_fresh_session(tmp_path):
    hub, calls = make_hub(tmp_path)
    run(say(hub, "a"))
    run(say(hub, "/new"))
    run(say(hub, "b"))
    assert calls[0][1] != calls[1][1]


def test_state_survives_restart(tmp_path):
    hub, _ = make_hub(tmp_path)
    run(say(hub, "/to rebecca"))
    hub2, _ = make_hub(tmp_path)
    assert hub2.agent == "rebecca"


def test_other_chats_are_ignored(tmp_path):
    hub, calls = make_hub(tmp_path)
    out = []

    async def send(t):
        out.append(t)
    run(hub.handle_update({"message": {"chat": {"id": 999}, "text": "hi"}}, send))
    assert out == [] and calls == []
    run(hub.handle_update({"message": {"chat": {"id": 42}, "text": "hi"}}, send))
    assert out == ["anna heard hi"]


def test_exchange_error_is_reported_not_swallowed(tmp_path):
    async def failing(agent, sid, text):
        return {"error": "no resource available"}
    hub, _ = make_hub(tmp_path, exchange=failing)
    assert run(say(hub, "hi")) == ["anna could not answer: no resource available"]


def test_exchange_exception_is_reported(tmp_path):
    async def boom(agent, sid, text):
        raise RuntimeError("down")
    hub, _ = make_hub(tmp_path, exchange=boom)
    assert "RuntimeError: down" in run(say(hub, "hi"))[0]


def test_long_reply_is_split_within_the_limit():
    parts = split_message(("word " * 30 + "\n\n") * 60, limit=500)
    assert len(parts) > 1 and all(len(p) <= 500 for p in parts)
    assert split_message("") == ["(empty reply)"]
