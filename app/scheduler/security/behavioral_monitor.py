"""
BehavioralMonitor — parallel observer for agentic executor sessions.

Maintains per-role behavioral baselines and scores each session against them
in real time.  Runs alongside every AgenticExecutor session without blocking
or modifying execution — the agent has no awareness of it.

Baseline is updated after each completed session using exponential moving average.
"""
# [mojo-integration]

from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config.paths import get_memory_subpath

logger = logging.getLogger(__name__)

# Exponential moving average decay factor (lower = faster adaptation)
_EMA_ALPHA = 0.15

# Suspicion score weights
_WEIGHTS = {
    "credential_path_access": 25,
    "scope_drift": 20,
    "exfiltration_chain": 40,
    "volume_anomaly": 10,
    "timing_anomaly": 8,
    "unusual_tool_combination": 5,
    "c2_pattern": 40,
}

# Credential path patterns — path-like strings only
_CREDENTIAL_PATH_PATTERNS = [
    ".ssh/id_",
    ".ssh/authorized_keys",
    ".kube/config",
    "docker/config.json",
    ".aws/credentials",
    ".gcp/",
    ".azure/",
    ".gnupg/",
    ".netrc",
]

# Credential keyword patterns — word-boundary anchored to avoid false positives
_CREDENTIAL_KEYWORD_PATTERNS = [
    re.compile(r'\bSECRET\b'),
    re.compile(r'\bTOKEN\b'),
    re.compile(r'\bKEY\b'),
    re.compile(r'\bPASSWORD\b'),
    re.compile(r'\bCREDENTIAL\b'),
]

# C2 / exfiltration patterns
_C2_PATTERNS = [
    ".xyz/", ".tk/", ".ml/", ".ga/", ".cf/",
    "/dev/tcp",
    "nc -e", "ncat -e",
    "mkfifo",
    "socat",
]

_EXFIL_PATTERNS = [
    "curl.*-d.*@",
    "wget.*--post",
    "scp.*@",
    "rsync.*-e",
    "base64.*upload",
    "upload.*base64",
]


