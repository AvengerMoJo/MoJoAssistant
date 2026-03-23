"""
MCPClientManager — connects MoJo's agent executor to external MCP servers.

Any MCP server listed in config/mcp_servers.json is connected at executor
startup. Each server's tools are auto-registered in the DynamicToolRegistry
with executor type "external_mcp" and the server's category (e.g. "browser").

Roles that declare tool_access: ["browser"] automatically receive all tools
discovered from servers in that category — no manual registration needed.

Example config/mcp_servers.json entry:
  {
    "id": "playwright",
    "name": "Playwright MCP",
    "transport": "stdio",
    "command": "npx",
    "args": ["@playwright/mcp@latest", "--headless"],
    "category": "browser",
    "enabled": true
  }
"""

import json
import logging
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ExternalMCPServer:
    id: str
    name: str
    transport: str          # "stdio" (HTTP planned)
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    category: str = "external"
    enabled: bool = True


class MCPClientManager:
    """
    Manages long-lived connections to external MCP servers.

    Usage:
        manager = MCPClientManager()
        count = await manager.discover_and_register(tool_registry)
        # tools are now available in the registry
        result = await manager.call_tool("playwright", "browser_navigate", {"url": "..."})
        await manager.close()
    """

    def __init__(self, config_path: str = "config/mcp_servers.json"):
        self._config_path = config_path
        self._servers: Dict[str, ExternalMCPServer] = {}
        self._sessions: Dict[str, Any] = {}   # server_id → ClientSession
        self._exit_stack = AsyncExitStack()
        self._connected = False
        self._load_config()

    def _load_config(self) -> None:
        """Load system config then merge personal config (~/.memory/config/mcp_servers.json).
        Personal entries override system entries with the same id."""
        from app.config.paths import get_memory_subpath
        personal_path = get_memory_subpath("config", "mcp_servers.json")
        for path in [self._config_path, personal_path]:
            self._load_config_file(path)

    def _load_config_file(self, path: str) -> None:
        """Parse a single mcp_servers.json file and merge its entries into _servers."""
        if not os.path.exists(path):
            return

        def _expand(s: str) -> str:
            return os.path.expanduser(os.path.expandvars(s))

        try:
            with open(path) as f:
                data = json.load(f)
            for srv in data.get("servers", []):
                if not srv.get("enabled", True):
                    continue
                s = ExternalMCPServer(
                    id=srv["id"],
                    name=srv.get("name", srv["id"]),
                    transport=srv.get("transport", "stdio"),
                    command=_expand(srv["command"]),
                    args=[_expand(a) for a in srv.get("args", [])],
                    env=srv.get("env", {}),
                    category=srv.get("category", "external"),
                    enabled=True,
                )
                self._servers[s.id] = s  # personal layer overwrites system layer
        except Exception as e:
            logger.warning(f"MCPClientManager: failed to load {path}: {e}")

    def has_servers(self) -> bool:
        """Return True if at least one enabled MCP server is configured."""
        return bool(self._servers)

    async def connect_all(self) -> Dict[str, List[Any]]:
        """
        Connect to all configured servers. Returns {server_id: [MCPTool, ...]}.
        Safe to call multiple times — skips already-connected servers.
        """
        results: Dict[str, List[Any]] = {}
        for server_id, server in self._servers.items():
            if server_id in self._sessions:
                continue
            try:
                tools = await self._connect_server(server)
                results[server_id] = tools
                logger.info(
                    f"MCPClientManager: connected '{server_id}' "
                    f"({len(tools)} tools: {[t.name for t in tools]})"
                )
            except Exception as e:
                logger.warning(f"MCPClientManager: failed to connect '{server_id}': {e}")
        self._connected = True
        return results

    async def _connect_server(self, server: ExternalMCPServer) -> List[Any]:
        if server.transport != "stdio":
            raise NotImplementedError(f"Transport '{server.transport}' not yet supported")

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        env = {**os.environ, **server.env} if server.env else None
        params = StdioServerParameters(
            command=server.command,
            args=server.args,
            env=env,
        )
        read, write = await self._exit_stack.enter_async_context(stdio_client(params))
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._sessions[server.id] = session

        response = await session.list_tools()
        return response.tools

    async def discover_and_register(self, tool_registry) -> int:
        """
        Connect to all servers, discover their tools, and register them in
        the DynamicToolRegistry with executor type "external_mcp".

        Tool names are prefixed with the server id to avoid collisions:
          playwright + browser_navigate → "playwright__browser_navigate"

        Returns the number of tools newly registered.
        """
        from app.scheduler.dynamic_tool_registry import ToolDefinition

        server_tools = await self.connect_all()
        count = 0
        for server_id, tools in server_tools.items():
            server = self._servers[server_id]
            for tool in tools:
                registered_name = f"{server_id}__{tool.name}"
                if tool_registry.get_tool(registered_name):
                    continue  # already registered

                schema = tool.inputSchema
                if not isinstance(schema, dict):
                    schema = {"type": "object", "properties": {}}

                td = ToolDefinition(
                    name=registered_name,
                    description=tool.description or f"{tool.name} (via {server.name})",
                    danger_level="low",
                    category=server.category,
                    parameters=schema,
                    executor={
                        "type": "external_mcp",
                        "server": server_id,
                        "tool": tool.name,
                    },
                )
                tool_registry._tools[registered_name] = td
                count += 1

        if count:
            tool_registry._save_registry()
            logger.info(f"MCPClientManager: registered {count} external tools")
        return count

    async def call_tool(self, server_id: str, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on a specific external MCP server."""
        if not self._connected:
            await self.connect_all()

        session = self._sessions.get(server_id)
        if not session:
            return {"success": False, "error": f"Server '{server_id}' not connected"}

        try:
            result = await session.call_tool(tool_name, args)
            # MCP returns a list of content blocks (text, image, resource)
            parts = []
            for block in (result.content or []):
                if hasattr(block, "text"):
                    parts.append(block.text)
                elif hasattr(block, "data"):
                    # Image block — pass base64 data for vision models
                    parts.append({
                        "type": "image",
                        "format": getattr(block, "mimeType", "image/png").split("/")[-1],
                        "data": block.data,
                    })
                elif hasattr(block, "uri"):
                    parts.append({"type": "resource", "uri": block.uri})

            payload = parts[0] if len(parts) == 1 else parts
            return {
                "success": not getattr(result, "isError", False),
                "result": payload,
            }
        except Exception as e:
            return {"success": False, "error": f"Tool call failed: {e}"}

    def get_server_for_registered_name(self, registered_name: str) -> Optional[Tuple[str, str]]:
        """
        Given 'playwright__browser_navigate', return ('playwright', 'browser_navigate').
        Returns None if the server is not managed by this instance.
        """
        if "__" in registered_name:
            server_id, tool_name = registered_name.split("__", 1)
            if server_id in self._servers:
                return server_id, tool_name
        return None

    async def close(self) -> None:
        """Disconnect all servers and release resources."""
        await self._exit_stack.aclose()
        self._sessions.clear()
        self._connected = False
