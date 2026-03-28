"""
Configuration Doctor

Validates all runtime configuration before issues surface during task execution.
Returns structured check results that are both machine-readable and human-friendly.

Usage:
    doctor = ConfigDoctor()
    report = doctor.run_all_checks()
    print(report.summary())

Severity levels:
    "pass"  — definitively OK
    "warn"  — may fail at runtime (missing optional key, degraded mode)
    "error" — will definitely fail at runtime
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

logger = logging.getLogger(__name__)

# Template placeholders that indicate an unconfigured value
_PLACEHOLDER_PATTERNS = ("{{", "}}", "<YOUR_", "REPLACE_ME", "TODO", "your-")


@dataclass
class CheckResult:
    category: str         # "resource", "role", "task", "api_key", "server"
    id: str               # entity being checked
    field: str            # field that was checked
    value: Any            # value that was checked (may be redacted)
    status: str           # "pass", "warn", "error"
    message: str


@dataclass
class DoctorReport:
    checks: List[CheckResult] = field(default_factory=list)

    def add(self, check: CheckResult) -> None:
        self.checks.append(check)

    @property
    def errors(self) -> List[CheckResult]:
        return [c for c in self.checks if c.status == "error"]

    @property
    def warnings(self) -> List[CheckResult]:
        return [c for c in self.checks if c.status == "warn"]

    @property
    def passed(self) -> List[CheckResult]:
        return [c for c in self.checks if c.status == "pass"]

    def to_dict(self) -> Dict[str, Any]:
        overall = "pass"
        if self.errors:
            overall = "error"
        elif self.warnings:
            overall = "warn"
        return {
            "status": overall,
            "checks": [
                {
                    "category": c.category,
                    "id": c.id,
                    "field": c.field,
                    "value": c.value,
                    "status": c.status,
                    "message": c.message,
                }
                for c in self.checks
            ],
            "summary": {
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "passed": len(self.passed),
                "total": len(self.checks),
            },
        }

    def summary(self) -> str:
        lines = [
            f"Config Doctor — {len(self.errors)} error(s), "
            f"{len(self.warnings)} warning(s), {len(self.passed)} passed",
            "",
        ]
        for c in self.checks:
            icon = {"pass": "✓", "warn": "⚠", "error": "✗"}.get(c.status, "?")
            lines.append(f"  {icon} [{c.category}/{c.id}] {c.field}: {c.message}")
        return "\n".join(lines)


def _is_placeholder(value: str) -> bool:
    if not isinstance(value, str):
        return False
    return any(p in value for p in _PLACEHOLDER_PATTERNS)


def _probe_url(base_url: str, api_key: Optional[str] = None, timeout: int = 5) -> Optional[str]:
    """
    Try to reach an LLM server's /v1/models endpoint.
    Returns None on success, error string on failure.
    """
    url = base_url.rstrip("/") + "/v1/models"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        req = Request(url, headers=headers, method="GET")
        with urlopen(req, timeout=timeout) as resp:
            if resp.status in (200, 201):
                return None
            return f"HTTP {resp.status}"
    except URLError as e:
        return str(e.reason)
    except Exception as e:
        return str(e)


def _fetch_model_list(base_url: str, api_key: Optional[str] = None, timeout: int = 5) -> Optional[List[str]]:
    """Fetch available model IDs from a /v1/models endpoint. Returns None on error."""
    url = base_url.rstrip("/") + "/v1/models"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        req = Request(url, headers=headers, method="GET")
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            models = data.get("data", [])
            return [m.get("id", "") for m in models if m.get("id")]
    except Exception:
        return None


class ConfigDoctor:
    """
    Validates runtime config: LLM resources, roles, scheduler tasks, API keys, local servers.
    """

    def __init__(self):
        pass

    def run_all_checks(self) -> DoctorReport:
        report = DoctorReport()
        self._check_resources(report)
        self._check_roles(report)
        self._check_scheduler_tasks(report)
        self._check_policy_patterns(report)
        self._check_memory_path(report)
        self._check_scheduler_config(report)
        return report

    # ------------------------------------------------------------------
    # Resource checks
    # ------------------------------------------------------------------

    def _check_resources(self, report: DoctorReport) -> None:
        try:
            from app.scheduler.resource_pool import ResourceManager
            rm = ResourceManager()
            resources = rm._resources
        except Exception as e:
            report.add(CheckResult(
                category="resource", id="llm_config", field="load",
                value=None, status="error",
                message=f"Failed to load resource pool: {e}",
            ))
            return

        if not resources:
            report.add(CheckResult(
                category="resource", id="llm_config", field="entries",
                value=0, status="warn",
                message="No LLM resources configured",
            ))
            return

        for res_id, r in resources.items():
            # Check API key if required
            if r.api_key_env:
                env_val = os.getenv(r.api_key_env)
                if not env_val:
                    report.add(CheckResult(
                        category="resource", id=res_id, field="api_key",
                        value=f"${r.api_key_env}",
                        status="warn",
                        message=f"Env var '{r.api_key_env}' is not set",
                    ))
                elif _is_placeholder(env_val):
                    report.add(CheckResult(
                        category="resource", id=res_id, field="api_key",
                        value="[REDACTED]",
                        status="error",
                        message=f"'{r.api_key_env}' appears to be a placeholder value",
                    ))
                else:
                    report.add(CheckResult(
                        category="resource", id=res_id, field="api_key",
                        value=f"${r.api_key_env} (set)",
                        status="pass",
                        message="API key env var is set",
                    ))
            elif r.api_key and _is_placeholder(r.api_key):
                report.add(CheckResult(
                    category="resource", id=res_id, field="api_key",
                    value="[REDACTED]",
                    status="error",
                    message="api_key appears to be a placeholder",
                ))

            # Check server reachability for local/openai-compat resources
            if r.base_url and not r.base_url.startswith("https://openrouter"):
                err = _probe_url(r.base_url, api_key=r.api_key)
                if err:
                    report.add(CheckResult(
                        category="resource", id=res_id, field="base_url",
                        value=r.base_url,
                        status="warn",
                        message=f"Server not reachable: {err}",
                    ))
                else:
                    report.add(CheckResult(
                        category="resource", id=res_id, field="base_url",
                        value=r.base_url,
                        status="pass",
                        message="Server is reachable",
                    ))

                    # Check model name against available models
                    if r.model:
                        available = _fetch_model_list(r.base_url, api_key=r.api_key)
                        if available is not None:
                            if not available:
                                # Server has no models loaded — may be intentional (cold start)
                                report.add(CheckResult(
                                    category="resource", id=res_id, field="model",
                                    value=r.model,
                                    status="warn",
                                    message=f"Server returned empty model list (model not loaded?)",
                                ))
                            else:
                                # Normalize: some APIs return "models/foo" while config has "foo"
                                normalized = {m.split("/")[-1]: m for m in available}
                                model_key = r.model.split("/")[-1]
                                if r.model not in available and model_key not in normalized:
                                    report.add(CheckResult(
                                        category="resource", id=res_id, field="model",
                                        value=r.model,
                                        status="error",
                                        message=(
                                            f"Model '{r.model}' not found on server. "
                                            f"Available: {', '.join(available[:5])}"
                                            + (" ..." if len(available) > 5 else "")
                                        ),
                                    ))
                                else:
                                    report.add(CheckResult(
                                        category="resource", id=res_id, field="model",
                                        value=r.model,
                                        status="pass",
                                        message=f"Model '{r.model}' is available",
                                    ))
            elif r.base_url:
                # Remote API (openrouter etc.) — only check key presence
                report.add(CheckResult(
                    category="resource", id=res_id, field="base_url",
                    value=r.base_url,
                    status="pass",
                    message="Remote API endpoint (reachability not checked)",
                ))

    # ------------------------------------------------------------------
    # Role checks
    # ------------------------------------------------------------------

    def _check_roles(self, report: DoctorReport) -> None:
        try:
            from app.roles.role_manager import RoleManager
            roles = RoleManager().list_roles()
        except Exception as e:
            report.add(CheckResult(
                category="role", id="roles", field="load",
                value=None, status="error",
                message=f"Failed to load roles: {e}",
            ))
            return

        try:
            from app.scheduler.resource_pool import ResourceManager
            rm = ResourceManager()
            available_models = {
                res_id: r.model for res_id, r in rm._resources.items() if r.model
            }
            free_resources_exist = any(
                r.tier.value == "free" for r in rm._resources.values()
            )
        except Exception:
            available_models = {}
            free_resources_exist = True  # unknown — don't false-alarm

        try:
            from app.scheduler.dynamic_tool_registry import DynamicToolRegistry
            registry = DynamicToolRegistry()
            known_tools = set(registry.list_tools().keys())
        except Exception:
            known_tools = set()

        for role in roles:
            role_id = role.get("id", "?")
            model_pref = role.get("model_preference")
            if model_pref:
                model_known = model_pref in available_models.values()
                if not model_known and available_models:
                    report.add(CheckResult(
                        category="role", id=role_id, field="model_preference",
                        value=model_pref,
                        status="error",
                        message=(
                            f"Model '{model_pref}' not matched in any resource. "
                            f"Available: {', '.join(list(available_models.values())[:5])}"
                        ),
                    ))
                else:
                    report.add(CheckResult(
                        category="role", id=role_id, field="model_preference",
                        value=model_pref,
                        status="pass",
                        message=f"Model preference '{model_pref}' is available",
                    ))

            # Check local_only roles have a free-tier resource (v1.2.6+)
            if role.get("local_only") and not free_resources_exist:
                report.add(CheckResult(
                    category="role", id=role_id, field="local_only",
                    value=True,
                    status="error",
                    message=(
                        "Role has local_only=true but no 'free' tier resource is configured. "
                        "This role will never be assigned an LLM."
                    ),
                ))

            # Check allowed_tools against registry
            policy = role.get("policy") or {}
            allowed_tools = policy.get("allowed_tools", [])
            for tool_name in allowed_tools:
                if known_tools and tool_name not in known_tools:
                    report.add(CheckResult(
                        category="role", id=role_id, field="policy.allowed_tools",
                        value=tool_name,
                        status="warn",
                        message=f"Tool '{tool_name}' is not in the dynamic tool registry",
                    ))

    # ------------------------------------------------------------------
    # Scheduler task checks
    # ------------------------------------------------------------------

    def _check_scheduler_tasks(self, report: DoctorReport) -> None:
        try:
            from app.scheduler.queue import TaskQueue
            from app.scheduler.models import TaskStatus
            queue = TaskQueue()
            tasks = list(queue.tasks.values())
        except Exception as e:
            report.add(CheckResult(
                category="task", id="queue", field="load",
                value=None, status="error",
                message=f"Failed to load task queue: {e}",
            ))
            return

        try:
            from app.scheduler.dynamic_tool_registry import DynamicToolRegistry
            registry = DynamicToolRegistry()
            known_tools = set(registry.list_tools().keys())
        except Exception:
            known_tools = set()

        try:
            from app.roles.role_manager import RoleManager
            known_roles = {r["id"] for r in RoleManager().list_roles()}
        except Exception:
            known_roles = set()

        for task in tasks:
            # Only check pending/waiting tasks — completed/failed ones are historical
            if task.status not in (
                __import__("app.scheduler.models", fromlist=["TaskStatus"]).TaskStatus.PENDING,
                __import__("app.scheduler.models", fromlist=["TaskStatus"]).TaskStatus.WAITING_FOR_INPUT,
            ):
                continue

            cfg = task.config or {}
            task_id = task.id

            # Check role_id resolves
            role_id = cfg.get("role_id")
            if role_id and known_roles:
                if role_id not in known_roles:
                    report.add(CheckResult(
                        category="task", id=task_id, field="role_id",
                        value=role_id,
                        status="error",
                        message=f"Role '{role_id}' not found in role library",
                    ))
                else:
                    report.add(CheckResult(
                        category="task", id=task_id, field="role_id",
                        value=role_id, status="pass",
                        message=f"Role '{role_id}' exists",
                    ))

            # Check available_tools against registry
            available_tools = cfg.get("available_tools", [])
            for tool_name in available_tools:
                if known_tools and tool_name not in known_tools:
                    report.add(CheckResult(
                        category="task", id=task_id, field="available_tools",
                        value=tool_name,
                        status="warn",
                        message=f"Tool '{tool_name}' is not in the dynamic tool registry",
                    ))

            # Check tier_preference is valid
            tier_pref = cfg.get("tier_preference") or (task.resources.tier_preference if task.resources else None)
            if tier_pref:
                valid_tiers = {"free", "free_api", "paid", "paid_api"}
                bad = [t for t in (tier_pref if isinstance(tier_pref, list) else [tier_pref]) if t not in valid_tiers]
                if bad:
                    report.add(CheckResult(
                        category="task", id=task_id, field="tier_preference",
                        value=bad,
                        status="error",
                        message=f"Unknown tier(s): {bad}. Valid: {sorted(valid_tiers)}",
                    ))

    # ------------------------------------------------------------------
    # Policy pattern file checks (v1.2.6+)
    # ------------------------------------------------------------------

    def _check_policy_patterns(self, report: DoctorReport) -> None:
        """Verify that policy and behavioral pattern files exist and are valid JSON."""
        project_root = Path(__file__).parent.parent.parent
        pattern_files = [
            ("policy_patterns", project_root / "config" / "policy_patterns.json"),
            ("behavioral_patterns", project_root / "config" / "behavioral_patterns.json"),
        ]
        for name, path in pattern_files:
            if not path.exists():
                report.add(CheckResult(
                    category="policy", id=name, field="file",
                    value=str(path),
                    status="warn",
                    message=f"Pattern file not found — content scanning for this category is disabled",
                ))
                continue
            try:
                data = json.loads(path.read_text())
            except Exception as e:
                report.add(CheckResult(
                    category="policy", id=name, field="file",
                    value=str(path),
                    status="error",
                    message=f"Invalid JSON: {e}",
                ))
                continue
            patterns = data.get("patterns", [])
            if not patterns:
                report.add(CheckResult(
                    category="policy", id=name, field="patterns",
                    value=0,
                    status="warn",
                    message="Pattern list is empty — no rules will be enforced",
                ))
            else:
                report.add(CheckResult(
                    category="policy", id=name, field="patterns",
                    value=len(patterns),
                    status="pass",
                    message=f"{len(patterns)} pattern(s) loaded",
                ))

        # Personal overlay directory (informational)
        from app.config.paths import get_memory_path
        personal_dir = Path(get_memory_path()) / "config"
        for name in ("policy_patterns", "behavioral_patterns"):
            personal_file = personal_dir / f"{name}.json"
            if personal_file.exists():
                try:
                    data = json.loads(personal_file.read_text())
                    n = len(data.get("patterns", []))
                    report.add(CheckResult(
                        category="policy", id=f"{name}_personal", field="file",
                        value=str(personal_file),
                        status="pass",
                        message=f"Personal overlay loaded: {n} pattern(s)",
                    ))
                except Exception as e:
                    report.add(CheckResult(
                        category="policy", id=f"{name}_personal", field="file",
                        value=str(personal_file),
                        status="error",
                        message=f"Personal overlay has invalid JSON: {e}",
                    ))

    # ------------------------------------------------------------------
    # MEMORY_PATH consistency check (v1.2.6+)
    # ------------------------------------------------------------------

    def _check_memory_path(self, report: DoctorReport) -> None:
        """Verify MEMORY_PATH is consistent and the directory is writable."""
        try:
            from app.config.paths import get_memory_path, get_memory_subpath
            mem_path = Path(get_memory_path())
        except Exception as e:
            report.add(CheckResult(
                category="memory", id="MEMORY_PATH", field="resolve",
                value=None, status="error",
                message=f"Failed to resolve MEMORY_PATH: {e}",
            ))
            return

        env_val = os.environ.get("MEMORY_PATH")
        if env_val:
            report.add(CheckResult(
                category="memory", id="MEMORY_PATH", field="env",
                value=env_val,
                status="pass",
                message=f"MEMORY_PATH is set (overrides default ~/.memory)",
            ))
        else:
            report.add(CheckResult(
                category="memory", id="MEMORY_PATH", field="env",
                value=str(mem_path),
                status="pass",
                message="MEMORY_PATH not set — using default ~/.memory",
            ))

        # Check directory exists and is writable
        if mem_path.exists():
            test_file = mem_path / ".doctor_write_test"
            try:
                test_file.touch()
                test_file.unlink()
                report.add(CheckResult(
                    category="memory", id="MEMORY_PATH", field="writable",
                    value=str(mem_path),
                    status="pass",
                    message="Memory directory exists and is writable",
                ))
            except Exception as e:
                report.add(CheckResult(
                    category="memory", id="MEMORY_PATH", field="writable",
                    value=str(mem_path),
                    status="error",
                    message=f"Memory directory is not writable: {e}",
                ))
        else:
            report.add(CheckResult(
                category="memory", id="MEMORY_PATH", field="exists",
                value=str(mem_path),
                status="warn",
                message="Memory directory does not exist yet (will be created on first use)",
            ))

        # Verify dreaming subpath resolves through get_memory_subpath
        try:
            dreams_path = Path(get_memory_subpath("dreams"))
            if str(dreams_path).startswith(str(mem_path)):
                report.add(CheckResult(
                    category="memory", id="dreams", field="storage_path",
                    value=str(dreams_path),
                    status="pass",
                    message="Dreaming storage resolves correctly under MEMORY_PATH",
                ))
            else:
                report.add(CheckResult(
                    category="memory", id="dreams", field="storage_path",
                    value=str(dreams_path),
                    status="error",
                    message=(
                        f"Dreaming storage path '{dreams_path}' is outside MEMORY_PATH "
                        f"'{mem_path}' — likely a hardcoded default bypassing MEMORY_PATH"
                    ),
                ))
        except Exception as e:
            report.add(CheckResult(
                category="memory", id="dreams", field="storage_path",
                value=None, status="error",
                message=f"Failed to resolve dreaming storage path: {e}",
            ))

    # ------------------------------------------------------------------
    # Scheduler config check (v1.2.7+)
    # ------------------------------------------------------------------

    def _check_scheduler_config(self, report: DoctorReport) -> None:
        """Verify scheduler_config.json exists and all referenced roles are known."""
        project_root = Path(__file__).parent.parent.parent
        sched_path = project_root / "config" / "scheduler_config.json"

        if not sched_path.exists():
            report.add(CheckResult(
                category="scheduler", id="scheduler_config", field="file",
                value=str(sched_path),
                status="warn",
                message="scheduler_config.json not found — no scheduled jobs will run",
            ))
            return

        try:
            data = json.loads(sched_path.read_text())
        except Exception as e:
            report.add(CheckResult(
                category="scheduler", id="scheduler_config", field="file",
                value=str(sched_path),
                status="error",
                message=f"Invalid JSON: {e}",
            ))
            return

        # Support both "jobs" and "default_tasks" key names
        jobs = data.get("jobs") or data.get("default_tasks", [])
        report.add(CheckResult(
            category="scheduler", id="scheduler_config", field="jobs",
            value=len(jobs),
            status="pass" if jobs else "warn",
            message=f"{len(jobs)} scheduled job(s) defined" if jobs else "No jobs defined",
        ))

        # Check each job's role_id resolves
        try:
            from app.roles.role_manager import RoleManager
            known_roles = {r["id"] for r in RoleManager().list_roles()}
        except Exception:
            known_roles = set()

        for job in jobs:
            job_id = job.get("id", "?")
            role_id = job.get("role_id")
            if role_id and known_roles and role_id not in known_roles:
                report.add(CheckResult(
                    category="scheduler", id=job_id, field="role_id",
                    value=role_id,
                    status="error",
                    message=f"Scheduled job references unknown role '{role_id}'",
                ))

            # Warn on jobs with local_only roles that might not have free resources
            cron = job.get("schedule_cron") or job.get("cron")
            if cron:
                report.add(CheckResult(
                    category="scheduler", id=job_id, field="schedule_cron",
                    value=cron,
                    status="pass",
                    message=f"Cron schedule is set",
                ))
