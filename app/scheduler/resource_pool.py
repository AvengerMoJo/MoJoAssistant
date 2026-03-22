"""
LLM Resource Pool

Manages available LLM endpoints with rate limiting, budget tracking,
and tier-based selection for agentic tasks.
"""

import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional
from app.config.paths import get_memory_subpath


class ResourceTier(Enum):
    FREE = "free"
    FREE_API = "free_api"
    PAID = "paid"


class ResourceStatus(Enum):
    AVAILABLE = "available"
    RATE_LIMITED = "rate_limited"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DISABLED = "disabled"
    UNREACHABLE = "unreachable"


@dataclass
class RateLimit:
    max_calls_per_window: int = 0
    window_seconds: int = 3600
    min_interval_seconds: float = 0.0


@dataclass
class Budget:
    max_calls_per_window: int = 0
    window_seconds: int = 18000  # 5 hours
    reserved_for_user_pct: float = 20.0


@dataclass
class LLMResource:
    id: str
    type: str  # "local", "api"
    provider: str  # "openai", etc.
    base_url: str
    model: str
    tier: ResourceTier
    priority: int = 1
    enabled: bool = True
    api_key: Optional[str] = None
    api_key_env: Optional[str] = None
    context_limit: int = 32768
    output_limit: int = 8192
    description: str = ""
    account_group: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    rate_limit: Optional[RateLimit] = None
    budget: Optional[Budget] = None


@dataclass
class UsageRecord:
    call_timestamps: Deque[float] = field(default_factory=deque)
    total_calls: int = 0
    last_call_at: Optional[float] = None
    consecutive_errors: int = 0


