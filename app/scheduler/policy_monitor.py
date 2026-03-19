"""
Role Policy Monitor

Runtime permission enforcement for agentic tasks.
Checks each tool call against the role's policy config before execution.

Policy is defined in the role JSON under the "policy" key:

  {
    "policy": {
      "allowed_tools": ["bash_exec", "memory_search", "read_file", "list_files"],
      "denied_tools": [],
      "require_confirmation_for": ["bash_exec"],
      "max_bash_exec_per_task": 20,
      "sandbox_paths_only": true
    }
  }

Priority order:
  1. denied_tools  — always blocked, no override
  2. allowed_tools — if set, anything not listed is blocked
  3. per-tool limits (e.g. max_bash_exec_per_task)
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PolicyDecision:
    def __init__(self, allowed: bool, reason: str = "", warn: bool = False):
        self.allowed = allowed
        self.reason = reason
        self.warn = warn  # True = allowed but log a warning


class PolicyMonitor:
    """
    Enforces a role's policy at runtime.

    One instance per task execution — tracks per-task counters (e.g. bash_exec count).
    """

    def __init__(self, role_id: Optional[str], policy: Optional[Dict[str, Any]]):
        self.role_id = role_id
        self._policy = policy or {}
        self._counters: Dict[str, int] = {}

    @classmethod
    def from_role(cls, role_id: Optional[str], role: Optional[Dict[str, Any]]) -> "PolicyMonitor":
        """Create a PolicyMonitor from a loaded role dict."""
        policy = role.get("policy") if role else None
        return cls(role_id=role_id, policy=policy)

    def check(self, tool_name: str, args: Dict[str, Any]) -> PolicyDecision:
        """
        Check whether a tool call is permitted under this role's policy.

        Returns a PolicyDecision with allowed=True/False and a reason string.
        """
        p = self._policy

        # 1. Denied tools — hard block
        denied: List[str] = p.get("denied_tools", [])
        if tool_name in denied:
            return PolicyDecision(
                allowed=False,
                reason=f"Tool '{tool_name}' is in role '{self.role_id}' denied_tools list",
            )

        # 2. Allowed tools allowlist — block anything not listed (if list is set)
        allowed: List[str] = p.get("allowed_tools", [])
        if allowed and tool_name not in allowed:
            return PolicyDecision(
                allowed=False,
                reason=f"Tool '{tool_name}' is not in role '{self.role_id}' allowed_tools list",
            )

        # 3. Per-tool execution limits
        limit_key = f"max_{tool_name}_per_task"
        limit = p.get(limit_key)
        if limit is not None:
            count = self._counters.get(tool_name, 0)
            if count >= limit:
                return PolicyDecision(
                    allowed=False,
                    reason=f"Tool '{tool_name}' exceeded per-task limit of {limit} calls",
                )

        # 4. Confirmation required — allowed but flagged (caller may act on this)
        confirm_list: List[str] = p.get("require_confirmation_for", [])
        if tool_name in confirm_list:
            return PolicyDecision(
                allowed=True,
                reason=f"Tool '{tool_name}' requires confirmation (proceeding in autonomous mode)",
                warn=True,
            )

        return PolicyDecision(allowed=True)

    def record_call(self, tool_name: str) -> None:
        """Track that a tool was called (for per-task limit counting)."""
        self._counters[tool_name] = self._counters.get(tool_name, 0) + 1

    def is_empty(self) -> bool:
        """True if no policy is configured (no-op monitor)."""
        return not self._policy

    def validate_available_tools(self, available_tools: List[str]) -> List[str]:
        """
        Check that a task's available_tools list doesn't exceed the role's allowed_tools ceiling.

        Returns a list of violation messages (empty = all OK).
        """
        allowed: List[str] = self._policy.get("allowed_tools", [])
        denied: List[str] = self._policy.get("denied_tools", [])

        if not allowed and not denied:
            return []  # No ceiling defined

        violations = []
        for tool in available_tools:
            if tool in denied:
                violations.append(
                    f"Tool '{tool}' is denied by role '{self.role_id}' policy"
                )
            elif allowed and tool not in allowed:
                violations.append(
                    f"Tool '{tool}' is not permitted by role '{self.role_id}' allowed_tools ceiling"
                )
        return violations
