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

logger = logging.getLogger(f"mojo_assistant.{__name__}")


class DiscordOwnerAdapter(PushAdapter):
    adapter_type = "discord_owner"

    async def _run(self) -> None:
        """Wait for the Discord client to connect before starting the poll loop.

        Catch-up for WAITING_FOR_INPUT tasks is handled by
        DiscordOwnerNotifier._catchup_waiting_tasks() called from on_ready.
        """
        import asyncio
        from app.community.discord_gateway import owner_notifier
        while owner_notifier._client is None:
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                return
        logger.info("[push/discord_owner] client ready — starting poll loop")
        await super()._run()

    async def dispatch(self, event: Dict[str, Any]) -> None:
        from app.community.discord_gateway import owner_notifier

        if not owner_notifier._client:
            logger.debug("[push/discord_owner] client not ready — skipping %s", event.get("event_type"))
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
