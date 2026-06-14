"""Pluggable HITL (Human-In-The-Loop) Adapter Base.

Each HITL adapter owns its own transport lifecycle and implements the
send_hitl() contract so that tasks can pause, wait for a human reply,
and resume with the chosen answer.  Mirrors PushAdapter design: registry,
config-driven instantiation, independent start/stop.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    pass

logger = logging.getLogger("mojo_assistant.hitl")


class HITLAdapter(ABC):
    """Abstract base for all Human-In-The-Loop adapters.

    Subclasses implement ``send_hitl()`` to post a proposal with choices
    through their transport (Discord buttons, Slack blocks, etc.).  The
    adapter also owns the transport lifecycle via ``start()/stop()`` and
    wires incoming replies back into the scheduler through
    ``handle_response()``.

    Contract for subclasses:
      - Set ``adapter_type: str`` class attribute (must match config key).
      - Implement ``async send_hitl(task_id, question, choices) -> None``.
      - Optionally override ``send_notification()`` for plain alerts.
    """

    adapter_type: str = ""

    def __init__(self, adapter_id: str, config: dict[str, Any]) -> None:
        self.adapter_id = adapter_id
        self.config = config
        self._scheduler: Any = None

    # ------------------------------------------------------------------
    # Lifecycle hooks called by HITLManager
    # ------------------------------------------------------------------

    def set_scheduler(self, scheduler: Any) -> None:
        """Give the adapter a reference to the task scheduler."""
        self._scheduler = scheduler

    async def start(self) -> None:
        """Start the transport (e.g. connect Discord client).

        Override in subclasses that own their own connection lifecycle.
        """

    async def stop(self) -> None:
        """Stop and clean up the transport."""

    # ------------------------------------------------------------------
    # Abstract interface — must be implemented by every adapter
    # ------------------------------------------------------------------

    @abstractmethod
    async def send_hitl(
        self, task_id: str, question: str, choices: List[str]
    ) -> None:
        """Post a HITL proposal with button/text choices.

        Parameters
        ----------
        task_id : str
            Unique identifier of the waiting task.
        question : str
            The prompt to display to the human operator.
        choices : list[str]
            Available reply options (rendered as buttons or quick replies).
        """

    # ------------------------------------------------------------------
    # Optional — plain notification (non-interactive)
    # ------------------------------------------------------------------

    async def send_notification(
        self, title: str, body: str, severity: str = "info"
    ) -> None:
        """Send a non-interactive notification.

        Default implementation is a no-op; override when the transport
        supports plain alerts (e.g. Discord embed without buttons).
        """

    # ------------------------------------------------------------------
    # Reply routing — called by subclass callbacks to resume tasks
    # ------------------------------------------------------------------

    def handle_response(self, task_id: str, reply: str) -> None:
        """Route a human reply back into the scheduler."""
        if self._scheduler is None:
            logger.warning(
                "[hitl/%s] scheduler not set — cannot resume task %s",
                self.adapter_id,
                task_id,
            )
            return
        try:
            self._scheduler.resume_task_with_reply(task_id, reply)
            logger.info(
                "[hitl/%s] resumed task %s with reply '%s'",
                self.adapter_id,
                task_id,
                reply,
            )
        except Exception as exc:
            logger.error(
                "[hitl/%s] failed to resume task %s: %s",
                self.adapter_id,
                task_id,
                exc,
            )
