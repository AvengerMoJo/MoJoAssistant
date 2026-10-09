"""OpenCode project servers must not collide on a port or kill each other.

2026-10-09: browser-instrumentation-poc and MoJoAssistant hash to the SAME port (4104). start_opencode
SIGKILLed whatever listened on the chosen port, so starting one killed the other; a failed restart left
MoJoAssistant 'inactive' and Popo lost his backend ("Backend not found").
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.mcp.opencode.manager import OpenCodeManager
from app.mcp.opencode.process_manager import ProcessManager
from app.mcp.opencode.utils import deterministic_port_for_git_url as port_for

BROWSER = "git@github.com:AvengerMoJo/browser-instrumentation-poc.git"
MOJO = "git@github.com:AvengerMoJo/MoJoAssistant.git"


class TestDeterministicPort(unittest.TestCase):
    def test_the_real_colliding_pair_hash_to_the_same_slot(self):
        self.assertEqual(port_for(BROWSER), port_for(MOJO))          # documents the incident

    def test_avoid_set_moves_the_second_project_to_the_next_free_port(self):
        first = port_for(BROWSER)
        second = port_for(MOJO, avoid={first})
        self.assertNotEqual(first, second)
        self.assertEqual(second, first + 1)

    def test_probing_wraps_inside_the_range_and_is_deterministic(self):
        start = port_for(MOJO)
        avoid = set(range(start, 4200))
        self.assertEqual(port_for(MOJO, avoid=avoid), 4100)
        self.assertEqual(port_for(MOJO, avoid={start}), port_for(MOJO, avoid={start}))

    def test_exhausted_range_raises(self):
        with self.assertRaises(ValueError):
            port_for(MOJO, avoid=set(range(4100, 4200)))

    def test_unconstrained_result_is_unchanged(self):
        self.assertTrue(4100 <= port_for(MOJO) < 4200)


def _config(base_dir, url=MOJO, port=None):
    Path(base_dir, "opencode.pid").write_text("4242\n")          # what the launch script's pgrep would write
    return SimpleNamespace(git_url=url, opencode_port=port, project_name="p", base_dir=str(base_dir), opencode_password="pw",
                           ssh_key_path="/tmp/key", opencode_bin="opencode")


class TestStartOpencodePorts(unittest.TestCase):
    def setUp(self):
        self.pm = ProcessManager.__new__(ProcessManager)
        self.pm.logs_dir = Path(tempfile.mkdtemp())
        self.repo = Path(tempfile.mkdtemp())

    def _patch(self, listening, ours=()):
        """listening: {port: [pids]}; ours: pids that are this project's server."""
        p1 = patch.object(ProcessManager, "listening_pids", staticmethod(lambda port: list(listening.get(port, []))))
        p2 = patch.object(ProcessManager, "is_this_projects_server", staticmethod(lambda pid, repo: pid in ours))
        for p in (p1, p2):
            p.start()
            self.addCleanup(p.stop)

    def test_reserved_ports_of_other_projects_are_skipped(self):
        self._patch({})
        start = port_for(MOJO)
        killed = []
        self.pm.kill_process_on_port = lambda port: killed.append(port) or (True, None)
        with patch("app.mcp.opencode.process_manager.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            pid, port, err = self.pm.start_opencode(_config(self.repo), self.repo, reserved_ports={start})
        self.assertIsNone(err)
        self.assertEqual(port, start + 1)

    def test_a_foreign_listener_is_never_killed(self):
        self._patch({4150: [999]}, ours=())
        self.pm.kill_process_on_port = MagicMock(return_value=(True, None))
        pid, port, err = self.pm.start_opencode(_config(self.repo, port=4150), self.repo)
        self.assertEqual((pid, port), (0, 4150))
        self.assertIn("not this project's OpenCode server", err)
        self.pm.kill_process_on_port.assert_not_called()

    def test_this_projects_own_stale_server_is_cleared(self):
        self._patch({4150: [555]}, ours={555})
        self.pm.kill_process_on_port = MagicMock(return_value=(True, None))
        with patch("app.mcp.opencode.process_manager.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            pid, port, err = self.pm.start_opencode(_config(self.repo, port=4150), self.repo)
        self.assertIsNone(err)
        self.pm.kill_process_on_port.assert_called_once_with(4150)

    def test_ports_with_foreign_listeners_are_avoided_when_allocating(self):
        start = port_for(MOJO)
        self._patch({start: [999]}, ours=())
        self.pm.kill_process_on_port = MagicMock(return_value=(True, None))
        with patch("app.mcp.opencode.process_manager.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            pid, port, err = self.pm.start_opencode(_config(self.repo), self.repo)
        self.assertIsNone(err)
        self.assertNotEqual(port, start)


class TestReservedPorts(unittest.TestCase):
    def test_other_projects_ports_are_reserved_not_the_projects_own(self):
        mgr = OpenCodeManager.__new__(OpenCodeManager)
        proj = lambda port: SimpleNamespace(opencode=SimpleNamespace(port=port))
        mgr.state_manager = SimpleNamespace(get_all_projects=lambda: {MOJO: proj(4104), BROWSER: proj(4104), "x": proj(4109), "y": proj(None)})
        self.assertEqual(mgr._reserved_ports(MOJO), {4104, 4109})       # BROWSER's 4104 and x's 4109
        self.assertEqual(mgr._reserved_ports("other"), {4104, 4109})


if __name__ == "__main__":
    unittest.main()
