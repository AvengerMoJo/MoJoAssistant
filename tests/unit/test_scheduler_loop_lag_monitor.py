"""The scheduler must name event-loop stalls (it cannot report one while it is stalled)."""
import asyncio
import time
import unittest
from unittest.mock import MagicMock

from app.scheduler.core import Scheduler


class TestLoopLagMonitor(unittest.TestCase):
    def _sched(self):
        s = Scheduler.__new__(Scheduler)
        s._log = MagicMock()
        s._running_tasks = set()
        return s

    def test_blocking_call_is_reported_with_running_task_names(self):
        s = self._sched()

        async def run():
            async def blocker():
                time.sleep(0.6)  # the bug being detected: a sync call on the loop
            m = asyncio.create_task(s._loop_lag_monitor(interval=0.05, warn_after=0.3))
            await asyncio.sleep(0.12)  # let the monitor take its first readings
            t = asyncio.create_task(blocker(), name="task-dreaming_x")
            s._running_tasks.add(t)
            await t
            await asyncio.sleep(0.15)
            m.cancel()
        asyncio.run(run())
        msgs = [c.args[0] for c in s._log.call_args_list]
        self.assertTrue(any("Event loop stalled" in m and "task-dreaming_x" in m for m in msgs), msgs)

    def test_healthy_loop_is_silent(self):
        s = self._sched()

        async def run():
            m = asyncio.create_task(s._loop_lag_monitor(interval=0.05, warn_after=0.3))
            await asyncio.sleep(0.5)
            m.cancel()
        asyncio.run(run())
        s._log.assert_not_called()


if __name__ == "__main__":
    unittest.main()
