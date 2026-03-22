"""
Agent Registry

Central registry of all agent managers. Provides unified access to
any agent type via a single interface.

File: app/mcp/agents/registry.py
"""

import os
from typing import Dict, Any, List, Optional, Tuple

from app.mcp.agents.base import BaseAgentManager


class AgentRegistry:
    """Central registry of all agent managers.

    Auto-registers enabled managers based on environment variables.
    Provides a single entry point for all agent lifecycle operations.
    """

    def __init__(self, logger=None, mcp_client_manager=None):
        self._managers: Dict[str, BaseAgentManager] = {}
        self._init_errors: Dict[str, str] = {}
        self.logger = logger

        # MCP server manager — always registered when a client manager is provided
        if mcp_client_manager is not None:
            try:
                from app.mcp.agents.mcp_server_manager import MCPServerManager
                self._managers["mcp_server"] = MCPServerManager(mcp_client_manager)
            except Exception as e:
                self._init_errors["mcp_server"] = str(e)
                self._log(f"MCPServerManager failed to initialize: {e}", "warning")

        # Auto-register enabled managers
        if os.getenv("ENABLE_OPENCODE", "false").lower() in ("true", "1", "yes"):
            try:
                from app.mcp.opencode.manager import OpenCodeManager
                self._managers["opencode"] = OpenCodeManager(logger=logger)
            except Exception as e:
                self._init_errors["opencode"] = str(e)
                self._log(f"OpenCode Manager failed to initialize: {e}", "warning")

        if os.getenv("ENABLE_CLAUDE_CODE", "false").lower() in ("true", "1", "yes"):
            try:
                from app.mcp.claude_code.manager import ClaudeCodeManager
                self._managers["claude_code"] = ClaudeCodeManager(logger=logger)
            except Exception as e:
                self._init_errors["claude_code"] = str(e)
                self._log(f"Claude Code Manager failed to initialize: {e}", "warning")

    def _log(self, message: str, level: str = "info"):
        if self.logger:
            getattr(self.logger, level, self.logger.info)(
                f"[AgentRegistry] {message}"
            )

    def list_types(self) -> List[Dict[str, Any]]:
        """Return enabled agent types with their supported actions."""
        result = []
        for name, mgr in self._managers.items():
            result.append({
                "agent_type": name,
                "identifier_description": mgr.identifier_description,
                "supported_actions": mgr.get_supported_actions(),
            })
        return result

    def get_manager(self, agent_type: str) -> BaseAgentManager:
        """Get manager by type.

        Raises:
            ValueError: If agent_type is not registered or not enabled.
        """
        if agent_type in self._managers:
            return self._managers[agent_type]

        if agent_type in self._init_errors:
            raise ValueError(
                f"Agent type '{agent_type}' failed to initialize: "
                f"{self._init_errors[agent_type]}"
            )

        available = list(self._managers.keys())
        raise ValueError(
            f"Unknown agent type '{agent_type}'. "
            f"Available types: {available or 'none (no agents enabled)'}"
        )

    def has_manager(self, agent_type: str) -> bool:
        """Check if an agent type is registered and available."""
        return agent_type in self._managers

    async def find_manager_for_agent(
        self, agent_id: str
    ) -> Optional[Tuple[str, "BaseAgentManager"]]:
        """Find which manager owns an agent by its identifier.

        Searches across all registered managers so callers don't need to know
        or pass the agent_type for lifecycle operations (stop/restart/destroy/status).

        Matches against common identifier fields: git_url, name, identifier, id.

        Returns:
            (agent_type, manager) tuple if found, None otherwise.
        """
        for atype, manager in self._managers.items():
            try:
                result = await manager.list_projects()
                projects = result.get("projects") or result.get("agents") or []
                for p in projects:
                    if not isinstance(p, dict):
                        continue
                    if agent_id in (
                        p.get("git_url"),
                        p.get("name"),
                        p.get("identifier"),
                        p.get("id"),
                    ):
                        return atype, manager
            except Exception:
                pass
        return None

    @property
    def enabled_types(self) -> List[str]:
        """List of enabled agent type names."""
        return list(self._managers.keys())
