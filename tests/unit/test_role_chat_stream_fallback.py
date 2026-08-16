"""
Regression tests for the streaming-fallback silent-connection bug.

When RoleChatSession.exchange_stream()'s call to client.call_stream_async()
raises, the code falls back to a blocking self._call_raw() call. Previously
this fallback sent zero bytes to the client for its entire duration --
which is exactly what happened when a real bug (httpx.AsyncClient invalid
`connect` kwarg, fixed 2026-08) broke every streaming call: every dashboard
chat silently fell back to a slow blocking call with no bytes flowing,
which trips proxy/client idle-connection timeouts and surfaces as
"Error: network error" client-side.

The fix: emit an immediate "status" SSE event when the fallback begins, and
send periodic SSE keepalive comments for as long as the blocking fallback
call takes, so the connection is never silent regardless of cause or
duration.
"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def _make_session(tmp_dir, role_id="test_role", session_id="test_session_stream"):
    from app.scheduler.role_chat import RoleChatSession
    from app.scheduler.interaction_mode import InteractionMode

    session = RoleChatSession.__new__(RoleChatSession)
    session.role_id = role_id
    session.session_id = session_id
    session.mode = InteractionMode.DASHBOARD_CHAT
    session._session_dir = Path(tmp_dir) / "roles" / role_id / "chat_history"
    session._session_dir.mkdir(parents=True, exist_ok=True)
    session._session_file = session._session_dir / f"{session_id}.json"
    return session


class TestStreamFallbackKeepsConnectionAlive(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    async def test_stream_failure_emits_status_before_blocking_fallback(self):
        """The client must receive a status event immediately when the stream
        breaks, not silence until the fallback call eventually returns."""
        session = _make_session(self.tmp)
        mock_role = {"system_prompt": "You are helpful.", "tool_access": []}

        async def fake_call_raw(messages, rm, tools=None):
            return {"choices": [{"message": {"content": "fallback answer", "tool_calls": None}}]}

        broken_client = MagicMock()

        async def broken_stream(*a, **kw):
            raise RuntimeError("stream construction failed")
            yield  # pragma: no cover -- makes this an async generator

        broken_client.call_stream_async = broken_stream

        with patch("app.scheduler.role_chat.RoleManager") as MockRM, \
             patch("app.llm.unified_client.UnifiedLLMClient", return_value=broken_client):
            MockRM.return_value.get.return_value = mock_role
            session._call_raw = fake_call_raw
            session._load_session = MagicMock(return_value={"exchanges": []})
            session._load_ku_context = MagicMock(return_value="")
            session._load_recent_activity = MagicMock(return_value="")
            session._save_session = MagicMock()
            session._get_chat_tools = MagicMock(return_value=[])

            resource_manager = MagicMock()
            resource = MagicMock(model="test-model", base_url="http://x", api_key="k",
                                  output_limit=8192, provider="test")
            resource_manager.acquire.return_value = resource

            events = []
            async for line in session.exchange_stream("hi", resource_manager=resource_manager):
                events.append(line)

        # First event after the break must be a status token, sent before any
        # fallback content -- proving bytes flow immediately, not after the
        # blocking call completes.
        parsed = [json.loads(e[len("data: "):]) for e in events if e.startswith("data: ")]
        types = [p["type"] for p in parsed]
        self.assertIn("status", types, f"no status event emitted; got types: {types}")
        status_idx = types.index("status")
        # The fallback's own content must come after the status event, not before.
        token_texts = "".join(p.get("text", "") for p in parsed[status_idx:] if p["type"] == "token")
        self.assertIn("fallback answer", token_texts)

    async def test_slow_fallback_emits_keepalive_comments(self):
        """If the blocking fallback call takes longer than the keepalive
        interval, the generator must emit SSE comment lines (`: keepalive`)
        rather than go silent."""
        import app.scheduler.role_chat as rc

        session = _make_session(self.tmp)
        mock_role = {"system_prompt": "You are helpful.", "tool_access": []}

        async def slow_call_raw(messages, rm, tools=None):
            await asyncio.sleep(0.05)
            return {"choices": [{"message": {"content": "done", "tool_calls": None}}]}

        broken_client = MagicMock()

        async def broken_stream(*a, **kw):
            raise RuntimeError("stream broke")
            yield  # pragma: no cover

        broken_client.call_stream_async = broken_stream

        with patch("app.scheduler.role_chat.RoleManager") as MockRM, \
             patch("app.llm.unified_client.UnifiedLLMClient", return_value=broken_client), \
             patch.object(rc, "STREAM_FALLBACK_KEEPALIVE_INTERVAL", 0.01):
            MockRM.return_value.get.return_value = mock_role
            session._call_raw = slow_call_raw
            session._load_session = MagicMock(return_value={"exchanges": []})
            session._load_ku_context = MagicMock(return_value="")
            session._load_recent_activity = MagicMock(return_value="")
            session._save_session = MagicMock()
            session._get_chat_tools = MagicMock(return_value=[])

            resource_manager = MagicMock()
            resource = MagicMock(model="test-model", base_url="http://x", api_key="k",
                                  output_limit=8192, provider="test")
            resource_manager.acquire.return_value = resource

            events = []
            async for line in session.exchange_stream("hi", resource_manager=resource_manager):
                events.append(line)

        self.assertTrue(
            any(e.startswith(": keepalive") for e in events),
            f"no keepalive comment emitted during slow fallback; got: {events}",
        )


if __name__ == "__main__":
    unittest.main()
