"""
agency-agents Parser

Reads markdown role files from the agency-agents submodule and extracts
structured fields that can be fed into the Nine Chapter wizard.

Each agency-agents .md file has:
  - YAML frontmatter: name, description, color, emoji, vibe
  - ## 🧠 Your Identity & Memory  → personality, experience
  - ## 🎯 Your Core Mission       → purpose
  - ## 🔧 Critical Rules          → operating principles → core_values
  - ## 💬 Communication Style     → social_orientation
  - Other sections (checklists, formats, etc.) — captured as extra context

Output: AgencyAgentEntry dataclass, ready for agency_agents_bridge to map.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

_SUBMODULE_PATH = Path(__file__).resolve().parents[2] / "submodules" / "agency-agents"

# Sections we care about — emoji prefix is optional/variable, so match loosely
_SECTION_IDENTITY    = re.compile(r"^#{1,3}\s+.*identity", re.IGNORECASE)
_SECTION_MISSION     = re.compile(r"^#{1,3}\s+.*core\s+mission|^#{1,3}\s+.*core\s+capabilit", re.IGNORECASE)
_SECTION_RULES       = re.compile(r"^#{1,3}\s+.*critical", re.IGNORECASE)
_SECTION_COMM        = re.compile(r"^#{1,3}\s+.*communication\s+style", re.IGNORECASE)
_SECTION_WORKFLOW    = re.compile(r"^#{1,3}\s+.*workflow\s+process|^#{1,3}\s+.*decision\s+framework", re.IGNORECASE)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_YAML_FIELD_RE  = re.compile(r"^(\w+):\s*(.+)$", re.MULTILINE)

# Divisions → canonical agent_type hint
_DIVISION_TYPE_MAP: Dict[str, str] = {
    "engineering":        "coder",
    "testing":            "reviewer",
    "design":             "analyst",
    "product":            "analyst",
    "strategy":           "analyst",
    "academic":           "researcher",
    "specialized":        "researcher",
    "project-management": "ops",
    "support":            "assistant",
    "sales":              "assistant",
    "marketing":          "assistant",
    "paid-media":         "assistant",
    "game-development":   "coder",
    "spatial-computing":  "coder",
    "integrations":       "ops",
}

# Name-level overrides — checked after division map; more specific wins
_NAME_TYPE_HINTS: List[tuple[re.Pattern, str]] = [
    (re.compile(r"review", re.I),    "reviewer"),
    (re.compile(r"research", re.I),  "researcher"),
    (re.compile(r"analyst|analyz", re.I), "analyst"),
    (re.compile(r"devops|ops|infra|deploy|sre\b", re.I), "ops"),
    (re.compile(r"data\s+scientist|ml\s+engineer|ai\s+engineer", re.I), "analyst"),
]


@dataclass
class AgencyAgentEntry:
    """Parsed representation of one agency-agents role file."""

    # From frontmatter
    name: str = ""
    description: str = ""
    vibe: str = ""
    emoji: str = ""
    color: str = ""

    # From body sections
    personality: str = ""    # Identity & Memory → Personality bullet
    experience: str = ""     # Identity & Memory → Experience bullet
    mission: str = ""        # Core Mission section (first 400 chars)
    rules: str = ""          # Critical Rules section (first 600 chars)
    communication: str = ""  # Communication Style section
    workflow: str = ""       # Workflow Process / Decision Framework → adaptability

    # Derived
    division: str = ""       # parent directory name
    file_path: str = ""      # absolute path to source file
    agent_type_hint: str = "assistant"  # canonical type derived from division


def _strip_emoji(text: str) -> str:
    """Remove leading emoji characters from a string."""
    return re.sub(r"^[\U00010000-\U0010ffff\u2600-\u27ff\U0001f300-\U0001faff\s]+", "", text).strip()


def _parse_frontmatter(content: str) -> Dict[str, str]:
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}
    return {k: v.strip() for k, v in _YAML_FIELD_RE.findall(m.group(1))}


def _extract_section(lines: List[str], header_re: re.Pattern, max_chars: int = 500) -> str:
    """
    Extract text content of the first matching section, up to max_chars.
    Only stops when a header at the same level or higher is encountered —
    subsections (deeper heading level) are included as part of the section.
    """
    in_section = False
    section_level = 2  # default H2
    buf: List[str] = []
    total = 0
    for line in lines:
        hm = re.match(r"^(#{1,6})\s", line)
        if hm:
            level = len(hm.group(1))
            if in_section and level <= section_level:
                break
            if not in_section and header_re.match(line):
                in_section = True
                section_level = level
                continue
        if in_section:
            buf.append(line)
            total += len(line)
            if total >= max_chars:
                break
    return "\n".join(buf).strip()


def _extract_bullet(text: str, keyword: str) -> str:
    """Pull the first bullet containing keyword from a text block."""
    for line in text.splitlines():
        if keyword.lower() in line.lower() and line.strip().startswith(("-", "*", "•")):
            # Strip markdown bullet and bold markers
            clean = re.sub(r"^\s*[-*•]\s*\*{0,2}[^*]*\*{0,2}:\s*", "", line).strip()
            clean = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", clean)
            return clean
    return ""


def parse_file(path: Path) -> Optional[AgencyAgentEntry]:
    """Parse a single agency-agents markdown file into an AgencyAgentEntry."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    fm = _parse_frontmatter(content)
    if not fm.get("name"):
        return None

    # Strip frontmatter for section parsing
    body = _FRONTMATTER_RE.sub("", content)
    lines = body.splitlines()

    identity_text  = _extract_section(lines, _SECTION_IDENTITY, max_chars=600)
    mission_text   = _extract_section(lines, _SECTION_MISSION,  max_chars=600)
    rules_text     = _extract_section(lines, _SECTION_RULES,    max_chars=800)
    comm_text      = _extract_section(lines, _SECTION_COMM,     max_chars=600)
    workflow_text  = _extract_section(lines, _SECTION_WORKFLOW,  max_chars=400)

    division = path.parent.name
    agent_type_hint = _DIVISION_TYPE_MAP.get(division, "assistant")
    # Name-level override is more specific than division
    role_name = fm.get("name", "")
    for pattern, hint in _NAME_TYPE_HINTS:
        if pattern.search(role_name):
            agent_type_hint = hint
            break

    entry = AgencyAgentEntry(
        name        = fm.get("name", ""),
        description = fm.get("description", ""),
        vibe        = fm.get("vibe", ""),
        emoji       = fm.get("emoji", ""),
        color       = fm.get("color", ""),
        personality = _extract_bullet(identity_text, "personality"),
        experience  = _extract_bullet(identity_text, "experience"),
        mission     = mission_text[:600],
        rules       = rules_text[:800],
        communication = comm_text[:600],
        workflow    = workflow_text[:400],
        division    = division,
        file_path   = str(path),
        agent_type_hint = agent_type_hint,
    )
    return entry


