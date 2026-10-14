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
