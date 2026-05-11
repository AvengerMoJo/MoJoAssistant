"""Default SkillProvider implementation.

Reads blueprints from two layers (same pattern as dynamic_tools.json):
  1. config/skill_blueprints/*.json   — system blueprints (repo)
  2. ~/.memory/config/skill_blueprints/*.json  — user-installed blueprints

install() renders template_vars substitution into executor_template and writes
the resulting CapabilityDefinition to the personal dynamic_tools layer.
"""

from __future__ import annotations

import json
import re
import subprocess
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config.paths import get_memory_path
from app.services.provider_contracts import (
    InstallResult,
    ProviderVersion,
    SkillBlueprint,
    SkillProvider,
    SkillTestResult,
)

_SYSTEM_BLUEPRINTS_DIR = Path(__file__).resolve().parents[2] / "config" / "skill_blueprints"
_PERSONAL_BLUEPRINTS_DIR = Path(get_memory_path()) / "config" / "skill_blueprints"
_PERSONAL_TOOLS_FILE = Path(get_memory_path()) / "config" / "dynamic_tools.json"

_BLUEPRINT_SCHEMA_REQUIRED = {"id", "name", "description", "category", "danger_level",
                               "version", "parameters", "executor_template"}


def _substitute(template: Any, env: Dict[str, str]) -> Any:
    """Recursively substitute ${VAR} in strings within a dict/list/str."""
    if isinstance(template, str):
        def _replace(m):
            return str(env.get(m.group(1), m.group(0)))
        return re.sub(r"\$\{([^}]+)\}", _replace, template)
    if isinstance(template, dict):
        return {k: _substitute(v, env) for k, v in template.items()}
    if isinstance(template, list):
        return [_substitute(item, env) for item in template]
    return template


def _load_blueprint_file(path: Path) -> Optional[SkillBlueprint]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = _BLUEPRINT_SCHEMA_REQUIRED - set(data.keys())
        if missing:
            return None
        return SkillBlueprint(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            category=data.get("category", ""),
            danger_level=data.get("danger_level", "low"),
            version=data.get("version", "1.0.0"),
            parameters=data.get("parameters", {"type": "object", "properties": {}, "required": []}),
            executor_template=data["executor_template"],
            template_vars=data.get("template_vars", {}),
            test_args=data.get("test_args", {}),
            tags=data.get("tags", []),
            source=data.get("source", "local"),
            requires_auth=data.get("requires_auth", False),
        )
    except Exception:
        return None


def _default_env() -> Dict[str, str]:
    """Populate common template vars from the runtime environment."""
    return {
        "MEMORY_PATH": str(Path(get_memory_path())),
        "HOME": str(Path.home()),
        "USER": os.environ.get("USER", ""),
    }


