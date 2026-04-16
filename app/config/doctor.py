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
import asyncio
import shutil
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
        self._check_mcp_servers(report)
        self._check_roles(report)
        self._check_nine_chapter_scores(report)
        self._check_scheduler_tasks(report)
        self._check_policy_patterns(report)
        self._check_memory_path(report)
        self._check_scheduler_config(report)
        self._check_capabilities(report)
        return report

    # ------------------------------------------------------------------
    # MCP server checks
    # ------------------------------------------------------------------

    def _check_mcp_servers(self, report: DoctorReport) -> None:
        try:
            from app.scheduler.mcp_client_manager import MCPClientManager
            mgr = MCPClientManager()
        except Exception as e:
            report.add(CheckResult(
                category="mcp", id="mcp_servers", field="load",
                value=None, status="error",
                message=f"Failed to load MCP server config: {e}",
            ))
            return

        if not mgr._servers:
            report.add(CheckResult(
                category="mcp", id="mcp_servers", field="entries",
                value=0, status="warn",
                message="No enabled MCP servers configured",
            ))
            return

        probe_targets: List[str] = []
        for server_id, server in mgr._servers.items():
            if server.transport == "stdio":
                resolved = server.command if os.path.isabs(server.command) else shutil.which(server.command)
                if resolved:
                    report.add(CheckResult(
                        category="mcp", id=server_id, field="command",
                        value=server.command,
                        status="pass",
                        message=f"Command resolves to '{resolved}'",
                    ))
                    probe_targets.append(server_id)
                else:
                    report.add(CheckResult(
                        category="mcp", id=server_id, field="command",
                        value=server.command,
                        status="error",
                        message="Command not found on PATH / filesystem",
                    ))
            elif server.transport in ("http", "streamable_http"):
                url = server.mcp_http_url or f"http://localhost:{server.port}/mcp"
                err = _probe_url(url.replace("/mcp", ""), timeout=5)
                if err:
                    report.add(CheckResult(
                        category="mcp", id=server_id, field="endpoint",
                        value=url,
                        status="warn",
                        message=f"Endpoint not reachable: {err}",
                    ))
                else:
                    report.add(CheckResult(
                        category="mcp", id=server_id, field="endpoint",
                        value=url,
                        status="pass",
                        message="Endpoint is reachable",
                    ))

        async def _probe_stdio_connections() -> Dict[str, Dict[str, Any]]:
            statuses: Dict[str, Dict[str, Any]] = {}
            try:
                for server_id in probe_targets:
                    server = mgr._servers[server_id]
                    try:
                        tools = await mgr._connect_server(server)
                        statuses[server_id] = {
                            "status": "pass",
                            "tool_count": len(tools),
                            "message": f"Connected successfully ({len(tools)} tools)",
                        }
                    except Exception as e:
                        statuses[server_id] = {
                            "status": "error",
                            "tool_count": 0,
                            "message": str(e),
                        }
            finally:
                try:
                    await mgr.close()
                except Exception:
                    pass
            return statuses

        if probe_targets:
            try:
                statuses = asyncio.run(_probe_stdio_connections())
            except Exception as e:
                report.add(CheckResult(
                    category="mcp", id="stdio_probe", field="connect",
                    value=None, status="error",
                    message=f"Failed to run MCP stdio probe: {e}",
                ))
                return

            for server_id in probe_targets:
                result = statuses.get(server_id)
                if not result:
                    report.add(CheckResult(
                        category="mcp", id=server_id, field="connect",
                        value=None, status="error",
                        message="No probe result returned",
                    ))
                    continue
                report.add(CheckResult(
                    category="mcp", id=server_id, field="connect",
                    value=result.get("tool_count", 0),
                    status=result["status"],
                    message=result["message"],
                ))

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
            # A usable free resource must be both tier=free AND enabled=True
            free_resources_usable = any(
                r.tier.value == "free" and r.enabled
                for r in rm._resources.values()
            )
        except Exception:
            available_models = {}
            free_resources_usable = True  # unknown — don't false-alarm

        try:
            from app.scheduler.capability_registry import CapabilityRegistry
            registry = CapabilityRegistry()
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
            if role.get("local_only") and not free_resources_usable:
                report.add(CheckResult(
                    category="role", id=role_id, field="local_only",
                    value=True,
                    status="error",
                    message=(
                        "Role has local_only=true but no enabled 'free' tier resource is configured. "
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
            from app.scheduler.capability_registry import CapabilityRegistry
            registry = CapabilityRegistry()
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
        """Verify scheduler_config.json exists and all referenced roles are known.

        Reads through both config layers (project config/ and ~/.memory/config/)
        so runtime overrides are visible to the doctor.
        """
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
            from app.config.config_loader import load_layered_json_config
            data = load_layered_json_config(str(sched_path))
        except Exception as e:
            report.add(CheckResult(
                category="scheduler", id="scheduler_config", field="file",
                value=str(sched_path),
                status="error",
                message=f"Failed to load scheduler config: {e}",
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

    # ------------------------------------------------------------------
    # NineChapter score validation (v1.2.11)
    # ------------------------------------------------------------------

    _NC_WEIGHTS = {
        "core_values":        0.30,
        "emotional_reaction": 0.25,
        "cognitive_style":    0.20,
        "social_orientation": 0.15,
        "adaptability":       0.10,
    }

    def _check_nine_chapter_scores(self, report: DoctorReport) -> None:
        """Verify that each role's nine_chapter_score matches the weighted average
        of its dimension scores.  Flags roles where the stored score drifts from
        what role_designer would compute — usually caused by manual edits."""
        try:
            from app.roles.role_manager import RoleManager
            rm = RoleManager()
            # list_roles() returns summaries without dimensions — load each role fully
            summaries = rm.list_roles()
            roles = []
            for s in summaries:
                full = rm.get(s["id"])
                if full:
                    roles.append(full)
        except Exception as e:
            report.add(CheckResult(
                category="nine_chapter", id="roles", field="load",
                value=None, status="error",
                message=f"Could not load roles for NineChapter validation: {e}",
            ))
            return

        for role in roles:
            role_id = role.get("id", "?")
            stored = role.get("nine_chapter_score")
            dims = role.get("dimensions")

            if stored is None:
                report.add(CheckResult(
                    category="nine_chapter", id=role_id, field="nine_chapter_score",
                    value=None, status="warn",
                    message="nine_chapter_score is missing — role was not created by role_designer",
                ))
                continue

            if not dims:
                report.add(CheckResult(
                    category="nine_chapter", id=role_id, field="dimensions",
                    value=None, status="warn",
                    message="dimensions block is missing — cannot validate nine_chapter_score",
                ))
                continue

            expected = round(sum(
                dims.get(dim, {}).get("score", 0) * weight
                for dim, weight in self._NC_WEIGHTS.items()
            ))

            if expected != stored:
                report.add(CheckResult(
                    category="nine_chapter", id=role_id, field="nine_chapter_score",
                    value=stored,
                    status="warn",
                    message=(
                        f"nine_chapter_score={stored} but weighted dimension average={expected}. "
                        f"Role may have been manually edited. Re-run role_designer to recompute."
                    ),
                ))
            else:
                report.add(CheckResult(
                    category="nine_chapter", id=role_id, field="nine_chapter_score",
                    value=stored,
                    status="pass",
                    message=f"nine_chapter_score={stored} matches weighted dimension average",
                ))

    # ------------------------------------------------------------------
    # Capability system checks (v1.2.12+)
    # Validates across all three layers:
    #   Layer 1 — system + personal capability_defaults.json
    #   Layer 2 — per-role capabilities list
    #   Layer 3 — runtime overlay tool name drift
    # Also simulates full resolution per role to surface dead assignments.
    # ------------------------------------------------------------------

    def _check_capabilities(self, report: DoctorReport) -> None:
        import re
        from app.config.config_loader import load_layered_json_config
        from app.config.paths import get_memory_path

        project_root = Path(__file__).parent.parent.parent
        personal_config_dir = Path(get_memory_path()) / "config"

        # ── Load catalog ─────────────────────────────────────────────────
        try:
            catalog = load_layered_json_config("config/capability_catalog.json")
        except Exception as e:
            report.add(CheckResult(
                category="capability", id="catalog", field="load",
                value=None, status="error",
                message=f"Failed to load capability_catalog.json: {e}",
            ))
            return

        known_categories: set = set(catalog.get("categories", {}).keys())
        catalog_tools: dict = catalog.get("tools", {})

        if not known_categories:
            report.add(CheckResult(
                category="capability", id="catalog", field="categories",
                value=0, status="error",
                message="capability_catalog.json has no categories defined",
            ))
        else:
            report.add(CheckResult(
                category="capability", id="catalog", field="categories",
                value=sorted(known_categories),
                status="pass",
                message=f"{len(known_categories)} categories defined: {', '.join(sorted(known_categories))}",
            ))

        if not catalog_tools:
            report.add(CheckResult(
                category="capability", id="catalog", field="tools",
                value=0, status="warn",
                message="capability_catalog.json has no tools defined",
            ))

        # ── Load registry ─────────────────────────────────────────────────
        try:
            from app.scheduler.capability_registry import CapabilityRegistry
            registry = CapabilityRegistry()
            registry_tools: set = set(registry.list_tools().keys())
        except Exception as e:
            report.add(CheckResult(
                category="capability", id="registry", field="load",
                value=None, status="error",
                message=f"Failed to load CapabilityRegistry: {e}",
            ))
            registry_tools = set()

        # ── Catalog ↔ Registry cross-check ───────────────────────────────
        # Tools in catalog but not in registry — they'll silently resolve to nothing
        for tool_name, meta in catalog_tools.items():
            if isinstance(meta, dict) and (meta.get("internal") or meta.get("mcp_external")):
                continue  # mcp_external tools come from MCP server, not capability registry
            if registry_tools and tool_name not in registry_tools:
                report.add(CheckResult(
                    category="capability", id=f"catalog/{tool_name}", field="registry",
                    value=tool_name, status="warn",
                    message=f"Tool '{tool_name}' is in catalog but NOT in registry — "
                            f"roles with category '{meta.get('category', '?')}' won't get it",
                ))

        # Tools in catalog with unknown category
        for tool_name, meta in catalog_tools.items():
            if not isinstance(meta, dict):
                continue
            cat = meta.get("category")
            if cat and cat not in known_categories:
                report.add(CheckResult(
                    category="capability", id=f"catalog/{tool_name}", field="category",
                    value=cat, status="error",
                    message=f"Tool '{tool_name}' references unknown category '{cat}'",
                ))

        # ── Layer 1: system capability_defaults.json ─────────────────────
        try:
            defaults = load_layered_json_config("config/capability_defaults.json")
        except Exception as e:
            report.add(CheckResult(
                category="capability", id="defaults/system", field="load",
                value=None, status="error",
                message=f"Failed to load capability_defaults.json: {e}",
            ))
            defaults = {}

        always_available = defaults.get("always_available", [])
        agent_defaults = defaults.get("agent_defaults", [])

        for tool_name in always_available:
            if registry_tools and tool_name not in registry_tools:
                report.add(CheckResult(
                    category="capability", id="defaults/system", field="always_available",
                    value=tool_name, status="error",
                    message=f"always_available tool '{tool_name}' is not in registry — "
                            f"it will be injected into prompts but will fail when called",
                ))
            else:
                report.add(CheckResult(
                    category="capability", id="defaults/system", field="always_available",
                    value=tool_name, status="pass",
                    message=f"'{tool_name}' is in registry",
                ))

        for cat in agent_defaults:
            if cat not in known_categories:
                report.add(CheckResult(
                    category="capability", id="defaults/system", field="agent_defaults",
                    value=cat, status="error",
                    message=f"agent_defaults category '{cat}' is not in capability_catalog.json",
                ))
            else:
                report.add(CheckResult(
                    category="capability", id="defaults/system", field="agent_defaults",
                    value=cat, status="pass",
                    message=f"Category '{cat}' exists in catalog",
                ))

        # ── Layer 1: personal capability_defaults.json ────────────────────
        personal_defaults_path = personal_config_dir / "capability_defaults.json"
        if personal_defaults_path.exists():
            try:
                personal_defaults = json.loads(personal_defaults_path.read_text(encoding="utf-8"))
                for tool_name in personal_defaults.get("always_available", []):
                    if registry_tools and tool_name not in registry_tools:
                        report.add(CheckResult(
                            category="capability", id="defaults/personal", field="always_available",
                            value=tool_name, status="error",
                            message=f"Personal always_available '{tool_name}' is not in registry",
                        ))
                for cat in personal_defaults.get("agent_defaults", []):
                    if cat not in known_categories:
                        report.add(CheckResult(
                            category="capability", id="defaults/personal", field="agent_defaults",
                            value=cat, status="warn",
                            message=f"Personal agent_defaults category '{cat}' is not in catalog",
                        ))
                report.add(CheckResult(
                    category="capability", id="defaults/personal", field="file",
                    value=str(personal_defaults_path), status="pass",
                    message="Personal capability_defaults.json loaded and validated",
                ))
            except Exception as e:
                report.add(CheckResult(
                    category="capability", id="defaults/personal", field="file",
                    value=str(personal_defaults_path), status="error",
                    message=f"Invalid JSON in personal capability_defaults.json: {e}",
                ))
        else:
            report.add(CheckResult(
                category="capability", id="defaults/personal", field="file",
                value=str(personal_defaults_path), status="pass",
                message="No personal capability_defaults.json — system defaults apply",
            ))

        # ── Layer 2: per-role capabilities ────────────────────────────────
        try:
            from app.roles.role_manager import RoleManager
            roles = RoleManager().list_roles()
            full_roles = []
            rm = RoleManager()
            for s in roles:
                full = rm.get(s["id"])
                if full:
                    full_roles.append(full)
        except Exception as e:
            report.add(CheckResult(
                category="capability", id="roles", field="load",
                value=None, status="error",
                message=f"Failed to load roles for capability check: {e}",
            ))
            full_roles = []

        # Regex to find backtick-quoted tool-like names in overlay text
        _tool_name_re = re.compile(r"`([a-z][a-z0-9_]{2,})`")

        for role in full_roles:
            role_id = role.get("id", "?")
            caps = role.get("capabilities") or []

            # Each capability should be a known category OR a known tool name
            for cap in caps:
                if cap in known_categories:
                    pass  # valid category
                elif registry_tools and cap in registry_tools:
                    pass  # valid explicit tool name
                elif registry_tools:
                    report.add(CheckResult(
                        category="capability", id=f"role/{role_id}", field="capabilities",
                        value=cap, status="warn",
                        message=f"Capability '{cap}' is not a known category or tool name",
                    ))

            # Simulate full resolution and report result
            try:
                from app.scheduler.capability_resolver import CapabilityResolver
                resolver = CapabilityResolver()
                resolved = resolver.resolve(role, None, registry)
                if not resolved or resolved == ["ask_user"]:
                    report.add(CheckResult(
                        category="capability", id=f"role/{role_id}", field="resolved_tools",
                        value=resolved, status="warn",
                        message=f"Role resolves to only {resolved} — effectively no tools beyond HITL",
                    ))
                else:
                    report.add(CheckResult(
                        category="capability", id=f"role/{role_id}", field="resolved_tools",
                        value=resolved, status="pass",
                        message=f"Resolves to {len(resolved)} tools: {', '.join(resolved)}",
                    ))
            except Exception as e:
                report.add(CheckResult(
                    category="capability", id=f"role/{role_id}", field="resolved_tools",
                    value=None, status="error",
                    message=f"Resolution failed: {e}",
                ))

            # Layer 3 drift: check tool names mentioned in overlay text against registry
            overlays = role.get("mode_overlays") or {}
            for overlay_name, overlay_text in overlays.items():
                if not isinstance(overlay_text, str):
                    continue
                mentioned = _tool_name_re.findall(overlay_text)
                # Only check names that look like tool names (contain underscore, not prose)
                tool_like = [
                    n for n in mentioned
                    if "_" in n and not n.startswith("e.g") and len(n) > 4
                ]
                stale = []
                for name in tool_like:
                    # Skip if it's a known tool
                    if name in registry_tools or name in catalog_tools:
                        continue
                    # Skip common non-tool patterns
                    if name in {"ask_user", "web_search", "fetch_url", "memory_search",
                                "knowledge_search", "task_search", "add_conversation",
                                "read_file", "write_file", "list_files", "search_in_files",
                                "bash_exec", "scheduler_add_task", "dispatch_subtask"}:
                        continue
                    stale.append(name)
                if stale:
                    report.add(CheckResult(
                        category="capability", id=f"role/{role_id}", field=f"overlay/{overlay_name}",
                        value=stale, status="warn",
                        message=f"Overlay mentions tool name(s) not in registry or catalog: {stale}. "
                                f"May be stale — check against actual executor tool names.",
                    ))
                elif tool_like:
                    report.add(CheckResult(
                        category="capability", id=f"role/{role_id}", field=f"overlay/{overlay_name}",
                        value=tool_like, status="pass",
                        message=f"All {len(tool_like)} tool name(s) in overlay match registry",
                    ))


# ===========================================================================
# ConfigHealer — runtime-data-driven config improvement suggestions
# ===========================================================================

@dataclass
class ImprovementSuggestion:
    """A single proposed config change, backed by runtime evidence."""
    category: str        # "resource" | "scheduler_task"
    target_id: str       # resource ID or cron job ID
    field: str           # config field to change
    current_value: Any
    suggested_value: Any
    reason: str          # human-readable explanation
    evidence: str        # what data drove this suggestion
    confidence: str      # "high" | "medium" | "low"
    auto_apply: bool     # True = safe to apply without user confirmation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "target_id": self.target_id,
            "field": self.field,
            "current_value": self.current_value,
            "suggested_value": self.suggested_value,
            "reason": self.reason,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "auto_apply": self.auto_apply,
        }


@dataclass
class ImprovementReport:
    suggestions: List[ImprovementSuggestion] = field(default_factory=list)
    applied: List[ImprovementSuggestion] = field(default_factory=list)

    @property
    def auto_applicable(self) -> List[ImprovementSuggestion]:
        return [s for s in self.suggestions if s.auto_apply]

    @property
    def manual_review(self) -> List[ImprovementSuggestion]:
        return [s for s in self.suggestions if not s.auto_apply]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "suggestions": [s.to_dict() for s in self.suggestions],
            "applied": [s.to_dict() for s in self.applied],
            "summary": {
                "total": len(self.suggestions),
                "auto_applicable": len(self.auto_applicable),
                "manual_review": len(self.manual_review),
                "applied": len(self.applied),
            },
        }

    def summary(self) -> str:
        lines = [
            f"Config Healer — {len(self.suggestions)} suggestion(s) "
            f"({len(self.auto_applicable)} auto-apply, {len(self.manual_review)} manual review)",
            "",
        ]
        for s in self.suggestions:
            tag = "[auto]" if s.auto_apply else "[manual]"
            lines.append(
                f"  {tag} [{s.category}/{s.target_id}] {s.field}: "
                f"{s.current_value!r} → {s.suggested_value!r}  ({s.confidence}) — {s.reason}"
            )
        if self.applied:
            lines.append("")
            lines.append(f"Applied {len(self.applied)} change(s):")
            for s in self.applied:
                lines.append(f"  ✓ [{s.target_id}] {s.field} = {s.suggested_value!r}")
        return "\n".join(lines)


class ConfigHealer:
    """
    Analyses runtime execution data and static config state to produce
    improvement suggestions.  Unlike ConfigDoctor (which only diagnoses),
    ConfigHealer proposes concrete changes and can apply them.

    Data sources:
      1. ConfigDoctor report          — static config errors / warnings
      2. BenchmarkStore execution log — success rates, speed, judge scores
      3. Task queue (failed tasks)    — error message patterns for cron jobs
    """

    # Thresholds
    LOW_SUCCESS_RATE = 0.25      # below this → suggest disable or lower priority
    MIN_SAMPLES = 5              # minimum runs before drawing conclusions
    BUDGET_BUMP_FACTOR = 1.5     # multiply max_iterations / danger_budget by this
    MAX_DANGER_BUDGET_DEFAULT = 160
    SCHEDULER_CONFIG_LOOKBACK_DAYS = 14

    def suggest_improvements(
        self,
        doctor_report: Optional["DoctorReport"] = None,
    ) -> ImprovementReport:
        """
        Run all improvement heuristics and return a report of suggestions.
        Optionally accepts an already-computed DoctorReport to avoid re-running checks.
        """
        if doctor_report is None:
            doctor_report = ConfigDoctor().run_all_checks()

        report = ImprovementReport()
        self._suggest_from_doctor_report(doctor_report, report)
        self._suggest_from_benchmark_history(report)
        self._suggest_from_task_failures(report)
        return report

    def apply_improvements(
        self,
        report: ImprovementReport,
        auto_only: bool = True,
    ) -> List[str]:
        """
        Apply suggestions to personal config files.
        Returns a list of human-readable messages for each applied change.
        Returns only auto-applicable ones by default.

        Writes:
          - resource priority / model / enabled changes → ~/.memory/config/resource_pool.json
          - max_iterations / danger_budget changes      → ~/.memory/config/scheduler_config.json
        """
        to_apply = report.auto_applicable if auto_only else report.suggestions
        messages: List[str] = []

        resource_updates: Dict[str, Dict[str, Any]] = {}
        scheduler_updates: Dict[str, Dict[str, Any]] = {}  # {cron_job_id: {field: value}}

        for s in to_apply:
            if s.category == "resource":
                resource_updates.setdefault(s.target_id, {})[s.field] = s.suggested_value
                messages.append(f"[resource/{s.target_id}] {s.field} = {s.suggested_value!r}")
            elif s.category == "scheduler_task":
                scheduler_updates.setdefault(s.target_id, {})[s.field] = s.suggested_value
                messages.append(
                    f"[scheduler_task/{s.target_id}] {s.field} = {s.suggested_value!r}"
                )

        if resource_updates:
            self._apply_resource_updates(resource_updates)
        if scheduler_updates:
            self._apply_scheduler_updates(scheduler_updates)

        for s in to_apply:
            report.applied.append(s)

        return messages

    # ------------------------------------------------------------------
    # Heuristic 1: static doctor report → fix obvious errors
    # ------------------------------------------------------------------

    def _suggest_from_doctor_report(
        self, doctor_report: "DoctorReport", out: ImprovementReport
    ) -> None:
        """
        Turn doctor errors/warnings into actionable suggestions where possible.

        Currently handles:
          - Model ID mismatch on single-model servers → auto-fix the model name
          - Server unreachable → suggest disable (manual — don't auto-disable)
        """
        # Group model errors and base_url checks by resource
        model_errors: Dict[str, str] = {}   # res_id → current (wrong) model
        unreachable: set = set()

        for c in doctor_report.checks:
            if c.category != "resource":
                continue
            if c.status == "error" and c.field == "model":
                model_errors[c.id] = c.value
            elif c.status in ("warn", "error") and c.field == "base_url":
                if "not reachable" in c.message.lower():
                    unreachable.add(c.id)

        # Try to fix model ID mismatches for local servers
        for res_id, wrong_model in model_errors.items():
            # Fetch actual model list from the server
            base_url = self._get_resource_base_url(res_id)
            if not base_url:
                continue
            api_key = self._get_resource_api_key(res_id)
            available = _fetch_model_list(base_url, api_key=api_key)
            if not available:
                continue
            if len(available) == 1:
                # Unambiguous — the only loaded model is the right one
                correct_model = available[0]
                out.suggestions.append(ImprovementSuggestion(
                    category="resource",
                    target_id=res_id,
                    field="model",
                    current_value=wrong_model,
                    suggested_value=correct_model,
                    reason=f"Config says '{wrong_model}' but server only has '{correct_model}' loaded.",
                    evidence=f"_fetch_model_list({base_url}) returned [{correct_model}]",
                    confidence="high",
                    auto_apply=True,
                ))
            else:
                # Multiple models — try to find a close match
                norm_wrong = wrong_model.split("/")[-1].lower()
                close = [m for m in available if norm_wrong in m.lower() or m.lower() in norm_wrong]
                if len(close) == 1:
                    out.suggestions.append(ImprovementSuggestion(
                        category="resource",
                        target_id=res_id,
                        field="model",
                        current_value=wrong_model,
                        suggested_value=close[0],
                        reason=f"Config says '{wrong_model}' not found; closest match: '{close[0]}'.",
                        evidence=f"Available: {', '.join(available[:5])}",
                        confidence="medium",
                        auto_apply=False,
                    ))

        # Suggest disabling consistently unreachable resources
        for res_id in unreachable:
            if not self._resource_is_enabled(res_id):
                continue  # already disabled
            out.suggestions.append(ImprovementSuggestion(
                category="resource",
                target_id=res_id,
                field="enabled",
                current_value=True,
                suggested_value=False,
                reason="Server has been unreachable. Disabling prevents wasted retries.",
                evidence="Doctor check: base_url not reachable",
                confidence="low",
                auto_apply=False,
            ))

    # ------------------------------------------------------------------
    # Heuristic 2: benchmark history → priority + disable suggestions
    # ------------------------------------------------------------------

    def _suggest_from_benchmark_history(self, out: ImprovementReport) -> None:
        """
        Use BenchmarkStore analysis to:
          - Suggest priority updates (delegated to BenchmarkStore.suggest_priority_updates)
          - Flag resources with very low success rates
        """
        try:
            from app.scheduler.benchmark_store import BenchmarkStore
            bs = BenchmarkStore()
            stats = bs.analyze(min_samples=self.MIN_SAMPLES)
        except Exception as e:
            logger.debug(f"ConfigHealer: benchmark analysis failed: {e}")
            return

        current_priorities = self._get_current_priorities()

        for s in stats:
            # Priority rebalancing
            suggested_priority = (stats.index(s) + 1) * 2  # rank-based, gaps for manual
            current_p = current_priorities.get(s.resource_id)
            if current_p is not None and abs(suggested_priority - current_p) >= 2:
                out.suggestions.append(ImprovementSuggestion(
                    category="resource",
                    target_id=s.resource_id,
                    field="priority",
                    current_value=current_p,
                    suggested_value=suggested_priority,
                    reason=(
                        f"Benchmark rank #{stats.index(s)+1} based on composite score "
                        f"(success={s.success_rate:.0%}, speed={s.median_duration_s:.0f}s, "
                        f"judge_win={s.judge_win_rate:.0%})"
                    ),
                    evidence=f"{s.n_runs} runs; composite={s.composite_score:.3f}",
                    confidence="medium",
                    auto_apply=True,
                ))

            # Low success rate warning (do not auto-apply disable)
            if s.success_rate < self.LOW_SUCCESS_RATE:
                out.suggestions.append(ImprovementSuggestion(
                    category="resource",
                    target_id=s.resource_id,
                    field="enabled",
                    current_value=True,
                    suggested_value=False,
                    reason=(
                        f"Success rate is only {s.success_rate:.0%} across {s.n_runs} runs. "
                        f"Consider disabling or investigating model compatibility."
                    ),
                    evidence=f"{s.n_runs} runs; {int(s.success_rate * s.n_runs)} succeeded",
                    confidence="medium",
                    auto_apply=False,
                ))

    # ------------------------------------------------------------------
    # Heuristic 3: task queue failures → scheduler config bumps
    # ------------------------------------------------------------------

    def _suggest_from_task_failures(self, out: ImprovementReport) -> None:
        """
        Scan the task queue for recently failed cron tasks and suggest
        bumping max_iterations or danger_budget when the failure pattern
        matches known budget-exhaustion signatures.
        """
        try:
            from app.scheduler.queue import TaskQueue
            from app.scheduler.models import TaskStatus
            queue = TaskQueue()
        except Exception as e:
            logger.debug(f"ConfigHealer: failed to load task queue: {e}")
            return

        # Load current scheduler config to know existing values
        try:
            from app.config.config_loader import load_layered_json_config
            project_root = Path(__file__).parent.parent.parent
            sched_path = str(project_root / "config" / "scheduler_config.json")
            sched_cfg = load_layered_json_config(sched_path)
            cron_jobs = {
                j["id"]: j.get("config", {})
                for j in (sched_cfg.get("default_tasks") or sched_cfg.get("jobs", []))
                if "id" in j
            }
        except Exception:
            cron_jobs = {}

        # Track failure patterns per task ID
        budget_exhausted: Dict[str, int] = {}    # task_id → count
        danger_exhausted: Dict[str, int] = {}    # task_id → count

        cutoff_dt = __import__("datetime").datetime.now() - __import__("datetime").timedelta(
            days=self.SCHEDULER_CONFIG_LOOKBACK_DAYS
        )

        for task in queue.tasks.values():
            if task.status not in (
                __import__("app.scheduler.models", fromlist=["TaskStatus"]).TaskStatus.FAILED,
                __import__("app.scheduler.models", fromlist=["TaskStatus"]).TaskStatus.COMPLETED,
            ):
                continue
            if task.completed_at and task.completed_at < cutoff_dt:
                continue

            err = ""
            if task.result:
                err = (task.result.error_message or "").lower()
            elif task.status == __import__(
                "app.scheduler.models", fromlist=["TaskStatus"]
            ).TaskStatus.FAILED:
                err = ""

            if not err:
                continue

            # Only cron-sourced tasks have meaningful IDs to look up
            task_id = task.id
            if task_id not in cron_jobs:
                continue  # dynamic/user task — skip

            if "iteration budget exhausted" in err or "max_iterations" in err:
                budget_exhausted[task_id] = budget_exhausted.get(task_id, 0) + 1
            if "danger budget" in err or "securitygate" in err.lower():
                danger_exhausted[task_id] = danger_exhausted.get(task_id, 0) + 1

        # Emit suggestions
        for task_id, count in budget_exhausted.items():
            cfg = cron_jobs.get(task_id, {})
            current = cfg.get("max_iterations", 20)
            suggested = max(int(current * self.BUDGET_BUMP_FACTOR), current + 5)
            out.suggestions.append(ImprovementSuggestion(
                category="scheduler_task",
                target_id=task_id,
                field="max_iterations",
                current_value=current,
                suggested_value=suggested,
                reason=(
                    f"Task '{task_id}' hit iteration budget {count} time(s) recently. "
                    f"Bumping from {current} → {suggested}."
                ),
                evidence=f"{count} failure(s) with 'iteration budget exhausted' in last "
                         f"{self.SCHEDULER_CONFIG_LOOKBACK_DAYS} days",
                confidence="medium",
                auto_apply=True,
            ))

        for task_id, count in danger_exhausted.items():
            cfg = cron_jobs.get(task_id, {})
            current_budget = cfg.get("danger_budget", self.MAX_DANGER_BUDGET_DEFAULT)
            suggested_budget = max(
                int(current_budget * self.BUDGET_BUMP_FACTOR),
                current_budget + 100,
            )
            out.suggestions.append(ImprovementSuggestion(
                category="scheduler_task",
                target_id=task_id,
                field="danger_budget",
                current_value=current_budget,
                suggested_value=suggested_budget,
                reason=(
                    f"Task '{task_id}' exhausted SecurityGate danger budget {count} time(s). "
                    f"Bumping from {current_budget} → {suggested_budget}."
                ),
                evidence=f"{count} failure(s) with danger budget exhaustion in last "
                         f"{self.SCHEDULER_CONFIG_LOOKBACK_DAYS} days",
                confidence="medium",
                auto_apply=True,
            ))

    # ------------------------------------------------------------------
    # Apply helpers — write to personal config layer only
    # ------------------------------------------------------------------

    def _apply_resource_updates(self, updates: Dict[str, Dict[str, Any]]) -> None:
        """Write resource field changes to ~/.memory/config/resource_pool.json."""
        try:
            from app.config.paths import get_memory_subpath
            path = Path(get_memory_subpath("config", "resource_pool.json"))
            data: Dict[str, Any] = {}
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
            resources = data.setdefault("resources", {})
            for res_id, fields in updates.items():
                resources.setdefault(res_id, {}).update(fields)
                logger.info(f"ConfigHealer: resource/{res_id} ← {fields}")
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"ConfigHealer: failed to write resource_pool.json: {e}")

    def _apply_scheduler_updates(self, updates: Dict[str, Dict[str, Any]]) -> None:
        """
        Write scheduler task config overrides to ~/.memory/config/scheduler_config.json.
        Merges into the personal layer's default_tasks list by task ID.
        """
        try:
            from app.config.paths import get_memory_subpath
            path = Path(get_memory_subpath("config", "scheduler_config.json"))
            data: Dict[str, Any] = {}
            if path.exists():
                with open(path) as f:
                    data = json.load(f)

            default_tasks: List[Dict[str, Any]] = data.setdefault("default_tasks", [])

            # Build index by id
            by_id = {t["id"]: t for t in default_tasks if "id" in t}

            for task_id, fields in updates.items():
                entry = by_id.setdefault(task_id, {"id": task_id})
                cfg = entry.setdefault("config", {})
                cfg.update(fields)
                logger.info(f"ConfigHealer: scheduler_task/{task_id} ← {fields}")

            # Rebuild list preserving order
            seen = set()
            new_list = []
            for entry in default_tasks:
                eid = entry.get("id")
                if eid in by_id:
                    new_list.append(by_id[eid])
                    seen.add(eid)
                elif eid is None:
                    new_list.append(entry)
            for eid, entry in by_id.items():
                if eid not in seen:
                    new_list.append(entry)

            data["default_tasks"] = new_list
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"ConfigHealer: failed to write scheduler_config.json: {e}")

    # ------------------------------------------------------------------
    # Resource pool helpers
    # ------------------------------------------------------------------

    def _get_resource_base_url(self, res_id: str) -> Optional[str]:
        try:
            from app.scheduler.resource_pool import ResourceManager
            rm = ResourceManager()
            r = rm._resources.get(res_id)
            return getattr(r, "base_url", None) if r else None
        except Exception:
            return None

    def _get_resource_api_key(self, res_id: str) -> Optional[str]:
        try:
            from app.scheduler.resource_pool import ResourceManager
            rm = ResourceManager()
            r = rm._resources.get(res_id)
            if r is None:
                return None
            key = getattr(r, "api_key", None)
            if key:
                return key
            env_var = getattr(r, "api_key_env", None)
            if env_var:
                return os.getenv(env_var)
            return None
        except Exception:
            return None

    def _resource_is_enabled(self, res_id: str) -> bool:
        try:
            from app.scheduler.resource_pool import ResourceManager
            rm = ResourceManager()
            r = rm._resources.get(res_id)
            return bool(getattr(r, "enabled", True)) if r else False
        except Exception:
            return False

    def _get_current_priorities(self) -> Dict[str, int]:
        try:
            from app.scheduler.resource_pool import ResourceManager
            rm = ResourceManager()
            return {
                rid: getattr(res, "priority", 50)
                for rid, res in rm._resources.items()
            }
        except Exception:
            return {}
