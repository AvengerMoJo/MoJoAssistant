"""WeCom (企业微信 / WeChat Work) MessengerAdapter.

Sends HITL questions and notifications to a WeCom custom-app conversation
(group chat or 1:1) via the `message/send` API, and receives replies through
WeCom's signed+encrypted callback webhook (mounted by
app/mcp/routers/wecom.py at /api/wecom/callback).

Requires a WeCom "custom app" (企业内部应用), not just a group robot webhook
— only the custom-app path gets inbound message callbacks, which is what
makes replies possible at all.

Config (notifications_config.json "messengers" section):
  {
    "messengers": {
      "wecom": {
        "enabled": true,
        "corp_id": "...",           // or WECOM_CORP_ID
        "agent_id": "...",          // or WECOM_AGENT_ID
        "secret": "...",            // or WECOM_SECRET
        "token": "...",             // or WECOM_TOKEN (callback signing)
        "encoding_aes_key": "...",  // or WECOM_ENCODING_AES_KEY (43 chars)
        "to_user": "@all"           // touser recipient, or a specific userid
      }
    }
  }

No credentials exist yet at implementation time (corporate WeCom account
registration is a separate, longer-running process) — this adapter is
written directly against WeCom's documented API/crypto spec so it's ready
to wire in once real Corp ID / Agent ID / Secret / Token / EncodingAESKey
are issued. See wecom_crypto.py for the callback signature/AES scheme.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from app.mcp.adapters.messenger.base import MessengerAdapter
from app.mcp.adapters.messenger.registry import register
from app.mcp.adapters.messenger.wecom_crypto import WeComCrypto, WeComCryptoError

logger = logging.getLogger("mojo_assistant.messenger.wecom")

_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"
_MAX_TEXT = 2048  # WeCom text message content limit


@register
class WeComMessengerAdapter(MessengerAdapter):
    """Delivers notifications and HITL questions to a WeCom custom app."""

    adapter_type = "wecom"

    def __init__(self, adapter_id: str, config: Dict[str, Any]) -> None:
        super().__init__(adapter_id, config)
        self._corp_id: str = (config.get("corp_id") or os.getenv("WECOM_CORP_ID", "")).strip()
        self._agent_id: str = str(
            config.get("agent_id") or os.getenv("WECOM_AGENT_ID", "")
        ).strip()
        self._secret: str = (config.get("secret") or os.getenv("WECOM_SECRET", "")).strip()
        self._token: str = (config.get("token") or os.getenv("WECOM_TOKEN", "")).strip()
        self._encoding_aes_key: str = (
            config.get("encoding_aes_key") or os.getenv("WECOM_ENCODING_AES_KEY", "")
        ).strip()
        self._to_user: str = config.get("to_user") or os.getenv("WECOM_TO_USER", "@all")

        self._crypto: Optional[WeComCrypto] = None
        if self._token and self._encoding_aes_key and self._corp_id:
            try:
                self._crypto = WeComCrypto(self._token, self._encoding_aes_key, self._corp_id)
            except ValueError as exc:
                logger.error("[messenger/wecom] bad encoding_aes_key: %s", exc)

        self._access_token: str = ""
        self._token_expires_at: float = 0.0
        # user_id → (task_id, choices) for the most recent HITL question sent to that user
        self._pending: Dict[str, Tuple[str, List[str]]] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self._ready():
            logger.warning(
                "[messenger/wecom] corp_id/agent_id/secret not configured. "
                "Set WECOM_CORP_ID + WECOM_AGENT_ID + WECOM_SECRET env vars "
                "or add them to notifications_config.json messengers.wecom"
            )
            return
        if not self._crypto:
            logger.warning(
                "[messenger/wecom] token/encoding_aes_key missing — outbound "
                "send will work but the callback webhook cannot verify or "
                "decrypt inbound replies"
            )
        logger.info("[messenger/wecom] started (corp_id=%s, agent_id=%s)", self._corp_id, self._agent_id)

    async def stop(self) -> None:
        logger.info("[messenger/wecom] stopped")

    def _ready(self) -> bool:
        return bool(self._corp_id and self._agent_id and self._secret)

    # ------------------------------------------------------------------
    # MessengerAdapter contract
    # ------------------------------------------------------------------

    async def send_notification(self, title: str, body: str, severity: str = "info") -> None:
        if not self._ready():
            return
        _EMOJI = {"error": "\U0001f534", "warning": "\U0001f7e1", "info": "\U0001f535"}
        emoji = _EMOJI.get(severity, "\U0001f535")
        text = f"{emoji} {title}\n\n{body}"[:_MAX_TEXT]
        await self._send_text(text)

    async def send_hitl(
        self,
        task_id: str,
        question: str,
        choices: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self._ready():
            return

        ctx = context or {}
        role_id = ctx.get("role_id", "")
        goal_preview = ctx.get("goal_preview", "") or ctx.get("description", "")
        dashboard_url = ctx.get("dashboard_url", "")

        context_lines = []
        if role_id:
            context_lines.append(f"Role: {role_id}")
        if goal_preview:
            context_lines.append(f"Goal: {goal_preview[:300]}")
        if dashboard_url:
            context_lines.append(f"Dashboard: {dashboard_url}")
        context_block = "\n".join(context_lines)

        choices_block = ""
        if choices:
            choices_block = "\n\nReply with one of: " + " | ".join(str(c) for c in choices)

        text = (
            f"\U0001f514 Agent needs your input\n\n"
            f"Task: {task_id}\n"
            + (f"{context_block}\n" if context_block else "")
            + f"\n{question}"
            + choices_block
        )[:_MAX_TEXT]

        ok = await self._send_text(text)
        if ok:
            self._pending[self._to_user] = (task_id, choices)
            logger.info("[messenger/wecom] sent HITL for task %s", task_id)

    # ------------------------------------------------------------------
    # Inbound callback (called by app/mcp/routers/wecom.py)
    # ------------------------------------------------------------------

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        """One-time GET handshake. Raises WeComCryptoError on bad signature."""
        if not self._crypto:
            raise WeComCryptoError("callback crypto not configured")
        return self._crypto.verify_url(msg_signature, timestamp, nonce, echostr)

    def handle_callback(
        self, msg_signature: str, timestamp: str, nonce: str, body_xml: str
    ) -> None:
        """POST callback. Decrypts the message and, if it's a plain-text
        reply from the owner to a pending HITL question, resumes the task.
        """
        if not self._crypto:
            logger.warning("[messenger/wecom] callback received but crypto not configured")
            return
        try:
            outer = ET.fromstring(body_xml)
            encrypted = outer.findtext("Encrypt") or ""
            if not encrypted:
                logger.warning("[messenger/wecom] callback body missing <Encrypt>")
                return
            inner_xml = self._crypto.decrypt_message(msg_signature, timestamp, nonce, encrypted)
        except WeComCryptoError as exc:
            logger.warning("[messenger/wecom] callback verify/decrypt failed: %s", exc)
            return
        except ET.ParseError as exc:
            logger.warning("[messenger/wecom] callback body not valid XML: %s", exc)
            return

        try:
            inner = ET.fromstring(inner_xml)
        except ET.ParseError as exc:
            logger.warning("[messenger/wecom] decrypted message not valid XML: %s", exc)
            return

        msg_type = inner.findtext("MsgType") or ""
        from_user = inner.findtext("FromUserName") or ""
        if msg_type != "text":
            return  # only plain-text replies are treated as HITL answers
        text = (inner.findtext("Content") or "").strip()
        if not text:
            return

        pending = self._pending.get(from_user) or (
            list(self._pending.values())[-1] if self._pending else None
        )
        if not pending:
            logger.debug("[messenger/wecom] text from %s but no pending HITL", from_user)
            return
        task_id, _choices = pending
        self._pending.pop(from_user, None)
        logger.info("[messenger/wecom] task %s answered by %s: '%s'", task_id, from_user, text)
        self.handle_response(task_id, text)

    # ------------------------------------------------------------------
    # WeCom API helpers
    # ------------------------------------------------------------------

    async def _access_token_value(self) -> str:
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token
        params = urllib.parse.urlencode({"corpid": self._corp_id, "corpsecret": self._secret})
        url = f"{_API_BASE}/gettoken?{params}"
        resp = await self._http_get(url)
        if not resp or resp.get("errcode", 0) != 0:
            logger.warning("[messenger/wecom] gettoken failed: %s", resp)
            return ""
        self._access_token = resp["access_token"]
        # Refresh a little early to avoid racing the actual expiry.
        self._token_expires_at = time.time() + max(60, int(resp.get("expires_in", 7200)) - 120)
        return self._access_token

    async def _send_text(self, text: str) -> bool:
        token = await self._access_token_value()
        if not token:
            return False
        payload = {
            "touser": self._to_user,
            "msgtype": "text",
            "agentid": self._agent_id,
            "text": {"content": text},
            "safe": 0,
        }
        resp = await self._http_post_json(
            f"{_API_BASE}/message/send?access_token={urllib.parse.quote(token)}", payload
        )
        if not resp or resp.get("errcode", 0) != 0:
            logger.warning("[messenger/wecom] message/send failed: %s", resp)
            return False
        return True

    async def _http_get(self, url: str, timeout: int = 10) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, lambda: _sync_get(url, timeout))
        except Exception as exc:
            logger.warning("[messenger/wecom] GET %s failed: %s", url, exc)
            return None

    async def _http_post_json(
        self, url: str, payload: Dict[str, Any], timeout: int = 10
    ) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, lambda: _sync_post_json(url, payload, timeout))
        except Exception as exc:
            logger.warning("[messenger/wecom] POST %s failed: %s", url, exc)
            return None


def _sync_get(url: str, timeout: int) -> Dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _sync_post_json(url: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))
