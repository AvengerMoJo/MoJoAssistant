"""
PolicyMonitor — coordinator that runs a pipeline of PolicyCheckers.

Usage (same API as the old policy_monitor.py):

    monitor = PolicyMonitor.from_role(role_id, role_dict)
    decision = monitor.check("bash_exec", {"command": "ls"})
    if not decision.allowed:
        raise PolicyViolation(decision.reason)
    monitor.record_call("bash_exec")

Extending with a custom checker:

    from app.scheduler.policy.base import PolicyChecker, PolicyDecision

    class MyChecker(PolicyChecker):
        name = "my_checker"
        def check(self, tool_name, args, context):
            ...

    PolicyMonitor.register_checker("my_checker", MyChecker)

    # Then in a role JSON:
    # "policy": { "checkers": ["static", "content", "my_checker"] }

Future MCP checker example:

    class MCPPolicyChecker(PolicyChecker):
        name = "mcp"
        async def check(self, tool_name, args, context):
            result = await mcp_client.call("policy_agent", "check", {...})
            return PolicyDecision(**result)
    PolicyMonitor.register_checker("mcp", MCPPolicyChecker)
"""

import logging
from typing import Any, Dict, List, Optional, Type

from app.scheduler.policy.base import PolicyChecker, PolicyDecision
from app.scheduler.policy.static import StaticPolicyChecker
from app.scheduler.policy.content import ContentAwarePolicyChecker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Checker registry — maps string names to checker classes
# ---------------------------------------------------------------------------

_CHECKER_REGISTRY: Dict[str, Type[PolicyChecker]] = {
    "static": StaticPolicyChecker,
    "content": ContentAwarePolicyChecker,
}


class PolicyMonitor:
    """
    Runs an ordered pipeline of PolicyCheckers before each tool call.

    Default pipeline: [StaticPolicyChecker, ContentAwarePolicyChecker]
    Configurable per role via "policy": { "checkers": ["static", "content"] }
    """

    def __init__(
        self,
        role_id: Optional[str],
        policy: Optional[Dict[str, Any]],
        checkers: Optional[List[PolicyChecker]] = None,
    ) -> None:
        self.role_id = role_id
        self._policy = policy or {}
        self._checkers: List[PolicyChecker] = checkers or []
        self._context: Dict[str, Any] = {
            "role_id": role_id,
            "policy": self._policy,
            "call_counts": {},
        }
        for checker in self._checkers:
            checker.configure(self._context)

    @classmethod
    def register_checker(cls, name: str, checker_class: Type[PolicyChecker]) -> None:
        """Register a custom checker class under a name for use in role config."""
        _CHECKER_REGISTRY[name] = checker_class

    @classmethod
    def from_role(
        cls,
        role_id: Optional[str],
        role: Optional[Dict[str, Any]],
    ) -> "PolicyMonitor":
        """
        Build a PolicyMonitor from a loaded role dict.

        The role's policy block may specify a 'checkers' list to control which
        checkers run and in what order. Defaults to ["static", "content"].

        Example:
            "policy": {
                "checkers": ["static", "content"],   # default
                "denied_tools": ["bash_exec"],
                "content_check": true
            }
        """
        policy = (role.get("policy") if role else None) or {}
        checker_names: List[str] = policy.get("checkers", ["static", "content"])

        checkers: List[PolicyChecker] = []
        for name in checker_names:
            klass = _CHECKER_REGISTRY.get(name)
            if klass is None:
                logger.warning("PolicyMonitor: unknown checker '%s' for role '%s' — skipping", name, role_id)
                continue
            checkers.append(klass())

        return cls(role_id=role_id, policy=policy, checkers=checkers)

    # ------------------------------------------------------------------
    # Public interface (unchanged from old PolicyMonitor)
    # ------------------------------------------------------------------

    def check(self, tool_name: str, args: Dict[str, Any]) -> PolicyDecision:
        """
        Run all checkers. First BLOCK decision wins.
        Returns PolicyDecision(allowed=True) if all checkers pass.
        """
        for checker in self._checkers:
            decision = checker.check(tool_name, args, self._context)
            if not decision.allowed:
                logger.warning(
                    "PolicyMonitor [%s]: BLOCK '%s' — %s",
                    checker.name, tool_name, decision.reason,
                )
                return decision
            if decision.warn:
                logger.warning(
                    "PolicyMonitor [%s]: WARN '%s' — %s",
                    checker.name, tool_name, decision.reason,
                )
        return PolicyDecision.allow()

    def record_call(self, tool_name: str) -> None:
        """Notify all checkers that a tool call completed."""
        counts = self._context.setdefault("call_counts", {})
        counts[tool_name] = counts.get(tool_name, 0) + 1
        for checker in self._checkers:
            checker.record_call(tool_name)

    def validate_available_tools(self, available_tools: List[str]) -> List[str]:
        """Setup-time validation across all checkers."""
        violations: List[str] = []
        for checker in self._checkers:
            violations.extend(checker.validate_available_tools(available_tools))
        return violations

    def is_empty(self) -> bool:
        """True if no checkers are configured."""
        return not self._checkers
