"""Tests for WeComMessengerAdapter (app/mcp/adapters/messenger/wecom.py).

No live WeCom account exists yet (registration is a separate, ongoing
process) so all HTTP calls are mocked, following the same pattern as
tests/unit/test_network_provider.py mocking subprocess.run for the
headscale CLI.
"""
import asyncio
import unittest
from unittest.mock import patch

from app.mcp.adapters.messenger.wecom import WeComMessengerAdapter
from app.mcp.adapters.messenger.wecom_crypto import WeComCrypto

_AES_KEY = "jWmYm7qr5nMoAUwZRjGtBxmz3KA1tkAj3ykkR6q2B2C"


def _config(**overrides):
    cfg = {
        "corp_id": "wwtestcorp",
        "agent_id": "1000002",
        "secret": "sekret",
        "token": "QDG6eK",
        "encoding_aes_key": _AES_KEY,
        "to_user": "alex",
    }
    cfg.update(overrides)
    return cfg


class TestReadiness(unittest.TestCase):
    def test_not_ready_without_credentials(self):
        adapter = WeComMessengerAdapter("wecom", {})
        self.assertFalse(adapter._ready())
        self.assertIsNone(adapter._crypto)

    def test_ready_with_full_config(self):
        adapter = WeComMessengerAdapter("wecom", _config())
        self.assertTrue(adapter._ready())
        self.assertIsNotNone(adapter._crypto)

    def test_ready_for_send_without_crypto(self):
        # corp_id/agent_id/secret enough to send; token/aes_key only needed
        # for the inbound callback webhook.
        cfg = _config()
        del cfg["token"]
        del cfg["encoding_aes_key"]
        adapter = WeComMessengerAdapter("wecom", cfg)
        self.assertTrue(adapter._ready())
        self.assertIsNone(adapter._crypto)


class TestSendNotification(unittest.TestCase):
    def setUp(self):
        self.adapter = WeComMessengerAdapter("wecom", _config())

    def test_send_notification_calls_message_send_with_token(self):
        calls = []

        async def fake_get(url, timeout=10):
            calls.append(("GET", url))
            return {"errcode": 0, "access_token": "tok123", "expires_in": 7200}

        async def fake_post(url, payload, timeout=10):
            calls.append(("POST", url, payload))
            return {"errcode": 0}

        with patch.object(self.adapter, "_http_get", side_effect=fake_get), \
             patch.object(self.adapter, "_http_post_json", side_effect=fake_post):
            asyncio.run(self.adapter.send_notification("Task failed", "details here", "error"))

        self.assertEqual(calls[0][0], "GET")
        self.assertIn("gettoken", calls[0][1])
        self.assertEqual(calls[1][0], "POST")
        self.assertIn("access_token=tok123", calls[1][1])
        payload = calls[1][2]
        self.assertEqual(payload["touser"], "alex")
        self.assertEqual(payload["agentid"], "1000002")
        self.assertIn("Task failed", payload["text"]["content"])

    def test_access_token_is_cached_across_calls(self):
        get_calls = []

        async def fake_get(url, timeout=10):
            get_calls.append(url)
            return {"errcode": 0, "access_token": "tok123", "expires_in": 7200}

        async def fake_post(url, payload, timeout=10):
            return {"errcode": 0}

        with patch.object(self.adapter, "_http_get", side_effect=fake_get), \
             patch.object(self.adapter, "_http_post_json", side_effect=fake_post):
            asyncio.run(self.adapter.send_notification("a", "b"))
            asyncio.run(self.adapter.send_notification("c", "d"))

        self.assertEqual(len(get_calls), 1)  # second send reused cached token

    def test_not_ready_skips_http_entirely(self):
        adapter = WeComMessengerAdapter("wecom", {})
        with patch.object(adapter, "_http_get") as mock_get:
            asyncio.run(adapter.send_notification("x", "y"))
            mock_get.assert_not_called()


