"""A known-but-inactive OpenCode server must be restarted, not reported as 'never bootstrapped'.

After a reboot every project server is dead and entries are left inactive; BackendRegistry.reload skips
inactive entries, so _get_backend() failed and the auto-start path (which needs a backend object to learn
its type) never ran -- Paul's subtasks to Popo died instantly with 'Backend not found' (2026-10-09).
"""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.scheduler.coding_agent_executor import CodingAgentExecutor

URL = "git@github.com:AvengerMoJo/MoJoAssistant.git"


def _executor(entries):
    ex = CodingAgentExecutor.__new__(CodingAgentExecutor)
    ex._log = MagicMock()
    ex._registry = object()                              # pretend the registry is loaded
    ex._servers_config = SimpleNamespace(servers=[SimpleNamespace(id=i, status=s) for i, s in entries])
    ex._get_registry = lambda: ex._registry
    return ex


class TestRecovery(unittest.TestCase):
    def test_known_inactive_server_is_detected(self):
        ex = _executor([(URL, "inactive"), ("other", "active")])
        self.assertTrue(ex._known_but_inactive(URL))
        self.assertFalse(ex._known_but_inactive("other"))        # active -> nothing to recover
        self.assertFalse(ex._known_but_inactive("never-seen"))   # unknown -> still needs bootstrapping
        self.assertFalse(ex._known_but_inactive(None))

    def test_recovery_starts_the_project_and_reloads_the_registry(self):
        ex = _executor([(URL, "inactive")])
        mgr = MagicMock()
        mgr.start_project = AsyncMock(return_value={"status": "success"})
        with patch("app.mcp.opencode.manager.OpenCodeManager", return_value=mgr):
            self.assertTrue(asyncio.run(ex._recover_inactive_server(URL)))
        mgr.start_project.assert_awaited_once_with(URL)
        self.assertIsNone(ex._registry)                          # forces a re-read of the server config

    def test_failed_start_is_not_reported_as_recovered(self):
        ex = _executor([(URL, "inactive")])
        mgr = MagicMock()
        mgr.start_project = AsyncMock(return_value={"status": "error", "message": "port in use"})
        with patch("app.mcp.opencode.manager.OpenCodeManager", return_value=mgr):
            self.assertFalse(asyncio.run(ex._recover_inactive_server(URL)))
        self.assertIsNotNone(ex._registry)

    def test_exception_in_start_is_contained_and_logged(self):
        ex = _executor([(URL, "inactive")])
        mgr = MagicMock()
        mgr.start_project = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("app.mcp.opencode.manager.OpenCodeManager", return_value=mgr):
            self.assertFalse(asyncio.run(ex._recover_inactive_server(URL)))
        self.assertTrue(any("failed" in c.args[0] for c in ex._log.call_args_list))

    def test_unknown_server_is_never_bootstrapped_automatically(self):
        ex = _executor([("other", "active")])
        with patch("app.mcp.opencode.manager.OpenCodeManager") as cls:
            self.assertFalse(asyncio.run(ex._recover_inactive_server("never-seen")))
        cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class TestStartRunsOffTheLoop(unittest.TestCase):
    """start_project waits synchronously (live: 37.6s event-loop stall); it must not run on the scheduler loop."""

    def test_a_blocking_start_does_not_stall_the_loop(self):
        import time as _t

        class SlowManager:
            async def start_project(self, server_id):
                _t.sleep(1.0)             # stands in for the sleeps / blocking health polls
                return {"status": "success"}
        ex = _executor([(URL, "inactive")])

        async def go():
            beats = []

            async def heartbeat():
                while True:
                    beats.append(_t.monotonic())
                    await asyncio.sleep(0.05)
            hb = asyncio.create_task(heartbeat())
            await asyncio.sleep(0.15)
            with patch("app.mcp.opencode.manager.OpenCodeManager", SlowManager):
                ok = await ex._recover_inactive_server(URL)
            await asyncio.sleep(0.15)
            hb.cancel()
            return ok, beats
        ok, beats = asyncio.run(go())
        self.assertTrue(ok)
        self.assertLess(max(b - a for a, b in zip(beats, beats[1:])), 0.5, "event loop was blocked during start_project")


class TestAutoStartBackendTypes(unittest.TestCase):
    def test_opencode_v2_backend_is_auto_started_like_v1(self):
        # 2026-10-09: backend_type 'opencode_v2' fell through to "Unknown backend_type -- skipping auto-start".
        for backend_type in ("opencode", "opencode_v2"):
            ex = _executor([(URL, "active")])
            backend = MagicMock(backend_type=backend_type)
            backend.health = AsyncMock(return_value={"status": "ok"})
            ex._get_backend = lambda role, config, b=backend: b
            ex._start_project_off_loop = AsyncMock(return_value={"status": "success"})
            with patch("app.scheduler.coding_agent_executor.asyncio.sleep", new=AsyncMock()):
                got = asyncio.run(ex._auto_start_backend({}, {}, URL))
            ex._start_project_off_loop.assert_awaited_once_with(URL)
            self.assertIs(got, backend)
