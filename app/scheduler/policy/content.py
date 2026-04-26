"""
ContentAwarePolicyChecker — scans tool arguments for secrets, PII, and
behavioral threat patterns.

Loads regex patterns from three sources (in order, later entries override):
  1. config/policy_patterns.json       — secrets / API keys / PII (system)
  2. config/behavioral_patterns.json  — C2, exfiltration, privilege escalation (system)
  3. ~/.memory/config/policy_patterns.json     — personal overlay for policy patterns
  4. ~/.memory/config/behavioral_patterns.json — personal overlay for behavioral patterns

Pattern severity:
  "block" — reject the tool call and notify the user
  "warn"  — also rejected; any match is treated as a block.
            The 'warn' level only affects the notification severity
            (warning vs error) — the tool call never proceeds.

This checker is intentionally simple and fast — pure regex, no LLM.
It is the foundation; a future LLMPolicyChecker or MCPPolicyChecker can
extend this interface with deeper context understanding.
"""
# [hitl-orchestrator: generic]

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from app.scheduler.policy.base import PolicyChecker, PolicyDecision

logger = logging.getLogger(__name__)

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config")
_SYSTEM_PATTERNS_PATH = os.path.join(_CONFIG_DIR, "policy_patterns.json")
_BEHAVIORAL_PATTERNS_PATH = os.path.join(_CONFIG_DIR, "behavioral_patterns.json")


def _load_patterns() -> List[Dict]:
    """Load and merge system + behavioral + personal pattern files."""
    patterns: Dict[str, Dict] = {}

    def _merge(path: str) -> None:
        if not os.path.exists(path):
            return
        try:
            with open(path) as f:
                data = json.load(f)
            for p in data.get("patterns", []):
                patterns[p["name"]] = p  # later files overwrite earlier ones
        except Exception as e:
            logger.warning("ContentAwarePolicyChecker: failed to load %s: %s", path, e)

    _merge(_SYSTEM_PATTERNS_PATH)
    _merge(_BEHAVIORAL_PATTERNS_PATH)

    try:
        from app.config.paths import get_memory_subpath
        _merge(get_memory_subpath("config", "policy_patterns.json"))
        _merge(get_memory_subpath("config", "behavioral_patterns.json"))
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
                # Any match — regardless of pattern severity — is a block.
                # 'warn'-tagged patterns use severity="warning" in violation events;
                # 'block'-tagged patterns use severity="error". Both halt the call.
                return PolicyDecision.block(
                    reason=msg,
                    checker=self.name,
                    metadata={
                        "pattern": pattern["name"],
                        "tool": tool_name,
                        "pattern_severity": severity,
                    },
                )

        return PolicyDecision.allow(checker=self.name)
