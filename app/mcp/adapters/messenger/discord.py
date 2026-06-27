"""Discord MessengerAdapter.

Wraps the existing DiscordHITLAdapter so Discord works through the unified
MessengerAdapter SDK without rewriting the gateway integration.

Config (notifications_config.json "messengers" section):
  {
    "messengers": {
      "discord": {
        "enabled": true,
        "channel_id": "123456789"   // optional — falls back to DISCORD_OWNER_CHANNEL_ID env
      }
    }
  }

Requires:
  DISCORD_BOT_TOKEN        — bot token (shared with community bot)
  DISCORD_OWNER_CHANNEL_ID — private channel for owner notifications
  ENABLE_DISCORD_BOT=true  — the gateway bot must be running
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.mcp.adapters.messenger.base import MessengerAdapter
from app.mcp.adapters.messenger.registry import register


@register
class DiscordMessengerAdapter(MessengerAdapter):
    """MessengerAdapter wrapper around DiscordHITLAdapter."""

    adapter_type = "discord"

    def __init__(self, adapter_id: str, config: Dict[str, Any]) -> None:
        super().__init__(adapter_id, config)
        from app.mcp.adapters.hitl.discord import DiscordHITLAdapter
        self._impl = DiscordHITLAdapter(adapter_id=adapter_id, config=config)

    def set_scheduler(self, scheduler: Any) -> None:
        super().set_scheduler(scheduler)
        self._impl.set_scheduler(scheduler)

    async def start(self) -> None:
        await self._impl.start()

    async def stop(self) -> None:
        await self._impl.stop()

    async def send_notification(
        self, title: str, body: str, severity: str = "info"
    ) -> None:
        await self._impl.send_notification(title, body, severity)

    async def send_hitl(
        self, task_id: str, question: str, choices: List[str]
    ) -> None:
        await self._impl.send_hitl(task_id, question, choices)
