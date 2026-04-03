"""
agency-agents → Nine Chapter Bridge

Takes an AgencyAgentEntry (parsed from agency-agents markdown) and produces
pre-filled answers for the Nine Chapter wizard steps.

The pre-fills are *suggestions* — the user still goes through the full wizard
and predict-verify to calibrate the Nine Chapter score. Nothing is written to
a role spec without user confirmation.
"""

from __future__ import annotations

from typing import Any, Dict

from app.roles.agency_agents_parser import AgencyAgentEntry


def build_prefills(entry: AgencyAgentEntry) -> Dict[str, Any]:
    """
    Map an AgencyAgentEntry to Nine Chapter wizard step pre-fills.

    Returns a dict keyed by wizard step name. Values are suggested answer
    strings. Empty string means no pre-fill available for that step.

    Mapping rationale:
      intro            ← name + description + vibe
      core_values      ← Critical Rules section (operating principles)
      emotional_reaction ← personality bullet + vibe tone
      cognitive_style  ← experience bullet + mission approach
      social_orientation ← Communication Style section
      adaptability     ← (no direct mapping — left for user)
      purpose          ← Core Mission section
      role_type        ← agent_type_hint (canonical ID)
    """
    intro = _build_intro(entry)
    core_values = _build_core_values(entry)
    emotional_reaction = _build_emotional_reaction(entry)
    cognitive_style = _build_cognitive_style(entry)
    social_orientation = _build_social_orientation(entry)
    purpose = _build_purpose(entry)

    return {
        "intro":              intro,
        "core_values":        core_values,
        "emotional_reaction": emotional_reaction,
        "cognitive_style":    cognitive_style,
        "social_orientation": social_orientation,
        "adaptability":       _build_adaptability(entry),
        "purpose":            purpose,
        "role_type":          entry.agent_type_hint,
    }


# ── Field builders ─────────────────────────────────────────────────────────────

def _build_intro(entry: AgencyAgentEntry) -> str:
    parts = []
    name = entry.name
    if name:
        parts.append(f"{name}.")
    if entry.description:
        parts.append(entry.description)
    if entry.vibe:
        parts.append(f"Vibe: {entry.vibe}")
    return " ".join(parts)


def _build_core_values(entry: AgencyAgentEntry) -> str:
    """Critical Rules → operating principles → core_values."""
    if not entry.rules:
        return ""
    # Extract numbered/bulleted rules as a condensed list
    lines = []
    for line in entry.rules.splitlines():
        stripped = line.strip()
        if stripped and (stripped[0].isdigit() or stripped.startswith(("-", "*", "•"))):
            # Clean markdown bold/italic
            import re
            clean = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", stripped)
            clean = re.sub(r"`(.+?)`", r"\1", clean)
            if clean:
                lines.append(clean)
    return "\n".join(lines[:8])  # cap at 8 rules to stay focused


def _build_emotional_reaction(entry: AgencyAgentEntry) -> str:
    """Personality bullet + vibe as emotional default description."""
    parts = []
    if entry.personality:
        parts.append(entry.personality)
    if entry.vibe:
        parts.append(entry.vibe)
    return ". ".join(p.rstrip(".") for p in parts if p)


def _build_cognitive_style(entry: AgencyAgentEntry) -> str:
    """Experience bullet as a proxy for cognitive approach."""
    if entry.experience:
        return entry.experience
    # Fall back to first sentence of mission
    if entry.mission:
        first = entry.mission.split(".")[0].strip()
        return first if len(first) > 20 else ""
    return ""


def _build_social_orientation(entry: AgencyAgentEntry) -> str:
    """Communication Style section — most direct mapping."""
    if not entry.communication:
        return ""
    # Take first 300 chars, skip header lines
    import re
    lines = []
    for line in entry.communication.splitlines():
        stripped = line.strip()
        if not stripped or re.match(r"^#{1,3}\s", stripped):
            continue
        lines.append(stripped)
    return "\n".join(lines)[:300]


def _build_adaptability(entry: AgencyAgentEntry) -> str:
    """Workflow process as a proxy for how the role handles change/uncertainty."""
    if not entry.workflow:
        return ""
    import re
    lines = []
    for line in entry.workflow.splitlines():
        stripped = line.strip()
        if not stripped or re.match(r"^#{1,3}\s", stripped):
            continue
        lines.append(stripped)
    return "\n".join(lines)[:250]


def _build_purpose(entry: AgencyAgentEntry) -> str:
    """Core Mission section — purpose of the role."""
    if not entry.mission:
        return entry.description
    # First paragraph only
    paras = [p.strip() for p in entry.mission.split("\n\n") if p.strip()]
    if paras:
        import re
        clean = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", paras[0])
        return clean[:400]
    return entry.description


def prefills_to_session_answers(prefills: Dict[str, Any]) -> Dict[str, str]:
    """
    Convert prefills dict to the answers dict format used by RoleDesignSession.
    Skips empty values so wizard shows blank rather than empty string.
    """
    return {k: v for k, v in prefills.items() if isinstance(v, str) and v.strip()}
