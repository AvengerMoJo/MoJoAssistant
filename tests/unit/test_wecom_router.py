"""Tests for the WeCom callback HTTP router (app/mcp/routers/wecom.py).

Verifies the router correctly delegates to whatever adapter instance the
shared MessengerManager exposes as adapter_type "wecom", and fails safely
(503, not a crash) when no such adapter is configured -- the expected
state until the real WeCom account exists.
"""
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.mcp.routers.wecom import router
from app.mcp.adapters.messenger.wecom_crypto import WeComCryptoError


class TestWeComRouter(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_get_verify_returns_503_when_no_adapter_configured(self):
        with patch("app.mcp.routers.wecom._find_adapter", return_value=None):
            resp = self.client.get("/api/wecom/callback", params={
                "msg_signature": "s", "timestamp": "1", "nonce": "n", "echostr": "e",
            })
        self.assertEqual(resp.status_code, 503)

    def test_get_verify_returns_plaintext_on_success(self):
        adapter = MagicMock()
        adapter.verify_url.return_value = "decrypted-echo"
        with patch("app.mcp.routers.wecom._find_adapter", return_value=adapter):
            resp = self.client.get("/api/wecom/callback", params={
                "msg_signature": "s", "timestamp": "1", "nonce": "n", "echostr": "e",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "decrypted-echo")
        adapter.verify_url.assert_called_once_with("s", "1", "n", "e")

    def test_get_verify_returns_403_on_bad_signature(self):
        adapter = MagicMock()
        adapter.verify_url.side_effect = WeComCryptoError("bad sig")
        with patch("app.mcp.routers.wecom._find_adapter", return_value=adapter):
            resp = self.client.get("/api/wecom/callback", params={
                "msg_signature": "s", "timestamp": "1", "nonce": "n", "echostr": "e",
            })
        self.assertEqual(resp.status_code, 403)

    def test_post_receive_returns_503_when_no_adapter_configured(self):
        with patch("app.mcp.routers.wecom._find_adapter", return_value=None):
            resp = self.client.post(
                "/api/wecom/callback?msg_signature=s&timestamp=1&nonce=n",
                content=b"<xml></xml>",
            )
        self.assertEqual(resp.status_code, 503)

    def test_post_receive_delegates_body_to_adapter_and_returns_success(self):
        adapter = MagicMock()
        with patch("app.mcp.routers.wecom._find_adapter", return_value=adapter):
            resp = self.client.post(
                "/api/wecom/callback?msg_signature=s&timestamp=1&nonce=n",
                content=b"<xml><Encrypt>abc</Encrypt></xml>",
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "success")
        adapter.handle_callback.assert_called_once_with(
            "s", "1", "n", "<xml><Encrypt>abc</Encrypt></xml>"
        )


if __name__ == "__main__":
    unittest.main()
