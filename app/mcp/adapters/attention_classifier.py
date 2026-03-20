"""
AttentionClassifier

Deterministic System-1 pre-processor that assigns a hitl_level (0–5) to every
event before it is persisted in the EventLog.  No LLM, no I/O — just rules.

Base rules are evaluated in descending priority order; first match wins.
Per-source rules (from config/attention_routing.json) then apply min/max caps.

| Level | Rule                                              | Example                          |
|-------|---------------------------------------------------|----------------------------------|
|   5   | severity == "critical"                            | Server crash, fatal error        |
|   4   | event_type == "task_waiting_for_input"            | Ahman asking a question          |
|   3   | severity == "error" OR event_type == "task_failed"| Task failed permanently          |
|   2   | event_type == "task_completed" AND notify_user    | Ahman finished a scan            |
|   1   | notify_user == True (any event)                   | Background update worth noting   |
|   0   | everything else                                   | Heartbeats, ticks, dreaming, etc.|

Per-source rules add min/max caps on top of the base level:
  - dreaming   → max_level 1  (never interrupt for memory consolidation)
  - agent      → min_level 2  (external coding agent events always notable)
  - scheduled  → max_level 2  (cron tasks are quiet unless they ask to notify)
"""

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_DEFAULT_SOURCE_RULES: Dict[str, Dict[str, int]] = {
    "dreaming":  {"max_level": 1},
    "agent":     {"min_level": 2},
    "scheduled": {"max_level": 2},
}

_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "config", "attention_routing.json"
)


def _load_source_rules() -> Dict[str, Dict[str, int]]:
    """Load per-source rules from config file, falling back to defaults."""
    try:
        path = os.path.normpath(_CONFIG_PATH)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
            rules: Dict[str, Dict[str, int]] = {}
            for source, rule in cfg.get("source_rules", {}).items():
                entry: Dict[str, int] = {}
                if "min_level" in rule:
                    entry["min_level"] = int(rule["min_level"])
                if "max_level" in rule:
                    entry["max_level"] = int(rule["max_level"])
                rules[source] = entry
            return rules
    except Exception as e:
        logger.warning("AttentionClassifier: failed to load attention_routing.json: %s", e)
    return dict(_DEFAULT_SOURCE_RULES)


# Module-level cache — loaded once per process start.
_SOURCE_RULES: Optional[Dict[str, Dict[str, int]]] = None


def _get_source_rules() -> Dict[str, Dict[str, int]]:
    global _SOURCE_RULES
    if _SOURCE_RULES is None:
        _SOURCE_RULES = _load_source_rules()
    return _SOURCE_RULES


class AttentionClassifier:
    """
    Classify an event and return its hitl_level (0–5).

    Usage:
        level = AttentionClassifier.classify(event)
        event["hitl_level"] = level
    """

    @staticmethod
    def classify(event: Dict[str, Any]) -> int:
        """
        Return the attention level for *event*.  Deterministic; no side-effects.

        Args:
            event: The event dict (must have at least event_type and/or severity).

        Returns:
            int in range 0–5.
        """
        event_type = event.get("event_type", "")
        severity = event.get("severity", "info")
        notify_user = event.get("notify_user", False)
        task_type = event.get("task_type", "")

        # --- Base level (first match wins) ---

        # Level 5 — critical severity (system crash, fatal error)
        if severity == "critical":
            level = 5

        # Level 4 — task waiting for human input (blocks progress)
        elif event_type == "task_waiting_for_input":
            level = 4

        # Level 3 — error severity or task failure
        elif severity == "error" or event_type == "task_failed":
            level = 3

        # Level 2 — task completed and the task asked to notify user
        elif event_type == "task_completed" and notify_user:
            level = 2

        # Level 1 — any event with notify_user flag set
        elif notify_user:
            level = 1

        # Level 0 — background noise (heartbeats, ticks, dreaming, etc.)
        else:
            level = 0

        # --- Per-source adjustments ---
        # task_type maps directly to the source_rules keys.
        if task_type:
            rules = _get_source_rules().get(task_type, {})
            min_l = rules.get("min_level")
            max_l = rules.get("max_level")
            if min_l is not None:
                level = max(level, min_l)
            if max_l is not None:
                level = min(level, max_l)

        return level

    @staticmethod
    def reload_rules() -> None:
        """Force reload of source rules from config (useful after config changes)."""
        global _SOURCE_RULES
        _SOURCE_RULES = _load_source_rules()
