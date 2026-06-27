"""Self-Tunable Role Parameters — file I/O layer.

Allows agents to adapt their own operating parameters based on task outcomes.
Applies autoresearch's scaffold-vs-experiment separation.

Usage:
    from app.scheduler.role_self_tuning import propose_param_update, get_tunable_params

    # Agent proposes a parameter change after a task
    result = propose_param_update("popo", "temperature", 0.8, "lower temp improved accuracy")
    # Returns {"success": True, "old": 0.7, "new": 0.8}

    # Get current tunable params for a role
    params = get_tunable_params("popo")
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config.paths import get_memory_path

logger = logging.getLogger(__name__)

# Default tunable parameters with validation bounds
TUNABLE_PARAM_DEFS = {
    "temperature": {"type": "float", "min": 0.0, "max": 2.0, "default": 0.7},
    "max_iterations": {"type": "int", "min": 1, "max": 100, "default": 10},
    "max_duration_seconds": {"type": "int", "min": 60, "max": 7200, "default": 300},
    "model_preference": {"type": "string", "default": None},
    "top_p": {"type": "float", "min": 0.0, "max": 1.0, "default": 1.0},
    "frequency_penalty": {"type": "float", "min": -2.0, "max": 2.0, "default": 0.0},
    "presence_penalty": {"type": "float", "min": -2.0, "max": 2.0, "default": 0.0},
}

# Fields agents can never modify
IMMUTABLE_FIELDS = {
    "id", "name", "archetype", "agent_type", "capabilities",
    "system_prompt", "purpose", "dimensions", "nine_chapter_score",
    "created_at", "self_tunable_params",
}


def _role_path(role_id: str) -> Path:
    return Path(get_memory_path()) / "roles" / f"{role_id}.json"


def _load_role(role_id: str) -> Optional[Dict[str, Any]]:
    path = _role_path(role_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as e:
        logger.warning(f"Failed to load role {role_id}: {e}")
        return None


def _save_role(role_id: str, role: Dict[str, Any]) -> bool:
    path = _role_path(role_id)
    try:
        role["updated_at"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(role, indent=2, ensure_ascii=False))
        return True
    except Exception as e:
        logger.error(f"Failed to save role {role_id}: {e}")
        return False


def get_tunable_params(role_id: str) -> Dict[str, Any]:
    """Get current tunable parameter values for a role.

    Returns dict of {param_name: current_value} for all tunable params.
    """
    role = _load_role(role_id)
    if not role:
        return {}

    # Get role's custom tunable list if defined
    role_tunable = role.get("self_tunable_params", {})
    if isinstance(role_tunable, dict):
        custom_fields = set(role_tunable.get("fields", []))
    elif isinstance(role_tunable, list):
        custom_fields = set(role_tunable)
    else:
        custom_fields = set()

    all_tunable = set(TUNABLE_PARAM_DEFS.keys()) | custom_fields

    result = {}
    for param in sorted(all_tunable):
        if param in IMMUTABLE_FIELDS:
            continue
        value = role.get(param)
        if value is not None:
            result[param] = value
        elif param in TUNABLE_PARAM_DEFS:
            result[param] = TUNABLE_PARAM_DEFS[param].get("default")

    return result


def propose_param_update(
    role_id: str,
    param: str,
    value: Any,
    reason: str = "",
) -> Dict[str, Any]:
    """Propose a parameter update for a role.

    Validates the parameter is tunable and within bounds, then writes to disk.

    Args:
        role_id: Role to update
        param: Parameter name
        value: New value
        reason: Why this change is proposed

    Returns:
        {"success": bool, "old": old_value, "new": new_value, "error": str}
    """
    # Check immutable
    if param in IMMUTABLE_FIELDS:
        return {"success": False, "error": f"'{param}' is immutable"}

    # Check if tunable
    role = _load_role(role_id)
    if not role:
        return {"success": False, "error": f"Role '{role_id}' not found"}

    role_tunable = role.get("self_tunable_params", {})
    if isinstance(role_tunable, dict):
        custom_fields = set(role_tunable.get("fields", []))
    elif isinstance(role_tunable, list):
        custom_fields = set(role_tunable)
    else:
        custom_fields = set()

    all_tunable = set(TUNABLE_PARAM_DEFS.keys()) | custom_fields
    if param not in all_tunable:
        return {"success": False, "error": f"'{param}' is not tunable for this role"}

    # Validate bounds
    if param in TUNABLE_PARAM_DEFS:
        spec = TUNABLE_PARAM_DEFS[param]
        param_type = spec.get("type")

        if param_type == "float":
            try:
                value = float(value)
            except (TypeError, ValueError):
                return {"success": False, "error": f"'{param}' must be a float"}
            if "min" in spec and value < spec["min"]:
                return {"success": False, "error": f"'{param}' must be >= {spec['min']}"}
            if "max" in spec and value > spec["max"]:
                return {"success": False, "error": f"'{param}' must be <= {spec['max']}"}

        elif param_type == "int":
            try:
                value = int(value)
            except (TypeError, ValueError):
                return {"success": False, "error": f"'{param}' must be an integer"}
            if "min" in spec and value < spec["min"]:
                return {"success": False, "error": f"'{param}' must be >= {spec['min']}"}
            if "max" in spec and value > spec["max"]:
                return {"success": False, "error": f"'{param}' must be <= {spec['max']}"}

    # Apply update
    old_value = role.get(param)
    role[param] = value

    # Add to tuning history
    if "tuning_history" not in role:
        role["tuning_history"] = []
    role["tuning_history"].append({
        "param": param,
        "old": old_value,
        "new": value,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    if _save_role(role_id, role):
        logger.info(f"Role {role_id}: {param} {old_value} → {value} ({reason})")
        return {"success": True, "old": old_value, "new": value}

    return {"success": False, "error": "Failed to save role config"}


def reset_tunable_params(role_id: str) -> Dict[str, Any]:
    """Reset all tunable params to defaults.

    Returns dict of {param: {"old": old_value, "new": default_value}}
    """
    role = _load_role(role_id)
    if not role:
        return {"error": f"Role '{role_id}' not found"}

    changes = {}
    for param, spec in TUNABLE_PARAM_DEFS.items():
        old_value = role.get(param)
        default = spec.get("default")
        if old_value is not None and old_value != default:
            role[param] = default
            changes[param] = {"old": old_value, "new": default}

    if changes:
        _save_role(role_id, role)

    return changes


def parse_self_tune_from_answer(answer: str) -> List[Dict[str, Any]]:
    """Parse SELF_TUNE directives from an agent's FINAL_ANSWER.

    Format: SELF_TUNE: param=value; reason

    Returns list of {"param": str, "value": str, "reason": str}
    """
    import re
    pattern = r"SELF_TUNE:\s*(\w+)\s*=\s*(.+?)(?:;\s*(.+))?$"
    results = []
    for line in answer.split("\n"):
        match = re.match(pattern, line.strip())
        if match:
            results.append({
                "param": match.group(1).strip(),
                "value": match.group(2).strip(),
                "reason": (match.group(3) or "").strip(),
            })
    return results
