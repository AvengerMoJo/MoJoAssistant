"""
Agency-Agents Import Bridge — parse markdown personas into MoJoAssistant roles.

Reads markdown persona files from the agency-agents library and converts them
into MoJoAssistant role JSON format with NineChapter dimension pre-fills.

Usage:
    from app.roles.agency_importer import parse_agency_persona, import_persona

    # Parse a single file
    role = parse_agency_persona(Path("submodules/agency-agents/product/product-manager.md"))

    # Import into ~/.memory/roles/
    path = import_persona(Path("submodules/agency-agents/product/product-manager.md"))
"""
# [mojo-integration]

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.roles.role_manager import RoleManager

logger = logging.getLogger(__name__)

# Maps agency-agents tool names to MoJoAssistant capability categories
_TOOL_MAP: Dict[str, str] = {
    "WebFetch": "web",
    "WebSearch": "web",
    "Read": "file",
    "Write": "file",
    "Edit": "file",
    "Bash": "bash",
    "Glob": "file",
    "Grep": "file",
    "TodoWrite": "memory",
    "Task": "orchestration",
}


def _parse_frontmatter(text: str) -> Dict[str, str]:
    """Extract YAML frontmatter from markdown."""
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    result = {}
    for line in match.group(1).strip().split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


def _extract_section(text: str, heading: str) -> str:
    """Extract content under a markdown heading (## level)."""
    pattern = rf"## {re.escape(heading)}\s*\n(.*?)(?=\n## |\Z)"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_identity(text: str) -> str:
    """Extract the Identity & Memory section content."""
    return _extract_section(text, "🧠 Identity & Memory")


def _extract_critical_rules(text: str) -> List[str]:
    """Extract numbered rules from Critical Rules section."""
    rules_text = _extract_section(text, "🚨 Critical Rules")
    rules = []
    for match in re.finditer(r"\d+\.\s+\*\*(.+?)\*\*\s*(.*?)(?=\d+\.|\Z)", rules_text, re.DOTALL):
        title = match.group(1).strip()
        body = match.group(2).strip()
        rules.append(f"{title}: {body}" if body else title)
    return rules


def _extract_communication_style(text: str) -> str:
    """Extract Communication Style section."""
    return _extract_section(text, "💬 Communication Style")


def _extract_personality_highlights(text: str) -> List[str]:
    """Extract blockquote personality highlights."""
    section = _extract_section(text, "🎭 Personality Highlights")
    return [m.group(1).strip() for m in re.finditer(r">\s*(.+?)(?=\n>|\n\n|\Z)", section, re.DOTALL)]


def _map_tools_to_capabilities(tools_str: str) -> List[str]:
    """Convert comma-separated tool names to capability categories."""
    if not tools_str:
        return ["memory"]
    caps = set()
    for tool in tools_str.split(","):
        tool = tool.strip()
        cap = _TOOL_MAP.get(tool)
        if cap:
            caps.add(cap)
        else:
            caps.add(tool.lower())
    if not caps:
        caps.add("memory")
    return sorted(caps)