class ResourceManager:
    """Manages LLM resource selection, rate limiting, and budget tracking."""

    SANDBOX_ENV_FILE = Path(get_memory_subpath("resource_pool.env"))
    USAGE_FILE = Path(get_memory_subpath("resource_pool_usage.json"))
    META_FILE = Path(get_memory_subpath("resource_pool_meta.json"))

    def __init__(self, config_path: str = "config/resource_pool.json", logger=None):
        self._config_path = config_path
        self._logger = logger
        self._lock = threading.RLock()
        self._resources: Dict[str, LLMResource] = {}
        self._usage: Dict[str, UsageRecord] = {}
        self._approved_paid: set = set()
        # Round-robin counters per account_group
        self._group_counters: Dict[str, int] = {}
        self._sandbox_env: Dict[str, str] = {}
        self._config_mtime_ns: Optional[int] = None
        self._runtime_mtime_ns: Optional[int] = None
        self._env_mtime_ns: Optional[int] = None
        # Smoke test results: resource_id → bool (agentic_capable)
        self._agentic_capable: Dict[str, bool] = {}
        self._load_sandbox_env()
        self._load_usage()
        self._load_meta()
        self._load_config()

    def _load_sandbox_env(self):
        """Load API keys from the sandbox env file (~/.memory/resource_pool.env)."""
        self._sandbox_env.clear()
        if not self.SANDBOX_ENV_FILE.exists():
            self._env_mtime_ns = None
            return
        for line in self.SANDBOX_ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                self._sandbox_env[key.strip()] = value.strip()
        self._env_mtime_ns = self.SANDBOX_ENV_FILE.stat().st_mtime_ns

    def _load_usage(self):
        """Restore persisted usage stats from disk."""
        if not self.USAGE_FILE.exists():
            return
        try:
            data = json.loads(self.USAGE_FILE.read_text(encoding="utf-8"))
            for rid, rec in data.items():
                self._usage[rid] = UsageRecord(
                    total_calls=rec.get("total_calls", 0),
                    last_call_at=rec.get("last_call_at"),
                    # Reset on startup — stale errors from a dead process must not
                    # permanently block resources on the next server start.
                    consecutive_errors=0,
                )
            self._log(f"Loaded usage stats for {len(data)} resource(s)")
        except Exception as e:
            self._log(f"Failed to load usage stats: {e}", "warning")

    def _persist_usage(self):
        """Persist lightweight usage stats to disk."""
        try:
            data = {}
            for rid, usage in self._usage.items():
                data[rid] = {
                    "total_calls": usage.total_calls,
                    "last_call_at": usage.last_call_at,
                    "consecutive_errors": usage.consecutive_errors,
                }
            self.USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.USAGE_FILE.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except Exception as e:
            self._log(f"Failed to persist usage stats: {e}", "warning")

    def _log(self, message: str, level: str = "info"):
        if self._logger:
            getattr(self._logger, level)(f"[ResourcePool] {message}")

    def _load_config(self):
        from app.config.config_loader import load_layered_json_config, MEMORY_CONFIG_DIR

        # Prefer resource_pool.json (flat format); fall back to llm_config.json (legacy format)
        primary_path = "config/resource_pool.json"
        fallback_path = "config/llm_config.json"
        use_flat = Path(primary_path).exists()
        resolved_path = primary_path if use_flat else fallback_path

        # Update the tracked config path so mtime checks use the correct file
        self._config_path = resolved_path

        codebase_path = Path(resolved_path)
        runtime_path = Path(MEMORY_CONFIG_DIR) / codebase_path.name

        data = load_layered_json_config(resolved_path)

        self._config_mtime_ns = codebase_path.stat().st_mtime_ns if codebase_path.exists() else None
        self._runtime_mtime_ns = runtime_path.stat().st_mtime_ns if runtime_path.exists() else None

        if use_flat:
            self._parse_flat_resources(data)
            self._auto_sync_flat_servers(data)
        else:
            self._log("resource_pool.json not found, falling back to llm_config.json (legacy format)", "warning")
            self._parse_legacy_resources(data)
            self._auto_sync_local_servers(data)

    def _parse_flat_resources(self, data: dict) -> None:
        """Parse flat `resources` dict format (resource_pool.json)."""
        with self._lock:
            self._resources.clear()
            for rid, rconf in data.get("resources", {}).items():
                if not isinstance(rconf, dict):
                    continue
                rconf = dict(rconf)
                rconf.setdefault(
                    "type",
                    "local" if rconf.get("base_url", "").startswith("http://localhost") else "api"
                )
                rconf.setdefault("provider", "openai")
                resource = self._parse_resource(rid, rconf)
                self._resources[rid] = resource
                if rid not in self._usage:
                    self._usage[rid] = UsageRecord()
            self._tier_policy = data.get("tier_policy", {})
            self._selection_strategy = data.get("selection_strategy", "priority_then_availability")
            self._log(f"Loaded {len(self._resources)} resources (flat format)")

    def _auto_sync_flat_servers(self, config_data: dict) -> None:
        """Auto-expand flat resources with dynamic_discovery=True or model=None."""
        for name, entry in config_data.get("resources", {}).items():
            if not isinstance(entry, dict):
                continue
            if entry.get("dynamic_discovery") or entry.get("model") is None:
                if entry.get("base_url", "").startswith("http://localhost"):
                    try:
                        self.sync_local_server_models(name)
                    except Exception as e:
                        self._log(f"Auto-sync failed for '{name}': {e}", "warning")

    def _parse_legacy_resources(self, data: dict) -> None:
        """Parse legacy llm_config.json format with local_models/api_models nesting."""
        with self._lock:
            self._resources.clear()

            # local_models → LLMResource with type="local"
            for rid, rconf in data.get("local_models", {}).items():
                if not isinstance(rconf, dict):
                    continue
                rconf = dict(rconf)
                rconf.setdefault("type", "local")
                rconf.setdefault("provider", "openai")
                # local_models use "server_url" or "path" — base_url defaults to empty
                rconf.setdefault("base_url", rconf.get("server_url") or "")
                resource = self._parse_resource(rid, rconf)
                self._resources[rid] = resource
                if rid not in self._usage:
                    self._usage[rid] = UsageRecord()

            # api_models → flat entries or nested sub-accounts
            for name, api_conf in data.get("api_models", {}).items():
                if not isinstance(api_conf, dict) or not api_conf:
                    continue
                if api_conf.get("provider"):
                    # Flat entry — register directly
                    rconf = dict(api_conf)
                    rconf.setdefault("type", "api")
                    resource = self._parse_resource(name, rconf)
                    self._resources[name] = resource
                    if name not in self._usage:
                        self._usage[name] = UsageRecord()
                else:
                    # Nested sub-accounts: register as "{parent}_{child}"
                    for sub_name, sub_conf in api_conf.items():
                        if not isinstance(sub_conf, dict) or not sub_conf.get("provider"):
                            continue
                        rid = f"{name}_{sub_name}"
                        rconf = dict(sub_conf)
                        rconf.setdefault("type", "api")
                        resource = self._parse_resource(rid, rconf)
                        self._resources[rid] = resource
                        if rid not in self._usage:
                            self._usage[rid] = UsageRecord()

            self._tier_policy = data.get("tier_policy", {})
            self._selection_strategy = data.get("selection_strategy", "priority_then_availability")
            self._log(f"Loaded {len(self._resources)} resources (legacy format)")

    def _auto_sync_local_servers(self, config_data: dict) -> None:
        """
        After loading config, auto-expand any local server entry that has
        ``dynamic_discovery: true`` OR has ``model: null`` into per-model entries.
        Runs outside the lock — calls sync_local_server_models() which re-acquires it.
        """
        for name, entry in config_data.get("api_models", {}).items():
            if not isinstance(entry, dict) or not entry.get("provider"):
                continue
            if entry.get("dynamic_discovery") or entry.get("model") is None:
                if entry.get("type") == "local" or entry.get("base_url", "").startswith("http://localhost"):
                    try:
                        self.sync_local_server_models(name)
                    except Exception as e:
                        self._log(f"Auto-sync failed for '{name}': {e}", "warning")

    def _maybe_reload_runtime_state(self):
        """Reload config/env when changed by another client/process (checks both config layers)."""
        from app.config.config_loader import MEMORY_CONFIG_DIR

        codebase_path = Path(self._config_path)
        runtime_path = Path(MEMORY_CONFIG_DIR) / codebase_path.name

        codebase_changed = codebase_path.exists() and (
            self._config_mtime_ns is None
            or codebase_path.stat().st_mtime_ns != self._config_mtime_ns
        )
        runtime_changed = runtime_path.exists() and (
            self._runtime_mtime_ns is None
            or runtime_path.stat().st_mtime_ns != self._runtime_mtime_ns
        )
        config_changed = codebase_changed or runtime_changed

        env_changed = self.SANDBOX_ENV_FILE.exists() and (
            self._env_mtime_ns is None
            or self.SANDBOX_ENV_FILE.stat().st_mtime_ns != self._env_mtime_ns
        )

        if not config_changed and not env_changed:
            return

        self._log(
            f"Detected external update (config_changed={config_changed}, env_changed={env_changed}); reloading",
            "info",
        )
        # Load env first so fresh keys are present when resources are parsed.
        self._load_sandbox_env()
        self._load_config()

    def _parse_tier(self, value: str) -> ResourceTier:
        """Parse a tier string, falling back to FREE for unrecognised values."""
        try:
            return ResourceTier(value)
        except ValueError:
            self._log(f"Unknown tier value '{value}', treating as 'free'", "warning")
            return ResourceTier.FREE

    def _parse_resource(self, rid: str, conf: Dict[str, Any]) -> LLMResource:
        # Resolve API key: inline api_key wins; otherwise resolve from key_var/api_key_env;
        # final fallback: resolve_llm_resource() reads layered llm_config.json directly.
        from app.llm.unified_client import UnifiedLLMClient
        api_key = UnifiedLLMClient.resolve_key(rid, conf, env_override=self._sandbox_env)
        api_key_env = conf.get("key_var") or conf.get("api_key_env")

        rate_limit = None
        if "rate_limit" in conf:
            rl = conf["rate_limit"]
            rate_limit = RateLimit(
                max_calls_per_window=rl.get("max_calls_per_window", 0),
                window_seconds=rl.get("window_seconds", 3600),
                min_interval_seconds=rl.get("min_interval_seconds", 0.0),
            )

        budget = None
        if "budget" in conf:
            b = conf["budget"]
            budget = Budget(
                max_calls_per_window=b.get("max_calls_per_window", 0),
                window_seconds=b.get("window_seconds", 18000),
                reserved_for_user_pct=b.get("reserved_for_user_pct", 20.0),
            )

        return LLMResource(
            id=rid,
            type=conf.get("type", "local"),
            provider=conf.get("provider", "openai"),
            base_url=conf.get("base_url", ""),
            model=conf.get("model", ""),
            tier=self._parse_tier(conf.get("tier", "free")),
            priority=conf.get("priority", 1),
            enabled=conf.get("enabled", True),
            api_key=api_key,
            api_key_env=api_key_env,
            context_limit=conf.get("context_limit", 32768),
            output_limit=conf.get("output_limit", 8192),
            description=conf.get("description", ""),
            account_group=conf.get("account_group"),
            capabilities=conf.get("capabilities", []),
            rate_limit=rate_limit,
            budget=budget,
        )

    def acquire(
        self,
        tier_preference: Optional[List[ResourceTier]] = None,
        min_context: int = 0,
        min_output: int = 0,
    ) -> Optional[LLMResource]:
        """
        Acquire the best available resource matching constraints.

        Returns None if no resource is available.
        """
        if tier_preference is None:
            tier_preference = [ResourceTier.FREE, ResourceTier.FREE_API]

        with self._lock:
            self._maybe_reload_runtime_state()
            candidates = []
            for resource in self._resources.values():
                if not resource.enabled:
                    continue
                if resource.tier not in tier_preference:
                    continue
                if resource.tier == ResourceTier.PAID and resource.id not in self._approved_paid:
                    continue
                if resource.context_limit < min_context:
                    continue
                if resource.output_limit < min_output:
                    continue
                if self._is_rate_limited(resource):
                    continue
                if not self._is_budget_available(resource):
                    continue
                if self._compute_status(resource) == ResourceStatus.UNREACHABLE:
                    continue
                candidates.append(resource)

            if not candidates:
                return None

            # Sort by priority (lower = preferred)
            candidates.sort(key=lambda r: r.priority)

            # For resources in the same account_group, apply round-robin
            best = candidates[0]
            group = best.account_group
            if group:
                group_candidates = [c for c in candidates if c.account_group == group]
                if len(group_candidates) > 1:
                    idx = self._group_counters.get(group, 0) % len(group_candidates)
                    best = group_candidates[idx]
                    self._group_counters[group] = idx + 1

            return best

    def acquire_by_id(self, resource_id: str) -> Optional[LLMResource]:
        """
        Acquire a specific resource by ID, applying the same availability checks as acquire().

        Returns None if the resource doesn't exist, is disabled, rate-limited, or unreachable.
        """
        with self._lock:
            self._maybe_reload_runtime_state()
            resource = self._resources.get(resource_id)
            if resource is None or not resource.enabled:
                return None
            if self._is_rate_limited(resource):
                return None
            if not self._is_budget_available(resource):
                return None
            if self._compute_status(resource) == ResourceStatus.UNREACHABLE:
                return None
            return resource

    def acquire_by_requirements(
        self,
        requirements: Dict[str, Any],
    ) -> Optional[LLMResource]:
        """
        Acquire the best available resource matching structured requirements.

        requirements keys (all optional):
            tier (str | list[str]):    e.g. "free" or ["free", "free_api"]
            min_context (int):         minimum context_limit required
            min_output (int):          minimum output_limit required
            capabilities (list[str]): resource must declare all listed capabilities

        Returns None if nothing satisfies the requirements.
        """
        tier_strs = requirements.get("tier", ["free", "free_api"])
        if isinstance(tier_strs, str):
            tier_strs = [tier_strs]
        tier_preference = []
        for t in tier_strs:
            try:
                tier_preference.append(ResourceTier(t))
            except ValueError:
                self._log(f"acquire_by_requirements: unknown tier '{t}', skipping", "warning")
        if not tier_preference:
            tier_preference = [ResourceTier.FREE, ResourceTier.FREE_API]

        min_context = requirements.get("min_context", 0)
        min_output = requirements.get("min_output", 0)
        required_caps = set(requirements.get("capabilities", []))

        with self._lock:
            self._maybe_reload_runtime_state()
            candidates = []
            for resource in self._resources.values():
                if not resource.enabled:
                    continue
                if resource.tier not in tier_preference:
                    continue
                if resource.tier == ResourceTier.PAID and resource.id not in self._approved_paid:
                    continue
                if resource.context_limit < min_context:
                    continue
                if resource.output_limit < min_output:
                    continue
                if required_caps and not required_caps.issubset(set(resource.capabilities)):
                    continue
                if self._is_rate_limited(resource):
                    continue
                if not self._is_budget_available(resource):
                    continue
                if self._compute_status(resource) == ResourceStatus.UNREACHABLE:
                    continue
                candidates.append(resource)

            if not candidates:
                return None

            candidates.sort(key=lambda r: r.priority)
            best = candidates[0]
            group = best.account_group
            if group:
                group_candidates = [c for c in candidates if c.account_group == group]
                if len(group_candidates) > 1:
                    idx = self._group_counters.get(group, 0) % len(group_candidates)
                    best = group_candidates[idx]
                    self._group_counters[group] = idx + 1
            return best

    def record_usage(self, resource_id: str, tokens_used: int = 0, success: bool = True):
        """Record a completed LLM call."""
        with self._lock:
            usage = self._usage.get(resource_id)
            if usage is None:
                usage = UsageRecord()
                self._usage[resource_id] = usage

            now = time.time()
            usage.call_timestamps.append(now)
            usage.total_calls += 1
            usage.last_call_at = now

            if success:
                usage.consecutive_errors = 0
            else:
                usage.consecutive_errors += 1

            self._persist_usage()

    def get_status(self) -> Dict[str, Any]:
        """Return status of all resources with usage stats."""
        with self._lock:
            self._maybe_reload_runtime_state()
            resources_snapshot = list(self._resources.items())
            usage_snapshot = dict(self._usage)

        # Probe local servers outside the lock to avoid blocking
        result = {}
        for rid, resource in resources_snapshot:
            usage = usage_snapshot.get(rid, UsageRecord())
            with self._lock:
                status = self._compute_status(resource)
            model = resource.model or self._probe_live_model(resource)
            result[rid] = {
                "model": model,
                "tier": resource.tier.value,
                "priority": resource.priority,
                "enabled": resource.enabled,
                "status": status.value,
                "total_calls": usage.total_calls,
                "consecutive_errors": usage.consecutive_errors,
                "description": resource.description,
            }
        return result

    def _probe_live_model(self, resource: "LLMResource") -> str:
        """For local resources without a configured model, query the server for the active model."""
        models = self._probe_all_models(resource)
        return models[0] if models else ""

    def _probe_all_models(self, resource: "LLMResource") -> list:
        """Query a local server's /v1/models and return all model IDs."""
        import requests as req
        if not resource.base_url:
            return []
        base = resource.base_url.rstrip("/").rstrip("/v1")
        auth = f"Bearer {resource.api_key}" if resource.api_key else ""
        headers = {"Authorization": auth} if auth else {}
        for path in ("/v1/models", "/models"):
            try:
                resp = req.get(f"{base}{path}", headers=headers, timeout=2)
                if resp.status_code == 200:
                    return [m.get("id", "") for m in resp.json().get("data", []) if m.get("id")]
            except Exception:
                pass
        return []

    def sync_local_server_models(self, template_resource_id: str = "lmstudio") -> list:
        """
        Query a local server and expand it into one resource entry per loaded model.

        For each model discovered at {template_resource_id}'s base_url:
          - Creates/updates a resource entry "{template_resource_id}__{slug}" where
            slug is the model id with non-alphanumeric chars replaced by '_'
          - Inherits all settings from the template (api_key, tier, base_url, etc.)
          - Sets the model field explicitly
          - Removes stale entries from a previous sync that are no longer loaded

        Returns list of resource IDs that are now registered.
        """
        with self._lock:
            self._maybe_reload_runtime_state()
            template = self._resources.get(template_resource_id)
            if not template:
                self._log(f"sync_local_server_models: template '{template_resource_id}' not found")
                return []

        model_ids = self._probe_all_models(template)
        if not model_ids:
            self._log(f"sync_local_server_models: no models found at {template.base_url}")
            return []

        prefix = f"{template_resource_id}__"
        active_ids = set()

        with self._lock:
            # Remove stale entries from previous sync
            stale = [rid for rid in list(self._resources) if rid.startswith(prefix)]
            for rid in stale:
                del self._resources[rid]

            # Create one entry per model
            base_priority = template.priority + 1  # slightly lower priority than template
            for i, model_id in enumerate(model_ids):
                slug = "".join(c if c.isalnum() else "_" for c in model_id).strip("_")
                rid = f"{prefix}{slug}"
                resource = LLMResource(
                    id=rid,
                    provider=template.provider,
                    base_url=template.base_url,
                    api_key=template.api_key,
                    api_key_env=template.api_key_env,
                    model=model_id,
                    context_limit=template.context_limit,
                    output_limit=template.output_limit,
                    type=template.type,
                    tier=template.tier,
                    priority=base_priority + i,
                    enabled=template.enabled,
                    description=f"{model_id} (via {template_resource_id})",
                    account_group=template.account_group,
                    rate_limit=template.rate_limit,
                    budget=template.budget,
                )
                self._resources[rid] = resource
                if rid not in self._usage:
                    self._usage[rid] = UsageRecord()
                active_ids.add(rid)

        self._log(f"sync_local_server_models: registered {len(active_ids)} models from {template_resource_id}")
        return sorted(active_ids)

    def _load_meta(self) -> None:
        """Load persistent resource metadata (e.g. smoke test results) from disk."""
        if not self.META_FILE.exists():
            return
        try:
            data = json.loads(self.META_FILE.read_text(encoding="utf-8"))
            self._agentic_capable = data.get("agentic_capable", {})
        except Exception:
            pass

    def _save_meta(self) -> None:
        """Persist resource metadata to disk."""
        try:
            data = {"agentic_capable": self._agentic_capable}
            self.META_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def set_agentic_capable(self, resource_id: str, capable: bool) -> None:
        """Record the smoke test result for a resource."""
        with self._lock:
            self._agentic_capable[resource_id] = capable
            self._save_meta()
            self._log(f"Resource '{resource_id}' agentic_capable = {capable}")

    def get_agentic_capable(self, resource_id: str) -> Optional[bool]:
        """Return the smoke test result for a resource, or None if not tested."""
        return self._agentic_capable.get(resource_id)

    def approve_paid_resource(self, resource_id: str):
        with self._lock:
            self._maybe_reload_runtime_state()
            self._approved_paid.add(resource_id)
            self._log(f"Approved paid resource: {resource_id}")

    def revoke_paid_resource(self, resource_id: str):
        with self._lock:
            self._maybe_reload_runtime_state()
            self._approved_paid.discard(resource_id)
            self._log(f"Revoked paid resource: {resource_id}")

    def reload_config(self):
        """Re-read config from disk."""
        self._log("Reloading resource pool config")
        self._load_sandbox_env()
        self._load_config()

    def _is_rate_limited(self, resource: LLMResource) -> bool:
        rl = resource.rate_limit
        if rl is None:
            return False

        usage = self._usage.get(resource.id)
        if usage is None:
            return False

        now = time.time()

        # Check min interval
        if rl.min_interval_seconds > 0 and usage.last_call_at:
            if now - usage.last_call_at < rl.min_interval_seconds:
                return True

        # Check calls per window
        if rl.max_calls_per_window > 0:
            window_start = now - rl.window_seconds
            calls_in_window = sum(1 for ts in usage.call_timestamps if ts >= window_start)
            if calls_in_window >= rl.max_calls_per_window:
                return True

        return False

    def _is_budget_available(self, resource: LLMResource) -> bool:
        budget = resource.budget
        if budget is None:
            return True  # No budget constraint

        usage = self._usage.get(resource.id)
        if usage is None:
            return True

        now = time.time()
        window_start = now - budget.window_seconds

        calls_in_window = sum(1 for ts in usage.call_timestamps if ts >= window_start)

        # Agent gets (100 - reserved_for_user_pct)% of the budget
        agent_limit = int(
            budget.max_calls_per_window * (100 - budget.reserved_for_user_pct) / 100
        )

        return calls_in_window < agent_limit

    def _compute_status(self, resource: LLMResource) -> ResourceStatus:
        if not resource.enabled:
            return ResourceStatus.DISABLED

        usage = self._usage.get(resource.id)
        if usage and usage.consecutive_errors >= 5:
            return ResourceStatus.UNREACHABLE

        if self._is_rate_limited(resource):
            return ResourceStatus.RATE_LIMITED

        if not self._is_budget_available(resource):
            return ResourceStatus.BUDGET_EXHAUSTED

        return ResourceStatus.AVAILABLE
