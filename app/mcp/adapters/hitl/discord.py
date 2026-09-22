"""Discord HITL Adapter.

Implements the HITLAdapter contract using the Discord bot already running for
community chat. The bot is owned by discord_gateway.py; this adapter registers
itself so the shared on_ready hook wires the Discord client in.

Transport lifecycle:
  start()  — registers self with discord_gateway; the bot task is started
             separately by http.py (shared with community chat)
  stop()   — unregisters; pending HITL messages remain visible in Discord
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.mcp.adapters.hitl.base import HITLAdapter

logger = logging.getLogger(f"mojo_assistant.{__name__}")


class DiscordHITLAdapter(HITLAdapter):
    """Sends HITL proposals to the owner's private Discord channel with buttons."""

    adapter_type = "discord_owner"

    def __init__(self, adapter_id: str, config: dict[str, Any]) -> None:
        super().__init__(adapter_id, config)
        self._client: Any = None
        self._channel_id: Optional[int] = self._channel_id_from_config()
        # message_id -> (task_id, choices)
        self._pending: Dict[int, Tuple[str, List[str]]] = {}

    def _channel_id_from_config(self) -> Optional[int]:
        import os
        raw = (
            self.config.get("channel_id")
            or os.getenv("DISCORD_OWNER_CHANNEL_ID", "")
        ).strip()
        return int(raw) if str(raw).isdigit() else None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        from app.community.discord_gateway import register_hitl_adapter
        register_hitl_adapter(self)
        logger.info("[hitl/discord] registered with discord_gateway (channel=%s)", self._channel_id)

    async def stop(self) -> None:
        from app.community.discord_gateway import register_hitl_adapter
        register_hitl_adapter(None)
        logger.info("[hitl/discord] unregistered from discord_gateway")

    # ------------------------------------------------------------------
    # Called by discord_gateway.on_ready
    # ------------------------------------------------------------------

    def set_client(self, client: Any) -> None:
        self._client = client
        logger.info("[hitl/discord] client set, channel_id=%s", self._channel_id)

    async def on_ready_hook(self) -> None:
        """Catch up any tasks already waiting for input when the bot connects."""
        await self._catchup_waiting_tasks()

    async def _catchup_waiting_tasks(self) -> None:
        logger.info("[hitl/discord] catch-up: running, scheduler=%s", self._scheduler is not None)
        if not self._scheduler:
            logger.warning("[hitl/discord] catch-up: no scheduler set — skipping")
            return
        try:
            from app.scheduler.models import TaskStatus
            waiting = self._scheduler.queue.list_tasks(status=TaskStatus.WAITING_FOR_INPUT)
            logger.info("[hitl/discord] catch-up: found %d waiting task(s)", len(waiting))
            for task in waiting:
                if not task.pending_question:
                    continue
                choices = task.config.get("pending_options") or task.config.get("pending_choices") or []
                if task.id not in {tid for tid, _ in self._pending.values()}:
                    logger.info("[hitl/discord] catch-up: notifying task %s", task.id)
                    await self.send_hitl(task.id, task.pending_question, choices)
        except Exception as exc:
            logger.warning("[hitl/discord] catch-up failed: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Cross-loop bridge
    # ------------------------------------------------------------------

    async def _run_on_client_loop(self, coro: Any) -> Any:
        """Run `coro` on the Discord client's own event loop and await the
        result from whatever loop/thread we're actually called on.

        The scheduler runs in its own dedicated thread with its own event
        loop (app/mcp/core/tools.py run_scheduler: loop.run_until_complete),
        separate from the loop discord.py's Client (and its aiohttp
        ClientSession) was started on. Awaiting a Discord API call directly
        from the scheduler's loop raises aiohttp's "Timeout context manager
        should be used inside a task" -- the session belongs to a different
        loop than the one actually executing the await. Found live
        2026-09-22: every ask_user HITL prompt failed to post to Discord
        with exactly this error, so nothing ever reached the owner channel
        to reply to.

        Mirrors the already-correct pattern in Scheduler.wake() (see
        app/scheduler/core.py) for the reverse direction.
        """
        target_loop = getattr(self._client, "loop", None)
        if target_loop is None:
            return await coro
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if current_loop is target_loop:
            return await coro
        future = asyncio.run_coroutine_threadsafe(coro, target_loop)
        return await asyncio.wrap_future(future)

    # ------------------------------------------------------------------
    # Channel helper
    # ------------------------------------------------------------------

    async def _get_channel(self) -> Any:
        if not self._client or not self._channel_id:
            return None
        ch = self._client.get_channel(self._channel_id)
        if ch is None:
            try:
                ch = await self._client.fetch_channel(self._channel_id)
            except Exception as exc:
                logger.warning(
                    "[hitl/discord] cannot fetch channel %s: %s", self._channel_id, exc, exc_info=True
                )
        return ch

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def send_hitl(
        self,
        task_id: str,
        question: str,
        choices: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        await self._run_on_client_loop(
            self._send_hitl_impl(task_id, question, choices, context)
        )

    async def _send_hitl_impl(
        self,
        task_id: str,
        question: str,
        choices: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        ch = await self._get_channel()
        if ch is None:
            logger.warning("[hitl/discord] owner channel not available — cannot send HITL")
            return
        try:
            import discord  # type: ignore
            ctx = context or {}
            role_id = ctx.get("role_id", "")
            goal_preview = ctx.get("goal_preview", "") or ctx.get("description", "")
            dashboard_url = ctx.get("dashboard_url", "")

            embed = discord.Embed(
                title="Owner Action Required",
                description=question[:4096],
                color=discord.Color.orange(),
            )
            if role_id:
                embed.add_field(name="Role", value=role_id, inline=True)
            if goal_preview:
                embed.add_field(name="Goal", value=goal_preview[:512], inline=False)
            if not choices:
                embed.add_field(
                    name="How to reply",
                    value="Type your response in this channel — no buttons needed.",
                    inline=False,
                )
            if dashboard_url:
                embed.add_field(name="Dashboard", value=dashboard_url, inline=False)
            footer_text = f"task: {task_id}"
            embed.set_footer(text=footer_text)

            view = _HITLView(task_id=task_id, choices=choices, adapter=self)
            msg = await ch.send(embed=embed, view=view if choices else None)
            self._pending[msg.id] = (task_id, choices)
            logger.info("[hitl/discord] HITL posted (task=%s, msg=%s)", task_id, msg.id)
        except Exception as exc:
            logger.error("[hitl/discord] failed to send HITL: %s", exc, exc_info=True)

    async def send_notification(self, title: str, body: str, severity: str = "info") -> None:
        await self._run_on_client_loop(self._send_notification_impl(title, body, severity))

    async def _send_notification_impl(self, title: str, body: str, severity: str = "info") -> None:
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
            logger.error("[hitl/discord] failed to send notification: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    async def handle_button_click(self, task_id: str, choice: str) -> None:
        self._resolve_pending_by_task(task_id)
        self.handle_response(task_id, choice)

    async def handle_owner_message(self, message: Any) -> None:
        """Route a free-text owner message to the most recent pending HITL
        task that actually expects a reply.

        Quality Monitor's alert tasks (config.source == "quality_monitor")
        are pure one-way notifications -- Task(type=CUSTOM, no "command")
        posted to WAITING_FOR_INPUT purely so this adapter's existing
        send_hitl path delivers them, never meant to be resumed. Found
        live 2026-09-22: a genuine reply ("where are we", meant for a real
        pending task) landed on a stale alert instead because it happened
        to be the most recently posted message -- resuming it flips it to
        PENDING and dispatches it through CustomHandler, which fails with
        "Missing 'command' in task config" since it was never meant to run.
        Skip notification-only tasks here even when they're most recent.
        """
        candidates = sorted(self._pending.items(), key=lambda kv: kv[0], reverse=True)
        for msg_id, (task_id, _choices) in candidates:
            if self._is_notification_only(task_id):
                continue
            self._resolve_pending_by_task(task_id)
            self.handle_response(task_id, message.content.strip())
            await message.add_reaction("✅")
            return
        await message.reply("No pending HITL task right now.", mention_author=False)

    def _is_notification_only(self, task_id: str) -> bool:
        """True for tasks posted to Discord purely as notifications (e.g.
        Quality Monitor alerts) that must never be resumed via a reply."""
        if self._scheduler is None:
            return False
        task = self._scheduler.queue.get(task_id)
        if task is None:
            return False
        return task.config.get("source") == "quality_monitor"

    def _resolve_pending_by_task(self, task_id: str) -> None:
        self._pending = {k: v for k, v in self._pending.items() if v[0] != task_id}


# ---------------------------------------------------------------------------
# Lazy discord.ui classes — only constructed when discord.py is available
# ---------------------------------------------------------------------------

class _HITLView:
    def __new__(cls, task_id: str, choices: List[str], adapter: DiscordHITLAdapter):
        try:
            import discord  # type: ignore

            class _View(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=None)
                    for choice in choices[:5]:
                        self.add_item(_HITLButton(task_id=task_id, choice=choice, adapter=adapter))

            return _View()
        except Exception:
            return None  # discord.py not available — send without view


class _HITLButton:
    def __new__(cls, task_id: str, choice: str, adapter: DiscordHITLAdapter):
        import discord  # type: ignore

        cid = f"hitl:{task_id[:60]}:{choice[:30]}"

        class _Button(discord.ui.Button):
            def __init__(self):
                style = (
                    discord.ButtonStyle.success if choice.lower() in ("approve", "accept", "yes")
                    else discord.ButtonStyle.danger if choice.lower() in ("reject", "no", "deny")
                    else discord.ButtonStyle.primary
                )
                super().__init__(label=choice, style=style, custom_id=cid)
                self._adapter = adapter
                self._task_id = task_id
                self._choice = choice

            async def callback(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True)
                await self._adapter.handle_button_click(self._task_id, self._choice)
                await interaction.followup.send(
                    f"Replied **{self._choice}** to task `{self._task_id}`.",
                    ephemeral=True,
                )

        return _Button()
