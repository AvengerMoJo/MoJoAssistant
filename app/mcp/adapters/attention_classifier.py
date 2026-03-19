"""
AttentionClassifier

Deterministic System-1 pre-processor that assigns a hitl_level (0–5) to every
event before it is persisted in the EventLog.  No LLM, no I/O — just rules.

Rules are evaluated in descending priority order; first match wins.

| Level | Rule                                              | Example                          |
|-------|---------------------------------------------------|----------------------------------|
|   5   | severity == "critical"                            | Server crash, fatal error        |
|   4   | event_type == "task_waiting_for_input"            | Ahman asking a question          |
|   3   | severity == "error" OR event_type == "task_failed"| Task failed permanently          |
|   2   | event_type == "task_completed" AND notify_user    | Ahman finished a scan            |
|   1   | notify_user == True (any event)                   | Background update worth noting   |
|   0   | everything else                                   | Heartbeats, scheduler ticks, noise |
"""

from typing import Any, Dict


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

        # Level 5 — critical severity (system crash, fatal error)
        if severity == "critical":
            return 5

        # Level 4 — task waiting for human input (blocks progress)
        if event_type == "task_waiting_for_input":
            return 4

        # Level 3 — error severity or task failure
        if severity == "error" or event_type == "task_failed":
            return 3

        # Level 2 — task completed and the task asked to notify user
        if event_type == "task_completed" and notify_user:
            return 2

        # Level 1 — any event with notify_user flag set
        if notify_user:
            return 1

        # Level 0 — background noise (heartbeats, ticks, dreaming, etc.)
        return 0
