#!/usr/bin/env python3
"""Plugin SDK CLI: scaffold and validate module plugins."""

from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_\\-]+", "-", name.lower()).strip("-")
    return slug or "plugin"


def _provider_template(plugin_name: str, provider_type: str) -> str:
    header = f'"""Scaffold provider for {plugin_name} ({provider_type})."""\n\n'
    if provider_type == "memory":
        return header + """from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.provider_contracts import MemoryProvider, ProviderVersion


class PluginProvider(MemoryProvider):
    def get_version(self) -> ProviderVersion:
        return ProviderVersion("plugin_memory", "0.1.0", "1.0")

    def add_conversation(self, role_id: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        raise NotImplementedError

    def get_conversation(self, role_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def search_conversations(self, role_id: str, query: str, max_items: int = 10) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def add_knowledge(self, role_id: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        raise NotImplementedError

    def search_knowledge(self, role_id: str, query: str, max_items: int = 10) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def archive_knowledge(self, role_id: str, knowledge_units: List[Dict[str, Any]]) -> str:
        raise NotImplementedError

    def health_check(self) -> Dict[str, Any]:
        return {"status": "ok", "details": {"provider": "plugin_memory"}}
"""
    if provider_type == "dream":
        return header + """from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.provider_contracts import DreamProvider, DreamStageResult, ProviderVersion


class PluginProvider(DreamProvider):
    def get_version(self) -> ProviderVersion:
        return ProviderVersion("plugin_dream", "0.1.0", "1.0")

    def run_stage_a(self, conversation_text: str, session_id: str) -> DreamStageResult: raise NotImplementedError
    def run_stage_b(self, stage_a_result: DreamStageResult, session_id: str) -> DreamStageResult: raise NotImplementedError
    def run_stage_c(self, stage_b_result: DreamStageResult, session_id: str) -> DreamStageResult: raise NotImplementedError
    def run_stage_d(self, stage_c_result: DreamStageResult, stage_b_result: Optional[DreamStageResult] = None, session_id: str = "") -> DreamStageResult: raise NotImplementedError
    def run_pipeline(self, conversation_text: str, session_id: str, stages: Optional[List[str]] = None) -> Dict[str, DreamStageResult]: raise NotImplementedError
    def validate_input(self, conversation_text: str) -> Dict[str, Any]: raise NotImplementedError
"""
    if provider_type == "persona":
        return header + """from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.provider_contracts import PersonaProvider, PersonaScore, PersonaSpec, PersonaSummary, ProviderVersion


class PluginProvider(PersonaProvider):
    def get_version(self) -> ProviderVersion:
        return ProviderVersion("plugin_persona", "0.1.0", "1.0")
    def generate(self, spec: PersonaSpec) -> Dict[str, Any]: raise NotImplementedError
    def score(self, role_def: Dict[str, Any]) -> PersonaScore: raise NotImplementedError
    def list_personas(self, filter: Optional[Dict[str, Any]] = None) -> List[PersonaSummary]: raise NotImplementedError
"""
    if provider_type == "growth":
        return header + """from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.provider_contracts import GrowthProvider, GrowthSnapshot, ProviderVersion


class PluginProvider(GrowthProvider):
    def get_version(self) -> ProviderVersion:
        return ProviderVersion("plugin_growth", "0.1.0", "1.0")
    def snapshot(self, role_id: str, context: Optional[Dict[str, Any]] = None) -> GrowthSnapshot: raise NotImplementedError
    def evaluate(self, role_id: str, signals: Dict[str, Any]) -> Dict[str, Any]: raise NotImplementedError
    def propose(self, role_id: str, evaluation: Dict[str, Any]) -> Dict[str, Any]: raise NotImplementedError
    def validate(self, role_id: str, proposal: Dict[str, Any], decision: str) -> Dict[str, Any]: raise NotImplementedError
"""
    # skill
    return header + """from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.provider_contracts import InstallResult, ProviderVersion, SkillBlueprint, SkillProvider, SkillTestResult


class PluginProvider(SkillProvider):
    def get_version(self) -> ProviderVersion:
        return ProviderVersion("plugin_skill", "0.1.0", "1.0")
    def catalog(self, filter: Optional[Dict[str, Any]] = None) -> List[SkillBlueprint]: raise NotImplementedError
    def blueprint(self, skill_id: str) -> Optional[SkillBlueprint]: raise NotImplementedError
    def install(self, skill_id: str, env: Optional[Dict[str, Any]] = None) -> InstallResult: raise NotImplementedError
    def install_blueprint(self, blueprint: Dict[str, Any], env: Optional[Dict[str, Any]] = None) -> InstallResult: raise NotImplementedError
    def uninstall(self, skill_id: str) -> bool: raise NotImplementedError
    def test(self, skill_id: str) -> SkillTestResult: raise NotImplementedError
    def search(self, query: str) -> List[SkillBlueprint]: raise NotImplementedError
"""


