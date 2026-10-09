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
