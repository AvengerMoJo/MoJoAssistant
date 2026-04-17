"""
MCPClientManager — connects MoJo's agent executor to external MCP servers.

Any MCP server listed in config/mcp_servers.json is connected at executor
startup. Each server's tools are auto-registered in the CapabilityRegistry
with executor type "external_mcp" and the server's category (e.g. "browser").

Roles that declare capabilities: ["browser"] automatically receive all tools
discovered from servers in that category — no manual registration needed.

Two transport models are supported:

  stdio  — MoJo spawns the process and communicates via stdin/stdout.
           Required fields: command, args.
           Example: Playwright MCP, tmux MCP.

  http   — The server is already running (started externally, by systemd,
           the user, or another process). MoJo registers how to reach it.
           Required fields: mcp_http_url OR port (fallback: localhost:{port}/mcp).
           Optional fields: pid (informational), authorization (Bearer token).
           Example: OpenCode, Google Workspace MCP, any long-running service.

The personal layer (~/.memory/config/mcp_servers.json) overrides system
entries with the same id. Users or internal assistants can add entries there
without touching the system config.
"""

import asyncio
import json
import logging
import os
from contextlib import AsyncExitStack
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ExternalMCPServer:
    id: str
    name: str
    transport: str                      # "stdio" | "http"
    # stdio fields
    command: str = ""
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    # http / externally-running fields
    mcp_http_url: Optional[str] = None  # full URL, e.g. http://localhost:3100/mcp
    port: Optional[int] = None          # fallback if mcp_http_url absent → localhost:{port}/mcp
    pid: Optional[int] = None           # informational only — not used for connection
    authorization: Optional[str] = None # Bearer token or raw API key
    # common
    category: str = "external"
    enabled: bool = True
    install_hint: str = ""


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
        # Lazily created in connect_all() so it's always bound to the running
        # event loop — creating asyncio.Lock() in __init__ (sync context) binds
        # it to whichever loop is current at construction time, which breaks after
        # a daemon_restart spins up a new event loop.
        self._connect_lock: Optional[asyncio.Lock] = None
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

        _project_root_str = str(Path(__file__).resolve().parent.parent.parent)

        def _expand(s: str) -> str:
            s = s.replace("{project_root}", _project_root_str)
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
                    command=_expand(srv.get("command", "")),
                    args=[_expand(a) for a in srv.get("args", [])],
                    env={k: _expand(v) for k, v in srv.get("env", {}).items()},
                    mcp_http_url=srv.get("mcp_http_url"),
                    port=srv.get("port"),
                    pid=srv.get("pid"),
                    authorization=srv.get("authorization") or os.environ.get(srv.get("authorization_env", "") or ""),
                    category=srv.get("category", "external"),
                    enabled=True,
                    install_hint=srv.get("install_hint", ""),
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
        Serialized via _connect_lock to prevent concurrent callers from
        double-connecting the same server.
        """
        if self._connect_lock is None:
            self._connect_lock = asyncio.Lock()
        async with self._connect_lock:
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
        if server.transport == "stdio":
            return await self._connect_stdio(server)
        elif server.transport in ("http", "streamable_http"):
            return await self._connect_http(server)
        else:
            raise NotImplementedError(f"Transport '{server.transport}' not yet supported")

    async def _connect_stdio(self, server: ExternalMCPServer) -> List[Any]:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        spawn_env = {**os.environ, **server.env} if server.env else dict(os.environ)
        _project_root = Path(__file__).resolve().parent.parent.parent
        args = list(server.args)
        # tmux-mcp-rs defaults to a socket named 'default.sock' which differs from
        # the standard tmux socket 'default'. Inject the correct socket path so agents
        # see the same sessions as the operator's terminal.
        if server.category == "terminal" and "--socket" not in args and "-s" not in args:
            tmux_socket = Path(f"/tmp/tmux-{os.getuid()}/default")
            if tmux_socket.exists():
                args += ["--socket", str(tmux_socket)]

        params = StdioServerParameters(
            command=server.command,
            args=args,
            env=spawn_env,
            cwd=str(_project_root),
        )
        read, write = await self._exit_stack.enter_async_context(stdio_client(params))
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._sessions[server.id] = session
        response = await session.list_tools()
        return response.tools

    async def _connect_http(self, server: ExternalMCPServer) -> List[Any]:
        """Connect to an externally-running MCP server over HTTP (Streamable HTTP)."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        url = server.mcp_http_url or f"http://localhost:{server.port}/mcp"
        headers: Dict[str, str] = {}
        if server.authorization:
            headers["Authorization"] = f"Bearer {server.authorization}"

        read, write, _ = await self._exit_stack.enter_async_context(
            streamablehttp_client(url, headers=headers or None)
        )
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._sessions[server.id] = session
        response = await session.list_tools()
        return response.tools

    async def discover_and_register(self, tool_registry) -> int:
        """
        Connect to all servers, discover their tools, and register them in
        the CapabilityRegistry with executor type "external_mcp".

        Tool names are prefixed with the server id to avoid collisions:
          playwright + browser_navigate → "playwright__browser_navigate"

        Returns the number of tools newly registered.
        """
        from app.scheduler.capability_registry import CapabilityDefinition

        server_tools = await self.connect_all()

        # Drop stale cached entries for servers we successfully connected to,
        # so renamed or removed tools don't linger across restarts.
        for server_id in server_tools:
            stale = [
                name for name, td in list(tool_registry._tools.items())
                if name.startswith(f"{server_id}__")
                and getattr(td, "executor", {}).get("type") == "external_mcp"
            ]
            for name in stale:
                del tool_registry._tools[name]

        count = 0
        for server_id, tools in server_tools.items():
            server = self._servers[server_id]
            for tool in tools:
                registered_name = f"{server_id}__{tool.name}"
                schema = tool.inputSchema
                if not isinstance(schema, dict):
                    schema = {"type": "object", "properties": {}}

                td = CapabilityDefinition(
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

    # Per-call timeout so a hung external process (e.g. frozen browser) cannot
    # hold a semaphore slot forever. 5 minutes gives SPAs like Portainer enough
    # time to load without blocking a semaphore slot indefinitely.
    CALL_TIMEOUT_SECONDS: float = 300.0

    async def call_tool(self, server_id: str, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on a specific external MCP server."""
        if not self._connected:
            await self.connect_all()

        session = self._sessions.get(server_id)
        if not session:
            return {"success": False, "error": f"Server '{server_id}' not connected"}

        try:
            result = await asyncio.wait_for(
                session.call_tool(tool_name, args),
                timeout=self.CALL_TIMEOUT_SECONDS,
            )
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
        except asyncio.TimeoutError:
            logger.warning(
                f"MCPClientManager: '{server_id}/{tool_name}' timed out "
                f"after {self.CALL_TIMEOUT_SECONDS}s"
            )
            return {"success": False, "error": f"Tool call timed out after {self.CALL_TIMEOUT_SECONDS}s"}
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
