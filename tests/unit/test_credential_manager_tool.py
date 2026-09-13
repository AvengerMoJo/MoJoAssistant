"""
Tests for credential_manager_tool.py's call_llm_via_route -- the agent-facing
proxy tool (task #18 follow-up, 2026-08-01): agent supplies route_id +
messages, MoJoAssistant resolves the credential internally and makes the
call itself. Raw api_key must never appear in the tool's return value,
including partial fragments a provider's own error response might echo back
(found live: LMStudio's 401 body included a masked prefix of the rejected
key -- "0uQer5WlAb**********" -- which the first version of this tool
forwarded verbatim).
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

from app.scheduler.credential_manager_tool import run, _redact_key_fragments


class TestRedactKeyFragments(unittest.TestCase):
    def test_full_key_is_redacted(self):
        text = 'error: bad key "sk-abc123xyz"'
        self.assertNotIn("sk-abc123xyz", _redact_key_fragments(text, "sk-abc123xyz"))

    def test_partial_prefix_is_redacted(self):
        """The exact case found live: a provider echoes back a truncated
        prefix of the key, not the full value."""
        text = "Malformed API token provided: 0uQer5WlAb**********."
        result = _redact_key_fragments(text, "0uQer5WlAbNPQl3lP0FZ")
        self.assertNotIn("0uQer5WlAb", result)
        self.assertIn("[REDACTED]", result)

    def test_short_fragments_below_threshold_are_left_alone(self):
        """Redacting very short fragments (e.g. 2-3 chars) would mangle
        unrelated text -- only fragments >= min_fragment_length count."""
        text = "the number 0u appears here"
        result = _redact_key_fragments(text, "0uQer5WlAbNPQl3lP0FZ", min_fragment_length=6)
        self.assertEqual(text, result)

    def test_empty_inputs_are_safe(self):
        self.assertEqual(_redact_key_fragments("", "sk-abc"), "")
        self.assertEqual(_redact_key_fragments("some text", ""), "some text")


class TestCallLlmViaRoute(unittest.TestCase):
    def _mock_resolved(self):
        return {
            "api_key": "sk-test-key-1234567890",
            "base_url": "http://localhost:8080/v1",
            "model": "test-model",
        }

    def test_missing_route_id_fails_fast(self):
        result = asyncio.run(run({"messages": [{"role": "user", "content": "hi"}]}))
        self.assertFalse(result["success"])
        self.assertIn("route_id", result["error"])

    def test_missing_messages_fails_fast(self):
        result = asyncio.run(run({"route_id": "route_x"}))
        self.assertFalse(result["success"])
        self.assertIn("messages", result["error"])

    def test_successful_call_returns_completion_never_the_key(self):
        async def scenario():
            with patch("app.scheduler.credential_manager_client.get_credential_manager_client") as get_client:
                mock_client = MagicMock()
                mock_client.aresolve_credential = AsyncMock(return_value=self._mock_resolved())
                mock_client.areport_usage = AsyncMock(return_value={"status": "available"})
                get_client.return_value = mock_client

                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "choices": [{"message": {"content": "hello!"}}],
                    "usage": {"total_tokens": 5},
                }

                with patch("httpx.AsyncClient") as mock_http_cls:
                    mock_http = AsyncMock()
                    mock_http.post = AsyncMock(return_value=mock_response)
                    mock_http_cls.return_value.__aenter__.return_value = mock_http

                    result = await run({
                        "route_id": "route_x",
                        "messages": [{"role": "user", "content": "hi"}],
                    })

            self.assertTrue(result["success"])
            self.assertEqual(result["completion"], "hello!")
            self.assertNotIn("api_key", result)
            self.assertNotIn("sk-test-key-1234567890", str(result))
            mock_client.areport_usage.assert_awaited_once()

        asyncio.run(scenario())

    def test_failed_call_redacts_key_fragments_from_error(self):
        async def scenario():
            with patch("app.scheduler.credential_manager_client.get_credential_manager_client") as get_client:
                mock_client = MagicMock()
                mock_client.aresolve_credential = AsyncMock(return_value=self._mock_resolved())
                mock_client.areport_usage = AsyncMock(return_value={"status": "available"})
                get_client.return_value = mock_client

                mock_response = MagicMock()
                mock_response.status_code = 401
                mock_response.text = 'Malformed token: sk-test-key-1234**********'

                with patch("httpx.AsyncClient") as mock_http_cls:
                    mock_http = AsyncMock()
                    mock_http.post = AsyncMock(return_value=mock_response)
                    mock_http_cls.return_value.__aenter__.return_value = mock_http

                    result = await run({
                        "route_id": "route_x",
                        "messages": [{"role": "user", "content": "hi"}],
                    })

            self.assertFalse(result["success"])
            self.assertNotIn("sk-test-key", result["error"])
            self.assertIn("[REDACTED]", result["error"])

        asyncio.run(scenario())

    def test_credential_resolution_failure_returns_error_not_exception(self):
        async def scenario():
            from app.scheduler.credential_manager_client import CredentialManagerError

            with patch("app.scheduler.credential_manager_client.get_credential_manager_client") as get_client:
                mock_client = MagicMock()
                mock_client.aresolve_credential = AsyncMock(
                    side_effect=CredentialManagerError("no grant for this route")
                )
                get_client.return_value = mock_client

                result = await run({
                    "route_id": "route_x",
                    "messages": [{"role": "user", "content": "hi"}],
                })

            self.assertFalse(result["success"])
            self.assertIn("route_x", result["error"])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
