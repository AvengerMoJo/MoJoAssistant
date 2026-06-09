"""Discord Owner Push Adapter

Delivers MoJo events to the owner's private Discord channel.
Supports bidirectional HITL: owner can click buttons or type replies.

Config example (notifications_config.json):
  {
    "id": "discord_owner",
    "type": "discord_owner",
    "enabled": true,
    "filter": { "notify_user_only": true }
  }

Requires:
  DISCORD_BOT_TOKEN        — bot token (shared with community bot)
  DISCORD_OWNER_CHANNEL_ID — private channel ID for owner notifications
  ENABLE_DISCORD_BOT=true  — bot must be running
"""

import logging
from typing import Any, Dict

from app.mcp.adapters.push.base import PushAdapter

logger = logging.getLogger(__name__)


class DiscordOwnerAdapter(PushAdapter):
    adapter_type = "discord_owner"

    async def dispatch(self, event: Dict[str, Any]) -> None:
        from app.community.discord_gateway import owner_notifier

        if not owner_notifier._client:
            logger.debug("[push/discord_owner] client not ready — skipping event %s", event.get("event_type"))
            return

        event_type = event.get("event_type", "")

        if event_type == "task_waiting_for_input":
            task_id = event.get("task_id", "")
            question = event.get("question") or event.get("title") or "Owner input required"
            choices = event.get("choices") or []
            if not task_id:
                logger.warning("[push/discord_owner] task_waiting_for_input with no task_id")
                return
            await owner_notifier.send_hitl(
                task_id=task_id,
                question=question,
                choices=choices,
            )
        else:
            await owner_notifier.send_notification(
                title=self._format_title(event),
                body=self._format_body(event),
                severity=event.get("severity", "info"),
            )
