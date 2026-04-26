"""
PolicyChecker — abstract base class for all policy enforcement implementations.

Any policy backend (static rules, content inspection, LLM agent, MCP service)
implements this interface and plugs into PolicyMonitor's checker pipeline.

Implementing a custom checker:

    class MyChecker(PolicyChecker):
        def check(self, tool_name, args, context):
            if something_bad(args):
                return PolicyDecision.block("reason")
            return PolicyDecision.allow()

    # Register via role config:
    # "policy": { "checkers": ["static", "my_checker"] }
    # Or register programmatically:
    PolicyMonitor.register_checker("my_checker", MyChecker)
"""
# [hitl-orchestrator: generic]

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PolicyDecision:
    """Result of a policy check."""
    allowed: bool
    reason: str = ""
    warn: bool = False          # allowed but log a warning
    checker: str = ""           # which checker made this decision
    metadata: Dict = field(default_factory=dict)

    @classmethod
    def allow(cls, reason: str = "", warn: bool = False, checker: str = "") -> "PolicyDecision":
        return cls(allowed=True, reason=reason, warn=warn, checker=checker)

    @classmethod
    def block(cls, reason: str, checker: str = "", metadata: Dict = None) -> "PolicyDecision":
        return cls(allowed=False, reason=reason, checker=checker, metadata=metadata or {})


class PolicyChecker(ABC):
    """
    Abstract base for a single policy enforcement layer.

    PolicyMonitor holds an ordered list of PolicyCheckers and runs them in
    sequence — first BLOCK decision wins. All checkers must ALLOW for the
    tool call to proceed.

    Lifecycle per task:
      __init__ / configure(context)  — called once at task start
      check(tool_name, args, context) — called before every tool dispatch
      record_call(tool_name)          — called after every successful tool call
      validate_available_tools(tools) — called once at setup time

    Future MCP-based checker:
      class MCPPolicyChecker(PolicyChecker):
          async def check(...): return await mcp_call("policy_check", ...)
      PolicyMonitor.register_checker("mcp", MCPPolicyChecker)
    """

    #: Short identifier used in role config and log messages
    name: str = "base"

    def configure(self, context: Dict[str, Any]) -> None:
        """
        Called once when the task starts, with task/role context.
        Override to do per-task initialisation (load role config, etc.).
        context keys: role_id, task_id, policy (role policy dict)
        """

    @abstractmethod
    def check(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> PolicyDecision:
        """
        Decide whether this tool call is permitted.

        Args:
            tool_name: Name of the tool being called.
            args:      Tool arguments dict.
            context:   Runtime context — role_id, task_id, iteration, call_counts.

        Returns:
            PolicyDecision with allowed=True or False.
        """

    def record_call(self, tool_name: str) -> None:
        """Called after a tool call completes successfully. Default: no-op."""

    def validate_available_tools(self, available_tools: List[str]) -> List[str]:
        """
        Setup-time check: verify a task's tool list is within policy.
        Returns a list of violation strings (empty = all OK).
        """
        return []
