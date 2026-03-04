"""
SSE Notification Sidecar

Lightweight Server-Sent Events notifier for real-time task status updates.
Uses asyncio queues for fan-out to multiple subscribers.
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, Set


class SSENotifier:
    """Manages SSE subscribers and broadcasts task events."""

    def __init__(self):
        self._subscribers: Set[asyncio.Queue] = set()

    async def subscribe(self) -> asyncio.Queue:
        """Create a new subscriber queue."""
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove a subscriber queue."""
        self._subscribers.discard(queue)

    async def broadcast(self, event: Dict[str, Any]) -> None:
        """Send an event to all subscribers."""
        if not self._subscribers:
            return
        # Add timestamp if not present
        if "timestamp" not in event:
            event["timestamp"] = datetime.now().isoformat()

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
