"""MessengerManager — lifecycle owner and event dispatcher for all messenger adapters."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mojo_assistant.messenger.manager")

_shared_manager: Optional["MessengerManager"] = None


def init_shared_manager(mgr: "MessengerManager") -> None:
    """Store the live manager for process-wide reuse. Called once at startup."""
    global _shared_manager
    _shared_manager = mgr


def get_shared_manager() -> "MessengerManager":
    """Return the live shared manager (or an empty fallback with a warning)."""
    if _shared_manager is not None:
        return _shared_manager
    logger.warning(
        "[messenger/manager] get_shared_manager called before init — "
        "creating empty fallback; notifications will not be delivered"
    )
    return MessengerManager()


class MessengerManager:
    """
    Loads, starts, and dispatches to all configured messenger adapters.

    Config shape (notifications_config.json):
    {
      "messengers": {
        "discord":  { "enabled": true },
        "telegram": { "enabled": true, "bot_token": "...", "chat_id": "..." },
        "slack":    { "enabled": false }
      }
    }

    Event routing:
      task_waiting_for_input  →  send_hitl()        (interactive, with buttons)
      everything else         →  send_notification() (plain message)

    Only events with notify_user=True are delivered (silent events are skipped).
    """

    def __init__(self) -> None:
        self._adapters: List[Any] = []

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def load_from_config(self, config_path: Optional[str] = None) -> None:
        """Discover all adapter types then instantiate those enabled in config."""
        from app.mcp.adapters.messenger.registry import load_all, get
        load_all()

        path = Path(
            config_path
            or os.path.expanduser("~/.memory/config/notifications_config.json")
        )
        try:
            raw = json.loads(path.read_text())
        except FileNotFoundError:
            logger.info("[messenger/manager] config not found at %s — no adapters loaded", path)
            return
        except Exception as exc:
            logger.warning("[messenger/manager] config read failed: %s", exc)
            return

        for adapter_type, cfg in raw.get("messengers", {}).items():
            if not isinstance(cfg, dict):
                continue
            if not cfg.get("enabled", True):
                continue
            cls = get(adapter_type)
            if cls is None:
                logger.warning(
                    "[messenger/manager] unknown adapter type '%s' — "
                    "install the plugin or add it to ~/.memory/plugins/messenger/",
                    adapter_type,
                )
                continue
            adapter = cls(adapter_id=adapter_type, config=cfg)
            self._adapters.append(adapter)
            logger.info("[messenger/manager] loaded '%s'", adapter_type)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def set_scheduler(self, scheduler: Any) -> None:
        for a in self._adapters:
            a.set_scheduler(scheduler)

    async def start(self) -> None:
        for a in self._adapters:
            try:
                await a.start()
            except Exception as exc:
                logger.error(
                    "[messenger/manager] start failed for '%s': %s", a.adapter_id, exc
                )

    async def stop(self) -> None:
        for a in self._adapters:
            try:
                await a.stop()
            except Exception as exc:
                logger.warning(
                    "[messenger/manager] stop failed for '%s': %s", a.adapter_id, exc
                )

    # ------------------------------------------------------------------
    # Event dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, event: Dict[str, Any]) -> None:
        """Route a scheduler event to all registered adapters.

        Skipped when notify_user=False — silent/internal events never reach users.
        """
        if not self._adapters:
            return
        if not event.get("notify_user", False):
            return

        event_type = event.get("event_type", "")
        is_hitl = event_type == "task_waiting_for_input"

        for adapter in self._adapters:
            try:
                if is_hitl:
                    await adapter.send_hitl(
                        task_id=event.get("task_id", ""),
                        question=(
                            event.get("question")
                            or event.get("title")
                            or "Owner input required"
                        ),
                        choices=event.get("choices") or [],
                        context=event.get("context"),
                    )
                else:
                    await adapter.send_notification(
                        title=event.get("title", event_type),
                        body=_format_body(event),
                        severity=event.get("severity", "info"),
                    )
            except Exception as exc:
                logger.error(
                    "[messenger/manager] dispatch to '%s' failed: %s",
                    adapter.adapter_id, exc,
                )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def adapters(self) -> List[Any]:
        return list(self._adapters)

    def __len__(self) -> int:
        return len(self._adapters)


def _format_body(event: Dict[str, Any]) -> str:
    """Build a human-readable body from a scheduler event dict."""
    parts: List[str] = []
    if event.get("task_id"):
        parts.append(f"Task: {event['task_id']}")
    if event.get("error"):
        parts.append(f"Error: {event['error']}")
    if event.get("final_answer"):
        preview = str(event["final_answer"])
        parts.append(preview[:400] + ("…" if len(preview) > 400 else ""))
    data = event.get("data") or {}
    if data.get("description"):
        parts.append(data["description"])
    return "\n".join(parts) or event.get("title", "")
