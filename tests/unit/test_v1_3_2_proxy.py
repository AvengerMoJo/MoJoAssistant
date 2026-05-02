"""
Unit tests for OpenAI-Compatible Proxy (v1.3.2).

Covers:
  - /v1/models endpoint (lists roles as models)
  - /v1/chat/completions endpoint (routes to RoleChatSession)
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.dashboard.openai_proxy import router


class TestOpenAIProxy(unittest.TestCase):

    def setUp(self):
        from fastapi import FastAPI
        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app)

    @patch("app.dashboard.openai_proxy.RoleManager")
    def test_list_models_returns_roles(self, MockRoleManager):
        mock_manager = MagicMock()
        mock_manager.list_roles.return_value = [
            {"id": "researcher", "name": "Researcher", "capabilities": ["web", "memory"], "purpose": "Research assistant"},
            {"id": "coder", "name": "Coder", "capabilities": ["file", "bash"], "purpose": "Code reviewer"},
        ]
        MockRoleManager.return_value = mock_manager

        response = self.client.get("/v1/models")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["object"], "list")
        self.assertEqual(len(data["data"]), 2)
        self.assertEqual(data["data"][0]["id"], "researcher")
        self.assertEqual(data["data"][0]["object"], "model")
        self.assertEqual(data["data"][0]["owned_by"], "mojoassistant")

    @patch("app.dashboard.openai_proxy.RoleManager")
    def test_list_models_empty(self, MockRoleManager):
        mock_manager = MagicMock()
        mock_manager.list_roles.return_value = []
        MockRoleManager.return_value = mock_manager

        response = self.client.get("/v1/models")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["data"]), 0)

    def test_chat_completions_requires_model(self):
        response = self.client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hello"}],
        })
        self.assertEqual(response.status_code, 400)

    def test_chat_completions_requires_messages(self):
        response = self.client.post("/v1/chat/completions", json={
            "model": "researcher",
        })
        self.assertEqual(response.status_code, 400)

    @patch("app.dashboard.openai_proxy.RoleManager")
    def test_chat_completions_returns_404_for_unknown_role(self, MockRoleManager):
        mock_manager = MagicMock()
        mock_manager.get.return_value = None
        MockRoleManager.return_value = mock_manager

        response = self.client.post("/v1/chat/completions", json={
            "model": "nonexistent",
            "messages": [{"role": "user", "content": "hello"}],
        })
        self.assertEqual(response.status_code, 404)

    @patch("app.scheduler.role_chat.RoleChatSession")
    @patch("app.dashboard.openai_proxy.RoleManager")
    def test_chat_completions_returns_response(self, MockRoleManager, MockSession):
        mock_manager = MagicMock()
        mock_manager.get.return_value = {"id": "researcher", "name": "Researcher"}
        MockRoleManager.return_value = mock_manager

        mock_session_instance = MagicMock()
        mock_session_instance.chat = AsyncMock(return_value={
            "response": "Hello! I'm Researcher.",
            "session_id": "test_session",
        })
        MockSession.return_value = mock_session_instance

        response = self.client.post("/v1/chat/completions", json={
            "model": "researcher",
            "messages": [{"role": "user", "content": "hello"}],
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["object"], "chat.completion")
        self.assertEqual(data["model"], "researcher")
        self.assertEqual(data["choices"][0]["message"]["content"], "Hello! I'm Researcher.")


if __name__ == "__main__":
    unittest.main()
