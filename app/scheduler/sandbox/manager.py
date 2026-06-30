"""Unified SandboxManager — the single source of truth for sandbox lifecycle.

Analogous to ResourcePool for LLMs: one manager, one config, every module
that needs a sandbox goes through it.

Usage::

    mgr = SandboxManager.load()

    # In a handler, before the agent loop:
    handle = await mgr.acquire(task_id=task.id, git_url=cfg.get("git_url"))
    token = _cv_sandbox_handle.set(handle)
    try:
        result = await executor.execute(task)
    finally:
        _cv_sandbox_handle.reset(token)
        await mgr.release(handle)

    # capability_registry._bash_exec() transparently:
    handle = _cv_sandbox_handle.get()
    if handle:
        return await mgr.exec(handle, command)

Config is read from ~/.memory/config/sandbox.json; see _DEFAULT_CONFIG for
the schema and defaults.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from app.scheduler.sandbox.base import SandboxHandle, delete_handle, load_handle, store_handle
from app.scheduler.sandbox.context import _cv_sandbox_handle

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path.home() / ".memory" / "config" / "sandbox.json"

_DEFAULT_CONFIG: Dict[str, Any] = {
    "default_backend": "docker",
    "auto_provision": {
        "on_git_url": True,
        "on_task_type": ["coding", "external_agent"],
        "on_explicit_flag": True,
    },
    "backends": {
        "docker": {
            "image": "opencode-sandbox:latest",
            "memory": "4g",
            "cpus": "2",
            "port_range": [4500, 4599],
            "auto_remove_on_kill": True,
        },
        "host": {
            "workdir": str(Path.home() / ".memory" / "sandboxes"),
        },
    },
}


class SandboxManager:
    """Unified sandbox lifecycle manager."""

    _instance: Optional["SandboxManager"] = None

    def __init__(self, config: Dict[str, Any]) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Singleton loader
    # ------------------------------------------------------------------

    @classmethod
    def load(cls) -> "SandboxManager":
        """Load from ~/.memory/config/sandbox.json. Returns cached singleton."""
        if cls._instance is not None:
            return cls._instance
        config = dict(_DEFAULT_CONFIG)
        if _CONFIG_PATH.exists():
            try:
                user_cfg = json.loads(_CONFIG_PATH.read_text())
                # Deep-merge backends block
                for key, val in user_cfg.items():
                    if key == "backends" and isinstance(val, dict):
                        merged = dict(config.get("backends", {}))
                        merged.update(val)
                        config["backends"] = merged
                    else:
                        config[key] = val
                logger.debug("SandboxManager: loaded config from %s", _CONFIG_PATH)
            except Exception as e:
                logger.warning("SandboxManager: failed to load %s: %s — using defaults", _CONFIG_PATH, e)
        cls._instance = cls(config)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Clear singleton — for tests."""
        cls._instance = None

    # ------------------------------------------------------------------
    # Auto-provision decision
    # ------------------------------------------------------------------

    def should_provision(self, task: Any) -> bool:
        """Return True if this task should automatically get a sandbox."""
        import re
        rules = self._config.get("auto_provision", {})
        cfg = getattr(task, "config", None) or {}

        if rules.get("on_explicit_flag") and cfg.get("sandbox_required"):
            return True

        if rules.get("on_git_url"):
            # Check config key first, then scan goal text for git URLs
            if cfg.get("git_url"):
                return True
            goal = cfg.get("goal", "") or getattr(task, "description", "") or ""
            if re.search(r"(git@|https?://github\.com|https?://gitlab\.com|https?://bitbucket\.org)\S+", goal):
                return True

        task_type = getattr(task, "type", None) or cfg.get("type", "")
        if task_type in (rules.get("on_task_type") or []):
            return True

        return False

    # ------------------------------------------------------------------
    # Acquire / release
    # ------------------------------------------------------------------

    async def acquire(
        self,
        task_id: str,
        git_url: Optional[str] = None,
        working_dir: Optional[str] = None,
        role_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        environment: Optional[str] = None,
        backend_override: Optional[str] = None,
    ) -> SandboxHandle:
        """Provision or resume a sandbox for task_id.

        1. Check session store — if an existing handle is paused, resume it.
        2. Otherwise pick backend and call backend.start().
        3. If git_url provided, clone into /workspace/repo inside the sandbox.
        4. Set _cv_sandbox_handle so tools route through this sandbox.
        """
        # 1. Check for existing paused session
        existing = load_handle(task_id)
        if existing and existing.state in ("paused", "running") and existing.sandbox_id:
            backend = self._get_backend(existing.backend)
            health = backend.health_check(existing)
            if health.get("status") in ("ok",):
                if existing.state == "paused":
                    handle = backend.resume(existing)
                    logger.info("SandboxManager.acquire: resumed %s sandbox for %s",
                                handle.backend, task_id)
                else:
                    handle = existing
                    logger.info("SandboxManager.acquire: reusing running %s sandbox for %s",
                                handle.backend, task_id)
                return handle
            else:
                # Stale handle — clean up and start fresh
                logger.info("SandboxManager.acquire: stale handle for %s (%s), starting fresh",
                            task_id, health.get("status"))
                try:
                    backend.kill(existing)
                except Exception:
                    pass
                delete_handle(task_id)

        # 2. Pick backend
        backend_name = backend_override or self._config.get("default_backend", "docker")
        backend_cfg = self._config.get("backends", {}).get(backend_name, {})
        backend = self._get_backend(backend_name, backend_cfg)

        handle = backend.start(
            task_id=task_id,
            working_dir=working_dir or "",
            role_id=role_id,
            parent_task_id=parent_task_id,
            environment=environment,
        )
        logger.info("SandboxManager.acquire: started %s sandbox for %s (id=%s)",
                    backend_name, task_id, handle.sandbox_id)

        # 3. Clone git repo if requested
        if git_url:
            try:
                clone_dir = "/workspace/repo"
                clone_result = await self.exec(
                    handle,
                    f"git clone {git_url} {clone_dir}",
                    timeout=180,
                )
                if clone_result["success"]:
                    handle.working_dir = clone_dir
                    store_handle(handle)
                    logger.info("SandboxManager.acquire: cloned %s → %s", git_url, clone_dir)
                else:
                    logger.warning("SandboxManager.acquire: git clone failed: %s",
                                   clone_result.get("stderr", ""))
            except Exception as e:
                logger.warning("SandboxManager.acquire: git clone error: %s", e)

        return handle

    async def release(
        self,
        handle: SandboxHandle,
        mode: Literal["kill", "pause"] = "pause",
    ) -> None:
        """Release sandbox after task completion.

        mode="pause": freeze container, keep handle in session store (re-attachable)
        mode="kill":  destroy container, delete handle
        Default is pause so the user can inspect what the agent did.
        """
        try:
            backend = self._get_backend(handle.backend)
            if mode == "kill":
                backend.kill(handle)
                logger.info("SandboxManager.release: killed %s sandbox for %s",
                            handle.backend, handle.task_id)
            else:
                backend.pause(handle)
                logger.info("SandboxManager.release: paused %s sandbox for %s",
                            handle.backend, handle.task_id)
        except Exception as e:
            logger.warning("SandboxManager.release: error releasing %s: %s", handle.task_id, e)

    async def kill_all_for_task(self, task_id: str) -> None:
        """Force-kill all sandboxes associated with task_id."""
        handle = load_handle(task_id)
        if handle:
            await self.release(handle, mode="kill")

    # ------------------------------------------------------------------
    # Tool routing — called by capability_registry when handle is active
    # ------------------------------------------------------------------

    async def exec(
        self,
        handle: SandboxHandle,
        command: str,
        timeout: int = 60,
        workdir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a shell command inside the sandbox."""
        backend = self._get_backend(handle.backend)
        return backend.exec(handle, command, timeout=timeout, workdir=workdir)

    async def read_file(self, handle: SandboxHandle, path: str) -> str:
        """Read a file from inside the sandbox."""
        backend = self._get_backend(handle.backend)
        return backend.read_file(handle, path)

    async def write_file(self, handle: SandboxHandle, path: str, content: str) -> None:
        """Write content to a file inside the sandbox."""
        backend = self._get_backend(handle.backend)
        backend.write_file(handle, path, content)

    async def list_files(self, handle: SandboxHandle, path: str) -> List[str]:
        """List directory contents inside the sandbox."""
        backend = self._get_backend(handle.backend)
        return backend.list_files(handle, path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_backend(self, name: str, config: Optional[Dict[str, Any]] = None):
        from app.scheduler.sandbox.registry import SandboxRegistry
        return SandboxRegistry.create(name, config or {})
