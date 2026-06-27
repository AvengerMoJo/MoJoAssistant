"""Self-Tunable Role Parameters.

Allows agents to adapt their own operating parameters based on task outcomes.
Applies autoresearch's scaffold-vs-experiment separation:
- Scaffold (immutable): name, persona, capabilities, identity
- Experiment (tunable): temperature, max_iterations, tool preferences

Usage:
    from app.memory.self_tunable import TunableParams, validate_update

    params = TunableParams.from_role(role_dict)
    validated = validate_update(params, {"temperature": 0.8})
    # Returns validated dict with only tunable fields
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Default tunable parameters — agents can modify these
DEFAULT_TUNABLE = {
    "temperature",
    "max_iterations",
    "max_duration_seconds",
    "model_preference",
    "top_p",
    "frequency_penalty",
    "presence_penalty",
}

# Immutable parameters — agents cannot modify these
IMMUTABLE = {
    "id",
    "name",
    "archetype",
    "agent_type",
    "capabilities",
    "system_prompt",
    "purpose",
    "dimensions",
    "nine_chapter_score",
    "created_at",
}


@dataclass
class TunableParams:
    """Defines which parameters an agent can modify."""
    tunable: Set[str] = field(default_factory=lambda: set(DEFAULT_TUNABLE))
    immutable: Set[str] = field(default_factory=lambda: set(IMMUTABLE))
    custom_tunable: Set[str] = field(default_factory=set)

    @classmethod
    def from_role(cls, role: Dict[str, Any]) -> "TunableParams":
        """Load tunable params from a role dict."""
        role_tunable = role.get("self_tunable_params", {})
        if isinstance(role_tunable, dict):
            custom = set(role_tunable.get("fields", []))
            overrides = set(role_tunable.get("overrides", []))
        elif isinstance(role_tunable, list):
            custom = set(role_tunable)
            overrides = set()
        else:
            custom = set()
            overrides = set()

        return cls(
            tunable=set(DEFAULT_TUNABLE) | custom | overrides,
            immutable=set(IMMUTABLE) - overrides,
            custom_tunable=custom,
        )

    def is_tunable(self, field_name: str) -> bool:
        """Check if a field is tunable by the agent."""
        return field_name in self.tunable and field_name not in self.immutable

    def is_immutable(self, field_name: str) -> bool:
        """Check if a field is immutable."""
        return field_name in self.immutable or field_name not in self.tunable

    def validate_update(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Filter updates to only include tunable fields.

        Returns dict with only valid tunable updates.
        Logs warnings for rejected immutable fields.
        """
        valid = {}
        for key, value in updates.items():
            if self.is_tunable(key):
                valid[key] = value
            else:
                logger.warning(f"Rejected immutable field update: {key}")
        return valid

    def get_tunable_list(self) -> List[str]:
        """Return sorted list of tunable field names."""
        return sorted(self.tunable - self.immutable)


def validate_update(
    params: TunableParams,
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    """Convenience function to validate updates against tunable params."""
    return params.validate_update(updates)


def apply_tunable_update(
    role: Dict[str, Any],
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply tunable updates to a role dict.

    Returns updated role dict with changes logged.
    Raises ValueError if any update targets an immutable field.
    """
    params = TunableParams.from_role(role)
    validated = params.validate_update(updates)

    if not validated:
        return role

    # Apply validated updates
    for key, value in validated.items():
        old_value = role.get(key)
        role[key] = value
        logger.info(f"Role {role.get('id')}: {key} {old_value} → {value}")

    # Update timestamp
    from datetime import datetime, timezone
    role["updated_at"] = datetime.now(timezone.utc).isoformat()

    return role
