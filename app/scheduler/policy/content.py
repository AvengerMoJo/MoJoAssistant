"""
ContentAwarePolicyChecker — scans tool arguments for secrets and PII patterns.

Loads regex patterns from config/policy_patterns.json (system layer) and
~/.memory/config/policy_patterns.json (personal overlay, merged at startup).

Pattern severity:
  "block" — reject the tool call, emit audit event
  "warn"  — allow but log a warning

This checker is intentionally simple and fast — pure regex, no LLM.
It is the foundation; a future LLMPolicyChecker or MCPPolicyChecker can
extend this interface with deeper context understanding.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from app.scheduler.policy.base import PolicyChecker, PolicyDecision

logger = logging.getLogger(__name__)

_SYSTEM_PATTERNS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "config", "policy_patterns.json"
)


def _load_patterns() -> List[Dict]:
    """Load and merge system + personal pattern files."""
    patterns: Dict[str, Dict] = {}

    def _merge(path: str) -> None:
        if not os.path.exists(path):
            return
        try:
            with open(path) as f:
                data = json.load(f)
            for p in data.get("patterns", []):
                patterns[p["name"]] = p  # personal overlay overwrites system
        except Exception as e:
            logger.warning("ContentAwarePolicyChecker: failed to load %s: %s", path, e)

    _merge(_SYSTEM_PATTERNS_PATH)

    try:
        from app.config.paths import get_memory_subpath
        _merge(get_memory_subpath("config", "policy_patterns.json"))
    except Exception:
        pass

    return list(patterns.values())


class ContentAwarePolicyChecker(PolicyChecker):
    """
    Scans the string representation of tool arguments against a set of
    regex patterns that indicate secrets, credentials, or PII.

    Enabled by default unless the role sets:
        "policy": { "content_check": false }
    """

    name = "content"

    def __init__(self) -> None:
        self._enabled = True
        self._compiled: List[Dict] = []   # [{"name", "regex", "severity", "description"}, ...]

    def configure(self, context: Dict[str, Any]) -> None:
        policy = context.get("policy") or {}
        self._enabled = policy.get("content_check", True)
        if self._enabled:
            self._compiled = _load_patterns()

    def check(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> PolicyDecision:
        if not self._enabled or not self._compiled:
            return PolicyDecision.allow(checker=self.name)

        # Flatten args to a single string for scanning
        try:
            args_text = json.dumps(args, default=str)
        except Exception:
            args_text = str(args)

        for pattern in self._compiled:
            regex = pattern.get("regex", "")
            severity = pattern.get("severity", "warn")
            description = pattern.get("description", pattern.get("name", ""))
            try:
                match = re.search(regex, args_text)
            except re.error:
                continue

            if match:
                snippet = match.group(0)[:40] + ("…" if len(match.group(0)) > 40 else "")
                msg = (
                    f"[{pattern['name']}] {description} — "
                    f"matched in '{tool_name}' args: {snippet!r}"
                )
                if severity == "block":
                    return PolicyDecision.block(
                        reason=msg,
                        checker=self.name,
                        metadata={"pattern": pattern["name"], "tool": tool_name},
                    )
                else:  # warn
                    return PolicyDecision.allow(reason=msg, warn=True, checker=self.name)

        return PolicyDecision.allow(checker=self.name)
