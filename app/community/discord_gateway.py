"""Discord community assistant gateway (safe-by-default baseline).

This module intentionally keeps runtime dependencies optional:
- If `discord.py` is not installed, import still works.
- `run_bot()` / `start_bot_async()` will fail with a clear error message.

Lifecycle integration:
- Standalone: `run_bot()` blocks the calling thread (for scripts/run_discord_bot.py)
- Managed:    `start_bot_async()` returns a coroutine for asyncio.create_task()
              Used by http.py startup_event when ENABLE_DISCORD_BOT=true

Owner HITL channel:
- Set DISCORD_OWNER_CHANNEL_ID to a private Discord channel ID.
- MoJo posts HITL proposals there with Approve/Reject buttons.
- Owner can click buttons OR type a free-text reply in the channel.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(f"mojo_assistant.{__name__}")


# ---------------------------------------------------------------------------
# Owner HITL notifier — singleton populated when the Discord client connects
# ---------------------------------------------------------------------------

class DiscordOwnerNotifier:
    """Sends HITL proposals to the owner's private Discord channel.

    Lifecycle:
      1. http.py calls owner_notifier.set_scheduler(scheduler) at startup.
      2. _build_client() calls owner_notifier.set_client(client) in on_ready.
      3. DiscordOwnerAdapter.dispatch() calls send_hitl() / send_notification().
      4. Button clicks / channel messages call handle_interaction() / handle_message().
    """

    def __init__(self) -> None:
        self._client: Any = None
        self._channel_id: Optional[int] = _owner_channel_id_from_env()
        self._scheduler: Any = None
        # message_id -> (task_id, choices)
        self._pending: Dict[int, Tuple[str, List[str]]] = {}

    def set_client(self, client: Any) -> None:
        self._client = client
        logger.info("[discord_owner] client set, owner_channel_id=%s", self._channel_id)

    async def on_ready_hook(self) -> None:
        """Called directly from on_ready so we're inside the event loop."""
        await self._catchup_waiting_tasks()

    async def _catchup_waiting_tasks(self) -> None:
        """Re-notify any tasks already in WAITING_FOR_INPUT when the bot connects."""
        logger.info("[discord_owner] catch-up: running, scheduler=%s", self._scheduler is not None)
        if not self._scheduler:
            logger.warning("[discord_owner] catch-up: no scheduler set — skipping")
            return
        try:
            from app.scheduler.models import TaskStatus
            waiting = self._scheduler.queue.list_tasks(status=TaskStatus.WAITING_FOR_INPUT)
            logger.info("[discord_owner] catch-up: found %d waiting task(s)", len(waiting))
            for task in waiting:
                if not task.pending_question:
                    logger.info("[discord_owner] catch-up: task %s has no pending_question", task.id)
                    continue
                choices = task.config.get("pending_choices") or []
                if task.id not in {tid for tid, _ in self._pending.values()}:
                    logger.info("[discord_owner] catch-up: notifying task %s", task.id)
                    await self.send_hitl(task.id, task.pending_question, choices)
                else:
                    logger.info("[discord_owner] catch-up: task %s already pending", task.id)
        except Exception as exc:
            logger.warning("[discord_owner] catch-up failed: %s", exc, exc_info=True)

    def set_scheduler(self, scheduler: Any) -> None:
        self._scheduler = scheduler

    async def _get_channel(self) -> Any:
        if not self._client or not self._channel_id:
            return None
        ch = self._client.get_channel(self._channel_id)
        if ch is None:
            try:
                ch = await self._client.fetch_channel(self._channel_id)
            except Exception as exc:
                logger.warning("[discord_owner] cannot fetch channel %s: %s", self._channel_id, exc)
        return ch

    async def send_hitl(
        self,
        task_id: str,
        question: str,
        choices: List[str],
    ) -> None:
        """Post a HITL proposal to the owner channel with button choices."""
        ch = await self._get_channel()
        if ch is None:
            logger.warning("[discord_owner] owner channel not available — cannot send HITL")
            return
        try:
            import discord  # type: ignore
            embed = discord.Embed(
                title="Owner Action Required",
                description=question[:4096],
                color=discord.Color.orange(),
            )
            embed.set_footer(text=f"task: {task_id}")
            view = _HITLView(task_id=task_id, choices=choices, notifier=self)
            msg = await ch.send(embed=embed, view=view)
            self._pending[msg.id] = (task_id, choices)
            logger.info("[discord_owner] HITL posted (task=%s, msg=%s)", task_id, msg.id)
        except Exception as exc:
            logger.error("[discord_owner] failed to send HITL: %s", exc)

    async def send_notification(self, title: str, body: str, severity: str = "info") -> None:
        """Post a plain informational notification to the owner channel."""
        ch = await self._get_channel()
        if ch is None:
            return
        try:
            import discord  # type: ignore
            color_map = {
                "info": discord.Color.blue(),
                "warning": discord.Color.yellow(),
                "error": discord.Color.red(),
                "critical": discord.Color.dark_red(),
            }
            embed = discord.Embed(
                title=title,
                description=body[:4096],
                color=color_map.get(severity, discord.Color.blue()),
            )
            await ch.send(embed=embed)
        except Exception as exc:
            logger.error("[discord_owner] failed to send notification: %s", exc)

    async def handle_button_click(self, task_id: str, choice: str) -> None:
        """Route a button click to the scheduler as a HITL reply."""
        self._resolve_pending_by_task(task_id)
        self._resume(task_id, choice)

    async def handle_owner_message(self, message: Any) -> None:
        """Route a free-text message in the owner channel to the pending HITL task."""
        if not self._pending:
            await message.reply("No pending HITL task right now.", mention_author=False)
            return
        # Pick the most recent pending task
        latest_msg_id = max(self._pending)
        task_id, _ = self._pending[latest_msg_id]
        self._resolve_pending_by_task(task_id)
        self._resume(task_id, message.content.strip())
        await message.add_reaction("✅")

    def _resolve_pending_by_task(self, task_id: str) -> None:
        self._pending = {
            k: v for k, v in self._pending.items() if v[0] != task_id
        }

    def _resume(self, task_id: str, reply: str) -> None:
        if not self._scheduler:
            logger.warning("[discord_owner] scheduler not set — cannot resume task %s", task_id)
            return
        try:
            self._scheduler.resume_task_with_reply(task_id, reply)
            logger.info("[discord_owner] resumed task %s with reply '%s'", task_id, reply)
        except Exception as exc:
            logger.error("[discord_owner] failed to resume task %s: %s", task_id, exc)


