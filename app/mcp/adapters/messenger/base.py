"""MessengerAdapter — SDK base class for community messenger plugins."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mojo_assistant.messenger")


class MessengerAdapter(ABC):
    """
    SDK base for all MoJoAssistant messenger plugins.

    One class handles both plain notifications AND interactive HITL questions.
    The scheduler calls send_notification() for task completions/failures and
    send_hitl() when an agent pauses waiting for owner input.

    When the owner replies (button click, text message, etc.), call
    handle_response(task_id, reply) — the base class resumes the task.

    Minimal implementation
    ----------------------
    class SlackAdapter(MessengerAdapter):
        adapter_type = "slack"

        async def send_notification(self, title, body, severity="info"):
            await post_slack(self.config["webhook_url"], f"*{title}*\n{body}")

        async def send_hitl(self, task_id, question, choices):
            msg_ts = await post_slack_blocks(question, choices)
            # store msg_ts → task_id so you can route the button click back:
            #   self.handle_response(task_id, chosen_option)
    """

    # Must be set in every subclass — matched against config key in notifications_config.json
    adapter_type: str = ""

    def __init__(self, adapter_id: str, config: Dict[str, Any]) -> None:
        self.adapter_id = adapter_id
        self.config = config
        self._scheduler: Any = None

    # ------------------------------------------------------------------
    # Lifecycle — override to open/close connections (bots, websockets…)
    # ------------------------------------------------------------------

    def set_scheduler(self, scheduler: Any) -> None:
        """Called by MessengerManager at startup. Gives access to task queue."""
        self._scheduler = scheduler

    async def start(self) -> None:
        """Connect to the messaging platform. Override as needed."""

    async def stop(self) -> None:
        """Disconnect and clean up. Override as needed."""

    # ------------------------------------------------------------------
    # Required — implement both in every subclass
    # ------------------------------------------------------------------

    @abstractmethod
    async def send_notification(
        self, title: str, body: str, severity: str = "info"
    ) -> None:
        """Send a plain (non-interactive) notification to the owner."""

    @abstractmethod
    async def send_hitl(
        self, task_id: str, question: str, choices: List[str]
    ) -> None:
        """
        Send an interactive question to the owner.

        Present choices as buttons / quick-replies / numbered options.
        When the owner picks one, call:
            self.handle_response(task_id, chosen_option)
        """

    # ------------------------------------------------------------------
    # Provided — call this when the owner replies; do NOT override
    # ------------------------------------------------------------------

    def handle_response(self, task_id: str, reply: str) -> None:
        """Route the owner's reply back into the scheduler to resume the task."""
        if self._scheduler is None:
            logger.warning(
                "[messenger/%s] scheduler not set — cannot resume task %s",
                self.adapter_id, task_id,
            )
            return
        try:
            self._scheduler.resume_task_with_reply(task_id, reply)
            logger.info(
                "[messenger/%s] resumed task %s with reply '%s'",
                self.adapter_id, task_id, reply,
            )
        except Exception as exc:
            logger.error(
                "[messenger/%s] failed to resume task %s: %s",
                self.adapter_id, task_id, exc,
            )