def _scaffold(args: argparse.Namespace) -> int:
    plugin_name = _slugify(args.name)
    provider_type = args.provider_type
    contract_version = args.contract_version
    version = args.version
    root = Path(args.output_dir).resolve() / plugin_name
    src_pkg = plugin_name.replace("-", "_")

    if root.exists() and any(root.iterdir()) and not args.force:
        print(f"[error] target exists and is not empty: {root}")
        print("Use --force to overwrite generated files where possible.")
        return 2

    (root / "src" / src_pkg).mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)

    class_name = "PluginProvider"
    entry_point = f"{src_pkg}.provider.{class_name}"
    module_json = {
        "name": plugin_name,
        "version": version,
        "provider_type": provider_type,
        "entry_point": entry_point,
        "contract_version": contract_version,
        "description": f"{provider_type} plugin scaffold for {plugin_name}",
        "capabilities": {},
    }
    (root / "module.json").write_text(
        json.dumps(module_json, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    provider_py = _provider_template(plugin_name, provider_type)
    (root / "src" / src_pkg / "provider.py").write_text(provider_py, encoding="utf-8")
    (root / "src" / src_pkg / "__init__.py").write_text("", encoding="utf-8")
    (root / "README.md").write_text(
        f"# {plugin_name}\n\nGenerated by `scripts/plugin_sdk.py scaffold`.\n\n"
        "Next steps:\n"
        "1. Implement provider contract in `src/*/provider.py`.\n"
        "2. Run `python3 scripts/plugin_sdk.py validate --path <plugin-dir>`.\n"
        "3. Add conformance tests for your provider.\n",
        encoding="utf-8",
    )
    print(str(root))
    return 0


def _validate(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    module_path = root / "module.json"
    errors: list[str] = []
    warnings: list[str] = []

    module_data: dict[str, Any] | None = None
    if not module_path.exists():
        errors.append("missing module.json")
    else:
        try:
            data = json.loads(module_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid module.json: {exc}")
            data = None

        if isinstance(data, dict):
            module_data = data
            required = ["name", "version", "provider_type", "entry_point", "contract_version"]
            for key in required:
                if key not in data or not str(data[key]).strip():
                    errors.append(f"module.json missing required key: {key}")
            ep = str(data.get("entry_point", ""))
            if "." not in ep:
                errors.append("entry_point must look like 'pkg.module.ClassName'")
            provider_type = str(data.get("provider_type", ""))
            if not re.match(r"^[a-z][a-z0-9_]*$", provider_type):
                errors.append(
                    "provider_type must be a lowercase snake_case string (e.g. memory, skill, orchestration, voice)"
                )

    src_dir = root / "src"
    if not src_dir.exists():
        errors.append("missing src/ directory")
    else:
        # Validate entry_point importability with src/ on path.
        if module_data and "entry_point" in module_data:
            entry_point = str(module_data["entry_point"])
            provider_type = str(module_data.get("provider_type", ""))
            try:
                mod_name, class_name = entry_point.rsplit(".", 1)
                sys.path.insert(0, str(src_dir))
                module = importlib.import_module(mod_name)
                if not hasattr(module, class_name):
                    errors.append(f"entry_point class not found: {entry_point}")
                else:
                    provider_cls = getattr(module, class_name)
                    # Best-effort contract subclass check.
                    try:
                        from app.services import provider_contracts as pc

                        contract_map = {
                            "memory": pc.MemoryProvider,
                            "dream": pc.DreamProvider,
                            "persona": pc.PersonaProvider,
                            "growth": pc.GrowthProvider,
                            "skill": pc.SkillProvider,
                        }
                        expected = contract_map.get(provider_type)
                        if expected is not None and not issubclass(provider_cls, expected):
                            errors.append(
                                f"entry_point class does not implement expected contract "
                                f"for provider_type='{provider_type}'"
                            )
                    except Exception as exc:
                        msg = str(exc)
                        if "No module named 'app'" in msg:
                            warnings.append(
                                f"contract subclass check deferred (host deps missing): {entry_point} ({exc})"
                            )
                        else:
                            warnings.append(
                                f"contract subclass check skipped: {entry_point} ({exc})"
                            )
            except Exception as exc:
                msg = str(exc)
                if "No module named 'app'" in msg:
                    warnings.append(
                        f"entry_point import deferred (host deps missing): {entry_point} ({exc})"
                    )
                else:
                    errors.append(f"entry_point import failed: {entry_point} ({exc})")

    # Optional schema validation against docs/schemas/module.json
    if module_data:
        schema_path = Path(__file__).resolve().parents[1] / "docs" / "schemas" / "module.json"
        if schema_path.exists():
            try:
                import jsonschema  # type: ignore

                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                jsonschema.validate(module_data, schema)
            except ImportError:
                pass
            except Exception as exc:
                errors.append(f"module.json schema validation failed: {exc}")

    if errors:
        print("[invalid]")
        for e in errors:
            print(f"- {e}")
        return 2

    if warnings:
        print("[ok-with-warnings] plugin manifest validated")
        for w in warnings:
            print(f"- {w}")
        return 0

    print("[ok] plugin manifest validated")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Plugin SDK helper (scaffold + validate).")
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("scaffold", help="Generate a plugin scaffold.")
    sc.add_argument("--name", required=True, help="Plugin name (e.g. my-memory-plugin)")
    sc.add_argument("--provider-type", required=True,
                    help="Provider type — known: memory/dream/persona/growth/skill/retrieval/embedding/storage, or any custom lowercase string")
    sc.add_argument("--contract-version", default="1.0")
    sc.add_argument("--version", default="0.1.0")
    sc.add_argument("--output-dir", default="plugins")
    sc.add_argument("--force", action="store_true")
    sc.set_defaults(func=_scaffold)

    vd = sub.add_parser("validate", help="Validate a plugin manifest/package layout.")
    vd.add_argument("--path", required=True, help="Path to plugin root")
    vd.set_defaults(func=_validate)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
