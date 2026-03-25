"""
ContextAwarePolicyChecker — cross-iteration violation accumulator.

Tracks how many tool calls have been blocked within a task and halts
execution once a configurable threshold is reached.

This checker must be placed LAST in the checkers pipeline so it can
read the accumulated violation_total set by PolicyMonitor before each
call. It never makes its own content decisions; it only enforces the
ceiling imposed by prior checkers' outcomes.

Role config example:
  "policy": {
    "checkers": ["static", "content", "data_boundary", "context"],
    "context_rules": {
      "max_violations_before_halt": 3
    }
  }

With max_violations_before_halt=0 (the default) this checker is a no-op,
so roles that omit context_rules are entirely unaffected.
"""

import logging
from typing import Any, Dict

from app.scheduler.policy.base import PolicyChecker, PolicyDecision

logger = logging.getLogger(__name__)


class ContextAwarePolicyChecker(PolicyChecker):
    """
    Halts a task after too many policy violations within a single run.

    Reads the 'violation_total' counter maintained by PolicyMonitor and
    blocks once it reaches the configured ceiling.
    """

    name = "context"

    def __init__(self) -> None:
        self._max_violations: int = 0  # 0 = disabled

    def configure(self, context: Dict[str, Any]) -> None:
        rules = (context.get("policy") or {}).get("context_rules", {})
        self._max_violations = int(rules.get("max_violations_before_halt", 0))
        if self._max_violations > 0:
            logger.debug(
                "[policy/context] halt threshold set to %d violations",
                self._max_violations,
            )

    def check(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> PolicyDecision:
        if self._max_violations <= 0:
            return PolicyDecision.allow(checker=self.name)

        total = context.get("violation_total", 0)
        if total >= self._max_violations:
            return PolicyDecision.block(
                reason=(
                    f"Task halted: {total} policy violation(s) exceeded the limit of "
                    f"{self._max_violations}. Check the dashboard or ntfy for details."
                ),
                checker=self.name,
                metadata={"violation_count": total, "limit": self._max_violations},
            )

        return PolicyDecision.allow(checker=self.name)
