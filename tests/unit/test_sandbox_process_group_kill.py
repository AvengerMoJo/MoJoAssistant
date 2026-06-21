"""Tests for ProcessBackend process group kill (Bug 9 fix).

Covers:
  - PGID file is read on stop()
  - stop() uses killpg with the PGID from agent.pgid (avoids recycled PID)
  - stop() falls back to PID for killpg when no PGID file (since start_new_session=True means pid == pgid)
  - PGID + PID files are cleaned up on stop
"""
from __future__ import annotations

import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.sandbox.models import SandboxEntry
from app.sandbox.process import ProcessBackend


def _make_entry(tmp: Path, port: int = 4101) -> SandboxEntry:
    working_dir = tmp / "repo"
    working_dir.mkdir()
    return SandboxEntry(
        sandbox_id="test",
        repo_url="git@example.com:test.git",
        agent_type="opencode",
        working_dir=str(working_dir),
        status="running",
        port=port,
        pid=99999,
    )


class TestProcessGroupKill(unittest.TestCase):
    """Bug 9: process group kill."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.backend = ProcessBackend(base_dir=self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pgid_file_read_returns_int(self):
        pgid_path = self.tmp / "agent.pgid"
        pgid_path.write_text("54321")
        entry = _make_entry(self.tmp)
        self.assertEqual(self.backend._read_pgid(entry), 54321)

    def test_pgid_file_missing_returns_none(self):
        entry = _make_entry(self.tmp)
        self.assertIsNone(self.backend._read_pgid(entry))

    def test_pgid_file_corrupt_returns_none(self):
        pgid_path = self.tmp / "agent.pgid"
        pgid_path.write_text("not-a-number")
        entry = _make_entry(self.tmp)
        self.assertIsNone(self.backend._read_pgid(entry))

    def test_stop_uses_pgid_from_file(self):
        """stop() reads PGID from agent.pgid and uses it via killpg."""
        entry = _make_entry(self.tmp, port=4101)
        entry.pid = 12345
        pid_path = self.tmp / "agent.pid"
        pid_path.write_text("12345")
        pgid_path = self.tmp / "agent.pgid"
        pgid_path.write_text("99999")  # PGID differs from PID

        killpg_calls = []
        with patch("os.killpg", side_effect=lambda pgid, sig: killpg_calls.append((pgid, sig))), \
             patch("os.kill"), \
             patch.object(ProcessBackend, "_pid_alive", return_value=True), \
             patch("time.sleep", return_value=None), \
             patch.object(ProcessBackend, "_wait_healthy", return_value=True):
            self.backend.stop(entry)

        # killpg must use the PGID from the file (99999), not the recycled PID
        self.assertEqual(killpg_calls[0], (99999, signal.SIGTERM))
        self.assertFalse(pgid_path.exists())
        self.assertFalse(pid_path.exists())

    def test_stop_uses_pid_when_pgid_missing(self):
        """No PGID file → stop() falls back to PID as PGID (start_new_session guarantees pid==pgid)."""
        entry = _make_entry(self.tmp, port=4101)
        entry.pid = 12345
        pid_path = self.tmp / "agent.pid"
        pid_path.write_text("12345")

        killpg_calls = []
        with patch("os.killpg", side_effect=lambda pgid, sig: killpg_calls.append((pgid, sig))), \
             patch("os.kill"), \
             patch.object(ProcessBackend, "_pid_alive", return_value=True), \
             patch("time.sleep", return_value=None), \
             patch.object(ProcessBackend, "_wait_healthy", return_value=True):
            self.backend.stop(entry)

        # Falls back to PID for the group kill
        self.assertEqual(killpg_calls[0], (12345, signal.SIGTERM))


if __name__ == "__main__":
    unittest.main()
