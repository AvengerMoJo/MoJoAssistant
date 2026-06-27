"""Telegram MessengerAdapter.

Sends HITL questions and notifications to the owner's Telegram chat via the
Bot API. Uses inline keyboard buttons for choices. Long-polls for replies.

Config (notifications_config.json "messengers" section):
  {
    "messengers": {
      "telegram": {
        "enabled": true,
        "bot_token": "...",   // or set TELEGRAM_BOT_TOKEN env var
        "chat_id":   "..."    // or set TELEGRAM_OWNER_CHAT_ID env var
      }
    }
  }

No extra Python packages required — uses urllib + asyncio.run_in_executor.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from app.mcp.adapters.messenger.base import MessengerAdapter
from app.mcp.adapters.messenger.registry import register

logger = logging.getLogger("mojo_assistant.messenger.telegram")

_MAX_TEXT = 4096          # Telegram message character limit
_BUTTONS_PER_ROW = 2      # inline keyboard layout


@register
class TelegramMessengerAdapter(MessengerAdapter):
    """Delivers notifications and HITL questions to a Telegram chat."""

    adapter_type = "telegram"

    def __init__(self, adapter_id: str, config: Dict[str, Any]) -> None:
        super().__init__(adapter_id, config)
        self._bot_token: str = (
            config.get("bot_token") or os.getenv("TELEGRAM_BOT_TOKEN", "")
        ).strip()
        self._chat_id: str = (
            config.get("chat_id") or os.getenv("TELEGRAM_OWNER_CHAT_ID", "")
        ).strip()
        # message_id → (task_id, choices) for active HITL questions
        self._pending: Dict[int, Tuple[str, List[str]]] = {}
        self._poll_task: Optional[asyncio.Task] = None
        self._poll_offset: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self._bot_token or not self._chat_id:
            logger.warning(
                "[messenger/telegram] bot_token or chat_id not configured. "
                "Set TELEGRAM_BOT_TOKEN + TELEGRAM_OWNER_CHAT_ID env vars "
                "or add them to notifications_config.json messengers.telegram"
            )
            return
        self._poll_task = asyncio.create_task(
            self._poll_loop(), name="telegram-messenger-poll"
        )
        logger.info("[messenger/telegram] started (chat_id=%s)", self._chat_id)

    async def stop(self) -> None:
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("[messenger/telegram] stopped")

    # ------------------------------------------------------------------
    # MessengerAdapter contract
    # ------------------------------------------------------------------

    async def send_notification(
        self, title: str, body: str, severity: str = "info"
    ) -> None:
        if not self._ready():
            return
        _EMOJI = {"error": "\U0001f534", "warning": "\U0001f7e1", "info": "\U0001f535"}
        emoji = _EMOJI.get(severity, "\U0001f535")
        text = f"{emoji} *{title}*\n\n{body}"[:_MAX_TEXT]
        await self._api("sendMessage", {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "Markdown",
        })

    async def send_hitl(
        self, task_id: str, question: str, choices: List[str]
    ) -> None:
        if not self._ready():
            return

        text = (
            f"\U0001f514 *Agent needs your input*\n\n"
            f"*Task:* `{task_id}`\n\n"
            f"{question}"
        )[:_MAX_TEXT]

        payload: Dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }

        if choices:
            rows = []
            for i in range(0, len(choices), _BUTTONS_PER_ROW):
                row = [
                    {
                        "text": str(c),
                        # callback_data is limited to 64 bytes; truncate choice if needed
                        "callback_data": f"hitl:{task_id}:{str(c)}"[:64],
                    }
                    for c in choices[i : i + _BUTTONS_PER_ROW]
                ]
                rows.append(row)
            payload["reply_markup"] = {"inline_keyboard": rows}

        resp = await self._api("sendMessage", payload)
        if resp and resp.get("ok"):
            msg_id = resp["result"]["message_id"]
            self._pending[msg_id] = (task_id, choices)
            logger.info(
                "[messenger/telegram] sent HITL for task %s (msg_id=%s)",
                task_id, msg_id,
            )
        else:
            logger.warning(
                "[messenger/telegram] sendMessage failed for task %s: %s",
                task_id, resp,
            )

    # ------------------------------------------------------------------
    # Update polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Long-poll Telegram for button callbacks and free-text replies."""
        backoff = 1
        while True:
            try:
                resp = await self._api(
                    "getUpdates",
                    {
                        "offset": self._poll_offset,
                        "timeout": 30,
                        "allowed_updates": ["message", "callback_query"],
                    },
                    http_timeout=35,
                )
                if resp and resp.get("ok"):
                    for update in resp.get("result", []):
                        self._poll_offset = update["update_id"] + 1
                        await self._handle_update(update)
                    backoff = 1
                else:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("[messenger/telegram] poll error: %s", exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _handle_update(self, update: Dict[str, Any]) -> None:
        # Inline keyboard button click
        cb = update.get("callback_query")
        if cb:
            data = cb.get("data", "")
            if data.startswith("hitl:"):
                parts = data.split(":", 2)
                if len(parts) == 3:
                    _, task_id, choice = parts
                    # Acknowledge immediately so Telegram removes the spinner
                    await self._api("answerCallbackQuery", {"callback_query_id": cb["id"]})
                    # Remove the inline keyboard from the original message
                    orig = cb.get("message", {})
                    if orig:
                        await self._api("editMessageReplyMarkup", {
                            "chat_id": self._chat_id,
                            "message_id": orig["message_id"],
                            "reply_markup": {"inline_keyboard": []},
                        })
                    self._pending.pop(orig.get("message_id"), None)
                    logger.info(
                        "[messenger/telegram] task %s answered via button: '%s'",
                        task_id, choice,
                    )
                    self.handle_response(task_id, choice)
            return

        # Plain text reply from the owner chat
        msg = update.get("message", {})
        text = (msg.get("text") or "").strip()
        if not text:
            return
        if str(msg.get("chat", {}).get("id", "")) != str(self._chat_id):
            return  # message not from owner chat
        if self._pending:
            # Route to the most recently pending HITL task
            task_id, _ = list(self._pending.values())[-1]
            logger.info(
                "[messenger/telegram] task %s answered via text: '%s'", task_id, text
            )
            self.handle_response(task_id, text)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _ready(self) -> bool:
        return bool(self._bot_token and self._chat_id)

    async def _api(
        self,
        method: str,
        payload: Dict[str, Any],
        http_timeout: int = 10,
    ) -> Optional[Dict[str, Any]]:
        """Call a Telegram Bot API method asynchronously."""
        url = f"https://api.telegram.org/bot{self._bot_token}/{method}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                None,
                lambda: _sync_http(req, http_timeout),
            )
        except Exception as exc:
            logger.warning("[messenger/telegram] %s failed: %s", method, exc)
            return None


def _sync_http(req: urllib.request.Request, timeout: int) -> Dict[str, Any]:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))
