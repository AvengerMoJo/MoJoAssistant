"""Agent bridge MCP server — Streamable HTTP, backed by OpenCodeClient.

Run standalone:  python -m app.mcp.agent_bridge.server
Mount in existing FastAPI:  from app.mcp.agent_bridge.server import bridge_app

Tools exposed to MCP clients:
  agent_servers         – list configured OpenCode hosts + health
  agent_status          – health-check one host (or a specific session)
  agent_run             – create session + send a prompt (blocking reply)
  agent_reply           – continue an existing session with a new prompt
  agent_sessions        – list sessions on a host
  agent_close_session   – delete a session on a host
  agent_fleet           – full fleet: registry metadata + live availability,
                          every host regardless of backend/protocol
  agent_fleet_summary   – agent_fleet grouped by region/tier, with
                          per-group session counts

Multiple backends, one dashboard: a host's `backend` field (default
"opencode_serve") selects how its availability is actually checked.
"legacy_mcp" hosts (e.g. a legacy pre-AgentBridge Express MCP
server) speak a different wire protocol entirely and are never routed
through OpenCodeClient; see _check_availability below. This is the
"virtual interface" the fleet tools present: every host shows up in one
list with a real status, whatever backend it actually runs.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.mcp.agent_bridge.config import load_config
from app.mcp.agent_bridge.registry import HostRegistry

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Singleton (created lazily on first tool call or explicit build)
# ------------------------------------------------------------------

_mcp: Optional[FastMCP] = None
_registry: Optional[HostRegistry] = None


def _ensure(reg: Optional[HostRegistry] = None) -> tuple[FastMCP, HostRegistry]:
    global _mcp, _registry
    if _mcp is not None and _registry is not None and reg is None:
        return _mcp, _registry
    cfg = load_config()
    if reg is None:
        reg = HostRegistry(cfg.get("hosts", {}))
    _registry = reg
    bind = cfg.get("bind", "0.0.0.0")
    transport_security_kw: Dict[str, Any] = {}
    if bind not in ("127.0.0.1", "localhost", "::1"):
        allowed = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
        if bind != "0.0.0.0":
            allowed.append(f"{bind}:*")
        transport_security_kw["transport_security"] = TransportSecuritySettings(
            enable_dns_rebinding_protection=bind != "0.0.0.0",
            allowed_hosts=allowed,
        )
    _mcp = FastMCP(
        "agent-bridge",
        instructions=(
            "Bridge to MoJoAssistant managed OpenCode agents. "
            "Use agent_run to start a coding task, agent_reply to continue, "
            "agent_sessions to see what's in flight."
        ),
        **transport_security_kw,
    )
    _register_tools(_mcp, reg)
    return _mcp, reg


# ------------------------------------------------------------------
# Availability — backend-dispatched so every host reports real status
# regardless of which protocol it actually speaks
# ------------------------------------------------------------------

async def _check_legacy_mcp(base_url: str) -> dict:
    """Reachability check for a legacy_mcp host (e.g. a legacy host's
    pre-AgentBridge Express server): a raw MCP `initialize` handshake,
    since it doesn't implement the opencode REST API OpenCodeClient
    speaks. A 200 response is treated as reachable regardless of body
    shape — this proves the process is up and speaking MCP, which is all
    "availability" claims here; it does not validate the legacy tool
    surface itself."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                base_url,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "agent-bridge-fleet-check", "version": "0.1"},
                    },
                },
            )
        if resp.status_code == 200:
            return {"status": "ok", "url": base_url}
        return {"status": "unreachable", "url": base_url, "error": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"status": "unreachable", "url": base_url, "error": str(exc)}


async def _check_availability(reg: HostRegistry, name: str) -> dict:
    """Dispatch by backend -- the one place that decides how a host's
    availability is actually determined. Add a new backend here, not by
    scattering isinstance-style checks through the tools below."""
    backend = reg.backend_of(name)
    if backend == "legacy_mcp":
        host = reg.describe(name)
        return await _check_legacy_mcp(host.get("base_url", ""))
    try:
        client = reg.get_client(name)
        health = await client.health()
        return {"status": "ok", **health}
    except Exception as exc:
        return {"status": "unreachable", "url": reg.list_hosts().get(name, "?"), "error": str(exc)}


# ------------------------------------------------------------------
# Tools
# ------------------------------------------------------------------


