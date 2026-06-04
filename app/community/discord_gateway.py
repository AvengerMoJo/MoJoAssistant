"""Discord community assistant gateway (safe-by-default baseline).

This module intentionally keeps runtime dependencies optional:
- If `discord.py` is not installed, import still works.
- `run_bot()` / `start_bot_async()` will fail with a clear error message.

Lifecycle integration:
- Standalone: `run_bot()` blocks the calling thread (for scripts/run_discord_bot.py)
- Managed:    `start_bot_async()` returns a coroutine for asyncio.create_task()
              Used by http.py startup_event when ENABLE_DISCORD_BOT=true
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def _sanitize_message(content: str, max_len: int = 2000) -> str:
    text = (content or "").strip()
    # Block obvious command-style attempts from being treated as normal chat.
    if text.startswith(("!sudo", "/sudo", "!exec", "/exec")):
        return ""
    if len(text) > max_len:
        text = text[:max_len]
    return text


@dataclass
class DiscordCommunityConfig:
    token: str
    role_id: str = "community_host"
    mention_only: bool = True
    max_prompt_chars: int = 2000

    @classmethod
    def from_env(cls) -> "DiscordCommunityConfig":
        token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
        if not token:
            raise ValueError("DISCORD_BOT_TOKEN is required")
        role_id = os.getenv("DISCORD_COMMUNITY_ROLE_ID", "community_host").strip() or "community_host"
        mention_only = os.getenv("DISCORD_MENTION_ONLY", "true").lower() in ("1", "true", "yes")
        max_prompt_chars = int(os.getenv("DISCORD_MAX_PROMPT_CHARS", "2000"))
        return cls(
            token=token,
            role_id=role_id,
            mention_only=mention_only,
            max_prompt_chars=max_prompt_chars,
        )


class CommunityAssistantService:
    """Bridges community messages to MoJo role chat sessions."""

    def __init__(self, role_id: str = "community_host") -> None:
        self.role_id = role_id
        self._sessions: Dict[str, str] = {}  # channel_id -> session_id
        self._resource_manager = None

    def _get_resource_manager(self):
        if self._resource_manager is None:
            try:
                from app.scheduler.resource_pool import ResourceManager
                self._resource_manager = ResourceManager()
            except Exception as e:
                logger.warning(f"[discord_gateway] could not load ResourceManager: {e}")
        return self._resource_manager

    async def ask(self, channel_id: str, user_message: str) -> str:
        message = _sanitize_message(user_message)
        if not message:
            return "I can only help with project-support questions in normal chat format."

        from app.scheduler.role_chat import RoleChatSession

        session_id: Optional[str] = self._sessions.get(channel_id)
        role_chat = RoleChatSession(role_id=self.role_id, session_id=session_id)
        result = await role_chat.exchange(message, resource_manager=self._get_resource_manager())
        self._sessions[channel_id] = role_chat.session_id
        return result.get("response") or result.get("error") or "No response."


def _build_client(config: DiscordCommunityConfig):
    """Build and wire a discord.Client for the given config. Returns (client,)."""
    import discord  # type: ignore

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    service = CommunityAssistantService(role_id=config.role_id)

    @client.event
    async def on_ready() -> None:
        logger.info(f"[discord_gateway] ready as {client.user}")

    @client.event
    async def on_message(message: "discord.Message") -> None:
        if message.author.bot:
            return
        if config.mention_only and client.user and client.user not in message.mentions:
            return

        content = message.content
        if client.user:
            content = content.replace(f"<@{client.user.id}>", "").strip()

        content = _sanitize_message(content, max_len=config.max_prompt_chars)
        if not content:
            return

        async with message.channel.typing():
            try:
                answer = await service.ask(str(message.channel.id), content)
            except Exception as e:
                logger.error(f"[discord_gateway] error answering message: {e}")
                answer = (
                    "I hit an internal issue while answering. "
                    "Please try again, or ask a maintainer to review."
                )
        await message.reply(answer[:2000])

    return client


async def start_bot_async(config: Optional[DiscordCommunityConfig] = None) -> None:
    """Asyncio-native bot entry point — use with asyncio.create_task().

    Called by http.py startup_event when ENABLE_DISCORD_BOT=true.
    Reconnects automatically on disconnect (discord.py default behaviour).
    """
    if config is None:
        config = DiscordCommunityConfig.from_env()

    try:
        import discord  # type: ignore  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "discord.py is required. Install with: pip install 'discord.py>=2.3'"
        ) from exc

    client = _build_client(config)
    try:
        await client.start(config.token)
    except asyncio.CancelledError:
        await client.close()
        logger.info("[discord_gateway] bot stopped")


def run_bot(config: Optional[DiscordCommunityConfig] = None) -> None:
    """Blocking entry point for standalone script (scripts/run_discord_bot.py).

    Requires `discord.py` (pip install discord.py>=2.3).
    """
    if config is None:
        config = DiscordCommunityConfig.from_env()

    try:
        import discord  # type: ignore  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "discord.py is required. Install with: pip install 'discord.py>=2.3'"
        ) from exc

    client = _build_client(config)
    client.run(config.token)
