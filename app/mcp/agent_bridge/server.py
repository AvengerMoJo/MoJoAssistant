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
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

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
    if reg is None:
        cfg = load_config()
        reg = HostRegistry(cfg.get("hosts", {}))
    _registry = reg
    _mcp = FastMCP(
        "agent-bridge",
        instructions=(
            "Bridge to MoJoAssistant managed OpenCode agents. "
            "Use agent_run to start a coding task, agent_reply to continue, "
            "agent_sessions to see what's in flight."
        ),
    )
    _register_tools(_mcp, reg)
    return _mcp, reg


# ------------------------------------------------------------------
# Tools
# ------------------------------------------------------------------


def _register_tools(mcp: FastMCP, reg: HostRegistry) -> None:

    @mcp.tool()
    async def agent_servers() -> Dict[str, Any]:
        """List configured OpenCode hosts and their reachability."""
        hosts = reg.list_hosts()
        out: Dict[str, Any] = {}
        for name, url in hosts.items():
            try:
                client = reg.get_client(name)
                await client.health()
                out[name] = {"status": "ok", "url": url}
            except Exception as exc:
                out[name] = {"status": "unreachable", "url": url, "error": str(exc)}
        return out

    @mcp.tool()
    async def agent_status(
        server: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
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
    ) -> Dict[str, Any]:
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
    ) -> Dict[str, Any]:
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
    ) -> Dict[str, Any]:
        """Delete a session on an OpenCode host."""
        client = reg.get_client(server)
        await client.delete_session(session_id)
        return {"deleted": session_id, "server": server}


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
