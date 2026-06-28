"""Task Router — assigns minimum viable model to each task.

Classifies tasks into complexity cells (A/B/C/D) based on tool breadth
and dependency depth, then routes to the smallest model that can handle it.

Spec: ~/.memory/research/task_routing_research_question.md
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config.paths import get_memory_path

logger = logging.getLogger(__name__)

# Tool categories (7-bit vector: memory/file/web/code/agent/system/external)
TOOL_CATEGORIES = {
    "memory_search": "memory", "knowledge_search": "memory",
    "read_file": "file", "write_file": "file", "list_files": "file",
    "web_search": "web", "fetch_url": "web",
    "bash_exec": "code", "docker_sandbox_exec": "code",
    "dispatch_subtask": "agent", "ask_user": "agent",
    "read_config": "system", "write_config": "system",
}

# Tools with high argument complexity (A_c bonus)
HIGH_AC_TOOLS = {"bash_exec", "docker_sandbox_exec", "dispatch_subtask",
                 "write_file", "write_config"}

# Keywords that signal sequential dependency (D_d proxy)
DEPENDENCY_KEYWORDS = [
    "then", "after", "based on", "use the result", "use that",
    "once you have", "given what you found", "with that", "using the output",
]


def compute_cell(goal_text: str, declared_tools: list[str]) -> str:
    """Classify task complexity into cell A/B/C/D.

    Returns one of: 'A' (low breadth, low depth), 'B' (low breadth, high depth),
    'C' (high breadth, low depth), 'D' (high breadth, high depth).
    """
    # Breadth score: distinct tool categories + A_c bonus
    categories = {TOOL_CATEGORIES.get(t, "other") for t in declared_tools}
    ac_bonus = 1 if any(t in HIGH_AC_TOOLS for t in declared_tools) else 0
    breadth_score = len(categories) + ac_bonus

    # Depth score: dependency keywords + state-passing tool presence
    goal_lower = goal_text.lower()
    kw_count = sum(1 for kw in DEPENDENCY_KEYWORDS if kw in goal_lower)
    state_bonus = 1 if any(t in {"write_file", "bash_exec", "dispatch_subtask"}
                            for t in declared_tools) else 0
    depth_score = kw_count + state_bonus

    # Thresholds (tunable)
    HIGH_BREADTH = breadth_score >= 2
    HIGH_DEPTH = depth_score >= 1

    if HIGH_BREADTH and HIGH_DEPTH:
        return "D"
    if HIGH_BREADTH and not HIGH_DEPTH:
        return "C"
    if not HIGH_BREADTH and HIGH_DEPTH:
        return "B"
    return "A"


@dataclass
class RoutingResult:
    """Result of task routing."""
    cell: str
    model_id: str
    confidence: float
    explain: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cell": self.cell,
            "model_id": self.model_id,
            "confidence": self.confidence,
            "explain": self.explain,
        }


class TaskRouter:
    """Routes tasks to minimum viable model based on complexity classification."""

    def __init__(self, routing_table: Dict[str, str], capability_profile: Optional[Dict] = None):
        self._routing_table = routing_table
        self._capability_profile = capability_profile or {}

    @classmethod
    def load(cls) -> "TaskRouter":
        """Load routing table and capability profile from ~/.memory/benchmarks/routing/."""
        base = Path(get_memory_path()) / "benchmarks" / "routing"

        # Load routing table
        table_path = base / "routing_table.json"
        if table_path.exists():
            routing_table = json.loads(table_path.read_text())
        else:
            # Default hypothesis
            routing_table = {
                "A": "lmstudio_gemma4_12b",
                "B": "lmstudio_qwen36_27b_mtp",
                "C": "lmstudio__google_gemma_4_26b_a4b",
                "D": "lmstudio_qwen36_mtp",
            }

        # Load capability profile
        profile_path = base / "capability_profile.json"
        capability_profile = {}
        if profile_path.exists():
            capability_profile = json.loads(profile_path.read_text())

        return cls(routing_table=routing_table, capability_profile=capability_profile)

    def classify_and_route(
        self,
        goal: str,
        role_id: str,
        declared_tools: list[str],
    ) -> Dict[str, Any]:
        """Classify task and select minimum viable model.

        Returns dict with: cell, model_id, confidence, explain
        """
        cell = compute_cell(goal, declared_tools)
        model_id = self._routing_table.get(cell, self._routing_table.get("A", ""))

        # Confidence based on profile data availability
        confidence = 0.5  # default: hypothesis only
        if self._capability_profile:
            cell_profile = self._capability_profile.get(cell, {})
            if cell_profile.get(model_id, {}).get("success_rate"):
                confidence = cell_profile[model_id]["success_rate"]

        explain = f"Cell {cell}: {self._cell_description(cell)} → {model_id}"

        return {
            "cell": cell,
            "model_id": model_id,
            "confidence": confidence,
            "explain": explain,
        }

    def _cell_description(self, cell: str) -> str:
        descriptions = {
            "A": "low breadth, low depth — single tool, no chaining",
            "B": "low breadth, high depth — sequential with state passing",
            "C": "high breadth, low depth — parallel independent lookups",
            "D": "high breadth, high depth — multi-tool sequential with state",
        }
        return descriptions.get(cell, "unknown")

    def validate_tool_call(
        self,
        call: Dict[str, Any],
        role_tools: list[str],
    ) -> Tuple[bool, str]:
        """Validate a tool call against role's available tools.

        Returns (valid, reason).
        """
        tool_name = call.get("function", {}).get("name", "") if "function" in call else call.get("name", "")
        if not tool_name:
            return False, "No tool name in call"
        if tool_name not in role_tools:
            return False, f"Tool '{tool_name}' not in role's available tools"
        return True, ""

    def should_escalate(
        self,
        execution_trace: List[Dict],
    ) -> Tuple[bool, str]:
        """Check if execution should be escalated to a larger model.

        Returns (escalate, reason).
        """
        if len(execution_trace) < 2:
            return False, ""

        # Check for loops: same tool called twice with same args
        recent = execution_trace[-2:]
        if len(recent) == 2:
            t1 = recent[0].get("tool_name", "")
            t2 = recent[1].get("tool_name", "")
            a1 = json.dumps(recent[0].get("args", {}), sort_keys=True)
            a2 = json.dumps(recent[1].get("args", {}), sort_keys=True)
            if t1 == t2 and a1 == a2:
                return True, f"Loop detected: {t1} called twice with same args"

        # Check for consecutive errors
        errors = [t for t in execution_trace[-3:] if t.get("error")]
        if len(errors) >= 2:
            return True, f"{len(errors)} consecutive errors"

        return False, ""
