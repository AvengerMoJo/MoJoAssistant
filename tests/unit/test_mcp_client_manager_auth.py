"""Unit tests for MCPClientManager's HTTP auth header construction.

Added to support registering AgentBridge (app/mcp/agent_bridge/server.py)
as an internal-facing MCP tool source for roles like Ahman/network_admin --
AgentBridge enforces HTTP Basic Auth (username always "opencode", matching
OpenCodeClient's convention), but _connect_http previously only supported
Bearer tokens, so an internal role had no way to authenticate to it.
"""

from __future__ import annotations

import base64
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from app.scheduler.mcp_client_manager import ExternalMCPServer, MCPClientManager


def _server(**overrides):
    defaults = dict(
        id="test_server",
        name="Test Server",
        transport="http",
        mcp_http_url="http://100.66.212.7:8497/mcp",
    )
    defaults.update(overrides)
    return ExternalMCPServer(**defaults)


class TestConnectHttpAuthHeaders(unittest.IsolatedAsyncioTestCase):
    async def _connect_and_capture_headers(self, server):
        manager = MCPClientManager()
        captured = {}

        @asynccontextmanager
        async def fake_streamablehttp_client(url, headers=None):
            captured["url"] = url
            captured["headers"] = headers
            yield (AsyncMock(), AsyncMock(), None)

        fake_session = AsyncMock()
        fake_session.initialize = AsyncMock()
        fake_session.list_tools = AsyncMock(return_value=AsyncMock(tools=[]))

        with patch(
            "mcp.client.streamable_http.streamablehttp_client",
            fake_streamablehttp_client,
        ), patch("mcp.ClientSession") as mock_session_cls:
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=fake_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await manager._connect_http(server)

        return captured["headers"]

    async def test_default_bearer_scheme(self):
        server = _server(authorization="my-token")
        headers = await self._connect_and_capture_headers(server)
        self.assertEqual(headers["Authorization"], "Bearer my-token")

    async def test_basic_scheme_uses_opencode_username(self):
        server = _server(authorization="the-password", auth_scheme="basic")
        headers = await self._connect_and_capture_headers(server)
        expected_creds = base64.b64encode(b"opencode:the-password").decode()
        self.assertEqual(headers["Authorization"], f"Basic {expected_creds}")

    async def test_no_authorization_means_no_auth_header(self):
        server = _server(authorization=None)
        headers = await self._connect_and_capture_headers(server)
        self.assertIsNone(headers)

    async def test_basic_scheme_with_no_password_falls_back_to_no_header(self):
        server = _server(authorization="", auth_scheme="basic")
        headers = await self._connect_and_capture_headers(server)
        self.assertIsNone(headers)


class TestExternalMCPServerDefaults(unittest.TestCase):
    def test_auth_scheme_defaults_to_bearer(self):
        server = _server()
        self.assertEqual(server.auth_scheme, "bearer")


if __name__ == "__main__":
    unittest.main()
