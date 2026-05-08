"""
Unit tests for Cross-Role Referral (v1.3.2).

Covers:
  - refer_to_role tool in _execute_tool
  - Referral to existing role
  - Referral to non-existent role
  - Referral response structure
"""

import asyncio
import json
import unittest
from unittest.mock import MagicMock, patch

from app.scheduler.role_chat import RoleChatSession


class TestCrossRoleReferral(unittest.TestCase):

    def setUp(self):
        with patch("app.scheduler.role_chat.get_memory_subpath", return_value="/tmp/test_mojo"):
            self.session = RoleChatSession(role_id="researcher", session_id="test_session")

    @patch("app.scheduler.role_chat.RoleManager")
    def test_refer_to_existing_role(self, MockRoleManager):
        mock_manager = MagicMock()
        mock_manager.get.return_value = {"id": "analyst", "name": "Analyst"}
        mock_manager.list_roles.return_value = [
            {"id": "analyst"}, {"id": "coder"}, {"id": "researcher"},
        ]
        MockRoleManager.return_value = mock_manager

        result = asyncio.run(self.session._execute_tool("refer_to_role", {
            "role_id": "analyst",
            "reason": "Analyst has better infrastructure knowledge",
            "context_summary": "User asking about server config",
        }))

        data = json.loads(result)
        self.assertTrue(data["success"])
        self.assertEqual(data["type"], "referral")
        self.assertEqual(data["referral_to"], "analyst")
        self.assertIn("Analyst", data["message"])
        self.assertIn("infrastructure knowledge", data["message"])

    @patch("app.scheduler.role_chat.RoleManager")
    def test_refer_to_nonexistent_role(self, MockRoleManager):
        mock_manager = MagicMock()
        mock_manager.get.return_value = None
        mock_manager.list_roles.return_value = [
            {"id": "analyst"}, {"id": "coder"},
        ]
        MockRoleManager.return_value = mock_manager

        result = asyncio.run(self.session._execute_tool("refer_to_role", {
            "role_id": "nonexistent",
            "reason": "test",
        }))

        data = json.loads(result)
        self.assertFalse(data["success"])
        self.assertIn("not found", data["error"])
        self.assertIn("analyst", data["error"])  # Should list available roles

    @patch("app.scheduler.role_chat.RoleManager")
    def test_refer_includes_context_summary(self, MockRoleManager):
        mock_manager = MagicMock()
        mock_manager.get.return_value = {"id": "coder", "name": "Coder"}
        mock_manager.list_roles.return_value = [{"id": "coder"}]
        MockRoleManager.return_value = mock_manager

        result = asyncio.run(self.session._execute_tool("refer_to_role", {
            "role_id": "coder",
            "reason": "Code review needed",
            "context_summary": "Reviewing PR #42 for security issues",
        }))

        data = json.loads(result)
        self.assertTrue(data["success"])
        self.assertEqual(data["context_summary"], "Reviewing PR #42 for security issues")


if __name__ == "__main__":
    unittest.main()
