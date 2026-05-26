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
        coro = self._run()
        try:
            self._task = asyncio.create_task(coro, name=f"push/{self.adapter_id}")
            logger.info("[push/%s] adapter started", self.adapter_id)
        except RuntimeError:
            # No running event loop — close coroutine cleanly to avoid "never awaited" warning
            coro.close()
            logger.debug("[push/%s] no running event loop — adapter deferred", self.adapter_id)

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
        notify_user = event.get("notify_user", False)

        # notify_user_only: skip events that don't request user attention
        if f.get("notify_user_only", True) and not notify_user:
            return False

        # min_severity threshold — waived when notify_user=True (explicit user signal)
        if not notify_user:
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

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Strip markdown formatting from text."""
        if not text:
            return ''
        # Remove code blocks
        text = re.sub(r'```[\s\S]*?```', '', text)
        # Remove inline code
        text = re.sub(r'`([^`]*)`', r'\1', text)
        # Remove headers
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        # Remove bold/italic
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = re.sub(r'(?<!\*)\*([^*]+)(?!\*)', r'\1', text)
        text = re.sub(r'_([^_]+)_', r'\1', text)
        # Remove links
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        # Remove blockquotes and list markers
        text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^[-*+]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
        return text.strip()

    @staticmethod
    def _extract_first_sentence(text: str) -> str:
        """Extract first meaningful sentence from text."""
        if not text:
            return ''
        clean = PushAdapter._strip_markdown(text)
        match = re.match(r'^([^\.\!\?]+[\.\!\?])', clean.strip())
        if match:
            return match.group(1).strip()
        first_line = clean.split('\n')[0].strip()
        if len(first_line) > 20:
            return first_line
        return clean[:50]

    @staticmethod
    def _get_status_emoji(event: dict) -> str:
        """Return status emoji based on event outcome."""
        status = event.get('status', '')
        if status in ('failed', 'error'):
            return '\u2717'  # ✗
        elif status == 'waiting_for_input':
            return '?'
        return '\u2713'  # ✓

    @staticmethod
    def _truncate_to_160(text: str) -> str:
        """Truncate text to exactly 160 characters."""
        if len(text) <= 160:
            return text
        return text[:157] + '[...]'

    def _format_title(self, event: Dict[str, Any]) -> str:
        return event.get("title") or event.get("event_type", "MoJoAssistant event")

    def _format_body(self, event: Dict[str, Any]) -> str:
        """Format notification body with status emoji, markdown stripped, first sentence only, capped at 160 chars."""
        data = event.get("data") or {}
        
        # Get status for emoji prefix
        emoji = PushAdapter._get_status_emoji(event)
        
        parts = [f"{emoji} Task: {data['task_id']}"] if data.get("task_id") else []
        
        # Process final_answer - strip markdown, extract first sentence, truncate to 160
        final_answer = event.get("final_answer") or data.get("final_answer")
        if final_answer:
            clean_text = PushAdapter._strip_markdown(str(final_answer))
            first_sentence = PushAdapter._extract_first_sentence(clean_text)
            truncated = PushAdapter._truncate_to_160(first_sentence)
            parts.append(truncated)
        
        # Add error/message at end if present (but keep total under control)
        if data.get("error"):
            err_part = f"Error: {data['error']}"
            if len('\n'.join(parts + [err_part])) > 160:
                parts.append(PushAdapter._truncate_to_160(err_part))
        
        return '\n'.join(parts) if parts else event.get("event_type", "")