def _infer_dimensions(text: str, frontmatter: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    """Generate NineChapter dimension scores from persona content.

    Heuristic mapping based on persona traits described in the markdown.
    """
    dims: Dict[str, Dict[str, Any]] = {}
    vibe = frontmatter.get("vibe", "").lower()
    identity = _extract_identity(text).lower()
    rules = _extract_critical_rules(text)
    comm = _extract_communication_style(text).lower()
    all_text = f"{vibe} {identity} {' '.join(rules)} {comm}"

    # core_values — evidence rigor, intellectual honesty
    core_score = 75
    core_hints = ["evidence", "honest", "integrity", "rigor", "accuracy", "truth", "verify"]
    if any(h in all_text for h in core_hints):
        core_score = 90
    if "uncertainty" in all_text and "explicit" in all_text:
        core_score = 95
    dims["core_values"] = {"score": core_score, "summary": f"Inferred from persona: {frontmatter.get('description', '')[:120]}"}

    # cognitive_style — structure, verification
    cog_score = 75
    cog_hints = ["systematic", "methodical", "structured", "analytical", "break.*down", "component"]
    if any(re.search(h, all_text) for h in cog_hints):
        cog_score = 85
    dims["cognitive_style"] = {"score": cog_score, "summary": "Inferred from persona behavioral patterns."}

    # social_orientation — question discipline, teaching
    so_score = 70
    so_hints = ["collaborative", "educational", "guide", "listen", "empathy", "teach"]
    if any(h in all_text for h in so_hints):
        so_score = 85
    dims["social_orientation"] = {"score": so_score, "summary": "Inferred from persona communication style."}

    # emotional_reaction — composure
    er_score = 70
    er_hints = ["calm", "composed", "direct", "respectful", "pushback", "challenged"]
    if any(h in all_text for h in er_hints):
        er_score = 85
    dims["emotional_reaction"] = {"score": er_score, "summary": "Inferred from persona emotional patterns."}

    # adaptability — gap handling
    adapt_score = 70
    adapt_hints = ["uncertainty", "comfortable", "adapt", "flexible", "incomplete"]
    if any(h in all_text for h in adapt_hints):
        adapt_score = 85
    dims["adaptability"] = {"score": adapt_score, "summary": "Inferred from persona adaptability signals."}

    return dims


def parse_agency_persona(file_path: Path) -> Dict[str, Any]:
    """Parse an agency-agents markdown file into a MoJoAssistant role dict.

    Args:
        file_path: Path to the .md persona file.

    Returns:
        Role dict ready for RoleManager.save().
    """
    text = file_path.read_text(encoding="utf-8")
    frontmatter = _parse_frontmatter(text)

    # Derive role_id from filename: product-manager → product_manager
    role_id = file_path.stem.replace("-", "_")

    # Build system prompt from identity + critical rules
    identity = _extract_identity(text)
    rules = _extract_critical_rules(text)
    system_prompt_parts = [f"You are {frontmatter.get('name', role_id)}."]
    if identity:
        system_prompt_parts.append(identity)
    if rules:
        system_prompt_parts.append("\n## Critical Rules\n" + "\n".join(f"- {r}" for r in rules))
    system_prompt = "\n\n".join(system_prompt_parts)

    # Map fields
    name = frontmatter.get("name", role_id.replace("_", " ").title())
    description = frontmatter.get("description", "")
    purpose = description or system_prompt_parts[1][:300] if len(system_prompt_parts) > 1 else name
    tools = frontmatter.get("tools", "")
    capabilities = _map_tools_to_capabilities(tools)
    dimensions = _infer_dimensions(text, frontmatter)
    nine_chapter_score = sum(d["score"] for d in dimensions.values()) // len(dimensions) if dimensions else 75

    # Extract success patterns from technical deliverables
    success_patterns = {}
    deliverables = _extract_section(text, "🛠️ Technical Deliverables")
    if deliverables:
        for match in re.finditer(r"### (.+?)\n", deliverables):
            pattern_name = match.group(1).strip().lower().replace(" ", "_")
            success_patterns[pattern_name] = f"Deliver a complete, structured {match.group(1).strip()} document."

    role = {
        "id": role_id,
        "name": name,
        "archetype": "imported_persona",
        "agent_type": frontmatter.get("agent_type", "general"),
        "nine_chapter_score": nine_chapter_score,
        "dimensions": dimensions,
        "purpose": purpose[:500],
        "system_prompt": system_prompt,
        "model_preference": None,
        "resource_requirements": {
            "tier": ["free_api", "free"],
            "min_context": 65536,
        },
        "behavior_rules": {
            "exhausts_tools_before_asking": True,
        },
        "success_patterns": success_patterns,
        "capabilities": capabilities,
        "imported_from": str(file_path),
        "imported_at": datetime.now().isoformat(),
    }

    return role


def import_persona(file_path: Path, roles_dir: Optional[str] = None) -> str:
    """Parse and save an agency-agents persona as a MoJoAssistant role.

    Args:
        file_path: Path to the .md persona file.
        roles_dir: Override roles directory (default: ~/.memory/roles/).

    Returns:
        Path to the saved role JSON file.
    """
    role = parse_agency_persona(file_path)
    manager = RoleManager(roles_dir) if roles_dir else RoleManager()
    path = manager.save(role)
    logger.info(f"Imported agency persona '{role['name']}' → {path}")
    return path


def list_available_personas(library_path: Optional[Path] = None) -> List[Dict[str, str]]:
    """List all available persona markdown files in the agency-agents library.

    Returns:
        List of {name, path, category, description} dicts.
    """
    if library_path is None:
        library_path = Path(__file__).parent.parent.parent / "submodules" / "agency-agents"

    if not library_path.is_dir():
        return []

    personas = []
    for md_file in sorted(library_path.rglob("*.md")):
        # Skip README, CONTRIBUTING, etc.
        if md_file.name.startswith(("README", "CONTRIBUTING", ".")):
            continue
        # Skip integration docs
        if "integrations" in md_file.parts:
            continue
        # Skip strategy/runbook/playbook docs
        if any(p in md_file.parts for p in ("runbooks", "playbooks", "coordination")):
            continue

        text = md_file.read_text(encoding="utf-8", errors="ignore")
        frontmatter = _parse_frontmatter(text)
        if not frontmatter.get("name"):
            continue

        category = md_file.parent.name if md_file.parent != library_path else "general"
        personas.append({
            "name": frontmatter.get("name", md_file.stem),
            "path": str(md_file),
            "category": category,
            "description": frontmatter.get("description", "")[:200],
        })

    return personas
