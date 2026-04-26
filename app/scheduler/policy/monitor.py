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
# [hitl-orchestrator: generic]

import logging
from typing import Any, Dict, List, Optional, Type

from app.scheduler.policy.base import PolicyChecker, PolicyDecision
from app.scheduler.policy.static import StaticPolicyChecker
from app.scheduler.policy.content import ContentAwarePolicyChecker
from app.scheduler.policy.data_boundary_checker import DataBoundaryChecker
from app.scheduler.policy.context import ContextAwarePolicyChecker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Checker registry — maps string names to checker classes
# ---------------------------------------------------------------------------

_CHECKER_REGISTRY: Dict[str, Type[PolicyChecker]] = {
    "static": StaticPolicyChecker,
    "content": ContentAwarePolicyChecker,
    "data_boundary": DataBoundaryChecker,
    "context": ContextAwarePolicyChecker,
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
        data_boundary: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
    ) -> None:
        self.role_id = role_id
        self._policy = policy or {}
        self._checkers: List[PolicyChecker] = checkers or []
        self._violation_total: int = 0  # cumulative blocks across all calls this task
        self._data_boundary: Dict[str, Any] = data_boundary or {}
        self._context: Dict[str, Any] = {
            "role_id": role_id,
            "task_id": task_id,
            "policy": self._policy,
            "data_boundary": data_boundary or {},
            "call_counts": {},
            "violation_total": 0,
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
        task_id: Optional[str] = None,
    ) -> "PolicyMonitor":
        """
        Build a PolicyMonitor from a loaded role dict.

        The role's policy block may specify a 'checkers' list to control which
        checkers run and in what order. Defaults to ["static", "content"].

        data_boundary is read from role["data_boundary"] and passed into
        checker context so DataBoundaryChecker can enforce it.

        ContextAwarePolicyChecker should always be last — it reads
        violation_total accumulated by earlier checkers in the same task.

        Example:
            "policy": {
                "checkers": ["static", "content", "data_boundary", "context"],
                "context_rules": { "max_violations_before_halt": 3 }
            }
            "data_boundary": {
                "allow_external_mcp": false,
                "allowed_tiers": ["free"]
            }

        local_only shorthand:
            "local_only": true
            Equivalent to data_boundary: {allow_external_mcp: false, allowed_tiers: ["free"]}.
            Explicit data_boundary values take precedence over local_only defaults.
        """
        policy = dict((role.get("policy") if role else None) or {})
        data_boundary = dict((role.get("data_boundary") if role else None) or {})

        # local_only: true is syntactic sugar for the most restrictive data_boundary.
        # Explicit data_boundary values take precedence over local_only defaults.
        if role and role.get("local_only"):
            data_boundary.setdefault("allow_external_mcp", False)
            data_boundary.setdefault("allowed_tiers", ["free"])

        # Trust-level coupling: owner_profile.assistant_relationships[role_id].trust_level
        # fills policy and data_boundary gaps before explicit role values are applied.
        # Explicit role policy always wins — trust_level only sets defaults.
        try:
            from app.scheduler.policy.relationship_coupler import apply_trust_defaults
            policy, data_boundary = apply_trust_defaults(role_id, policy, data_boundary)
        except Exception as _e:
            logger.debug("RelationshipPolicyCoupler skipped: %s", _e)

        checker_names: List[str] = policy.get("checkers", ["static", "content", "sensitive_domain"])

        checkers: List[PolicyChecker] = []
        for name in checker_names:
            klass = _CHECKER_REGISTRY.get(name)
            if klass is None:
                logger.warning("PolicyMonitor: unknown checker '%s' for role '%s' — skipping", name, role_id)
                continue
            checkers.append(klass())

        return cls(
            role_id=role_id,
            policy=policy,
            checkers=checkers,
            data_boundary=data_boundary,
            task_id=task_id,
        )

    # ------------------------------------------------------------------
    # Public interface (unchanged from old PolicyMonitor)
    # ------------------------------------------------------------------

    def check(self, tool_name: str, args: Dict[str, Any]) -> PolicyDecision:
        """
        Run all checkers. First BLOCK decision wins.
        Returns PolicyDecision(allowed=True) if all checkers pass.

        violation_total in context is updated before each call so
        ContextAwarePolicyChecker (if last) can enforce a halt ceiling.
        """
        # Expose accumulated violation count to checkers (read by ContextAwarePolicyChecker)
        self._context["violation_total"] = self._violation_total

        for checker in self._checkers:
            decision = checker.check(tool_name, args, self._context)
            if not decision.allowed:
                self._violation_total += 1
                self._context["violation_total"] = self._violation_total
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

    @property
    def data_boundary(self) -> Dict[str, Any]:
        """The resolved data_boundary config (after local_only expansion)."""
        return self._data_boundary

    def is_empty(self) -> bool:
        """True if no checkers are configured."""
        return not self._checkers
