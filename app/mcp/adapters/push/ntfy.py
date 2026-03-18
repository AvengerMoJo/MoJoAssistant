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

import json
import logging
import os
from typing import Any, Dict

from app.mcp.adapters.push.base import PushAdapter

logger = logging.getLogger(__name__)

# ntfy JSON API priority: 1=min 2=low 3=default 4=high 5=max
_DEFAULT_PRIORITY_MAP = {
    "info": 3,
    "warning": 4,
    "error": 5,
    "critical": 5,
}

# ntfy emoji shortcode tags (text, converted to emoji by the ntfy app)
_SEVERITY_TAG = {
    "info": "information_source",
    "warning": "warning",
    "error": "rotating_light",
    "critical": "rotating_light",
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

        severity = event.get("severity", "info")
        title = self._format_title(event)
        body = self._format_body(event) or title
        priority = self._priority_map.get(severity, "default")
        sev_tag = _SEVERITY_TAG.get(severity, "information_source")
        event_tag = event.get("event_type", "event").replace("_", "-")

        # Use JSON API — all fields are UTF-8, emoji work everywhere
        payload = {
            "topic": self._endpoint.rsplit("/", 1)[-1],
            "title": title,
            "message": body,
            "priority": priority,
            "tags": [sev_tag, event_tag],
            "markdown": True,
        }
        data = json.dumps(payload).encode("utf-8")

        # Derive base URL (everything before the topic path)
        base_url = self._endpoint.rsplit("/", 1)[0]

        import urllib.request
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        req = urllib.request.Request(
            base_url,
            data=data,
            headers=headers,
            method="POST",
        )

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
