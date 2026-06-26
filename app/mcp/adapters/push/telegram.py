"""Telegram Push Adapter

Delivers events to a Telegram chat via Bot API.

Config example:
  {
    "id": "telegram_owner",
    "type": "telegram",
    "enabled": true,
    "filter": { "notify_user_only": true }
  }

Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables.
"""

import json
import logging
import os
from typing import Any, Dict

from app.mcp.adapters.push.base import PushAdapter

logger = logging.getLogger(__name__)


_SEVERITY_ICON = {
    "info": "\u2139\ufe0f",
    "warning": "\u26a0\ufe0f",
    "error": "\ud83d\udea8",
    "critical": "\ud83d\udea8",
}


class TelegramAdapter(PushAdapter):
    adapter_type = "telegram"

    def __init__(self, adapter_id: str, config: Dict[str, Any], event_log):
        super().__init__(adapter_id, config, event_log)
        self._bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    async def dispatch(self, event: Dict[str, Any]) -> None:
        if not self._bot_token or not self._chat_id:
            logger.warning("[push/%s] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set", self.adapter_id)
            return

        severity = event.get("severity", "info")
        icon = _SEVERITY_ICON.get(severity, "")
        title = self._format_title(event)
        body = self._format_body(event)

        text = f"{icon} *{title}*\n{body}" if icon else f"*{title}*\n{body}"

        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        data = json.dumps(payload).encode("utf-8")

        import urllib.request
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._send, req)

        logger.debug("[push/%s] dispatched %s", self.adapter_id, event.get("event_type"))

    def _send(self, req) -> None:
        import urllib.request
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                if not result.get("ok"):
                    raise RuntimeError(f"Telegram API error: {result}")
        except Exception as exc:
            raise RuntimeError(f"Telegram delivery failed: {exc}") from exc
