"""A local model serves one request at a time: callers wait in line (visibly, in arrival order), the wait is
recorded per owner so it can stay out of a task's time budget, and a saturated model reads as busy."""
import asyncio
import threading

import pytest

from app.scheduler.resource_pool import LLMResource, ResourceBusyError, ResourceManager, ResourceTier


def res(rid, type_="local", model="m", cap=None, url="http://h/v1"):
    return LLMResource(id=rid, type=type_, provider="openai", base_url=url, model=model, tier=ResourceTier.FREE,
                       max_concurrent_requests=cap)


def pool(*resources):
    rm = ResourceManager.__new__(ResourceManager)
    rm._lock = threading.RLock()
    rm._resources = {r.id: r for r in resources}
    rm._slot_active, rm._slot_waiters, rm._queue_wait, rm._waiting_since = {}, {}, {}, {}
    rm._log = lambda *a, **k: None
    return rm


def test_second_caller_waits_for_the_first_and_the_wait_is_recorded():
    rm = pool(res("a"))
    order = []

    async def caller(name, hold, owner):
        async with rm.slot("a", owner=owner):
            order.append(f"{name} in")
            await asyncio.sleep(hold)
            order.append(f"{name} out")

    async def main():
        await asyncio.gather(caller("t1", 0.5, "task1"), caller("t2", 0.0, "task2"))

    asyncio.run(main())
    assert order == ["t1 in", "t1 out", "t2 in", "t2 out"]
    assert rm.queue_wait_s("task1") < 0.2 and rm.queue_wait_s("task2") >= 0.4
    rm.clear_queue_wait("task2")
    assert rm.queue_wait_s("task2") == 0.0


def test_saturated_model_is_busy_for_every_resource_that_serves_it():
    rm = pool(res("a"), res("a_alias"), res("other", model="other"))

    async def main():
        async with rm.slot("a"):
            return rm._slot_saturated_ids()

    assert asyncio.run(main()) == {"a", "a_alias"}  # same url|model, different resource ids
    assert rm._slot_saturated_ids() == set()  # released


def test_waiting_too_long_is_an_explicit_error_and_leaves_the_line():
    rm = pool(res("a"))

    async def main():
        async with rm.slot("a"):
            with pytest.raises(ResourceBusyError, match="stayed taken for 0s"):
                async with rm.slot("a", max_wait_s=0):
                    pass
            assert not rm._slot_waiters["http://h/v1|m"]  # the failed caller is not left queued

    asyncio.run(main())


def test_api_resources_are_not_limited_and_capacity_is_configurable():
    rm = pool(res("api", type_="api", model="x"), res("two", model="two", cap=2))

    async def main():
        async with rm.slot("api"), rm.slot("api"), rm.slot("api"):
            pass
        async with rm.slot("two"), rm.slot("two"):
            assert rm._slot_saturated_ids() == {"two"}  # both slots taken
        async with rm.slot("two"):
            assert rm._slot_saturated_ids() == set()

    asyncio.run(main())


def test_a_cancelled_waiter_does_not_block_the_line():
    rm = pool(res("a"))

    async def main():
        async with rm.slot("a"):
            waiter = asyncio.create_task(rm.slot("a").__aenter__())
            await asyncio.sleep(0.3)
            waiter.cancel()
            await asyncio.sleep(0.1)
        async with rm.slot("a", max_wait_s=1):
            pass

    asyncio.run(main())


def test_a_wait_still_going_on_counts_as_queue_time():
    rm = pool(res("a"))

    async def main():
        async with rm.slot("a"):
            waiter = asyncio.create_task(rm.slot("a", owner="t2").__aenter__())
            await asyncio.sleep(0.4)
            seen = rm.queue_wait_s("t2")
            waiter.cancel()
            return seen

    assert asyncio.run(main()) >= 0.3


def scheduler_with(rm, execute):
    from types import SimpleNamespace
    from app.scheduler.core import Scheduler
    s = Scheduler.__new__(Scheduler)
    s.executor = SimpleNamespace(_agentic_executor=SimpleNamespace(_rm=rm), execute=execute)
    return s


def test_scheduler_timer_leaves_queue_wait_out_and_still_times_out_real_work():
    from types import SimpleNamespace
    rm = pool(res("a"))
    task = SimpleNamespace(id="t1")

    async def waits_then_works(_task):
        async with rm.slot("a", owner=_task.id):  # held by another caller below
            await asyncio.sleep(0.3)
        return "done"

    async def hangs(_task):
        await asyncio.sleep(30)

    async def main():
        async with rm.slot("a"):
            run = asyncio.create_task(scheduler_with(rm, waits_then_works)._execute_within(task, 0.8))
            await asyncio.sleep(1.2)  # the task waits 1.2 s: longer than its 0.8 s limit, yet not timed out
        assert await run == "done"
        with pytest.raises(asyncio.TimeoutError):
            await scheduler_with(rm, hangs)._execute_within(task, 0.5)

    asyncio.run(main())
    assert rm.queue_wait_s("t1") == 0.0  # cleared when the run ends


def test_chat_call_waits_for_the_slot_and_a_long_wait_is_an_error_not_a_resource_fault(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.scheduler import role_chat
    from app.scheduler.interaction_mode import InteractionMode
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path))
    monkeypatch.setattr(role_chat, "CHAT_QUEUE_WAIT_MAX_SECONDS", 0)
    rm = pool(res("a"))
    rm.acquire = lambda **k: rm._resources["a"]
    rm.selection_order = lambda *a, **k: []
    rm.record_usage = lambda rid, **k: usage.append((rid, k.get("success")))
    usage = []
    s = role_chat.RoleChatSession("anna", session_id="t_slot", mode=InteractionMode.OWNER_HUB)

    async def main():
        async with rm.slot("a"):  # another caller holds the only slot
            with pytest.raises(RuntimeError, match="stayed taken for 0s.*busy"):
                await s._call_raw([{"role": "user", "content": "hi"}], rm)

    asyncio.run(main())
    assert usage == []  # nothing recorded against the resource