def _register_tools(mcp: FastMCP, reg: HostRegistry) -> None:

    @mcp.tool()
    async def agent_servers() -> dict:
        """List configured hosts and their reachability (backend-aware —
        a legacy_mcp host is checked on its own protocol, not assumed to
        speak the opencode REST API)."""
        out: Dict[str, Any] = {}
        for name in reg.list_hosts():
            out[name] = await _check_availability(reg, name)
        return out

    @mcp.tool()
    async def agent_status(
        server: str,
        session_id: Optional[str] = None,
    ) -> dict:
        """Health-check one OpenCode host. Optionally include a specific session."""
        client = reg.get_client(server)
        health = await client.health()
        result: Dict[str, Any] = {"server": server, **health}
        if session_id:
            result["session"] = await client.get_session(session_id)
        return result

    @mcp.tool()
    async def agent_run(
        server: str,
        prompt: str,
        working_dir: Optional[str] = None,
    ) -> dict:
        """Create a new session on an OpenCode host and send a prompt.

        Returns the session_id and the agent's reply (blocking).
        """
        client = reg.get_client(server)
        create_kw: Dict[str, Any] = {}
        if working_dir:
            create_kw["workingDir"] = working_dir
        session = await client.create_session(**create_kw)
        session_id = session.get("id") or session.get("sessionID")
        if not session_id:
            return {"error": "Failed to create session", "raw": session}
        reply = await client.send_message(session_id, prompt)
        text = _extract_text(reply)
        return {"session_id": session_id, "reply": text, "raw": reply}

    @mcp.tool()
    async def agent_reply(
        server: str,
        session_id: str,
        prompt: str,
    ) -> dict:
        """Continue an existing session with a new prompt."""
        client = reg.get_client(server)
        reply = await client.send_message(session_id, prompt)
        text = _extract_text(reply)
        return {"session_id": session_id, "reply": text, "raw": reply}

    @mcp.tool()
    async def agent_sessions(server: str) -> Any:
        """List sessions on an OpenCode host."""
        client = reg.get_client(server)
        return await client.list_sessions()

    @mcp.tool()
    async def agent_close_session(
        server: str,
        session_id: str,
    ) -> dict:
        """Delete a session on an OpenCode host."""
        client = reg.get_client(server)
        await client.delete_session(session_id)
        return {"deleted": session_id, "server": server}

    @mcp.tool()
    async def agent_fleet() -> dict:
        """Full workforce fleet: every registered host's location/hardware
        profile/tier metadata merged with a live availability check —
        one call instead of reading docs or probing hosts one at a time.

        Every host appears here regardless of backend (opencode_serve or
        legacy_mcp) — a host that speaks a different wire protocol still
        gets a real, correctly-checked status, not a false "unreachable"
        from assuming the wrong API shape."""
        out: Dict[str, Any] = {}
        for name in reg.list_hosts():
            entry = reg.describe(name)
            entry["availability"] = await _check_availability(reg, name)
            if reg.backend_of(name) == "opencode_serve" and entry["availability"]["status"] == "ok":
                try:
                    sessions = await reg.get_client(name).list_sessions()
                    entry["session_count"] = len(sessions)
                except Exception:
                    entry["session_count"] = None
            else:
                # legacy_mcp hosts don't implement the opencode session
                # API this bridge speaks -- report "unknown", never guess 0.
                entry["session_count"] = None
            out[name] = entry
        return out

    @mcp.tool()
    async def agent_fleet_summary() -> dict:
        """agent_fleet grouped by region and tier -- "what's running and
        what's it costing" at a glance."""
        fleet = await agent_fleet()
        groups: Dict[str, Any] = {}
        for name, entry in fleet.items():
            region = (entry.get("location") or {}).get("region", "unknown")
            tier_type = (entry.get("tier") or {}).get("type", "unknown")
            key = f"{region}/{tier_type}"
            group = groups.setdefault(key, {
                "region": region, "tier_type": tier_type,
                "hosts": [], "hosts_ok": 0, "total_sessions": 0,
            })
            group["hosts"].append(name)
            if entry["availability"]["status"] == "ok":
                group["hosts_ok"] += 1
            if isinstance(entry.get("session_count"), int):
                group["total_sessions"] += entry["session_count"]
        return groups


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _extract_text(msg: Any) -> str:
    """Best-effort extraction of text content from an OpenCode message response."""
    if not isinstance(msg, dict):
        return str(msg)
    parts = msg.get("parts") or msg.get("content")
    if isinstance(parts, list):
        texts = [
            p.get("text", "")
            for p in parts
            if isinstance(p, dict) and p.get("type") == "text"
        ]
        if texts:
            return "\n".join(texts)
    if "text" in msg:
        return str(msg["text"])
    return str(msg)


# ------------------------------------------------------------------
# Public ASGI entry-point (for uvicorn or mounting)
# ------------------------------------------------------------------


def build_app(password: str = ""):
    """Return a Starlette ASGI app for the bridge.  Used by __main__."""
    _ensure()
    app = _mcp.streamable_http_app()  # type: ignore[union-attr]
    return app
