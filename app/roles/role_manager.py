"""
Role Manager

Loads, saves, and lists role configs from ~/.memory/roles/.
Each role is a JSON file named {role_id}.json.
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from app.config.paths import get_memory_subpath

ROLES_DIR = get_memory_subpath("roles")


class RoleManager:

    def __init__(self, roles_dir: str = ROLES_DIR):
        self._dir = roles_dir
        os.makedirs(self._dir, exist_ok=True)

    def save(self, role: Dict[str, Any]) -> str:
        """Persist a role config. Returns the path it was saved to."""
        role_id = role.get("id")
        if not role_id:
            raise ValueError("Role must have an 'id' field")
        role["updated_at"] = datetime.now().isoformat()
        path = os.path.join(self._dir, f"{role_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(role, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return path

    def get(self, role_id: str) -> Optional[Dict[str, Any]]:
        """Load a role by id. Returns None if not found."""
        path = os.path.join(self._dir, f"{role_id}.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_roles(self) -> List[Dict[str, Any]]:
        """Return summary dicts for all saved roles (no system_prompt to keep it brief)."""
        roles = []
        for fname in sorted(os.listdir(self._dir)):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(self._dir, fname), "r", encoding="utf-8") as f:
                    role = json.load(f)
                roles.append({
                    "id": role.get("id"),
                    "name": role.get("name"),
                    "archetype": role.get("archetype"),
                    "nine_chapter_score": role.get("nine_chapter_score"),
                    "purpose": role.get("purpose"),
                    "model_preference": role.get("model_preference"),
                    "updated_at": role.get("updated_at"),
                })
            except Exception:
                continue
        return roles

    def delete(self, role_id: str) -> bool:
        path = os.path.join(self._dir, f"{role_id}.json")
        if os.path.exists(path):
            os.unlink(path)
            return True
        return False
