"""
NineChapter runtime behavioral and task context overlays.

Three public functions:

  build_behavioral_overlay(role)
      Converts dimension scores into behavioral directives.
      Injected in BOTH chat and agentic task prompts (shared constraints).
      Covers: evidence rigor, response structure, question discipline,
      composure, gap handling, response density, assertiveness, escalation threshold.

  build_task_context(role)
      Converts success_patterns and escalation_rules from the role config
      into a task-execution context block.
      Injected only in SCHEDULER_AGENTIC_TASK prompts.
      Tells the model what "done well" looks like and exactly when to escalate.

  build_capability_summary(role)
      Converts role.capabilities category names into a human-readable
      capability block injected at task start.  Tells the assistant exactly
      what it can and cannot do before the first tool call — no runtime
      discovery needed, no loop risk.

Dimension → behavior mapping
----------------------------
core_values        Evidence rigor, intellectual honesty, uncertainty naming
cognitive_style    Response structure, verification discipline, response density
social_orientation Question discipline, teaching orientation
emotional_reaction Composure under challenge, assertiveness level
adaptability       Gap discipline, escalation threshold

Thresholds: ≥90 → strong directive, 75–89 → moderate, <75 → silent.
"""
# [mojo-integration]
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Behavioral overlay (chat + agentic)
# ---------------------------------------------------------------------------

def build_behavioral_overlay(role: Dict[str, Any]) -> str:
    """
    Return a behavioral calibration block from NineChapter dimension scores.
    Empty string if no dimensions are defined.
    """
    dims = role.get("dimensions") or {}
    if not dims:
        return ""

    def score(dim: str) -> int:
        entry = dims.get(dim)
        if isinstance(entry, dict):
            return int(entry.get("score", 0))
        if isinstance(entry, (int, float)):
            return int(entry)
        return 0

    clauses: List[str] = []

    # core_values → evidence rigor and intellectual honesty
    cv = score("core_values")
    if cv >= 90:
        clauses.append(
            "Name uncertainty explicitly — never present incomplete findings as settled conclusions."
        )
        clauses.append(
            "Before stating a conclusion, verify it against at least 2 independent "
            "sources or pieces of evidence."
        )
    elif cv >= 75:
        clauses.append("Flag significant uncertainties before stating conclusions.")

    # cognitive_style → structure, verification discipline, response density
    cs = score("cognitive_style")
    if cs >= 90:
        clauses.append(
            "Structure responses systematically: break the problem into components before synthesizing."
        )
        clauses.append(
            "Response density: be comprehensive and detailed — brevity is not a virtue "
            "when depth is needed to give a complete answer."
        )
    elif cs >= 75:
        clauses.append("Organize complex responses into clear sections.")

    # social_orientation → question discipline and teaching orientation
    so = score("social_orientation")
    if so >= 90:
        clauses.append(
            "When clarification is needed, ask one focused question at a time — never a list."
        )
        clauses.append(
            "Teach as you answer: explain the reasoning behind conclusions, "
            "not just the conclusions themselves."
        )
    elif so >= 75:
        clauses.append("Ask one focused clarifying question at a time — never a list.")

    # emotional_reaction → composure and assertiveness
    er = score("emotional_reaction")
    if er >= 90:
        clauses.append(
            "Welcome pushback as a refinement opportunity — engage it directly with evidence, "
            "not defensiveness."
        )
        clauses.append(
            "State your position clearly and directly. Do not hedge every sentence "
            "with qualifiers when the evidence supports a clear conclusion."
        )

    # adaptability → gap discipline and escalation threshold
    ad = score("adaptability")
    if ad >= 85:
        clauses.append(
            "Work with incomplete information methodically: label gaps explicitly "
            "rather than avoiding them."
        )
        clauses.append(
            "Escalation threshold: only surface a blocker to the user when "
            "all tool alternatives are genuinely exhausted — uncertainty alone is not a blocker."
        )

    if not clauses:
        return ""

    lines = "\n".join(f"- {c}" for c in clauses)
    return f"## Behavioral calibration\n{lines}\n\n"


# ---------------------------------------------------------------------------
# Task context overlay (agentic tasks only)
# ---------------------------------------------------------------------------

def build_task_context(role: Dict[str, Any]) -> str:
    """
    Return a task execution context block from the role's success_patterns
    and escalation_rules config fields.  Empty string if neither is defined.

    success_patterns tells the model what a complete, high-quality answer
    looks like for this role.  escalation_rules tells it precisely when to
    use ask_user vs. keep working.
    """
    blocks: List[str] = []

    success = role.get("success_patterns") or {}
    if success:
        lines = "\n".join(f"- **{k}:** {v}" for k, v in success.items())
        blocks.append(
            "## What a complete answer looks like for this role\n"
            "Check your FINAL_ANSWER against the applicable pattern before submitting:\n"
            + lines
        )

    escalation = role.get("escalation_rules") or {}
    if escalation:
        escalate_lines = "\n".join(
            f"  - {r}" for r in escalation.get("escalate_when", [])
        )
        no_escalate_lines = "\n".join(
            f"  - {r}" for r in escalation.get("do_not_escalate_when", [])
        )
        esc_block = "## When to escalate (use ask_user)\n"
        if escalate_lines:
            esc_block += f"Escalate when:\n{escalate_lines}\n"
        if no_escalate_lines:
            esc_block += f"Do NOT escalate when:\n{no_escalate_lines}\n"
        blocks.append(esc_block)

    if not blocks:
        return ""

    return "\n\n".join(blocks) + "\n\n"


# ---------------------------------------------------------------------------
# Capability summary
# ---------------------------------------------------------------------------

_CAPABILITY_CATALOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "capability_catalog.json"
)
_capability_catalog_cache: Dict[str, Any] = {}


def _load_capability_catalog() -> Dict[str, Any]:
    global _capability_catalog_cache
    if _capability_catalog_cache:
        return _capability_catalog_cache
    try:
        with open(_CAPABILITY_CATALOG_PATH) as f:
            _capability_catalog_cache = json.load(f)
    except Exception:
        _capability_catalog_cache = {}
    return _capability_catalog_cache


def build_capability_summary(role: Dict[str, Any]) -> str:
    """
    Return a capability summary block — what this role can do.

    Lists capability categories with their descriptions only.
    The agent discovers concrete tool names from the tool schema injected
    by the executor; repeating them here creates a fragile static list that
    diverges the moment tools are added or renamed.

    Returns empty string if the role has no capabilities.
    """
    capabilities: List[str] = role.get("capabilities") or []
    if not capabilities:
        return ""

    catalog = _load_capability_catalog()
    categories = catalog.get("categories", {})

    lines = [
        f"- **{cap}** — {categories.get(cap, {}).get('description', cap)}"
        for cap in capabilities
    ]

    return (
        "## Your Capabilities\n"
        + "\n".join(lines)
        + "\n\n"
        "Discover the specific tools for each capability from the tool schema "
        "provided with this prompt. If a task requires something not covered "
        "above, use `ask_user` to escalate.\n\n"
    )
