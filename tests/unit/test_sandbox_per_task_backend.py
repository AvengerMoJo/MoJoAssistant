"""Tests for OpenCodePerTaskBackend (Phase 2: per-task OpenCode).

Covers the lifecycle:
  - spawn() creates a process, log file, pid/pgid files
  - Multiple tasks can run concurrently on different ports
  - status() detects dead processes
  - kill() does clean process group termination
  - kill_all() shuts down all instances
  - Per-task log dir is correctly under ~/.memory/task_logs/<task_id>/
"""
from __future__ import annotations

import os
import signal
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.scheduler.sandbox.per_task.opencode_per_task import (
    OpenCodePerTaskBackend,
    _allocate_port,
    _is_port_free,
    _TASK_PORT_END,
    _TASK_PORT_START,
)


def _find_free_port_in_range() -> int:
    for port in range(_TASK_PORT_START, _TASK_PORT_END + 1):
        if _is_port_free(port):
            return port
    raise RuntimeError("No free port in per-task range")


def _is_pid_alive(pid: int) -> bool:
    """Definitively check if a process is alive using /proc (avoids PID recycling)."""
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("State:"):
                    state = line.split(":", 1)[1].strip().split()[0]
                    return state != "Z"
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return False
    return True


def _force_kill_pgid(pid: int) -> None:
    """Best-effort kill: send SIGKILL to the whole process group."""
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class TestPortAllocation(unittest.TestCase):
    """Port allocator returns only free ports in the reserved range."""

    def test_allocate_returns_free_port(self):
        port = _allocate_port()
        self.assertGreaterEqual(port, _TASK_PORT_START)
        self.assertLessEqual(port, _TASK_PORT_END)

    def test_allocate_avoids_bound_port(self):
        port = _allocate_port()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            s.listen(1)
            next_port = _allocate_port()
            self.assertNotEqual(port, next_port)
        finally:
            s.close()


