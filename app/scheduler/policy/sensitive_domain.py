"""
SensitiveDomainChecker — owner-profile-aware policy checker.

Scans tool call arguments for content that touches the owner's declared
sensitive domains (e.g. "personal memory", "spiritual notes", "security
infrastructure"). Produces a warning by default; can be configured to BLOCK
via role policy: `"sensitive_domain_action": "block"`.

Sensitive domains are loaded once at task start from the owner profile.
If no owner profile exists, or sensitive_domains is empty, this checker
is effectively a no-op.
"""
# [mojo-integration]

import json
import logging
from typing import Any, Dict, List

from app.scheduler.policy.base import PolicyChecker, PolicyDecision
from app.roles.owner_context import load_owner_profile

logger = logging.getLogger(__name__)

_DEFAULT_ACTION = "warn"   # "warn" | "block"


class SensitiveDomainChecker(PolicyChecker):
    """Warn or block when tool args reference an owner-declared sensitive domain."""

    name = "sensitive_domain"

    def __init__(self) -> None:
        self._sensitive_domains: List[str] = []
        self._action: str = _DEFAULT_ACTION

    def configure(self, context: Dict[str, Any]) -> None:
        """Load sensitive domains from owner profile and action from role policy."""
        owner_profile = load_owner_profile()
        self._sensitive_domains = (
            owner_profile.get("privacy_preferences", {}).get("sensitive_domains", [])
        )
        policy = context.get("policy", {})
        self._action = policy.get("sensitive_domain_action", _DEFAULT_ACTION)
        if self._sensitive_domains:
            logger.debug(
                "SensitiveDomainChecker: monitoring %d domain(s), action=%s",
                len(self._sensitive_domains),
                self._action,
            )

    def check(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> PolicyDecision:
        if not self._sensitive_domains:
            return PolicyDecision.allow()

        # Serialise args to a single lowercase string for keyword scanning
        try:
            args_text = json.dumps(args, ensure_ascii=False).lower()
        except (TypeError, ValueError):
            args_text = str(args).lower()

        matched = [
            domain for domain in self._sensitive_domains
            if domain.lower() in args_text
        ]
        if not matched:
            return PolicyDecision.allow()

        reason = (
            f"Tool '{tool_name}' args reference sensitive domain(s): "
            + ", ".join(f'"{d}"' for d in matched)
            + ". Owner approval may be required before sharing this data externally."
        )

        if self._action == "block":
            return PolicyDecision.block(
                reason=reason,
                checker=self.name,
                metadata={"matched_domains": matched, "tool": tool_name},
            )

        # Default: warn — allowed but flagged
        logger.warning("SensitiveDomainChecker [WARN]: %s", reason)
        return PolicyDecision.allow(
            reason=reason,
            warn=True,
            checker=self.name,
        )