class BehavioralMonitor:
    """Parallel observer that maintains per-role baselines and scores sessions."""

    def __init__(self) -> None:
        self._baselines: Dict[str, Dict[str, Any]] = {}
        self._session_scores: Dict[str, float] = {}  # task_id → suspicion score
        self._load_baselines()

    def _baselines_path(self) -> Path:
        return Path(get_memory_subpath("security")) / "behavioral_baselines.json"

    def _load_baselines(self) -> None:
        path = self._baselines_path()
        if path.exists():
            try:
                self._baselines = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                self._baselines = {}

    def _save_baselines(self) -> None:
        path = self._baselines_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(
                json.dumps(self._baselines, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"BehavioralMonitor: failed to save baselines: {e}")

    def get_baseline(self, role_id: str) -> Dict[str, Any]:
        """Get or create baseline for a role."""
        if role_id not in self._baselines:
            self._baselines[role_id] = {
                "role_id": role_id,
                "typical_tools": [],
                "typical_call_count": {"mean": 5.0, "stddev": 3.0},
                "credential_path_access_rate": 0.0,
                "external_network_rate": 0.3,
                "bash_exec_rate": 0.1,
                "sessions_observed": 0,
            }
        return self._baselines[role_id]

    def observe_tool_call(
        self,
        task_id: str,
        role_id: str,
        tool_name: str,
        args: Dict[str, Any],
    ) -> float:
        """Observe a tool call and return the incremental suspicion score.

        Called by AgenticExecutor after each tool call.  Non-blocking.
        """
        score = 0.0
        baseline = self.get_baseline(role_id)

        # Serialize args for pattern matching
        try:
            args_text = json.dumps(args, ensure_ascii=False)
        except Exception:
            args_text = str(args)

        # Credential path access — only match path-like patterns
        if any(p in args_text for p in _CREDENTIAL_PATH_PATTERNS):
            score += _WEIGHTS["credential_path_access"]
            logger.warning(
                f"BehavioralMonitor: credential path access in task {task_id} "
                f"by role {role_id}, tool {tool_name}"
            )

        # Credential keyword patterns — word-boundary anchored, only for path operations
        if tool_name in ("read_file", "write_file", "bash_exec"):
            if any(p.search(args_text) for p in _CREDENTIAL_KEYWORD_PATTERNS):
                score += _WEIGHTS["credential_path_access"]
                logger.warning(
                    f"BehavioralMonitor: credential keyword in path operation in task {task_id} "
                    f"by role {role_id}, tool {tool_name}"
                )

        # C2 patterns
        if any(p in args_text for p in _C2_PATTERNS):
            score += _WEIGHTS["c2_pattern"]
            logger.warning(
                f"BehavioralMonitor: C2 pattern detected in task {task_id} "
                f"by role {role_id}, tool {tool_name}"
            )

        # Exfiltration patterns
        if any(p in args_text for p in _EXFIL_PATTERNS):
            score += _WEIGHTS["exfiltration_chain"]
            logger.warning(
                f"BehavioralMonitor: exfiltration pattern in task {task_id} "
                f"by role {role_id}, tool {tool_name}"
            )

        # Scope drift: researcher calling bash_exec on system paths
        if tool_name == "bash_exec" and role_id in ("researcher", "analyst"):
            if any(p in args_text for p in ["/etc/", "/usr/", "/var/", "/sys/", "/proc/"]):
                score += _WEIGHTS["scope_drift"]

        # Track tool usage for this session
        if task_id not in self._session_scores:
            self._session_scores[task_id] = 0.0
        self._session_scores[task_id] += score

        return score

    def observe_session_end(
        self,
        task_id: str,
        role_id: str,
        tools_used: List[str],
        iteration_count: int,
        success: bool,
    ) -> Dict[str, Any]:
        """Update baseline after session ends and return final assessment.

        Returns dict with suspicion_level (LOW/MEDIUM/HIGH) and score.
        """
        baseline = self.get_baseline(role_id)

        # Volume anomaly check
        mean = baseline["typical_call_count"]["mean"]
        stddev = baseline["typical_call_count"]["stddev"]
        if iteration_count > mean + 3 * stddev:
            self._session_scores.setdefault(task_id, 0.0)
            self._session_scores[task_id] += _WEIGHTS["volume_anomaly"]

        # Update baseline with EMA
        n = baseline["sessions_observed"] + 1
        alpha = _EMA_ALPHA

        # Update tool frequency
        for tool in tools_used:
            if tool not in baseline["typical_tools"]:
                baseline["typical_tools"].append(tool)
                baseline["typical_tools"] = baseline["typical_tools"][-20:]  # keep last 20

        # Update call count stats (Welford's online algorithm variant)
        old_mean = baseline["typical_call_count"]["mean"]
        new_mean = old_mean + alpha * (iteration_count - old_mean)
        old_var = baseline["typical_call_count"]["stddev"] ** 2
        new_var = (1 - alpha) * (old_var + alpha * (iteration_count - old_mean) ** 2)
        baseline["typical_call_count"]["mean"] = new_mean
        baseline["typical_call_count"]["stddev"] = math.sqrt(max(new_var, 0.01))

        # Update rates
        has_credential = any(
            p in " ".join(tools_used) for p in ["ssh", "kube", "aws", "credential"]
        )
        baseline["credential_path_access_rate"] = (
            baseline["credential_path_access_rate"] * (1 - alpha)
            + (1.0 if has_credential else 0.0) * alpha
        )

        has_network = any(t in tools_used for t in ["web_search", "fetch_url", "bash_exec"])
        baseline["external_network_rate"] = (
            baseline["external_network_rate"] * (1 - alpha)
            + (1.0 if has_network else 0.0) * alpha
        )

        has_bash = "bash_exec" in tools_used
        baseline["bash_exec_rate"] = (
            baseline["bash_exec_rate"] * (1 - alpha)
            + (1.0 if has_bash else 0.0) * alpha
        )

        baseline["sessions_observed"] = n
        self._baselines[role_id] = baseline
        self._save_baselines()

        # Final suspicion assessment
        # Normalize score by iteration count to prevent long legitimate sessions
        # from accumulating high scores via noise
        raw_score = self._session_scores.pop(task_id, 0.0)
        normalized_score = raw_score / max(1, iteration_count / 5)  # normalize per 5 iterations
        if normalized_score >= 85:
            level = "HIGH"
        elif normalized_score >= 60:
            level = "MEDIUM"
        elif normalized_score >= 30:
            level = "LOW"
        else:
            level = "NONE"

        return {
            "suspicion_level": level,
            "suspicion_score": normalized_score,
            "raw_score": raw_score,
            "role_id": role_id,
            "task_id": task_id,
            "assessed_at": datetime.now().isoformat(),
        }
