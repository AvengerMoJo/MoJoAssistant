"""Agent bridge host registry — maps host names to OpenCodeClient instances."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.scheduler.sandbox.opencode_client import OpenCodeClient

logger = logging.getLogger(__name__)


class HostRegistry:
    """Maintains one OpenCodeClient per configured host."""

    def __init__(self, hosts: Dict[str, Any]) -> None:
        self._hosts = hosts  # name → {"base_url": ..., "password": ...}
        self._clients: Dict[str, OpenCodeClient] = {}

    def get_client(self, name: str) -> OpenCodeClient:
        if name not in self._clients:
            host = self._hosts.get(name)
            if host is None:
                raise ValueError(f"Unknown host {name!r}. Known: {list(self._hosts)}")
            self._clients[name] = OpenCodeClient(
                base_url=host["base_url"],
                password=host.get("password", ""),
            )
        return self._clients[name]

    async def close_all(self) -> None:
        for c in self._clients.values():
            try:
                await c.close()
            except Exception:
                pass
        self._clients.clear()

    def list_hosts(self) -> Dict[str, str]:
        return {name: h.get("base_url", "?") for name, h in self._hosts.items()}
