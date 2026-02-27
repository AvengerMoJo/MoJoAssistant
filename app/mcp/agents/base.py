"""
Base Agent Manager ABC

Defines the lifecycle interface that all agent managers must implement.
Agent managers handle process lifecycle only (start/stop/restart/health).
Coding tools are exposed by external MCP tool projects.

File: app/mcp/agents/base.py
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List


class BaseAgentManager(ABC):
    """Base class for all agent managers.

    Manages process lifecycle for coding agent subprocesses.
    Does NOT expose coding tools — those are handled by external MCP tool projects.
    """

    # Subclasses must set these
    agent_type: str  # e.g. "opencode", "claude_code"
    identifier_description: str  # e.g. "git_url", "session_id"

    @abstractmethod
    async def start_project(self, identifier: str, **kwargs) -> Dict[str, Any]:
        """Start an agent instance identified by identifier (e.g. git_url, session_id)."""

    @abstractmethod
    async def stop_project(self, identifier: str) -> Dict[str, Any]:
        """Stop an agent instance."""

    @abstractmethod
    async def get_status(self, identifier: str) -> Dict[str, Any]:
        """Get agent instance status."""

    @abstractmethod
    async def list_projects(self) -> Dict[str, Any]:
        """List all managed instances."""

    @abstractmethod
    async def restart_project(self, identifier: str) -> Dict[str, Any]:
        """Restart an agent instance."""

    @abstractmethod
    async def destroy_project(self, identifier: str) -> Dict[str, Any]:
        """Destroy an agent instance and clean up resources."""

    def get_supported_actions(self) -> List[Dict[str, Any]]:
        """Return list of backend-specific actions this manager supports.

        Each action is a dict with 'action' name and 'params' list.
        Override in subclasses to expose extra functionality via agent_action.
        """
        return []

    async def execute_action(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a backend-specific action. Override in subclasses.

        Args:
            action: Action name (e.g. 'sandbox_create', 'llm_config')
            params: Action-specific parameters

        Returns:
            Result dictionary
        """
        supported = self.get_supported_actions()
        action_names = [a["action"] for a in supported]
        return {
            "status": "error",
            "message": f"Action '{action}' not supported by {self.agent_type}",
            "supported_actions": action_names,
        }
