"""
Embedding Resource Pool

Manages embedding backends with priority-based selection, failover,
and configuration-driven setup. Follows the same architecture as
the LLM resource pool (app/scheduler/resource_pool.py).
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config.paths import get_memory_path

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingResource:
    """A single embedding backend configuration."""
    id: str
    backend: str  # "huggingface", "api", "local", "random"
    model_name: str
    embedding_dim: int
    priority: int = 10  # lower = higher priority
    enabled: bool = True
    api_key: Optional[str] = None
    api_key_env: Optional[str] = None
    server_url: Optional[str] = None
    device: str = "cpu"
    matryoshka: bool = False
    request_format: str = "legacy"  # "legacy" or "openai"
    # Runtime state
    status: str = "available"  # available, failed, disabled
    last_error: Optional[str] = None
    last_used: float = 0.0
    failed_at: float = 0.0


class EmbeddingPool:
    """
    Pool of embedding backends with priority-based selection and failover.

    Configuration sources (in priority order):
    1. ~/.memory/config/embedding_pool.json — personal overrides
    2. config/embedding_config.json — system defaults
    3. Environment variables
    """

    def __init__(self, config_path: Optional[str] = None, recovery_ttl: int = 300):
        self._lock = threading.Lock()
        self._resources: Dict[str, EmbeddingResource] = {}
        self._config_path = config_path
        self._recovery_ttl = recovery_ttl
        self._config_mtime: float = 0.0
        # Metrics: resource_id -> {calls, failures, last_latency_ms}
        self._stats: Dict[str, Dict[str, Any]] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Load embedding configuration from file and env vars."""
        config = self._load_config_file()

        # Record config mtime for auto-reload
        config_path = self._config_path or str(
            Path(get_memory_path()) / "config" / "embedding_pool.json"
        )
        if not Path(config_path).exists():
            config_path = "config/embedding_config.json"
        try:
            self._config_mtime = Path(config_path).stat().st_mtime
        except OSError:
            pass

        models = config.get("embedding_models", {})
        for model_id, model_cfg in models.items():
            resource = self._parse_resource(model_id, model_cfg)
            if resource:
                self._resources[model_id] = resource

        self._apply_env_overrides()
        logger.info(f"EmbeddingPool: loaded {len(self._resources)} backends")

    def _load_config_file(self) -> Dict[str, Any]:
        """Load config from personal override or system default."""
        # Personal override
        personal_path = Path(get_memory_path()) / "config" / "embedding_pool.json"
        if personal_path.exists():
            try:
                return json.loads(personal_path.read_text())
            except Exception as e:
                logger.warning(f"Failed to load personal embedding config: {e}")

        # System default
        if self._config_path:
            config_path = Path(self._config_path)
        else:
            config_path = Path("config/embedding_config.json")

        if config_path.exists():
            try:
                return json.loads(config_path.read_text())
            except Exception as e:
                logger.warning(f"Failed to load system embedding config: {e}")

        return {}

    def _parse_resource(self, model_id: str, cfg: Dict[str, Any]) -> Optional[EmbeddingResource]:
        """Parse a single embedding model config into an EmbeddingResource."""
        try:
            # Resolve API key from env if specified
            api_key = cfg.get("api_key")
            if api_key and api_key.startswith("$"):
                env_var = api_key[1:]
                api_key = os.environ.get(env_var)

            return EmbeddingResource(
                id=model_id,
                backend=cfg.get("backend", "huggingface"),
                model_name=cfg.get("model_name", ""),
                embedding_dim=cfg.get("embedding_dim", 768),
                priority=cfg.get("priority", 10),
                enabled=cfg.get("enabled", True),
                api_key=api_key,
                api_key_env=cfg.get("api_key_env"),
                server_url=cfg.get("server_url"),
                device=cfg.get("device", "cpu"),
                matryoshka=cfg.get("matryoshka", False),
                request_format=cfg.get("request_format", "legacy"),
            )
        except Exception as e:
            logger.warning(f"Failed to parse embedding config '{model_id}': {e}")
            return None

    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides."""
        # EMBEDDING_MODEL overrides default selection
        default_model = os.environ.get("EMBEDDING_MODEL")
        if default_model and default_model in self._resources:
            # Boost priority of the env-specified model
            for rid, r in self._resources.items():
                if rid == default_model:
                    r.priority = 0

        # OPENAI_API_KEY for openai backend
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key:
            for r in self._resources.values():
                if r.backend == "api" and "openai" in r.id.lower() and not r.api_key:
                    r.api_key = openai_key

    def _available_candidates(self, min_dim: Optional[int] = None) -> List[EmbeddingResource]:
        """
        Return all healthy resources sorted by priority (caller must hold self._lock).

        Auto-recovers failed resources whose recovery_ttl has elapsed.
        Filters out disabled resources and those below min_dim.
        """
        now = time.time()
        candidates = []
        for res in self._resources.values():
            if not res.enabled:
                continue
            if res.status == "failed":
                if now - res.failed_at < self._recovery_ttl:
                    continue
                res.status = "available"
                res.last_error = None
                res.failed_at = 0.0
            if min_dim is not None and (res.embedding_dim or 0) < min_dim:
                continue
            candidates.append(res)
        candidates.sort(key=lambda x: x.priority)
        return candidates

    def acquire(
        self,
        preferred_id: Optional[str] = None,
        min_dim: Optional[int] = None,
    ) -> Optional[EmbeddingResource]:
        """
        Acquire an embedding resource by priority.

        Args:
            preferred_id: Specific resource ID to prefer (still checks health)
            min_dim: Minimum embedding dimension required

        Returns:
            EmbeddingResource or None if no suitable backend available
        """
        with self._lock:
            self._maybe_reload()
            candidates = self._available_candidates(min_dim)

            if not candidates:
                return None

            if preferred_id:
                for res in candidates:
                    if res.id == preferred_id:
                        res.last_used = time.time()
                        return res

            resource = candidates[0]
            resource.last_used = time.time()
            return resource

    def acquire_with_fallback(
        self,
        preferred_id: Optional[str] = None,
        min_dim: Optional[int] = None,
        strict_dim: bool = True,
    ) -> List[EmbeddingResource]:
        """
        Acquire primary + fallback resources ordered by priority.

        Args:
            preferred_id: Specific resource ID to prefer (floated to front)
            min_dim: Minimum embedding dimension required
            strict_dim: If True, only return resources matching primary's dim

        Returns:
            List of resources to try in order (empty if none available).
        """
        with self._lock:
            self._maybe_reload()
            candidates = self._available_candidates(min_dim)

            if preferred_id:
                preferred = [r for r in candidates if r.id == preferred_id]
                others = [r for r in candidates if r.id != preferred_id]
                candidates = preferred + others

            if strict_dim and candidates:
                primary_dim = candidates[0].embedding_dim
                candidates = [r for r in candidates if r.embedding_dim == primary_dim]

            return candidates

    def mark_failed(self, resource_id: str, error: str) -> None:
        """Mark a resource as failed with timestamp for auto-recovery."""
        with self._lock:
            if resource_id in self._resources:
                self._resources[resource_id].status = "failed"
                self._resources[resource_id].last_error = error
                self._resources[resource_id].failed_at = time.time()
                self._ensure_stats(resource_id)["failures"] += 1
                logger.warning(f"EmbeddingPool: marked '{resource_id}' as failed: {error}")

    def mark_available(self, resource_id: str) -> None:
        """Mark a resource as available (recovery)."""
        with self._lock:
            if resource_id in self._resources:
                self._resources[resource_id].status = "available"
                self._resources[resource_id].last_error = None
                self._resources[resource_id].failed_at = 0.0

    def _ensure_stats(self, resource_id: str) -> Dict[str, Any]:
        """Get or create stats entry for a resource. Caller must hold self._lock."""
        if resource_id not in self._stats:
            self._stats[resource_id] = {
                "calls": 0,
                "failures": 0,
                "total_latency_ms": 0.0,
                "last_latency_ms": 0.0,
            }
        return self._stats[resource_id]

    def record_call(self, resource_id: str, latency_ms: float) -> None:
        """Record a successful embedding call for latency and throughput metrics."""
        with self._lock:
            stats = self._ensure_stats(resource_id)
            stats["calls"] += 1
            stats["total_latency_ms"] += latency_ms
            stats["last_latency_ms"] = round(latency_ms, 1)

    def list_resources(self) -> List[Dict[str, Any]]:
        """List all configured embedding resources with runtime metrics."""
        with self._lock:
            result = []
            for res in sorted(self._resources.values(), key=lambda x: x.priority):
                stats = self._stats.get(res.id, {
                    "calls": 0, "failures": 0,
                    "total_latency_ms": 0.0, "last_latency_ms": 0.0,
                })
                calls = stats["calls"]
                avg_latency = round(stats["total_latency_ms"] / calls, 1) if calls else 0.0
                result.append({
                    "id": res.id,
                    "backend": res.backend,
                    "model_name": res.model_name,
                    "embedding_dim": res.embedding_dim,
                    "priority": res.priority,
                    "enabled": res.enabled,
                    "status": res.status,
                    "last_error": res.last_error,
                    "calls": calls,
                    "failures": stats["failures"],
                    "last_latency_ms": stats["last_latency_ms"],
                    "avg_latency_ms": avg_latency,
                })
            return result

    def get_resource(self, resource_id: str) -> Optional[EmbeddingResource]:
        """Get a specific resource by ID."""
        return self._resources.get(resource_id)

    def _maybe_reload(self) -> None:
        """Auto-reload if config file changed (cheap stat check)."""
        config_path = self._config_path or str(
            Path(get_memory_path()) / "config" / "embedding_pool.json"
        )
        if not Path(config_path).exists():
            config_path = "config/embedding_config.json"
        try:
            mtime = Path(config_path).stat().st_mtime
            if mtime > self._config_mtime:
                self._resources.clear()
                self._load_config()
                self._config_mtime = mtime
        except OSError:
            pass

    def reload(self) -> None:
        """Reload configuration from disk."""
        with self._lock:
            self._resources.clear()
            self._load_config()

    def diagnose_conflicts(
        self,
        memory_service: Any,
        query_set: Optional[List[str]] = None,
        role_id: str = "unknown",
    ) -> "DiagnosisSummary":
        """Scan for semantic contradictions, staleness, and knowledge gaps.

        Delegates to ConflictDiagnoser. Returns a typed DiagnosisSummary
        so callers can use .healthy, .summary(), and .gaps directly.
        """
        from app.memory.conflict_diagnosis import ConflictDiagnoser, DiagnosisSummary
        diagnoser = ConflictDiagnoser(
            memory_service=memory_service,
            role_id=role_id,
        )
        return diagnoser.diagnose(query_set=query_set)


# Singleton instance
_pool: Optional[EmbeddingPool] = None
_pool_lock = threading.Lock()


def get_embedding_pool() -> EmbeddingPool:
    """Get or create the singleton EmbeddingPool instance."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = EmbeddingPool()
    return _pool
