"""
MCPServerManager — BaseAgentManager implementation for external MCP servers.

Bridges MCPClientManager into the AgentRegistry so that MCP servers
(playwright, tmux, etc.) appear alongside OpenCode/ClaudeCode in:
  agent(action="list")
  agent(action="status",  agent_id="playwright")
  agent(action="restart", agent_id="tmux")
  agent(action="stop",    agent_id="playwright")
  agent(action="start",   agent_id="playwright")  ← reconnect

The "identifier" for an MCP server is its server_id from mcp_servers.json.
"""

import logging
from typing import Any, Dict, List, TYPE_CHECKING

from app.mcp.agents.base import BaseAgentManager

if TYPE_CHECKING:
    from app.scheduler.mcp_client_manager import MCPClientManager

logger = logging.getLogger(__name__)


class MCPServerManager(BaseAgentManager):
    """
    Lifecycle manager for external MCP servers registered in mcp_servers.json.

    One instance manages all MCP servers — each server_id is its own "project".
    """

    agent_type = "mcp_server"
    identifier_description = "server_id (e.g. 'playwright', 'tmux')"

    def __init__(self, mcp_client_manager: "MCPClientManager"):
        self._mgr = mcp_client_manager

    # ------------------------------------------------------------------
    # BaseAgentManager interface
    # ------------------------------------------------------------------

    async def start_project(self, identifier: str, **kwargs) -> Dict[str, Any]:
        """Connect (or reconnect) a specific MCP server."""
        server = self._mgr._servers.get(identifier)
        if not server:
            configured = list(self._mgr._servers.keys())
            return {
                "status": "error",
                "message": f"Unknown MCP server '{identifier}'. Configured: {configured}",
            }

        # Already connected — treat as a no-op (use restart to force reconnect)
        if identifier in self._mgr._sessions:
            return {
                "status": "ok",
                "message": f"MCP server '{identifier}' is already connected.",
            }

        try:
            tools = await self._mgr._connect_server(server)
            return {
                "status": "success",
                "message": f"MCP server '{identifier}' connected ({len(tools)} tools).",
                "tool_count": len(tools),
                "tools": [t.name for t in tools],
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to connect '{identifier}': {e}"}

    async def stop_project(self, identifier: str) -> Dict[str, Any]:
        """Disconnect a specific MCP server (others keep running).

        AsyncExitStack doesn't support partial close, so we close all sessions
        and reconnect the remaining ones.  If any reconnect fails we attempt
        a single rollback retry; if that also fails we report partial success
        rather than lying with a clean "success" response.
        """
        if identifier not in self._mgr._servers:
            return {"status": "error", "message": f"Unknown MCP server '{identifier}'"}

        if identifier not in self._mgr._sessions:
            return {"status": "ok", "message": f"MCP server '{identifier}' was not connected."}

        # Close all sessions atomically
        session_ids = list(self._mgr._sessions.keys())
        try:
            await self._mgr._exit_stack.aclose()
        except Exception:
            pass
        self._mgr._sessions.clear()
        self._mgr._exit_stack.__init__()
        self._mgr._connected = False

        # Reconnect every server except the one being stopped
        others = [sid for sid in session_ids if sid != identifier]
        reconnected: List[str] = []
        failed: List[str] = []

        for sid in others:
            srv = self._mgr._servers.get(sid)
            if srv:
                try:
                    await self._mgr._connect_server(srv)
                    reconnected.append(sid)
                except Exception as e:
                    logger.warning(f"MCPServerManager: could not reconnect '{sid}' after stop: {e}")
                    failed.append(sid)

        # Rollback: retry each failed server once before giving up
        still_failed: List[str] = []
        for sid in failed:
            srv = self._mgr._servers.get(sid)
            if srv:
                try:
                    await self._mgr._connect_server(srv)
                    reconnected.append(sid)
                    logger.info(f"MCPServerManager: rollback reconnect succeeded for '{sid}'")
                except Exception as e:
                    logger.error(f"MCPServerManager: rollback failed for '{sid}': {e}")
                    still_failed.append(sid)

        # Mark connected regardless — at least some servers may be up.
        # call_tool() will surface errors for any dead sessions naturally.
        self._mgr._connected = True

        if still_failed:
            return {
                "status": "partial",
                "message": (
                    f"MCP server '{identifier}' disconnected, but {len(still_failed)} "
                    f"server(s) could not be reconnected after rollback: {still_failed}"
                ),
                "reconnected": reconnected,
                "failed": still_failed,
            }

        return {"status": "success", "message": f"MCP server '{identifier}' disconnected."}

    async def get_status(self, identifier: str) -> Dict[str, Any]:
        """Return connection status for a single MCP server."""
        server = self._mgr._servers.get(identifier)
        if not server:
            return {"status": "error", "message": f"Unknown MCP server '{identifier}'"}

        connected = identifier in self._mgr._sessions
        return {
            "status": "success",
            "id": identifier,
            "name": server.name,
            "category": server.category,
            "command": server.command,
            "args": server.args,
            "connected": connected,
            "state": "connected" if connected else "disconnected",
        }

    async def list_projects(self) -> Dict[str, Any]:
        """List all configured MCP servers and their connection state."""
        servers = []
        for server_id, server in self._mgr._servers.items():
            servers.append({
                "id": server_id,
                "name": server.name,
                "category": server.category,
                "command": server.command,
                "connected": server_id in self._mgr._sessions,
                "state": "connected" if server_id in self._mgr._sessions else "disconnected",
                "agent_type": self.agent_type,
            })
        return {
            "status": "success",
            "agents": servers,   # "agents" key for compatibility with agent(action="list") aggregator
            "servers": servers,  # also kept for direct callers
            "count": len(servers),
        }

    async def restart_project(self, identifier: str) -> Dict[str, Any]:
        """Disconnect and reconnect a specific MCP server."""
        stop_result = await self.stop_project(identifier)
        if stop_result.get("status") == "error":
            return stop_result
        start_result = await self.start_project(identifier)
        # Surface rollback warnings from stop alongside the start result
        if stop_result.get("status") == "partial":
            start_result["warning"] = stop_result.get("message", "")
            start_result["failed_siblings"] = stop_result.get("failed", [])
        return start_result

    async def destroy_project(self, identifier: str) -> Dict[str, Any]:
        """Same as stop for MCP servers (no persistent state to clean up)."""
        return await self.stop_project(identifier)

    def get_supported_actions(self) -> List[Dict[str, Any]]:
        """Return the list of custom actions supported by this manager."""
        return [
            {"action": "list_servers", "params": [], "description": "List all MCP servers and their state"},
            {"action": "reconnect_all", "params": [], "description": "Reconnect all configured MCP servers"},
        ]

    async def execute_action(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch a custom action (list_servers, reconnect_all)."""
        if action == "list_servers":
            return await self.list_projects()
        if action == "reconnect_all":
            results = {}
            for server_id in list(self._mgr._servers.keys()):
                results[server_id] = await self.restart_project(server_id)
            return {"status": "success", "results": results}
        return await super().execute_action(action, params)
