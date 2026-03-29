"""
First-run helpers for MoJoAssistant.

Provides:
- unpack_bundled_roles()  — copy config/roles/*.json to ~/.memory/roles/ if absent
- OWNER_PROFILE_TEMPLATE  — default owner profile schema
- create_owner_profile()  — write ~/.memory/owner_profile.json if absent
- load_owner_profile()    — read ~/.memory/owner_profile.json (empty dict if missing)
"""

import json
import shutil
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Bundled roles
# ---------------------------------------------------------------------------

# Project root is two levels up from this file (app/config/first_run.py)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_BUNDLED_ROLES_DIR = _PROJECT_ROOT / "config" / "roles"


def unpack_bundled_roles(memory_path: Path) -> list[str]:
    """Copy any config/roles/*.json that doesn't exist yet in memory_path/roles/.

    Skips files whose name ends with '.example'.
    Never overwrites existing user-customised roles.

    Returns:
        List of role ids that were freshly unpacked.
    """
    roles_dir = memory_path / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)

    unpacked: list[str] = []

    for src in sorted(_BUNDLED_ROLES_DIR.glob("*.json")):
        if src.name.endswith(".example"):
            continue

        dest = roles_dir / src.name
        if dest.exists():
            continue  # idempotent — never overwrite

        shutil.copy2(src, dest)
        # Derive role id from filename (strip .json)
        role_id = src.stem
        unpacked.append(role_id)

    return unpacked


# ---------------------------------------------------------------------------
# Owner profile
# ---------------------------------------------------------------------------

OWNER_PROFILE_TEMPLATE: dict = {
    "owner_id": "",
    "name": "",
    "preferred_name": "",
    "pronouns": "",
    "timezone": "Asia/Taipei",
    "languages": ["en"],
    "identity": {
        "summary": "",
        "location_context": "",
        "roles_in_life": [],
    },
    "communication_preferences": {
        "style": ["direct", "high-signal", "low-fluff"],
        "verbosity_default": "concise",
        "likes_pushback_when_reasoned": True,
        "prefers_specific_recommendations": True,
    },
    "workflow_preferences": {
        "authorized_command_channel": "mcp",
        "dashboard_chat_is_read_only": True,
        "prefers_private_debrief_in_dashboard": True,
        "wants_clear_mode_labels": True,
    },
    "privacy_preferences": {
        "prefer_local_when_possible": True,
        "wants_auditability_for_external_use": True,
        "sensitive_domains": [
            "personal memory",
            "spiritual notes",
            "security infrastructure",
        ],
    },
    "core_goals": [],
    "assistant_relationships": {
        "rebecca": {
            "relationship": "research partner",
            "focus": ["deep analysis", "comparative reasoning", "explanation"],
        },
        "ahman": {
            "relationship": "security and operations specialist",
            "focus": ["hardening", "infrastructure", "risk surfacing"],
        },
        "carl": {
            "relationship": "code reviewer",
            "focus": ["code quality", "security", "maintainability"],
        },
    },
    "policy_authority": {
        "is_memory_owner": True,
        "can_approve_sensitive_actions": True,
        "can_override_role_defaults": True,
    },
}


def create_owner_profile(
    memory_path: Path, overrides: Optional[dict] = None
) -> Path:
    """Write ~/.memory/owner_profile.json if it doesn't exist.

    Merges *overrides* (top-level keys only) into the template before writing.
    Never overwrites an existing file.

    Returns:
        Path to the owner_profile.json file.
    """
    profile_path = memory_path / "owner_profile.json"

    if profile_path.exists():
        return profile_path

    profile = dict(OWNER_PROFILE_TEMPLATE)
    if overrides:
        profile.update(overrides)

    memory_path.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n")

    return profile_path


def load_owner_profile(memory_path: Path) -> dict:
    """Load owner_profile.json.

    Returns:
        Parsed dict, or empty dict if the file does not exist.
    """
    profile_path = memory_path / "owner_profile.json"
    if not profile_path.exists():
        return {}

    try:
        return json.loads(profile_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
