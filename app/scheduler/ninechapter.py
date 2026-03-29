"""
NineChapter runtime behavioral overlay.

Converts a role's dimensional scores into concrete behavioral directives
injected at the top of the system prompt (after the mode overlay, before
the persona body).  This makes NineChapter scores operationally meaningful
rather than purely descriptive metadata.

Dimensions and their behavioral mapping
----------------------------------------
core_values       Evidence rigor, uncertainty naming, intellectual honesty
cognitive_style   Response structure, verification discipline
social_orientation Question discipline (one focused question at a time)
emotional_reaction Composure under challenge, evidence-based pushback
adaptability      Handling incomplete information, labeling gaps

Thresholds: ≥90 → strong directive, 75–89 → moderate directive, <75 → silent.
"""
from __future__ import annotations

from typing import Any, Dict


def build_behavioral_overlay(role: Dict[str, Any]) -> str:
    """
    Return a short behavioral calibration block derived from the role's
    NineChapter dimension scores, or an empty string if no dimensions exist.

    The block is prepended to the system prompt so the model treats these
    directives as high-priority operating constraints.
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

    clauses: list[str] = []

    # core_values → evidence rigor and intellectual honesty
    cv = score("core_values")
    if cv >= 90:
        clauses.append(
            "Name uncertainty explicitly — never present incomplete findings as settled conclusions."
        )
    elif cv >= 75:
        clauses.append("Flag significant uncertainties before stating conclusions.")

    # cognitive_style → systematic structure
    cs = score("cognitive_style")
    if cs >= 90:
        clauses.append(
            "Structure responses systematically: break the problem into components before synthesizing."
        )
    elif cs >= 75:
        clauses.append("Organize complex responses into clear sections.")

    # social_orientation → question discipline
    so = score("social_orientation")
    if so >= 85:
        clauses.append(
            "When clarification is needed, ask one focused question at a time — never a list."
        )

    # emotional_reaction → composure under challenge
    er = score("emotional_reaction")
    if er >= 90:
        clauses.append(
            "Welcome pushback as a refinement opportunity — engage it directly with evidence, not defensiveness."
        )

    # adaptability → gap discipline
    ad = score("adaptability")
    if ad >= 85:
        clauses.append(
            "Work with incomplete information methodically: label gaps explicitly rather than avoiding them."
        )

    if not clauses:
        return ""

    lines = "\n".join(f"- {c}" for c in clauses)
    return f"## Behavioral calibration\n{lines}\n\n"
