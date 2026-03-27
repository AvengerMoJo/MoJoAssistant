"""
DataBoundaryChecker — gates calls to external MCP tools based on the
role's data_boundary configuration.

External MCP tools follow the server_id__tool_name naming convention
(double underscore) used by MCPClientManager when registering discovered
tools. Built-in tools (bash_exec, read_file, memory_search, ask_user,
etc.) never contain '__' and are always allowed through.

Role config example:
  "data_boundary": {
    "allow_external_mcp": false
  }

Default (when data_boundary is absent or allow_external_mcp is omitted)
is true — permissive, so existing roles are unaffected.

The tier constraint (allowed_tiers) is enforced at the resource-acquisition
level in AgenticExecutor, not here, because it governs LLM calls rather
than individual tool dispatches.
"""

import logging
from typing import Any, Dict

from app.scheduler.policy.base import PolicyChecker, PolicyDecision

logger = logging.getLogger(__name__)


class DataBoundaryChecker(PolicyChecker):
    """
    Blocks calls to external MCP tools when the role opts out of
    external MCP access via data_boundary.allow_external_mcp=false.
    """

    name = "data_boundary"

    def __init__(self) -> None:
        self._allow_external_mcp: bool = True

    def configure(self, context: Dict[str, Any]) -> None:
        data_boundary = context.get("data_boundary") or {}
        self._allow_external_mcp = bool(
            data_boundary.get("allow_external_mcp", True)
        )
        if not self._allow_external_mcp:
            logger.debug("[policy/data_boundary] external MCP tools are blocked for this role")

    def check(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> PolicyDecision:
        if self._allow_external_mcp:
            return PolicyDecision.allow(checker=self.name)

        # External MCP tools are identified by the server_id__tool_name convention
        if "__" in tool_name:
            return PolicyDecision.block(
                reason=(
                    f"Tool '{tool_name}' is an external MCP tool. "
                    "This role's data_boundary disallows external MCP calls "
                    "(data_boundary.allow_external_mcp=false)."
                ),
                checker=self.name,
                metadata={"tool": tool_name},
            )

        # Dispatch tools send work to other roles — same isolation boundary as external MCP
        if tool_name in ("dispatch_subtask", "scheduler_add_task"):
            return PolicyDecision.block(
                reason=(
                    f"Tool '{tool_name}' dispatches work to another role. "
                    "This role's data_boundary disallows outbound dispatch "
                    "(data_boundary.allow_external_mcp=false)."
                ),
                checker=self.name,
                metadata={"tool": tool_name},
            )

        return PolicyDecision.allow(checker=self.name)
