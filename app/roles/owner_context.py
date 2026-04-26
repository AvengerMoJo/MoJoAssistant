"""
Owner context injection — filtered owner profile slices for LLM prompts.

The MCP channel is trusted (owner is always on the other end). The concern is
downstream: owner profile fields injected into system prompts that leave the
device to an external LLM.

Context tiers:
  "full"    — local LLM only; all owner profile fields safe to include
  "minimal" — external LLM may be used; only non-sensitive fields injected

Per-role field filtering:
  Roles may declare `owner_context_fields` as a list of field keys to restrict
  which owner profile data is injected, regardless of tier. Available keys:
    "name"          — preferred_name / name
    "timezone"      — timezone
    "goals"         — core_goals
    "relationships" — assistant_relationships
    "sensitive"     — privacy_preferences.sensitive_domains
    "workdir"       — agent_workdir (infra_context)
    "communication" — communication_preferences

Rule: if all tier_preference entries are "free" (local), use "full".
      Any external-capable tier → "minimal".
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from app.config.paths import get_memory_subpath, get_memory_path

_OWNER_PROFILE_PATH = get_memory_subpath("owner_profile.json")

_FULL_FIELDS: Set[str] = {"name", "timezone", "goals", "relationships", "sensitive", "workdir", "communication"}
_MINIMAL_FIELDS: Set[str] = {"name", "communication"}


def _load_agent_workdir() -> str:
    """Return agent_workdir from infra_context.json, or empty string if not configured."""
    try:
        infra_path = Path(get_memory_path()) / "config" / "infra_context.json"
        data = json.loads(infra_path.read_text(encoding="utf-8"))
        return data.get("agent_workdir", "")
    except Exception:
        return ""


def load_owner_profile(path: Path = _OWNER_PROFILE_PATH) -> Dict[str, Any]:
    """Load owner_profile.json. Returns empty dict if missing or malformed."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def infer_context_tier(tier_preference: List[Any]) -> str:
    """Return "full" if all tiers are local-only, otherwise "minimal".

    Args:
        tier_preference: list of ResourceTier values or raw strings from task config.
    """
    local_tiers = {"free"}
    for t in tier_preference:
        val = t.value if hasattr(t, "value") else str(t)
        if val not in local_tiers:
            return "minimal"
    return "full"


def build_owner_context_slice(
    owner_profile: Dict[str, Any],
    context_tier: str,
    fields_filter: Optional[List[str]] = None,
) -> str:
    """Return a formatted owner context block for injection into a system prompt.

    "full" tier: all owner profile fields (local LLM only).
    "minimal" tier: name + communication preferences (safe for external LLMs).

    fields_filter: optional list of field keys to further restrict which fields
    appear, regardless of tier. Roles declare this as `owner_context_fields`.
    The intersection of tier-allowed fields and the filter is used.

    Returns empty string if owner_profile is empty or no fields match.
    """
    if not owner_profile:
        return ""

    tier_fields = _FULL_FIELDS if context_tier == "full" else _MINIMAL_FIELDS
    allowed = tier_fields & set(fields_filter) if fields_filter is not None else tier_fields

    lines: List[str] = ["\n## Owner Context"]

    if "name" in allowed:
        name = owner_profile.get("preferred_name") or owner_profile.get("name")
        if name:
            lines.append(f"You are working for **{name}**.")

    if "timezone" in allowed:
        timezone = owner_profile.get("timezone")
        if timezone:
            lines.append(f"Their timezone is {timezone}.")

    if "goals" in allowed:
        goals = owner_profile.get("core_goals", [])
        if goals:
            lines.append("\nTheir current goals:")
            for g in goals:
                lines.append(f"- {g}")

    if "relationships" in allowed:
        relationships = owner_profile.get("assistant_relationships", {})
        if relationships:
            lines.append("\nYour role in their assistant ecosystem:")
            for role_id, rel in relationships.items():
                rel_type = rel.get("relationship", "")
                focus = ", ".join(rel.get("focus", []))
                lines.append(f"- **{role_id}**: {rel_type}" + (f" ({focus})" if focus else ""))

    if "sensitive" in allowed:
        sensitive = owner_profile.get("privacy_preferences", {}).get("sensitive_domains", [])
        if sensitive:
            lines.append(
                "\n**Sensitive domains** — do not pass data in these areas to external tools "
                "or services without explicit owner approval: "
                + ", ".join(sensitive)
            )

    if "workdir" in allowed:
        agent_workdir = _load_agent_workdir()
        if agent_workdir:
            lines.append(
                f"\n**Default working directory:** When cloning repos, downloading files, or "
                f"creating scratch work, use `{agent_workdir}/<project-name>/` as the target "
                f"path. Never write to the MoJoAssistant project root or relative paths."
            )

    if "communication" in allowed:
        comm = owner_profile.get("communication_preferences", {})
        if comm:
            style = comm.get("style", [])
            verbosity = comm.get("verbosity_default", "")
            parts = []
            if style:
                parts.append("style: " + ", ".join(style))
            if verbosity:
                parts.append(f"verbosity: {verbosity}")
            if comm.get("likes_pushback_when_reasoned"):
                parts.append("welcomes reasoned pushback")
            if comm.get("prefers_specific_recommendations"):
                parts.append("prefers specific recommendations over open-ended options")
            if parts:
                lines.append("\nCommunication preferences: " + "; ".join(parts) + ".")

    if len(lines) == 1:
        return ""

    return "\n".join(lines) + "\n"