class TestSpawn(unittest.IsolatedAsyncioTestCase):
    """spawn() starts OpenCode, creates log/pid files, returns instance info."""

    def setUp(self):
        self.work_dir = Path(tempfile.mkdtemp(prefix="per_task_test_work_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.work_dir, ignore_errors=True)

    async def test_spawn_creates_pid_pgid_log_files(self):
        """spawn() writes agent.pid, agent.pgid, and agent.log."""
        with patch(
            "app.scheduler.sandbox.per_task.opencode_per_task._OPENCODE_BIN",
            "/bin/sleep"
        ), patch(
            "app.scheduler.sandbox.per_task.opencode_per_task._wait_healthy",
            return_value=True
        ):
            backend = OpenCodePerTaskBackend()
            inst = backend.spawn("cs-test-spawn-001", str(self.work_dir))

            try:
                self.assertEqual(inst.task_id, "cs-test-spawn-001")
                self.assertEqual(inst.working_dir, str(self.work_dir))
                self.assertGreaterEqual(inst.port, _TASK_PORT_START)
                self.assertLessEqual(inst.port, _TASK_PORT_END)
                self.assertTrue(len(inst.password) > 8)

                task_dir = Path(inst.task_dir)
                self.assertTrue((task_dir / "agent.pid").exists())
                self.assertTrue((task_dir / "agent.pgid").exists())
                self.assertTrue((task_dir / "agent.log").exists())
                self.assertIn("cs-test-spawn-001", backend._instances)
            finally:
                backend.kill("cs-test-spawn-001")
                _force_kill_pgid(inst.pid)

    async def test_spawn_fails_if_working_dir_missing(self):
        """spawn() raises clearly when working_dir doesn't exist."""
        backend = OpenCodePerTaskBackend()
        with self.assertRaises(RuntimeError) as cm:
            backend.spawn("cs-bad-dir", "/nonexistent/path/that/should/not/exist")
        self.assertIn("working_dir does not exist", str(cm.exception))


class TestStatusAndKill(unittest.IsolatedAsyncioTestCase):
    """status() detects dead processes, kill() does clean shutdown."""

    def setUp(self):
        self.work_dir = Path(tempfile.mkdtemp(prefix="per_task_test_work_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.work_dir, ignore_errors=True)

    async def _spawn_sleep(self, task_id: str):
        """Helper: spawn a sleep-based OpenCode for testing."""
        with patch(
            "app.scheduler.sandbox.per_task.opencode_per_task._OPENCODE_BIN",
            "/bin/sleep"
        ), patch(
            "app.scheduler.sandbox.per_task.opencode_per_task._wait_healthy",
            return_value=True
        ):
            backend = OpenCodePerTaskBackend()
            inst = backend.spawn(task_id, str(self.work_dir))
            return backend, inst

    async def test_status_returns_instance_when_alive(self):
        backend, inst = await self._spawn_sleep("cs-alive-001")
        try:
            status = backend.status("cs-alive-001")
            self.assertIsNotNone(status)
            self.assertEqual(status.task_id, "cs-alive-001")
        finally:
            backend.kill("cs-alive-001")
            _force_kill_pgid(inst.pid)

    async def test_status_returns_none_when_dead(self):
        backend, inst = await self._spawn_sleep("cs-dies-001")
        os.killpg(inst.pid, signal.SIGKILL)
        time.sleep(0.5)
        try:
            self.assertIsNone(backend.status("cs-dies-001"))
            self.assertNotIn("cs-dies-001", backend._instances)
        finally:
            _force_kill_pgid(inst.pid)

    async def test_kill_stops_process_and_removes_from_registry(self):
        backend, inst = await self._spawn_sleep("cs-kill-001")
        pid = inst.pid
        self.assertIn("cs-kill-001", backend._instances)

        result = backend.kill("cs-kill-001")
        self.assertTrue(result)
        self.assertNotIn("cs-kill-001", backend._instances)

        # Reap the zombie so the PID doesn't get recycled to a different process
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        time.sleep(0.2)
        # After reap, /proc/<pid> is gone, so _is_pid_alive returns False
        self.assertFalse(_is_pid_alive(pid))

    async def test_kill_is_idempotent(self):
        backend, inst = await self._spawn_sleep("cs-double-kill")
        try:
            self.assertTrue(backend.kill("cs-double-kill"))
            self.assertFalse(backend.kill("cs-double-kill"))
        finally:
            _force_kill_pgid(inst.pid)

    async def test_kill_all(self):
        with patch(
            "app.scheduler.sandbox.per_task.opencode_per_task._OPENCODE_BIN",
            "/bin/sleep"
        ), patch(
            "app.scheduler.sandbox.per_task.opencode_per_task._wait_healthy",
            return_value=True
        ):
            backend = OpenCodePerTaskBackend()
            insts = []
            for i in range(3):
                insts.append(backend.spawn(f"cs-kill-all-{i:03d}", str(self.work_dir)))

            try:
                killed = backend.kill_all()
                # Reap zombies so the test's later assertions about _is_pid_alive
                # don't see recycled PIDs
                for inst in insts:
                    try:
                        os.waitpid(inst.pid, 0)
                    except ChildProcessError:
                        pass
                self.assertEqual(killed, 3)
                self.assertEqual(len(backend._instances), 0)
            finally:
                for inst in insts:
                    _force_kill_pgid(inst.pid)

    def test_kill_returns_false_for_unknown_task(self):
        backend = OpenCodePerTaskBackend()
        self.assertFalse(backend.kill("cs-never-existed"))


class TestPerTaskLogDir(unittest.IsolatedAsyncioTestCase):
    """Per-task log files go to ~/.memory/task_logs/<task_id>/"""

    def setUp(self):
        self.work_dir = Path(tempfile.mkdtemp(prefix="per_task_test_work_"))
        self._orig_log_dir = None

    def tearDown(self):
        import shutil
        shutil.rmtree(self.work_dir, ignore_errors=True)
        if self._orig_log_dir is not None:
            from app.scheduler.sandbox.per_task import opencode_per_task as m
            m._TASK_LOG_DIR = self._orig_log_dir

    async def test_log_dir_uses_task_id(self):
        """Log dir is ~/.memory/task_logs/<task_id>/."""
        from app.scheduler.sandbox.per_task import opencode_per_task as m
        tmp_log = Path(tempfile.mkdtemp(prefix="per_task_logs_"))
        self._orig_log_dir = m._TASK_LOG_DIR
        m._TASK_LOG_DIR = tmp_log

        with patch.object(m, "_OPENCODE_BIN", "/bin/sleep"), \
             patch.object(m, "_wait_healthy", return_value=True):
            backend = OpenCodePerTaskBackend()
            inst = backend.spawn("cs-log-dir-test", str(self.work_dir))
            try:
                log_path = Path(inst.log_path)
                self.assertEqual(log_path.parent.name, "cs-log-dir-test")
                self.assertTrue(log_path.exists())
                self.assertTrue(log_path.parent.joinpath("agent.pid").exists())
                self.assertTrue(log_path.parent.joinpath("agent.pgid").exists())
            finally:
                backend.kill("cs-log-dir-test")
                _force_kill_pgid(inst.pid)


if __name__ == "__main__":
    unittest.main()
