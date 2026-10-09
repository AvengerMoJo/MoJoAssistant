"""Per-task executor state must not leak between concurrently running tasks (the 2026-07-22 race)."""
import asyncio

from app.scheduler.agentic_executor import AgenticExecutor
from app.scheduler.coding_agent_executor import CodingAgentExecutor
from app.scheduler.task_local import TaskLocal

AGENTIC = ["_role_id", "_policy_monitor", "_data_boundary", "_enabled_tool_names", "_tool_calls_made"]
CODING = ["_last_backend_error", "_model_override", "_quota_fallback_model",
          "_auto_approve_external_directory", "_waiting_for_input_question", "_pending_permission"]


def test_per_task_attributes_are_declared_task_local():
    for cls, names in ((AgenticExecutor, AGENTIC), (CodingAgentExecutor, CODING)):
        for n in names:
            assert isinstance(cls.__dict__[n], TaskLocal), f"{cls.__name__}.{n} is shared across tasks"


def test_two_interleaved_tasks_keep_their_own_values():
    ex = AgenticExecutor.__new__(AgenticExecutor)
    seen = {}

    async def run(name, role, tools):
        ex._role_id = role
        ex._enabled_tool_names = tools
        ex._tool_calls_made = 0
        for _ in range(3):
            await asyncio.sleep(0)               # yield: the other task runs and sets ITS values
            ex._tool_calls_made = ex._tool_calls_made + 1
        seen[name] = (ex._role_id, ex._enabled_tool_names, ex._tool_calls_made)

    async def main():
        await asyncio.gather(run("a", "paul", ["read_file"]), run("b", "carl", ["bash_exec"]),
                             run("c", "popo", None))

    asyncio.run(main())
    assert seen == {"a": ("paul", ["read_file"], 3), "b": ("carl", ["bash_exec"], 3), "c": ("popo", None, 3)}


def test_unset_attribute_reads_default_not_another_tasks_value():
    ex = CodingAgentExecutor.__new__(CodingAgentExecutor)

    async def setter():
        ex._model_override = {"providerID": "x", "modelID": "y"}
        ex._auto_approve_external_directory = True

    async def reader():
        await asyncio.sleep(0)
        return ex._model_override, ex._auto_approve_external_directory

    async def main():
        t = asyncio.create_task(setter())
        return await asyncio.gather(t, reader())

    _, got = asyncio.run(main())
    assert got == (None, False)
