"""Unit tests for OpenCodeClient's v1/v2 API branching.

opencode's v2 API (stonemojo, 2026-09) restructured everything under /api,
wraps every response in {"data": ...}, replaced message-sending with
POST /session/{id}/prompt (body {"text": ...} instead of {"parts": [...]}),
and replaced the Question API with session-scoped Forms. This file verifies
OpenCodeClient produces the exact request shape for each api_version and
correctly unwraps v2 responses, using httpx.MockTransport so no live server
is needed -- see app/scheduler/sandbox/opencode_client.py for the full
verified-against-a-real-server API mapping.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import httpx

from app.scheduler.sandbox import opencode_client as opencode_client_module
from app.scheduler.sandbox.opencode_client import OpenCodeClient


def _client_with_transport(api_version: str, handler):
    client = OpenCodeClient(base_url="http://test", password="pw", api_version=api_version)

    async def _get_client():
        if client._client is None or client._client.is_closed:
            client._client = httpx.AsyncClient(
                base_url=client._base_url,
                auth=client._auth,
                transport=httpx.MockTransport(handler),
            )
        return client._client

    client._get_client = _get_client
    return client


class TestApiVersionValidation(unittest.TestCase):
    def test_rejects_unknown_version(self):
        with self.assertRaises(ValueError):
            OpenCodeClient(base_url="http://test", api_version="v3")

    def test_defaults_to_v1(self):
        client = OpenCodeClient(base_url="http://test")
        self.assertFalse(client._v2)
        self.assertEqual(client._prefix, "")


class TestSendMessage(unittest.IsolatedAsyncioTestCase):
    async def test_v1_posts_parts_to_message_endpoint(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"id": "msg_1", "role": "assistant"})

        client = _client_with_transport("v1", handler)
        result = await client.send_message("sess_1", "hello")

        self.assertEqual(seen["path"], "/session/sess_1/message")
        self.assertEqual(seen["body"], {"parts": [{"type": "text", "text": "hello"}]})
        self.assertEqual(result["id"], "msg_1")

    async def test_v2_posts_text_to_prompt_endpoint(self):
        """v2's POST /prompt is a fire-and-forget ack (confirmed live against
        a real v2 server 2026-09-23: returns in ~0.25s with just an echo of
        the submitted user message) -- not the assistant's reply. Only the
        initial POST's request shape is checked here; the polling/reshaping
        behavior is covered by TestSendMessageV2Polling below."""
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                seen["path"] = request.url.path
                seen["body"] = json.loads(request.content)
                return httpx.Response(
                    200, json={"data": {"id": "msg_ack", "type": "user", "time": {"created": 100}}}
                )
            # GET /message poll: go straight to idle with no assistant reply.
            return httpx.Response(
                200,
                json={"data": [{"id": "msg_idle", "type": "idle", "outcome": "succeeded",
                                 "time": {"created": 101}}]},
            )

        client = _client_with_transport("v2", handler)
        result = await client.send_message("sess_1", "hello", poll_interval=0.001)

        self.assertEqual(seen["path"], "/api/session/sess_1/prompt")
        self.assertEqual(seen["body"], {"text": "hello"})
        self.assertEqual(result, {"parts": []})


class TestSendMessageV2Polling(unittest.IsolatedAsyncioTestCase):
    """v2's message flow is asynchronous -- POST /prompt only acks the
    user's message; the real assistant reply must be polled for via
    GET /message until an "idle" marker appears, then reshaped from v2's
    ".content[]" (mixed reasoning/text blocks) into v1's ".parts[]" (text
    only) so callers like _extract_text() in coding_session_opencode.py
    work identically for both versions. Confirmed live 2026-09-23."""

    async def test_polls_until_idle_then_returns_v1_shaped_parts(self):
        poll_responses = [
            # First poll: still running, no idle yet.
            {"data": [{"id": "msg_ack", "type": "user", "time": {"created": 100}}]},
            # Second poll: assistant replied and session went idle.
            {"data": [
                {"id": "msg_ack", "type": "user", "time": {"created": 100}},
                {"id": "msg_reply", "type": "assistant", "time": {"created": 105},
                 "content": [
                     {"type": "reasoning", "text": "thinking..."},
                     {"type": "text", "text": "PONG"},
                 ]},
                {"id": "msg_idle", "type": "idle", "outcome": "succeeded", "time": {"created": 106}},
            ]},
        ]
        calls = {"get": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(
                    200, json={"data": {"id": "msg_ack", "type": "user", "time": {"created": 100}}}
                )
            body = poll_responses[min(calls["get"], len(poll_responses) - 1)]
            calls["get"] += 1
            return httpx.Response(200, json=body)

        client = _client_with_transport("v2", handler)
        result = await client.send_message("sess_1", "ping", poll_interval=0.001)

        self.assertEqual(calls["get"], 2)
        self.assertEqual(result["parts"], [{"type": "text", "text": "PONG"}])
        # Reasoning blocks are dropped, matching v1's text-only _extract_text.
        self.assertNotIn("thinking...", json.dumps(result["parts"]))

    async def test_times_out_when_no_idle_marker_appears(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(
                    200, json={"data": {"id": "msg_ack", "type": "user", "time": {"created": 100}}}
                )
            return httpx.Response(200, json={"data": [{"id": "msg_ack", "type": "user",
                                                          "time": {"created": 100}}]})

        client = _client_with_transport("v2", handler)
        with patch.object(opencode_client_module, "MESSAGE_TIMEOUT", 0.01):
            with self.assertRaises(TimeoutError):
                await client.send_message("sess_1", "ping", poll_interval=0.001)

    async def test_latest_assistant_message_picks_most_recent(self):
        messages = [
            {"type": "assistant", "time": {"created": 50}, "content": [{"type": "text", "text": "old"}]},
            {"type": "assistant", "time": {"created": 200}, "content": [{"type": "text", "text": "new"}]},
            {"type": "user", "time": {"created": 150}},
        ]
        result = OpenCodeClient._latest_assistant_message(messages, since=0)
        self.assertEqual(result["content"][0]["text"], "new")

    async def test_latest_assistant_message_ignores_messages_before_since(self):
        messages = [
            {"type": "assistant", "time": {"created": 50}, "content": [{"type": "text", "text": "stale"}]},
        ]
        result = OpenCodeClient._latest_assistant_message(messages, since=100)
        self.assertIsNone(result)

    async def test_v2_message_to_v1_shape_drops_non_text_blocks(self):
        message = {
            "id": "msg_1",
            "content": [
                {"type": "reasoning", "text": "hmm"},
                {"type": "text", "text": "hello"},
                {"type": "text", "text": "world"},
            ],
        }
        shaped = OpenCodeClient._v2_message_to_v1_shape(message)
        self.assertEqual(
            shaped["parts"],
            [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}],
        )
        self.assertEqual(shaped["id"], "msg_1")


class TestSessionCrud(unittest.IsolatedAsyncioTestCase):
    async def test_v1_list_sessions_bare_array(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/session")
            return httpx.Response(200, json=[{"id": "s1"}, {"id": "s2"}])

        client = _client_with_transport("v1", handler)
        result = await client.list_sessions()
        self.assertEqual(result, [{"id": "s1"}, {"id": "s2"}])

    async def test_v2_list_sessions_wrapped_with_cursor(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/session")
            return httpx.Response(
                200,
                json={"data": [{"id": "s1"}], "cursor": {"previous": None, "next": None}},
            )

        client = _client_with_transport("v2", handler)
        result = await client.list_sessions()
        self.assertEqual(result, [{"id": "s1"}])

    async def test_v1_create_session_sends_no_body_by_default(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = request.content
            return httpx.Response(200, json={"id": "s1"})

        client = _client_with_transport("v1", handler)
        await client.create_session()
        self.assertEqual(seen["body"], b"")

    async def test_v2_create_session_sends_empty_json_object_by_default(self):
        """v2 400s on a bodyless POST /api/session -- confirmed live against
        a real v2 server 2026-09-23. Must send {} even with no kwargs."""
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"data": {"id": "s1"}})

        client = _client_with_transport("v2", handler)
        result = await client.create_session()
        self.assertEqual(seen["body"], {})
        self.assertEqual(result["id"], "s1")

    async def test_v2_delete_session_uses_api_prefix(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "DELETE")
            self.assertEqual(request.url.path, "/api/session/sess_1")
            return httpx.Response(200, json={"data": {"ok": True}})

        client = _client_with_transport("v2", handler)
        result = await client.delete_session("sess_1")
        self.assertEqual(result, {"ok": True})


class TestPermissions(unittest.IsolatedAsyncioTestCase):
    async def test_v1_filters_global_list_by_session(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/permission")
            return httpx.Response(
                200,
                json=[
                    {"id": "p1", "sessionID": "sess_1"},
                    {"id": "p2", "sessionID": "sess_2"},
                ],
            )

        client = _client_with_transport("v1", handler)
        result = await client.list_permissions("sess_1")
        self.assertEqual(result, [{"id": "p1", "sessionID": "sess_1"}])

    async def test_v2_permission_list_already_session_scoped(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/session/sess_1/permission")
            return httpx.Response(200, json={"data": [{"id": "p1"}]})

        client = _client_with_transport("v2", handler)
        result = await client.list_permissions("sess_1")
        self.assertEqual(result, [{"id": "p1"}])

    async def test_v2_respond_to_permission_path(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(
                request.url.path, "/api/session/sess_1/permission/perm_1/reply"
            )
            return httpx.Response(200, json={"data": {"ok": True}})

        client = _client_with_transport("v2", handler)
        result = await client.respond_to_permission("sess_1", "perm_1", "once")
        self.assertEqual(result, {"ok": True})

    async def test_respond_to_permission_rejects_bad_response(self):
        client = OpenCodeClient(base_url="http://test")
        with self.assertRaises(ValueError):
            await client.respond_to_permission("sess_1", "perm_1", "maybe")


class TestQuestionsAndForms(unittest.IsolatedAsyncioTestCase):
    async def test_v1_list_questions_filters_by_session(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/question")
            return httpx.Response(
                200,
                json=[
                    {"id": "q1", "sessionID": "sess_1"},
                    {"id": "q2", "sessionID": "sess_2"},
                ],
            )

        client = _client_with_transport("v1", handler)
        result = await client.list_questions("sess_1")
        self.assertEqual(result, [{"id": "q1", "sessionID": "sess_1"}])

    async def test_v2_list_questions_hits_form_endpoint(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/session/sess_1/form")
            return httpx.Response(200, json={"data": [{"id": "frm_1"}]})

        client = _client_with_transport("v2", handler)
        result = await client.list_questions("sess_1")
        self.assertEqual(result, [{"id": "frm_1"}])

    async def test_v1_reply_to_question_posts_answers_array(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"ok": True})

        client = _client_with_transport("v1", handler)
        result = await client.reply_to_question("sess_1", "q1", "postgres")

        self.assertTrue(result)
        self.assertEqual(seen["path"], "/question/q1/reply")
        self.assertEqual(seen["body"], {"answers": [["postgres"]]})

    async def test_v2_reply_to_question_fetches_form_then_replies_by_field_key(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, request.url.path))
            if request.method == "GET":
                self.assertEqual(request.url.path, "/api/session/sess_1/form/frm_1")
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "id": "frm_1",
                            "sessionID": "sess_1",
                            "fields": [{"key": "db_choice", "type": "string"}],
                        }
                    },
                )
            self.assertEqual(request.url.path, "/api/session/sess_1/form/frm_1/reply")
            body = json.loads(request.content)
            self.assertEqual(body, {"answer": {"db_choice": "postgres"}})
            return httpx.Response(204)

        client = _client_with_transport("v2", handler)
        result = await client.reply_to_question("sess_1", "frm_1", "postgres")

        self.assertTrue(result)
        self.assertEqual(
            calls,
            [
                ("GET", "/api/session/sess_1/form/frm_1"),
                ("POST", "/api/session/sess_1/form/frm_1/reply"),
            ],
        )

    async def test_v2_reject_question_deletes_form(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "DELETE")
            self.assertEqual(request.url.path, "/api/session/sess_1/form/frm_1")
            return httpx.Response(200, json={"data": {"ok": True}})

        client = _client_with_transport("v2", handler)
        result = await client.reject_question("sess_1", "frm_1")
        self.assertTrue(result)


class TestUnwrap(unittest.TestCase):
    def test_v2_unwrap_passes_through_non_data_dict(self):
        client = OpenCodeClient(base_url="http://test", api_version="v2")
        resp = httpx.Response(200, json={"status": "ok"})
        self.assertEqual(client._unwrap(resp), {"status": "ok"})

    def test_v2_unwrap_empty_body_returns_none(self):
        client = OpenCodeClient(base_url="http://test", api_version="v2")
        resp = httpx.Response(204)
        self.assertIsNone(client._unwrap(resp))

    def test_v1_unwrap_returns_bare_body(self):
        client = OpenCodeClient(base_url="http://test", api_version="v1")
        resp = httpx.Response(200, json={"data": "not actually an envelope"})
        self.assertEqual(client._unwrap(resp), {"data": "not actually an envelope"})


if __name__ == "__main__":
    unittest.main()
