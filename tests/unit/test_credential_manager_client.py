"""
Tests for credential_manager_client.py -- the Phase 2 additive-first-step
client for the standalone ai-credential-manager service (task #18, see
project_unified_provider_resource_pool_vision.md).

Network calls are mocked here (no live service dependency in the standard
test suite) -- the real end-to-end proof against the live deployed service
was run manually: resource_pool.py's resolve_via_service() pulled the real
lmstudio_qwen35b credential and it matched the local resource_pool.env
value exactly, and report_usage_to_service() round-tripped.
"""
import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.scheduler.credential_manager_client import (
    CredentialManagerClient,
    CredentialManagerError,
)


def _write_bootstrap(path: Path) -> None:
    path.write_text(json.dumps({
        "service_url": "http://127.0.0.1:8700",
        "mojoassistant_client": {
            "client_id": "test-client-id",
            "client_secret": "test-secret",
            "redirect_uri": "https://example.com/cb",
        },
    }))


class TestCredentialManagerClientBootstrap(unittest.TestCase):
    def test_missing_bootstrap_file_raises_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does_not_exist.json"
            with self.assertRaises(CredentialManagerError):
                CredentialManagerClient(bootstrap_path=missing)


class TestCredentialManagerClientTokenCaching(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.bootstrap_path = Path(self.tmpdir.name) / "bootstrap.json"
        _write_bootstrap(self.bootstrap_path)
        self.client = CredentialManagerClient(bootstrap_path=self.bootstrap_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_token_is_cached_and_reused_within_expiry(self):
        async def run():
            with patch.object(
                self.client, "_authorize_and_exchange", new=AsyncMock(return_value=("tok-abc", 3600))
            ) as mock_auth:
                t1 = await self.client._get_token("route:x:use")
                t2 = await self.client._get_token("route:x:use")
                self.assertEqual(t1, "tok-abc")
                self.assertEqual(t2, "tok-abc")
                mock_auth.assert_called_once()

        asyncio.run(run())

    def test_expired_token_triggers_a_fresh_exchange(self):
        async def run():
            with patch.object(
                self.client, "_authorize_and_exchange", new=AsyncMock(return_value=("tok-1", 3600))
            ):
                await self.client._get_token("route:x:use")

            # Force the cached entry to look expired.
            self.client._token_cache["route:x:use"].expires_at = time.time() - 10

            with patch.object(
                self.client, "_authorize_and_exchange", new=AsyncMock(return_value=("tok-2", 3600))
            ) as mock_auth:
                t = await self.client._get_token("route:x:use")
                self.assertEqual(t, "tok-2")
                mock_auth.assert_called_once()

        asyncio.run(run())

    def test_different_scopes_get_independent_cache_entries(self):
        async def run():
            async def fake_auth(scope):
                return (f"tok-for-{scope}", 3600)

            with patch.object(self.client, "_authorize_and_exchange", new=AsyncMock(side_effect=fake_auth)):
                t1 = await self.client._get_token("route:a:use")
                t2 = await self.client._get_token("route:b:use")
                self.assertEqual(t1, "tok-for-route:a:use")
                self.assertEqual(t2, "tok-for-route:b:use")

        asyncio.run(run())


class TestCredentialManagerClientErrorPropagation(unittest.TestCase):
    """No fallback pattern: a tool call that returns {"error": ...} must
    raise, never be silently swallowed or substituted with a default."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.bootstrap_path = Path(self.tmpdir.name) / "bootstrap.json"
        _write_bootstrap(self.bootstrap_path)
        self.client = CredentialManagerClient(bootstrap_path=self.bootstrap_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_resolve_credential_raises_on_tool_error(self):
        async def run():
            with patch.object(self.client, "_get_token", new=AsyncMock(return_value="tok")):
                with patch.object(
                    self.client, "_call_tool",
                    new=AsyncMock(return_value={"error": "access_token lacks required scope 'route:x:use'"}),
                ):
                    with self.assertRaises(CredentialManagerError):
                        await self.client.aresolve_credential("x")

        asyncio.run(run())

    def test_report_usage_raises_on_tool_error(self):
        async def run():
            with patch.object(self.client, "_get_token", new=AsyncMock(return_value="tok")):
                with patch.object(
                    self.client, "_call_tool", new=AsyncMock(return_value={"error": "unknown route_id: x"})
                ):
                    with self.assertRaises(CredentialManagerError):
                        await self.client.areport_usage("x", success=True)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
