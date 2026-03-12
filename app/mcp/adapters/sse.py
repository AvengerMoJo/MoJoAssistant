"""
SSE Notification Sidecar

Lightweight Server-Sent Events notifier for real-time task status updates.
Uses asyncio queues for fan-out to multiple subscribers.

All events are enriched with a standard envelope before broadcast:
  event_type, timestamp, severity, title, notify_user
and are also appended to the persistent EventLog when one is provided.
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, Optional, Set

# severity levels where notify_user defaults to True
_NOTIFY_SEVERITIES = {"warning", "error", "critical"}


class SSENotifier:
    """Manages SSE subscribers and broadcasts task events."""

    def __init__(self, event_log=None):
        """
        Args:
            event_log: Optional EventLog instance for persistent event storage.
        """
        self._subscribers: Set[asyncio.Queue] = set()
        self._event_log = event_log

    async def subscribe(self) -> asyncio.Queue:
        """Create a new subscriber queue."""
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove a subscriber queue."""
        self._subscribers.discard(queue)

    async def broadcast(self, event: Dict[str, Any]) -> None:
        """
        Enrich event with standard envelope fields, persist to EventLog,
        then fan out to all SSE subscribers.
        """
        # --- standard envelope ---
        if "timestamp" not in event:
            event["timestamp"] = datetime.now().isoformat()
        if "severity" not in event:
            event["severity"] = "info"
        if "title" not in event:
            event["title"] = event.get("event_type", "event")
        if "notify_user" not in event:
            event["notify_user"] = event["severity"] in _NOTIFY_SEVERITIES

        # --- persist to event log ---
        if self._event_log is not None:
            try:
                await self._event_log.append(event)
            except Exception:
                pass  # non-critical

        # --- fan out to SSE subscribers ---
        if not self._subscribers:
            return

        dead_queues = set()
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dead_queues.add(queue)

        # Clean up dead queues
        self._subscribers -= dead_queues

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


def format_sse(event_type: str, data: Dict[str, Any]) -> str:
    """Format a dict as an SSE message string."""
    payload = json.dumps(data, default=str, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"
