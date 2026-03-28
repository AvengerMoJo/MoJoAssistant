"""
Unit tests for Claude Code Manager

Tests lifecycle operations with mocked subprocess.

File: tests/unit/test_claude_code_manager.py
"""

import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from app.mcp.claude_code.manager import ClaudeCodeManager
from app.mcp.claude_code.models import SessionConfig, SessionState
from app.mcp.claude_code.state_manager import ClaudeCodeStateManager
from app.mcp.agents.base import BaseAgentManager


class TestBaseAgentManager(unittest.TestCase):
    """Test BaseAgentManager ABC"""

    def test_opencode_is_subclass(self):
        from app.mcp.opencode.manager import OpenCodeManager
        self.assertTrue(issubclass(OpenCodeManager, BaseAgentManager))

    def test_claude_code_is_subclass(self):
        self.assertTrue(issubclass(ClaudeCodeManager, BaseAgentManager))


class TestSessionModels(unittest.TestCase):
    """Test data models"""

    def test_session_state_roundtrip(self):
        state = SessionState(
            session_id="test-1",
            status="running",
            pid=12345,
            working_dir="/tmp/test",
            model="claude-sonnet-4-5-20250929",
        )
        d = state.to_dict()
        restored = SessionState.from_dict(d)
        self.assertEqual(restored.session_id, "test-1")
        self.assertEqual(restored.status, "running")
        self.assertEqual(restored.pid, 12345)
        self.assertEqual(restored.working_dir, "/tmp/test")

    def test_session_config_to_dict(self):
        config = SessionConfig(session_id="s1", working_dir="/tmp")
        d = config.to_dict()
        self.assertEqual(d["session_id"], "s1")
        self.assertIn("model", d)


class TestClaudeCodeStateManager(unittest.TestCase):
    """Test state persistence"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sm = ClaudeCodeStateManager(memory_root=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_get_session(self):
        state = SessionState(session_id="s1", status="running", pid=100)
        self.sm.save_session(state)

        restored = self.sm.get_session("s1")
        self.assertIsNotNone(restored)
        self.assertEqual(restored.session_id, "s1")
        self.assertEqual(restored.pid, 100)

    def test_delete_session(self):
        state = SessionState(session_id="s1", status="stopped")
        self.sm.save_session(state)
        self.sm.delete_session("s1")
        self.assertIsNone(self.sm.get_session("s1"))

    def test_list_sessions(self):
        self.sm.save_session(SessionState(session_id="a"))
        self.sm.save_session(SessionState(session_id="b"))
        ids = self.sm.list_sessions()
        self.assertEqual(sorted(ids), ["a", "b"])

    def test_get_all_sessions(self):
        self.sm.save_session(SessionState(session_id="x", pid=1))
        self.sm.save_session(SessionState(session_id="y", pid=2))
        all_s = self.sm.get_all_sessions()
        self.assertEqual(len(all_s), 2)
        self.assertEqual(all_s["x"].pid, 1)


class TestClaudeCodeManager(unittest.TestCase):
    """Test manager lifecycle with mocked subprocess"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.workdir = tempfile.mkdtemp()
        self.manager = ClaudeCodeManager(memory_root=self.tmpdir, logger=None)
        self.manager.claude_bin = "/usr/bin/true"  # Use a real binary that exists

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _run(self, coro):
        return asyncio.run(coro)

    @patch("subprocess.Popen")
    def test_start_stop_cycle(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_popen.return_value = mock_proc

        # Start
        result = self._run(self.manager.start_project(
            "test-session", working_dir=self.workdir
        ))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["pid"], 99999)

        # Verify state saved
        session = self.manager.state_manager.get_session("test-session")
        self.assertEqual(session.status, "running")

        # Stop (mock process as not running for clean stop)
        with patch.object(self.manager, "_is_process_running", return_value=False):
            result = self._run(self.manager.stop_project("test-session"))
            self.assertEqual(result["status"], "success")

    @patch("subprocess.Popen")
    def test_start_missing_workdir(self, mock_popen):
        result = self._run(self.manager.start_project(
            "test", working_dir="/nonexistent/path"
        ))
        self.assertEqual(result["status"], "error")
        self.assertIn("does not exist", result["message"])
        mock_popen.assert_not_called()

    def test_start_missing_workdir_param(self):
        result = self._run(self.manager.start_project("test"))
        self.assertEqual(result["status"], "error")
        self.assertIn("working_dir is required", result["message"])

    def test_stop_nonexistent_session(self):
        result = self._run(self.manager.stop_project("nonexistent"))
        self.assertEqual(result["status"], "error")
        self.assertIn("not found", result["message"])

    def test_status_nonexistent_session(self):
        result = self._run(self.manager.get_status("nonexistent"))
        self.assertEqual(result["status"], "error")

    @patch("subprocess.Popen")
    def test_list_projects(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 11111
        mock_popen.return_value = mock_proc

        self._run(self.manager.start_project(
            "s1", working_dir=self.workdir
        ))

        with patch.object(self.manager, "_is_process_running", return_value=True):
            result = self._run(self.manager.list_projects())
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["count"], 1)

    @patch("subprocess.Popen")
    def test_destroy_project(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 22222
        mock_popen.return_value = mock_proc

        self._run(self.manager.start_project(
            "to-destroy", working_dir=self.workdir
        ))

        with patch.object(self.manager, "_is_process_running", return_value=False):
            result = self._run(self.manager.destroy_project("to-destroy"))
            self.assertEqual(result["status"], "success")

        # Verify state deleted
        self.assertIsNone(self.manager.state_manager.get_session("to-destroy"))

    def test_no_claude_binary(self):
        self.manager.claude_bin = ""
        result = self._run(self.manager.start_project(
            "test", working_dir=self.workdir
        ))
        self.assertEqual(result["status"], "error")
        self.assertIn("not found", result["message"])


if __name__ == "__main__":
    unittest.main()
