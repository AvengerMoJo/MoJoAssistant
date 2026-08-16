"""
Regression test for the concurrency context race documented in
~/.memory/research/scheduler_concurrency_context_race_2607.md.

The bug: CapabilityRegistry.set_task_context() used to write task_id /
dispatch_depth / role_id / available_tools as plain instance attributes on
the shared singleton CapabilityRegistry. Two concurrently-running asyncio
tasks calling set_task_context() would silently clobber each other's
context across an `await` yield point. Fixed by moving this state into
ContextVars (app/scheduler/exec_context.py), which are isolated per
asyncio task by construction.

A purely sequential test would pass even with the bug present -- the race
only manifests when two coroutines interleave across a real `await` point.
This test forces that interleaving with asyncio.gather + asyncio.sleep(0).
"""

import asyncio
import unittest

from app.scheduler.capability_registry import CapabilityRegistry
from app.scheduler.exec_context import (
    cv_task_id,
    cv_dispatch_depth,
    cv_role_id,
    cv_enabled_tools,
)


class TestSchedulerContextIsolation(unittest.IsolatedAsyncioTestCase):

    async def test_concurrent_set_task_context_does_not_race(self):
        # Single shared registry instance, as in production (singleton).
        registry = CapabilityRegistry.__new__(CapabilityRegistry)
        registry._tools = {}
        registry._mcp_client_manager = None
        registry._scheduler = None
        registry._memory_service = None
        registry._resource_manager = None

        results = {}

        async def run_task(name: str, depth: int, role: str, tools):
            registry.set_task_context(
                task_id=name, dispatch_depth=depth, role_id=role, available_tools=tools
            )
            # Yield control so the other coroutine can run and (if the bug
            # were present) clobber the shared instance-attribute state.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            results[name] = {
                "task_id": cv_task_id.get(),
                "depth": cv_dispatch_depth.get(),
                "role": cv_role_id.get(),
                "tools": cv_enabled_tools.get(),
            }

        await asyncio.gather(
            run_task("task_A", 1, "role_a", ["web_search"]),
            run_task("task_B", 2, "role_b", ["bash_exec"]),
        )

        self.assertEqual(results["task_A"], {
            "task_id": "task_A", "depth": 1, "role": "role_a", "tools": ["web_search"],
        })
        self.assertEqual(results["task_B"], {
            "task_id": "task_B", "depth": 2, "role": "role_b", "tools": ["bash_exec"],
        })

    async def test_dispatch_subtask_reads_own_task_depth_under_concurrency(self):
        """End-to-end: _dispatch_subtask's own depth-cap check must use the
        calling coroutine's context, not whatever another concurrent task
        last set."""
        from unittest.mock import MagicMock

        registry = CapabilityRegistry.__new__(CapabilityRegistry)
        registry._tools = {}
        registry._mcp_client_manager = None
        registry._memory_service = None
        registry._resource_manager = None
        scheduler = MagicMock()
        scheduler.add_task.return_value = False  # fail fast past the depth check
        registry._scheduler = scheduler

        outcomes = {}

        async def run(name: str, depth: int):
            registry.set_task_context(task_id=name, dispatch_depth=depth)
            await asyncio.sleep(0)
            result = await registry._dispatch_subtask({
                "role_id": "analyst",
                "goal": (
                    "Summarize competitor pricing pages. Done when: a table of "
                    "5 competitors' prices exists. Out of scope: our own pricing. "
                    "Verify by: table has 5 rows with numeric prices."
                ),
            })
            outcomes[name] = result

        # task_A is at max depth and should be blocked; task_B is shallow
        # and should be allowed to proceed to the (mocked) add_task failure.
        await asyncio.gather(
            run("task_A", CapabilityRegistry.MAX_DISPATCH_DEPTH),
            run("task_B", 0),
        )

        self.assertFalse(outcomes["task_A"]["success"])
        self.assertIn("Max dispatch depth", outcomes["task_A"]["error"])

        self.assertFalse(outcomes["task_B"]["success"])
        self.assertIn("Failed to queue", outcomes["task_B"]["error"])


if __name__ == "__main__":
    unittest.main()
