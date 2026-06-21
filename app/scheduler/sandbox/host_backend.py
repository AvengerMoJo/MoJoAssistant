"""HostOpenCode backend — wraps OpenCodePerTaskBackend with session persistence.

Each task gets its own host `opencode serve` process on a unique port.
The process's PID, port, password, and log path are recorded in the
session_store so a re-attached handler can resume talking to the same
OpenCode instance (without restarting it).

Pause/resume map to POSIX SIGSTOP/SIGCONT on the process group.
"""

from __future__ import annotations

import logging
import os
import signal
from pathlib import Path
from typing import Any, Dict, Optional

from app.scheduler.sandbox.base import (
    SandboxBackend,
    SandboxHandle,
    delete_handle,
    load_handle,
    store_handle,
)
from app.scheduler.sandbox.registry import register_backend

logger = logging.getLogger(__name__)


@register_backend("host")
class HostOpenCodeBackend(SandboxBackend):
    """One host-process OpenCode per task."""

    name = "host"  # mirrored by register_backend decorator at import time

    def __init__(self) -> None:
        from app.scheduler.sandbox.per_task.opencode_per_task import (
            OpenCodePerTaskBackend,
            TaskInstance,
        )
        self._backend = OpenCodePerTaskBackend()
        self._TaskInstance = TaskInstance

    # ------------------------------------------------------------------
    #  SandboxBackend API                                                #
    # ------------------------------------------------------------------

    def start(self, task_id: str, working_dir: str, **kwargs: Any) -> SandboxHandle:
        # Resume an existing persisted instance if the PID is still alive
        existing = load_handle(task_id)
        if existing and existing.state in ("running", "paused"):
            inst = self._backend._instances.get(task_id)
            if inst is not None and _pid_alive(inst.pid):
                url = f"http://127.0.0.1:{inst.port}"
                existing.url = url
                existing.state = "running" if existing.state == "paused" else existing.state
                store_handle(existing)
                logger.info("HostOpenCodeBackend.start: re-attached %s pid=%s port=%s",
                            task_id, inst.pid, inst.port)
                return existing
            # Process died — clean up and start fresh
            logger.info("HostOpenCodeBackend.start: stale handle for %s, restarting", task_id)
            self._backend._instances.pop(task_id, None)
            delete_handle(task_id)

        inst = self._backend.spawn(task_id, working_dir)
        url = f"http://127.0.0.1:{inst.port}"
        handle = SandboxHandle(
            task_id=task_id,
            backend=self.name,
            sandbox_id=str(inst.pid),
            url=url,
            state="running",
            working_dir=working_dir,
            log_path=inst.log_path,
        )
        store_handle(handle)
        return handle

    def get_opencode_url(self, handle: SandboxHandle) -> str:
        return handle.url or ""

    def pause(self, handle: SandboxHandle) -> SandboxHandle:
        if not handle.sandbox_id:
            raise RuntimeError(f"Host handle {handle.task_id} has no pid")
        pid = int(handle.sandbox_id)
        try:
            os.killpg(pid, signal.SIGSTOP)
            handle.state = "paused"
            store_handle(handle)
            logger.info("HostOpenCodeBackend.pause: SIGSTOP pid=%s task=%s", pid, handle.task_id)
        except ProcessLookupError:
            logger.warning("pause: pid=%s already dead", pid)
            handle.state = "killed"
            delete_handle(handle.task_id)
        return handle

    def resume(self, handle: SandboxHandle) -> SandboxHandle:
        if not handle.sandbox_id:
            raise RuntimeError(f"Host handle {handle.task_id} has no pid")
        pid = int(handle.sandbox_id)
        try:
            os.killpg(pid, signal.SIGCONT)
            handle.state = "running"
            store_handle(handle)
            logger.info("HostOpenCodeBackend.resume: SIGCONT pid=%s task=%s", pid, handle.task_id)
        except ProcessLookupError:
            raise RuntimeError(f"Pid {pid} for task {handle.task_id} is gone — cannot resume")
        return handle

    def kill(self, handle: SandboxHandle) -> None:
        self._backend.kill(handle.task_id)
        delete_handle(handle.task_id)

    def health_check(self, handle: SandboxHandle) -> Dict[str, Any]:
        if not handle.url:
            return {"status": "stopped", "state": handle.state}
        try:
            import httpx
            r = httpx.get(f"{handle.url}/api/health", timeout=5)
            return {
                "status": "ok" if r.status_code == 200 else "error",
                "url": handle.url,
                "http_status": r.status_code,
                "state": handle.state,
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "state": handle.state}

    def get_log_path(self, handle: SandboxHandle) -> Optional[Path]:
        return Path(handle.log_path) if handle.log_path else None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