def _owner_channel_id_from_env() -> Optional[int]:
    raw = os.getenv("DISCORD_OWNER_CHANNEL_ID", "").strip()
    if raw.isdigit():
        return int(raw)
    return None


class _HITLView:
    """discord.ui.View with Approve/Reject-style buttons for HITL tasks.

    Constructed lazily so discord.py import is not required at module load.
    """

    def __new__(cls, task_id: str, choices: List[str], notifier: DiscordOwnerNotifier):
        try:
            import discord  # type: ignore

            class _View(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=None)
                    for choice in choices[:5]:
                        self.add_item(_HITLButton(task_id=task_id, choice=choice, notifier=notifier))

            return _View()
        except Exception:
            return None  # discord.py not available — send without view


class _HITLButton:
    """Lazy discord.ui.Button factory for HITL choice buttons."""

    def __new__(cls, task_id: str, choice: str, notifier: DiscordOwnerNotifier):
        import discord  # type: ignore

        # custom_id max 100 chars
        cid = f"hitl:{task_id[:60]}:{choice[:30]}"

        class _Button(discord.ui.Button):
            def __init__(self):
                style = (
                    discord.ButtonStyle.success if choice.lower() in ("approve", "accept", "yes")
                    else discord.ButtonStyle.danger if choice.lower() in ("reject", "no", "deny")
                    else discord.ButtonStyle.primary
                )
                super().__init__(label=choice, style=style, custom_id=cid)
                self._notifier = notifier
                self._task_id = task_id
                self._choice = choice

            async def callback(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True)
                await self._notifier.handle_button_click(self._task_id, self._choice)
                await interaction.followup.send(
                    f"Replied **{self._choice}** to task `{self._task_id}`.",
                    ephemeral=True,
                )

        return _Button()


# Module-level singleton — populated by _build_client() and http.py
owner_notifier = DiscordOwnerNotifier()


def _discord_sessions_dir() -> Path:
    from app.config.paths import get_memory_subpath
    return Path(get_memory_subpath("discord_sessions"))


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
        self._load_sessions_from_disk()

    def _load_sessions_from_disk(self) -> None:
        try:
            sessions_dir = _discord_sessions_dir()
            if not sessions_dir.exists():
                return
            for f in sessions_dir.glob("channel_*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    self._sessions[data["channel_id"]] = data["session_id"]
                except Exception:
                    pass
            if self._sessions:
                logger.info(f"[discord_gateway] restored {len(self._sessions)} channel session(s)")
        except Exception as e:
            logger.warning(f"[discord_gateway] could not load sessions from disk: {e}")

    def _save_session_to_disk(self, channel_id: str, session_id: str) -> None:
        try:
            sessions_dir = _discord_sessions_dir()
            sessions_dir.mkdir(parents=True, exist_ok=True)
            (sessions_dir / f"channel_{channel_id}.json").write_text(
                json.dumps({
                    "channel_id": channel_id,
                    "session_id": session_id,
                    "saved_at": datetime.now().isoformat(),
                }),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"[discord_gateway] could not save session to disk: {e}")

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
        self._save_session_to_disk(channel_id, role_chat.session_id)
        return result.get("response") or result.get("error") or "No response."


def _build_client(config: DiscordCommunityConfig):
    """Build and wire a discord.Client for the given config. Returns the client."""
    import discord  # type: ignore

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    service = CommunityAssistantService(role_id=config.role_id)

    @client.event
    async def on_ready() -> None:
        logger.info(f"[discord_gateway] ready as {client.user}")
        owner_notifier.set_client(client)
        await owner_notifier.on_ready_hook()

    @client.event
    async def on_message(message: "discord.Message") -> None:
        if message.author.bot:
            return

        # Owner channel — route to HITL handler, not community assistant
        if (
            owner_notifier._channel_id is not None
            and message.channel.id == owner_notifier._channel_id
        ):
            await owner_notifier.handle_owner_message(message)
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
    except Exception as exc:
        logger.error("[discord_gateway] bot task failed: %s", exc, exc_info=True)


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
