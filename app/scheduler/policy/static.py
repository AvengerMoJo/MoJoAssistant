"""
StaticPolicyChecker — rule-based enforcement from role config.

Implements the original PolicyMonitor logic as a pluggable checker:
  1. denied_tools      — always blocked
  2. allowed_tools     — allowlist (if set, anything not listed is blocked)
  3. per-tool limits   — max_{tool}_per_task counters
  4. require_confirmation_for — allowed but flagged
"""
# [hitl-orchestrator: generic]

from typing import Any, Dict, List

from app.scheduler.policy.base import PolicyChecker, PolicyDecision


class StaticPolicyChecker(PolicyChecker):
    """
    Enforces static rules declared in the role's "policy" config block.

    Example role policy:
        "policy": {
            "allowed_tools": ["bash_exec", "read_file"],
            "denied_tools": ["write_file"],
            "max_bash_exec_per_task": 20,
            "require_confirmation_for": ["bash_exec"]
        }
    """

    name = "static"

    def __init__(self) -> None:
        self._policy: Dict[str, Any] = {}
        self._role_id: str = ""
        self._counters: Dict[str, int] = {}

    def configure(self, context: Dict[str, Any]) -> None:
        self._policy = context.get("policy") or {}
        self._role_id = context.get("role_id") or ""
        self._counters = {}

    def check(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> PolicyDecision:
        p = self._policy

        # 1. Denied tools — hard block
        if tool_name in p.get("denied_tools", []):
            return PolicyDecision.block(
                reason=f"Tool '{tool_name}' is in role '{self._role_id}' denied_tools list",
                checker=self.name,
            )

        # 2. Allowed tools allowlist
        allowed: List[str] = p.get("allowed_tools", [])
        if allowed and tool_name not in allowed:
            return PolicyDecision.block(
                reason=f"Tool '{tool_name}' is not in role '{self._role_id}' allowed_tools list",
                checker=self.name,
            )

        # 3. Per-tool execution limits
        limit = p.get(f"max_{tool_name}_per_task")
        if limit is not None:
            if self._counters.get(tool_name, 0) >= limit:
                return PolicyDecision.block(
                    reason=f"Tool '{tool_name}' exceeded per-task limit of {limit} calls",
                    checker=self.name,
                )

        # 4. Confirmation required — allowed but flagged
        if tool_name in p.get("require_confirmation_for", []):
            return PolicyDecision.allow(
                reason=f"Tool '{tool_name}' requires confirmation (proceeding in autonomous mode)",
                warn=True,
                checker=self.name,
            )

        return PolicyDecision.allow(checker=self.name)

    def record_call(self, tool_name: str) -> None:
        self._counters[tool_name] = self._counters.get(tool_name, 0) + 1

    def validate_available_tools(self, available_tools: List[str]) -> List[str]:
        allowed: List[str] = self._policy.get("allowed_tools", [])
        denied: List[str] = self._policy.get("denied_tools", [])
        if not allowed and not denied:
            return []
        violations = []
        for tool in available_tools:
            if tool in denied:
                violations.append(f"Tool '{tool}' is denied by role '{self._role_id}' policy")
            elif allowed and tool not in allowed:
                violations.append(
                    f"Tool '{tool}' is not permitted by role '{self._role_id}' allowed_tools ceiling"
                )
        return violations
