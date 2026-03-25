"""
Persistent Event Log

Circular buffer that persists SSE events to disk so non-WebSocket clients
can poll for recent activity via the get_recent_events MCP tool.
"""

import json
import os
import threading
import uuid
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional
from app.config.paths import get_memory_subpath
from app.mcp.adapters.attention_classifier import AttentionClassifier


class EventLog:
    """
    Append-only circular buffer with JSON persistence.

    - In-memory deque capped at MAX_EVENTS (oldest dropped when full).
    - Persisted atomically to PATH after every append.
    - Process-level singleton: EventLog() always returns the same instance
      so the MCP server and the agentic executor (running in a separate
      daemon thread with its own event loop) share one consistent view
      and never overwrite each other's writes.
    - Thread-safe via threading.Lock (works across different event loops /
      threads; asyncio.Lock binds to one event loop and breaks cross-thread use).
    """

    MAX_EVENTS = 500
    PATH = get_memory_subpath("events.json")

    _instance: "Optional[EventLog]" = None
    _instance_lock: threading.Lock = threading.Lock()
    _instance_initialized: bool = False
    # Class-level write lock used by append/purge — always a threading.Lock so
    # it is safe to acquire from any thread or event loop, not just the one that
    # first created the instance (asyncio.Lock would bind to one event loop).
    _write_lock: threading.Lock = threading.Lock()

    def __new__(cls, path: str = None, max_events: int = None):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, path: str = None, max_events: int = None):
        with self.__class__._instance_lock:
            if self._instance_initialized:
                return
            self.__class__._instance_initialized = True
        self._path = path or self.PATH
        self._max = max_events or self.MAX_EVENTS
        self._lock = threading.Lock()
        self._events: deque[Dict[str, Any]] = deque(maxlen=self._max)
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def append(self, event: Dict[str, Any]) -> None:
        """Add an event to the log and persist atomically."""
        # Ensure required fields
        if "id" not in event:
            event = dict(event)
            event["id"] = str(uuid.uuid4())
        if "timestamp" not in event:
            event = dict(event)
            event["timestamp"] = datetime.now().isoformat()

        # Classify attention level (deterministic, no I/O)
        if "hitl_level" not in event:
            event = dict(event)
            event["hitl_level"] = AttentionClassifier.classify(event)

        with self.__class__._write_lock:
            self._events.append(event)
            self._persist()

    def get_recent(
        self,
        since: Optional[str] = None,
        types: Optional[List[str]] = None,
        limit: int = 50,
        include_data: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Return recent events, newest-last.

        Args:
            since: ISO-8601 timestamp; only return events strictly after this.
            types: If provided, only return events whose event_type is in this list.
            limit: Maximum number of events to return.
            include_data: If False, strip the 'data' key from each event.
        """
        results = list(self._events)

        if since:
            results = [e for e in results if e.get("timestamp", "") > since]

        if types:
            results = [e for e in results if e.get("event_type") in types]

        results = results[-limit:]

        if not include_data:
            results = [{k: v for k, v in e.items() if k != "data"} for e in results]

        return results

    async def purge_before(self, timestamp: str) -> int:
        """Remove events older than timestamp. Returns count removed."""
        with self.__class__._write_lock:
            before = len(self._events)
            kept = [e for e in self._events if e.get("timestamp", "") >= timestamp]
            self._events = deque(kept, maxlen=self._max)
            removed = before - len(self._events)
            if removed:
                self._persist()
            return removed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load persisted events from disk into memory."""
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            events = data if isinstance(data, list) else []
            # Trim to max capacity (keep newest)
            for e in events[-self._max:]:
                self._events.append(e)
        except Exception:
            pass  # Start fresh on corrupt file

    def _persist(self) -> None:
        """Atomically write events to disk."""
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(list(self._events), f, default=str, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