class DefaultSkillProvider(SkillProvider):
    PROVIDER_NAME = "default_skill"
    PROVIDER_VERSION = "1.0.0"
    CONTRACT_VERSION = "1.0"

    def get_version(self) -> ProviderVersion:
        return ProviderVersion(
            provider_name=self.PROVIDER_NAME,
            provider_version=self.PROVIDER_VERSION,
            contract_version=self.CONTRACT_VERSION,
        )

    # -- Catalog ----------------------------------------------------------------

    def _load_all_blueprints(self) -> Dict[str, SkillBlueprint]:
        """Load blueprints from system layer then personal layer (personal wins)."""
        blueprints: Dict[str, SkillBlueprint] = {}
        for directory in [_SYSTEM_BLUEPRINTS_DIR, _PERSONAL_BLUEPRINTS_DIR]:
            if not directory.exists():
                continue
            for f in sorted(directory.glob("*.json")):
                bp = _load_blueprint_file(f)
                if bp:
                    blueprints[bp.id] = bp
        return blueprints

    def catalog(self, filter: Optional[Dict[str, Any]] = None) -> List[SkillBlueprint]:
        all_bps = list(self._load_all_blueprints().values())
        if not filter:
            return all_bps
        category = str(filter.get("category", "")).strip().lower()
        query = str(filter.get("query", "")).strip().lower()
        tags = [str(t).lower() for t in filter.get("tags", [])]
        result = []
        for bp in all_bps:
            if category and bp.category.lower() != category:
                continue
            if query and query not in bp.name.lower() and query not in bp.description.lower():
                continue
            if tags and not any(t in [x.lower() for x in bp.tags] for t in tags):
                continue
            result.append(bp)
        return result

    def blueprint(self, skill_id: str) -> Optional[SkillBlueprint]:
        return self._load_all_blueprints().get(skill_id)

    def search(self, query: str) -> List[SkillBlueprint]:
        q = query.strip().lower()
        return [
            bp for bp in self._load_all_blueprints().values()
            if q in bp.name.lower()
            or q in bp.description.lower()
            or any(q in t.lower() for t in bp.tags)
        ]

    # -- Install ----------------------------------------------------------------

    def _render_and_write(
        self, bp: SkillBlueprint, env: Dict[str, Any]
    ) -> InstallResult:
        """Substitute template vars and append to personal dynamic_tools.json."""
        merged_env = {**_default_env(), **{k: str(v) for k, v in env.items()}}
        executor = _substitute(bp.executor_template, merged_env)

        tool_entry: Dict[str, Any] = {
            "name": bp.id,
            "description": bp.description,
            "danger_level": bp.danger_level,
            "version": bp.version,
            "requires_auth": bp.requires_auth,
            "created_at": datetime.now().isoformat(),
            "created_by": "skill_provider",
            "parameters": bp.parameters,
            "executor": executor,
            "category": bp.category,
        }

        # Write to personal dynamic_tools.json
        _PERSONAL_TOOLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        if _PERSONAL_TOOLS_FILE.exists():
            data = json.loads(_PERSONAL_TOOLS_FILE.read_text(encoding="utf-8"))
        else:
            data = {"last_updated": "", "tools": []}

        tools: List[Dict] = data.get("tools", [])
        tools = [t for t in tools if t.get("name") != bp.id]  # replace if exists
        tools.append(tool_entry)
        data["tools"] = tools
        data["last_updated"] = datetime.now().isoformat()
        _PERSONAL_TOOLS_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        return InstallResult(
            skill_id=bp.id,
            tool_entry=tool_entry,
            env_used=merged_env,
            installed_at=tool_entry["created_at"],
        )

    def install(self, skill_id: str, env: Optional[Dict[str, Any]] = None) -> InstallResult:
        bp = self.blueprint(skill_id)
        if bp is None:
            raise ValueError(f"Blueprint '{skill_id}' not found in catalog.")
        return self._render_and_write(bp, env or {})

    def install_blueprint(
        self, blueprint: Dict[str, Any], env: Optional[Dict[str, Any]] = None
    ) -> InstallResult:
        """Validate an agent-provided blueprint dict then install it.

        Also saves the blueprint to the personal blueprints dir so it appears
        in future catalog() calls.
        """
        missing = _BLUEPRINT_SCHEMA_REQUIRED - set(blueprint.keys())
        if missing:
            raise ValueError(f"Blueprint missing required fields: {missing}")

        bp = _load_blueprint_file.__func__ if False else None  # type hint hint
        # Build SkillBlueprint from dict
        bp = SkillBlueprint(
            id=blueprint["id"],
            name=blueprint["name"],
            description=blueprint["description"],
            category=blueprint.get("category", ""),
            danger_level=blueprint.get("danger_level", "low"),
            version=blueprint.get("version", "1.0.0"),
            parameters=blueprint.get("parameters", {"type": "object", "properties": {}, "required": []}),
            executor_template=blueprint["executor_template"],
            template_vars=blueprint.get("template_vars", {}),
            test_args=blueprint.get("test_args", {}),
            tags=blueprint.get("tags", []),
            source=blueprint.get("source", "agent"),
            requires_auth=blueprint.get("requires_auth", False),
        )

        # Save to personal blueprints dir
        _PERSONAL_BLUEPRINTS_DIR.mkdir(parents=True, exist_ok=True)
        bp_path = _PERSONAL_BLUEPRINTS_DIR / f"{bp.id}.json"
        bp_path.write_text(json.dumps(blueprint, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        result = self._render_and_write(bp, env or {})
        result.blueprint_saved_at = str(bp_path)
        return result

    # -- Uninstall --------------------------------------------------------------

    def uninstall(self, skill_id: str) -> bool:
        """Remove from personal dynamic_tools.json and personal blueprints dir."""
        removed = False
        if _PERSONAL_TOOLS_FILE.exists():
            data = json.loads(_PERSONAL_TOOLS_FILE.read_text(encoding="utf-8"))
            tools = data.get("tools", [])
            new_tools = [t for t in tools if t.get("name") != skill_id]
            if len(new_tools) < len(tools):
                data["tools"] = new_tools
                data["last_updated"] = datetime.now().isoformat()
                _PERSONAL_TOOLS_FILE.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                removed = True

        bp_path = _PERSONAL_BLUEPRINTS_DIR / f"{skill_id}.json"
        if bp_path.exists():
            bp_path.unlink()

        return removed

    # -- Test -------------------------------------------------------------------

    def test(self, skill_id: str) -> SkillTestResult:
        """Run the blueprint's test_args through the installed executor."""
        bp = self.blueprint(skill_id)
        if bp is None:
            return SkillTestResult(skill_id=skill_id, passed=False, output="", error="Blueprint not found")

        if not bp.test_args:
            return SkillTestResult(skill_id=skill_id, passed=True, output="no test_args defined — skipped")

        # Find the installed tool entry
        if not _PERSONAL_TOOLS_FILE.exists():
            return SkillTestResult(skill_id=skill_id, passed=False, output="", error="Not installed")
        data = json.loads(_PERSONAL_TOOLS_FILE.read_text(encoding="utf-8"))
        tool_entry = next((t for t in data.get("tools", []) if t.get("name") == skill_id), None)
        if tool_entry is None:
            return SkillTestResult(skill_id=skill_id, passed=False, output="", error="Not installed")

        executor = tool_entry.get("executor", {})
        exec_type = executor.get("type") if isinstance(executor, dict) else executor

        try:
            if exec_type in ("shell", "bash") or isinstance(executor, str) and executor == "bash":
                cmd = executor.get("command") if isinstance(executor, dict) else None
                if not cmd:
                    return SkillTestResult(skill_id=skill_id, passed=False, output="", error="No command in executor")
                result = subprocess.run(
                    cmd, shell=True, input=json.dumps(bp.test_args),
                    capture_output=True, text=True, timeout=15
                )
                output = result.stdout.strip()
                err = result.stderr.strip()
                passed = result.returncode == 0
                return SkillTestResult(skill_id=skill_id, passed=passed, output=output, error=err or None)

            # builtin — can't really test without the full executor context
            return SkillTestResult(skill_id=skill_id, passed=True, output="builtin executor — install verified only")

        except subprocess.TimeoutExpired:
            return SkillTestResult(skill_id=skill_id, passed=False, output="", error="Test timed out after 15s")
        except Exception as e:
            return SkillTestResult(skill_id=skill_id, passed=False, output="", error=str(e))

    def health_check(self) -> Dict[str, Any]:
        bps = self._load_all_blueprints()
        return {
            "status": "ok",
            "details": {
                "provider": self.PROVIDER_NAME,
                "blueprint_count": len(bps),
                "system_dir": str(_SYSTEM_BLUEPRINTS_DIR),
                "personal_dir": str(_PERSONAL_BLUEPRINTS_DIR),
            },
        }
