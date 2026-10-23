"""Dreaming sends the owner's conversations to a model: it stays inside the owner's network and waits its turn."""
import asyncio
from contextlib import asynccontextmanager

import pytest

from app.llm.resource_pool_interface import DreamingLLMError, ResourcePoolLLMInterface


class Res:
    id, base_url, model, api_key, provider, output_limit = "ornith", "http://x", "m", "k", "lmstudio", 1000


class RM:
    def __init__(self, busy=False):
        self.acquired, self.slots, self.usage, self.busy = [], [], [], busy

    def acquire(self, **kw):
        self.acquired.append(kw)
        return Res()

    def record_usage(self, rid, **kw):
        self.usage.append((rid, kw))

    @asynccontextmanager
    async def slot(self, rid, owner=None, max_wait_s=None):
        from app.scheduler.resource_pool import ResourceBusyError
        if self.busy:
            raise ResourceBusyError(f"{rid}: all 1 request slot(s) stayed taken for {max_wait_s:.0f}s")
        self.slots.append((rid, owner, max_wait_s))
        yield 0.0


def patch_client(monkeypatch):
    class C:
        async def call_async(self, **kw):
            return {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
    monkeypatch.setattr("app.llm.unified_client.UnifiedLLMClient", C)


def test_call_stays_in_data_scope_and_takes_a_slot(monkeypatch):
    patch_client(monkeypatch)
    rm = RM()
    out = asyncio.run(ResourcePoolLLMInterface(rm, queue_wait_seconds=77)._generate("q"))
    assert out == "{}"
    assert rm.acquired[0]["max_data_scope"] == "own_network"
    assert rm.slots == [("ornith", "dreaming", 77)]


def test_wider_scope_comes_from_config(monkeypatch):
    patch_client(monkeypatch)
    rm = RM()
    asyncio.run(ResourcePoolLLMInterface(rm, max_data_scope="third_party")._generate("q"))
    assert rm.acquired[0]["max_data_scope"] == "third_party"


def test_a_model_that_stays_busy_is_an_explicit_error(monkeypatch):
    patch_client(monkeypatch)
    with pytest.raises(DreamingLLMError, match="stayed busy"):
        asyncio.run(ResourcePoolLLMInterface(RM(busy=True), queue_wait_seconds=5)._generate("q"))


def test_only_resources_that_fit_the_prompt_and_reply_are_offered(monkeypatch):
    patch_client(monkeypatch)
    rm = RM()
    asyncio.run(ResourcePoolLLMInterface(rm, max_tokens=32000, min_output_tokens=16000)._generate("x" * 30000))
    assert rm.acquired[0]["min_context"] == 10000 + 32000   # 30000 chars / 3 + the reply budget
    assert rm.acquired[0]["min_output"] == 16000


def test_no_resource_error_names_what_was_needed(monkeypatch):
    class Empty(RM):
        def acquire(self, **kw):
            return None
    with pytest.raises(DreamingLLMError, match=r"needs 32000 tokens of context.*up to own_network"):
        asyncio.run(ResourcePoolLLMInterface(Empty(), max_tokens=32000)._generate("q"))