def list_roles(submodule_path: Path = _SUBMODULE_PATH) -> List[AgencyAgentEntry]:
    """
    Walk the agency-agents submodule and return all parsed role entries.
    Skips README, CONTRIBUTING, and non-role files.
    """
    if not submodule_path.exists():
        return []

    skip_names = {"README.md", "CONTRIBUTING.md", "CONTRIBUTING_zh-CN.md"}
    skip_dirs  = {"examples", ".github", "scripts"}

    entries: List[AgencyAgentEntry] = []
    for md_file in sorted(submodule_path.rglob("*.md")):
        if md_file.name in skip_names:
            continue
        if any(part in skip_dirs for part in md_file.parts):
            continue
        entry = parse_file(md_file)
        if entry:
            entries.append(entry)
    return entries


def search_roles(
    query: str,
    submodule_path: Path = _SUBMODULE_PATH,
    max_results: int = 10,
) -> List[AgencyAgentEntry]:
    """
    Simple keyword search across name, description, vibe, and division.
    Returns up to max_results matches, ranked by match score.
    """
    terms = query.lower().split()
    results: List[tuple[int, AgencyAgentEntry]] = []

    for entry in list_roles(submodule_path):
        haystack = " ".join([
            entry.name, entry.description, entry.vibe,
            entry.division, entry.personality,
        ]).lower()
        score = sum(1 for t in terms if t in haystack)
        if score > 0:
            results.append((score, entry))

    results.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in results[:max_results]]
