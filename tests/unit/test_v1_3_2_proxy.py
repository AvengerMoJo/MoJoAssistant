"""
Unit tests for OpenAI-Compatible Proxy (v1.3.2).

Covers:
  - /v1/models endpoint (lists roles as models)
  - /v1/chat/completions endpoint (routes to RoleChatSession)
  - Authentication (Bearer token required)
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.dashboard.openai_proxy import router, _get_role_manager

TEST_TOKEN = "test-api-key-12345"


class TestOpenAIProxy(unittest.TestCase):

    def setUp(self):
        from fastapi import FastAPI
        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app)
        self.headers = {"Authorization": f"Bearer {TEST_TOKEN}"}

        # Patch _load_proxy_config globally for all tests
        self._config_patcher = patch(
            "app.dashboard.openai_proxy._load_proxy_config",
            return_value={"api_key": TEST_TOKEN},
        )
        self._config_patcher.start()

    def tearDown(self):
        self._config_patcher.stop()

    @patch("app.dashboard.openai_proxy._get_role_manager")
    def test_list_models_returns_roles(self, MockGetRM):
        mock_manager = MagicMock()
        mock_manager.list_roles.return_value = [
            {"id": "researcher", "name": "Researcher", "capabilities": ["web", "memory"], "purpose": "Research assistant"},
            {"id": "coder", "name": "Coder", "capabilities": ["file", "bash"], "purpose": "Code reviewer"},
        ]
        MockGetRM.return_value = mock_manager

        response = self.client.get("/v1/models", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["object"], "list")
        self.assertEqual(len(data["data"]), 2)
        self.assertEqual(data["data"][0]["id"], "researcher")

    @patch("app.dashboard.openai_proxy._get_role_manager")
    def test_list_models_empty(self, MockGetRM):
        mock_manager = MagicMock()
        mock_manager.list_roles.return_value = []
        MockGetRM.return_value = mock_manager

        response = self.client.get("/v1/models", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["data"]), 0)

    def test_list_models_requires_auth(self):
        response = self.client.get("/v1/models")
        self.assertEqual(response.status_code, 401)

    def test_chat_completions_requires_model(self):
        response = self.client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hello"}],
        }, headers=self.headers)
        self.assertEqual(response.status_code, 400)

    def test_chat_completions_requires_messages(self):
        response = self.client.post("/v1/chat/completions", json={
            "model": "researcher",
        }, headers=self.headers)
        self.assertEqual(response.status_code, 400)

    def test_chat_completions_requires_auth(self):
        response = self.client.post("/v1/chat/completions", json={
            "model": "researcher",
            "messages": [{"role": "user", "content": "hello"}],
        })
        self.assertEqual(response.status_code, 401)

    @patch("app.dashboard.openai_proxy._get_role_manager")
    def test_chat_completions_returns_404_for_unknown_role(self, MockGetRM):
        mock_manager = MagicMock()
        mock_manager.get.return_value = None
        MockGetRM.return_value = mock_manager

        response = self.client.post("/v1/chat/completions", json={
            "model": "nonexistent",
            "messages": [{"role": "user", "content": "hello"}],
        }, headers=self.headers)
        self.assertEqual(response.status_code, 404)

    def test_chat_completions_rejects_streaming(self):
        response = self.client.post("/v1/chat/completions", json={
            "model": "researcher",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        }, headers=self.headers)
        self.assertEqual(response.status_code, 501)


if __name__ == "__main__":
    unittest.main()
