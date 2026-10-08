"""A slow shell command must not freeze the scheduler's event loop.

Found 2026-10-08 in a live test: `bash_exec` ran subprocess.run(..., timeout=60) directly
inside an async method, so one slow command stopped every scheduler tick (a 72s gap in a
60s loop) and made per-task wall-clock timeouts impossible to enforce.
"""
import asyncio
import time
import unittest

from app.scheduler.capability_registry import CapabilityRegistry


class TestNonBlocking(unittest.TestCase):
    def test_loop_keeps_ticking_while_bash_exec_runs(self):
        async def run():
            ticks = []

            async def ticker():
                while True:
                    ticks.append(time.monotonic())
                    await asyncio.sleep(0.1)

            t = asyncio.create_task(ticker())
            start = time.monotonic()
            result = await CapabilityRegistry._bash_exec(object(), {"commands": "sleep 1.5"})
            elapsed = time.monotonic() - start
            t.cancel()
            return result, elapsed, ticks

        result, elapsed, ticks = asyncio.run(run())
        self.assertTrue(result["success"], result)
        self.assertGreaterEqual(elapsed, 1.4)
        # A blocked loop would have recorded ~1 tick during the 1.5s command; a free one ~15.
        self.assertGreaterEqual(len(ticks), 10)
        self.assertLess(max(b - a for a, b in zip(ticks, ticks[1:])), 0.5)

    def test_wall_clock_timeout_can_fire_during_a_slow_command(self):
        async def run():
            task = asyncio.ensure_future(CapabilityRegistry._bash_exec(object(), {"commands": "sleep 3"}))
            start = time.monotonic()
            try:
                await asyncio.wait_for(task, timeout=0.5)
            except asyncio.TimeoutError:
                return time.monotonic() - start
            return None

        elapsed = asyncio.run(run())
        self.assertIsNotNone(elapsed, "wait_for never timed out")
        self.assertLess(elapsed, 1.0)  # the timeout fired on time, not after the command finished


if __name__ == "__main__":
    unittest.main()
