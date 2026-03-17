"""
ntfy Push Adapter

Delivers events to an ntfy topic via HTTP POST.
Works with ntfy.sh (public) or a self-hosted ntfy server.

Config example:
  {
    "id": "ntfy_push",
    "type": "ntfy",
    "enabled": true,
    "endpoint": "https://ntfy.sh/your-topic",
    "filter": { "min_severity": "warning", "notify_user_only": true }
  }

Optional:
  "auth_var": "NTFY_TOKEN"  — env var holding a Bearer token (for protected topics)
  "priority_map": { "info": "default", "warning": "high", "error": "urgent", "critical": "urgent" }
"""

import logging
import os
from typing import Any, Dict

from app.mcp.adapters.push.base import PushAdapter

logger = logging.getLogger(__name__)

_DEFAULT_PRIORITY_MAP = {
    "info": "default",
    "warning": "high",
    "error": "urgent",
    "critical": "urgent",
}

_SEVERITY_EMOJI = {
    "info": "ℹ️",
    "warning": "⚠️",
    "error": "🔴",
    "critical": "🚨",
}


class NtfyAdapter(PushAdapter):
    adapter_type = "ntfy"

    def __init__(self, adapter_id: str, config: Dict[str, Any], event_log):
        super().__init__(adapter_id, config, event_log)
        self._endpoint = config.get("endpoint", "").rstrip("/")
        auth_var = config.get("auth_var")
        self._token = os.getenv(auth_var) if auth_var else None
        self._priority_map = config.get("priority_map", _DEFAULT_PRIORITY_MAP)

    async def dispatch(self, event: Dict[str, Any]) -> None:
        if not self._endpoint:
            logger.warning("[push/%s] no endpoint configured", self.adapter_id)
            return

        import urllib.request

        severity = event.get("severity", "info")
        title = self._format_title(event)
        body = self._format_body(event)
        emoji = _SEVERITY_EMOJI.get(severity, "")
        priority = self._priority_map.get(severity, "default")

        headers = {
            "Title": f"{emoji} {title}".strip(),
            "Priority": priority,
            "Tags": f"mojoassistant,{event.get('event_type', 'event')}",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        message = body.encode("utf-8") if body else title.encode("utf-8")

        req = urllib.request.Request(
            self._endpoint,
            data=message,
            headers=headers,
            method="POST",
        )

        # Run blocking HTTP call in executor to avoid blocking the event loop
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._send, req)

        logger.debug(
            "[push/%s] dispatched %s → %s",
            self.adapter_id,
            event.get("event_type"),
            self._endpoint,
        )

    def _send(self, req) -> None:
        import urllib.request
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status not in (200, 201, 202):
                    raise RuntimeError(f"ntfy returned HTTP {resp.status}")
        except Exception as exc:
            raise RuntimeError(f"ntfy delivery failed: {exc}") from exc
