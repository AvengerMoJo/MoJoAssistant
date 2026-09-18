"""Agent bridge host registry — maps host names to OpenCodeClient instances."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.scheduler.sandbox.opencode_client import OpenCodeClient

logger = logging.getLogger(__name__)


class HostRegistry:
    """Maintains one OpenCodeClient per configured host.

    Hosts carry optional location/profile/tier/backend metadata (see
    docs/specs/agent_workforce_dashboard_spec.md) beyond base_url/password.
    All of it is opaque to OpenCodeClient — get_client() only ever reads
    base_url/password — so adding fields here never risks breaking the
    existing session/run/reply tools.

    backend defaults to "opencode_serve" (the real opencode REST API that
    OpenCodeClient speaks). A host with backend="legacy_mcp" speaks a
    different wire protocol entirely (the pre-AgentBridge Express MCP
    tool, e.g. a legacy host on :4097) — get_client() must never be called for
    it; use describe()/backend_of() and route availability checks
    accordingly (see server.py's agent_fleet).
    """

    def __init__(self, hosts: Dict[str, Any]) -> None:
        self._hosts = hosts  # name → {"base_url": ..., "password": ..., ...metadata}
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

    def backend_of(self, name: str) -> str:
        host = self._hosts.get(name, {})
        return host.get("backend", "opencode_serve")

    def describe(self, name: str) -> Dict[str, Any]:
        """Full registry entry for one host, metadata included, password
        stripped (this is surfaced through agent_fleet to any MCP client)."""
        host = dict(self._hosts.get(name, {}))
        host.pop("password", None)
        host["name"] = name
        return host

    def describe_all(self) -> Dict[str, Dict[str, Any]]:
        return {name: self.describe(name) for name in self._hosts}
