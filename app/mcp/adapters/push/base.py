"""
Push Adapter Base

Each push adapter is an independent reader of the EventLog. It maintains
its own cursor (last-seen timestamp) and filter config. Enabling or
disabling one adapter has zero effect on any other adapter or on the
SSE stream / MCP polling.

Contract for subclasses:
  - implement `adapter_type: str` class attribute
  - implement `async dispatch(event: dict) -> None`
    called for each event that passes the filter; raise on non-retriable error
"""

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config.paths import get_memory_subpath

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2, "critical": 3}


class PushAdapter(ABC):
    """
    Abstract base for all push notification adapters.

    Runs a background polling loop that reads from the EventLog and
    dispatches events that pass the configured filter.
    """

    adapter_type: str = "base"
    _default_poll_interval: int = 30  # seconds between EventLog polls

    def __init__(self, adapter_id: str, config: Dict[str, Any], event_log):
        self.adapter_id = adapter_id
        self.config = config
        self._event_log = event_log
        self._cursor: Optional[str] = self._load_cursor()
        self._task: Optional[asyncio.Task] = None
        self._filter = config.get("filter", {})
        self.poll_interval: int = int(config.get("poll_interval", self._default_poll_interval))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background polling loop (non-blocking)."""
        self._task = asyncio.create_task(self._run(), name=f"push/{self.adapter_id}")
        logger.info("[push/%s] adapter started", self.adapter_id)

    def stop(self) -> None:
        """Cancel the background polling loop."""
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("[push/%s] adapter stopped", self.adapter_id)

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def dispatch(self, event: Dict[str, Any]) -> None:
        """
        Deliver one event to the push channel.
        Raise an exception to signal delivery failure (will be logged, not crash).
        """

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("[push/%s] poll error: %s", self.adapter_id, exc)
            await asyncio.sleep(self.poll_interval)

    async def _poll_once(self) -> None:
        events = self._event_log.get_recent(
            since=self._cursor,
            include_data=True,
        )
        if not events:
            return

        for event in events:
            if self._matches_filter(event):
                try:
                    await self.dispatch(event)
                except Exception as exc:
                    logger.warning(
                        "[push/%s] dispatch failed for %s: %s",
                        self.adapter_id,
                        event.get("event_type"),
                        exc,
                    )

        # Advance cursor to timestamp of last event (newest)
        latest_ts = events[-1].get("timestamp")
        if latest_ts:
            self._cursor = latest_ts
            self._save_cursor(latest_ts)

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------

    def _matches_filter(self, event: Dict[str, Any]) -> bool:
        f = self._filter

        # notify_user_only: skip events that don't request user attention
        if f.get("notify_user_only", True) and not event.get("notify_user", False):
            return False

        # min_severity threshold
        min_sev = f.get("min_severity", "warning")
        event_sev = event.get("severity", "info")
        if _SEVERITY_ORDER.get(event_sev, 0) < _SEVERITY_ORDER.get(min_sev, 0):
            return False

        # event_types allowlist
        allowed_types: Optional[List[str]] = f.get("event_types")
        if allowed_types and event.get("event_type") not in allowed_types:
            return False

        return True

    # ------------------------------------------------------------------
    # Cursor persistence
    # ------------------------------------------------------------------

    def _cursor_path(self) -> str:
        return get_memory_subpath("cursors", f"{self.adapter_id}.json")

    def _load_cursor(self) -> Optional[str]:
        path = self._cursor_path()
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("cursor")
        except Exception:
            pass
        return None

    def _save_cursor(self, timestamp: str) -> None:
        path = self._cursor_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"cursor": timestamp, "updated": datetime.now().isoformat()}, f)
            os.replace(tmp, path)
        except Exception as exc:
            logger.warning("[push/%s] failed to save cursor: %s", self.adapter_id, exc)

    # ------------------------------------------------------------------
    # Helpers for subclasses
    # ------------------------------------------------------------------

    def _format_title(self, event: Dict[str, Any]) -> str:
        return event.get("title") or event.get("event_type", "MoJoAssistant event")

    def _format_body(self, event: Dict[str, Any]) -> str:
        data = event.get("data") or {}
        parts = []
        if data.get("task_id"):
            parts.append(f"Task: {data['task_id']}")
        if data.get("error"):
            parts.append(f"Error: {data['error']}")
        if data.get("message"):
            parts.append(data["message"])
        return " | ".join(parts) if parts else event.get("event_type", "")