class TestSendHitl(unittest.TestCase):
    def setUp(self):
        self.adapter = WeComMessengerAdapter("wecom", _config())

    def test_send_hitl_records_pending_and_includes_choices(self):
        async def fake_get(url, timeout=10):
            return {"errcode": 0, "access_token": "tok", "expires_in": 7200}

        sent = {}

        async def fake_post(url, payload, timeout=10):
            sent["payload"] = payload
            return {"errcode": 0}

        with patch.object(self.adapter, "_http_get", side_effect=fake_get), \
             patch.object(self.adapter, "_http_post_json", side_effect=fake_post):
            asyncio.run(
                self.adapter.send_hitl("task-1", "Proceed?", ["yes", "no"], {"role_id": "popo"})
            )

        self.assertIn("task-1", sent["payload"]["text"]["content"])
        self.assertIn("yes", sent["payload"]["text"]["content"])
        self.assertEqual(self.adapter._pending["alex"], ("task-1", ["yes", "no"]))

    def test_send_failure_does_not_record_pending(self):
        async def fake_get(url, timeout=10):
            return {"errcode": 0, "access_token": "tok", "expires_in": 7200}

        async def fake_post(url, payload, timeout=10):
            return {"errcode": 40001, "errmsg": "invalid credential"}

        with patch.object(self.adapter, "_http_get", side_effect=fake_get), \
             patch.object(self.adapter, "_http_post_json", side_effect=fake_post):
            asyncio.run(self.adapter.send_hitl("task-2", "Proceed?", []))

        self.assertNotIn("alex", self.adapter._pending)


class TestInboundCallback(unittest.TestCase):
    def setUp(self):
        self.adapter = WeComMessengerAdapter("wecom", _config())
        self.crypto = WeComCrypto("QDG6eK", _AES_KEY, "wwtestcorp")
        self.adapter._pending["alex"] = ("task-9", ["yes", "no"])

        self.resumed = []
        self.adapter._scheduler = _FakeScheduler(self.resumed)

    def _encrypted_text_message(self, content: str, from_user: str = "alex"):
        inner_xml = (
            f"<xml><ToUserName><![CDATA[wwtestcorp]]></ToUserName>"
            f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
            f"<MsgType><![CDATA[text]]></MsgType>"
            f"<Content><![CDATA[{content}]]></Content></xml>"
        )
        encrypted_b64, sig = self.crypto.encrypt_message(inner_xml, "1000", "999")
        body_xml = f"<xml><ToUserName><![CDATA[wwtestcorp]]></ToUserName><Encrypt><![CDATA[{encrypted_b64}]]></Encrypt></xml>"
        return sig, body_xml

    def test_verify_url_returns_decrypted_echostr(self):
        echostr = "echo-content-123"
        encrypted_b64, sig = self.crypto.encrypt_message(echostr, "1000", "999")
        result = self.adapter.verify_url(sig, "1000", "999", encrypted_b64)
        self.assertEqual(result, echostr)

    def test_valid_text_reply_resumes_pending_task(self):
        sig, body_xml = self._encrypted_text_message("yes")
        self.adapter.handle_callback(sig, "1000", "999", body_xml)
        self.assertEqual(self.resumed, [("task-9", "yes")])
        self.assertNotIn("alex", self.adapter._pending)

    def test_tampered_signature_is_dropped_silently(self):
        _sig, body_xml = self._encrypted_text_message("yes")
        self.adapter.handle_callback("0" * 40, "1000", "999", body_xml)
        self.assertEqual(self.resumed, [])
        self.assertIn("alex", self.adapter._pending)  # untouched

    def test_no_pending_hitl_is_ignored(self):
        self.adapter._pending.clear()
        sig, body_xml = self._encrypted_text_message("yes")
        self.adapter.handle_callback(sig, "1000", "999", body_xml)
        self.assertEqual(self.resumed, [])

    def test_missing_crypto_config_is_a_noop(self):
        adapter = WeComMessengerAdapter("wecom", {})
        adapter._scheduler = _FakeScheduler([])
        adapter.handle_callback("sig", "1000", "999", "<xml></xml>")  # must not raise


class _FakeScheduler:
    def __init__(self, sink):
        self._sink = sink

    def resume_task_with_reply(self, task_id, reply):
        self._sink.append((task_id, reply))


if __name__ == "__main__":
    unittest.main()
