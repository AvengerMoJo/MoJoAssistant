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

from app.scheduler.sandbox.base import (
    SandboxHandle, delete_handle, load_handle, store_handle,
    find_by_name, prune_stale_handles,
)
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
        prepare_hook: Optional[str] = None,
        hook_params: Optional[Dict[str, Any]] = None,
    ) -> SandboxHandle:
        """Provision or resume a sandbox for task_id.

        1. Check session store — if an existing handle is paused, resume it.
        2. Otherwise pick backend and call backend.start().
        3. If git_url provided, run the pre_prepare hook (default:
           "git_clone_default", a bare `git clone` — see sandbox/hooks.py for
           alternatives like "git_clone_public_https" that avoid needing SSH
           credentials at all for public repos). prepare_hook lets the caller
           pick a different strategy per project instead of one hardcoded path.
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

        # 3. Prepare repo via the pre_prepare hook, if requested
        if git_url:
            from app.scheduler.sandbox.hooks import HookContext, run_hook
            hook_name = prepare_hook or "git_clone_default"

            async def _exec_fn(command: str, timeout_s: int) -> Dict[str, Any]:
                return await self.exec(handle, command, timeout=timeout_s)

            ctx = HookContext(
                point="pre_prepare", git_url=git_url,
                exec_fn=_exec_fn, params=hook_params or {},
            )
            result = await run_hook(hook_name, ctx)
            if result.success:
                handle.working_dir = result.working_dir or handle.working_dir
                store_handle(handle)
                logger.info("SandboxManager.acquire: hook '%s' succeeded: %s", hook_name, result.message)
            else:
                logger.warning("SandboxManager.acquire: hook '%s' failed: %s", hook_name, result.message)

        return handle

    async def release(
        self,
        handle: SandboxHandle,
        mode: Literal["kill", "pause"] = "pause",
        post_task_hook: Optional[str] = None,
        hook_params: Optional[Dict[str, Any]] = None,
        task_result: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Release sandbox after task completion.

        mode="pause": freeze container, keep handle in session store (re-attachable)
        mode="kill":  destroy container, delete handle
        Default is pause so the user can inspect what the agent did.

        post_task_hook (optional): run a named hook (see sandbox/hooks.py)
        BEFORE backend teardown — e.g. upload artifacts, scrub injected
        credentials. Runs best-effort; a hook failure logs a warning but
        never blocks teardown.
        """
        if post_task_hook:
            try:
                from app.scheduler.sandbox.hooks import HookContext, run_hook

                async def _exec_fn(command: str, timeout_s: int) -> Dict[str, Any]:
                    return await self.exec(handle, command, timeout=timeout_s)

                ctx = HookContext(
                    point="post_task", working_dir=handle.working_dir, repo=handle.name,
                    exec_fn=_exec_fn, params=hook_params or {}, task_result=task_result,
                )
                result = await run_hook(post_task_hook, ctx)
                if not result.success:
                    logger.warning("SandboxManager.release: post_task hook '%s' failed: %s",
                                   post_task_hook, result.message)
            except Exception as e:
                logger.warning("SandboxManager.release: post_task hook error (non-fatal): %s", e)

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

    async def acquire_by_name(
        self,
        name: str,
        task_id: str,
        git_url: Optional[str] = None,
        working_dir: Optional[str] = None,
        role_id: Optional[str] = None,
        backend_override: Optional[str] = None,
        prepare_hook: Optional[str] = None,
        hook_params: Optional[Dict[str, Any]] = None,
    ) -> SandboxHandle:
        """Acquire a named sandbox — resume if it exists, provision fresh if not.

        Named sandboxes are long-lived pools keyed by a human name rather than
        task_id. Multiple tasks share the same environment; each task just
        git-checkouts a different repo or works in a different directory.

        The handle is stored under the original task_id that created it, but
        the name field is set so find_by_name() can locate it in future calls.

        prepare_hook selects how git_url gets checked out (see sandbox/hooks.py)
        — defaults to "git_clone_default" (bare `git clone`, whatever auth is
        already available) for backward compatibility. Pass e.g.
        "git_clone_public_https" for a public repo to avoid needing SSH auth.
        """
        existing = find_by_name(name)
        if existing and existing.sandbox_id:
            backend = self._get_backend(existing.backend)
            health = backend.health_check(existing)
            if health.get("status") == "ok":
                if existing.state == "paused":
                    handle = backend.resume(existing)
                    logger.info("SandboxManager.acquire_by_name: resumed named sandbox '%s' (task=%s)",
                                name, existing.task_id)
                else:
                    handle = existing
                    logger.info("SandboxManager.acquire_by_name: reusing running named sandbox '%s'",
                                name)
                if git_url:
                    from app.scheduler.sandbox.hooks import HookContext, run_hook
                    hook_name = prepare_hook or "git_clone_default"

                    async def _exec_fn(command: str, timeout_s: int) -> Dict[str, Any]:
                        return await self.exec(handle, command, timeout=timeout_s)

                    ctx = HookContext(
                        point="pre_prepare", git_url=git_url, repo=name,
                        exec_fn=_exec_fn,
                        params={"clone_dir": f"/workspace/{name}", **(hook_params or {})},
                    )
                    result = await run_hook(hook_name, ctx)
                    if result.success:
                        handle.working_dir = result.working_dir or handle.working_dir
                        store_handle(handle)
                    else:
                        logger.warning("acquire_by_name: hook '%s' failed: %s", hook_name, result.message)
                return handle
            else:
                logger.info("SandboxManager.acquire_by_name: stale named sandbox '%s', reprovisioning", name)
                try:
                    backend.kill(existing)
                except Exception:
                    pass
                delete_handle(existing.task_id)

        # Provision fresh — use task_id as the store key, set name for future lookups
        handle = await self.acquire(
            task_id=task_id,
            git_url=git_url,
            working_dir=working_dir,
            role_id=role_id,
            backend_override=backend_override,
            prepare_hook=prepare_hook,
            hook_params={"clone_dir": f"/workspace/{name}", **(hook_params or {})},
        )
        handle.name = name
        store_handle(handle)
        logger.info("SandboxManager.acquire_by_name: created named sandbox '%s' (task=%s id=%s)",
                    name, task_id, handle.sandbox_id)
        return handle

    def prune_stale(self, max_age_hours: float = 48.0) -> List[str]:
        """Remove stale anonymous handles from the session store.

        Named sandboxes are never pruned automatically. Unnamed handles in
        completed/failed/killed state are always removed. Unnamed paused/pending
        handles older than max_age_hours are removed.
        Returns list of pruned task_ids.
        """
        pruned = prune_stale_handles(max_age_hours=max_age_hours)
        if pruned:
            logger.info("SandboxManager.prune_stale: pruned %d handle(s)", len(pruned))
        return pruned

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
