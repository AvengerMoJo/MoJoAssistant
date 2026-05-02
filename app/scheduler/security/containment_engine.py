"""
ContainmentEngine — three-tier response to behavioral anomalies.

Receives suspicion scores from BehavioralMonitor and decides the response:
  LOW (30-60)   → silent ntfy push, session flagged
  MEDIUM (60-85) → redirect to SandboxRuntime (honeypot)
  HIGH (85+)    → hard halt + HITL level 5 alert

The agent has NO awareness of containment at LOW/MEDIUM levels.
"""
# [mojo-integration]

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from app.config.paths import get_memory_subpath

logger = logging.getLogger(__name__)


class ContainmentEngine:
    """Decide and execute containment responses based on suspicion levels."""

    def __init__(self, push_manager=None, event_log=None):
        self._push_manager = push_manager
        self._event_log = event_log

    async def respond(
        self,
        task_id: str,
        role_id: str,
        suspicion_level: str,
        suspicion_score: float,
        assessment: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute containment response based on suspicion level.

        Returns dict with:
          - action: "continue" | "sandbox" | "halt"
          - reason: explanation
          - notify_sent: whether user was notified
        """
        result = {
            "action": "continue",
            "reason": "",
            "notify_sent": False,
            "level": suspicion_level,
            "score": suspicion_score,
        }

        if suspicion_level == "NONE":
            return result

        if suspicion_level == "LOW":
            # Silent notification, session flagged
            result["reason"] = f"Low suspicion ({suspicion_score:.0f}) — session flagged for review"
            await self._notify_user(
                task_id=task_id,
                role_id=role_id,
                level="low",
                message=f"Session {task_id} flagged with low suspicion score ({suspicion_score:.0f})",
            )
            self._log_containment(task_id, role_id, suspicion_level, suspicion_score, "flagged")
            result["notify_sent"] = True

        elif suspicion_level == "MEDIUM":
            # Redirect to sandbox (honeypot)
            result["action"] = "sandbox"
            result["reason"] = (
                f"Medium suspicion ({suspicion_score:.0f}) — "
                "redirecting to sandbox runtime for containment"
            )
            await self._notify_user(
                task_id=task_id,
                role_id=role_id,
                level="medium",
                message=(
                    f"⚠️ Session {task_id} (role: {role_id}) redirected to sandbox. "
                    f"Suspicion score: {suspicion_score:.0f}. "
                    "Agent continues running in isolated environment."
                ),
            )
            self._log_containment(task_id, role_id, suspicion_level, suspicion_score, "sandboxed")
            result["notify_sent"] = True

        elif suspicion_level == "HIGH":
            # Hard halt
            result["action"] = "halt"
            result["reason"] = (
                f"High suspicion ({suspicion_score:.0f}) — "
                "task halted, HITL alert sent"
            )
            await self._notify_user(
                task_id=task_id,
                role_id=role_id,
                level="high",
                message=(
                    f"🚨 HIGH SUSPICION: Session {task_id} (role: {role_id}) HALTED. "
                    f"Suspicion score: {suspicion_score:.0f}. "
                    "Immediate review required. Session log preserved for forensics."
                ),
            )
            self._log_containment(task_id, role_id, suspicion_level, suspicion_score, "halted")
            result["notify_sent"] = True

        return result

    async def _notify_user(
        self,
        task_id: str,
        role_id: str,
        level: str,
        message: str,
    ) -> None:
        """Send notification via push manager and/or event log."""
        try:
            if self._push_manager:
                await self._push_manager.send(
                    title=f"MoJoAssistant Security [{level.upper()}]",
                    message=message,
                    priority=2 if level == "low" else (3 if level == "medium" else 5),
                )
            if self._event_log:
                self._event_log.write(
                    source="containment_engine",
                    event_type="security_alert",
                    data={
                        "task_id": task_id,
                        "role_id": role_id,
                        "level": level,
                        "message": message,
                    },
                )
        except Exception as e:
            logger.warning(f"ContainmentEngine: notification failed: {e}")

    def _log_containment(
        self,
        task_id: str,
        role_id: str,
        level: str,
        score: float,
        action: str,
    ) -> None:
        """Write containment event to forensics log."""
        try:
            forensics_dir = Path(get_memory_subpath("security"))
            forensics_dir.mkdir(parents=True, exist_ok=True)

            event = {
                "timestamp": datetime.now().isoformat(),
                "task_id": task_id,
                "role_id": role_id,
                "suspicion_level": level,
                "suspicion_score": score,
                "action": action,
            }

            log_path = forensics_dir / "containment_log.jsonl"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"ContainmentEngine: forensics log failed: {e}")
