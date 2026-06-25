"""Docker sandbox backend — one Docker container per task.

Each task gets its own Docker container running OpenCode. The container's
ID, port, and log path are recorded in the session_store so a re-attached
handler can resume talking to the same OpenCode instance.

Pause/resume map to docker pause/unpause (cgroup freezer, no SIGSTOP).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
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

# Default image — users can override via DOCKER_SANDBOX_IMAGE env var.
DEFAULT_IMAGE = "opencode-sandbox:latest"
# Port range for host port mapping (container always uses 4173).
_PORT_START = 4500
_PORT_END = 4599
_allocated_ports: set[int] = set()


def _next_port() -> int:
    """Find the next available host port in the 4500-4599 range."""
    for port in range(_PORT_START, _PORT_END + 1):
        if port not in _allocated_ports:
            # Double-check the port is actually free on the host.
            result = subprocess.run(
                ["ss", "-tlnH", f"sport = :{port}"],
                capture_output=True, text=True,
            )
            if not result.stdout.strip():
                _allocated_ports.add(port)
                return port
    raise RuntimeError(f"No free ports in range {_PORT_START}-{_PORT_END}")


def _release_port(port: int) -> None:
    _allocated_ports.discard(port)


@register_backend("docker")
class DockerSandboxBackend(SandboxBackend):
    """One Docker container per task, with session persistence."""

    name = "docker"

    def __init__(self, image: Optional[str] = None) -> None:
        self._image = image or os.getenv("DOCKER_SANDBOX_IMAGE", DEFAULT_IMAGE)
        self._containers: Dict[str, str] = {}  # task_id -> container_id

    # ------------------------------------------------------------------
    #  helpers                                                          #
    # ------------------------------------------------------------------

    def _session_log_path(self, task_id: str, container_id: Optional[str]) -> Path:
        base = Path.home() / ".memory" / "sandbox_logs"
        base.mkdir(parents=True, exist_ok=True)
        suffix = container_id or task_id
        return base / f"docker-{task_id}-{suffix[:12]}.log"

    def _run_docker(self, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
        cmd = ["docker"] + args
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def _inspect_container(self, container_id: str) -> Optional[Dict[str, Any]]:
        result = self._run_docker(["inspect", container_id])
        if result.returncode != 0:
            return None
        try:
            return json.loads(result.stdout)[0]
        except (json.JSONDecodeError, IndexError):
            return None

    # ------------------------------------------------------------------
    #  SandboxBackend API                                                #
    # ------------------------------------------------------------------

    def start(self, task_id: str, working_dir: str, **kwargs: Any) -> SandboxHandle:
        # Resume existing paused session
        existing = load_handle(task_id)
        if existing and existing.state == "paused" and existing.sandbox_id:
            container_info = self._inspect_container(existing.sandbox_id)
            if container_info and container_info.get("State", {}).get("Paused"):
                logger.info("DockerSandboxBackend.start: resuming paused container %s for %s",
                            existing.sandbox_id, task_id)
                return self.resume(existing)
            elif container_info and container_info.get("State", {}).get("Running"):
                logger.info("DockerSandboxBackend.start: container %s already running for %s",
                            existing.sandbox_id, task_id)
                existing.state = "running"
                store_handle(existing)
                return existing

        # Start fresh container
        port = _next_port()
        container_name = f"mojo-{task_id[:8]}-{int(time.time()) % 10000}"

        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--memory=2g",
            "--cpus=2",
            "-p", f"{port}:4173",
            "-e", f"TASK_ID={task_id}",
        ]

        # Mount working_dir into the container if it exists
        if working_dir and Path(working_dir).is_dir():
            cmd += ["-v", f"{working_dir}:/workspace:rw"]

        cmd.append(self._image)

        logger.info("DockerSandboxBackend.start: running %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            _release_port(port)
            raise RuntimeError(f"docker run failed: {result.stderr.strip()}")

        container_id = result.stdout.strip()
        self._containers[task_id] = container_id

        # Wait for container to be healthy
        url = f"http://127.0.0.1:{port}"
        role_id = kwargs.get("role_id")
        parent_task_id = kwargs.get("parent_task_id")
        environment = kwargs.get("environment")

        handle = SandboxHandle(
            task_id=task_id,
            backend=self.name,
            sandbox_id=container_id,
            url=url,
            state="running",
            working_dir=working_dir,
            log_path=str(self._session_log_path(task_id, container_id)),
            role_id=role_id,
            parent_task_id=parent_task_id,
            environment=environment,
        )
        self._append_log(handle, f"=== start: container={container_id} port={port} url={url} ===\n")
        store_handle(handle)
        logger.info("DockerSandboxBackend.start: container %s running on port %d", container_id[:12], port)
        return handle

    def get_opencode_url(self, handle: SandboxHandle) -> str:
        if not handle.url:
            raise RuntimeError(f"Docker sandbox {handle.task_id} has no URL")
        return handle.url

    def pause(self, handle: SandboxHandle) -> SandboxHandle:
        if not handle.sandbox_id:
            raise RuntimeError(f"Docker handle {handle.task_id} has no container_id")
        result = self._run_docker(["pause", handle.sandbox_id])
        if result.returncode != 0:
            logger.warning("docker pause failed for %s: %s", handle.task_id, result.stderr)
        handle.state = "paused"
        handle.updated_at = time.time()
        self._append_log(handle, f"=== pause at {handle.updated_at} ===\n")
        store_handle(handle)
        logger.info("DockerSandboxBackend.pause: %s paused (container=%s)",
                    handle.task_id, handle.sandbox_id[:12])
        return handle

    def resume(self, handle: SandboxHandle) -> SandboxHandle:
        if not handle.sandbox_id:
            raise RuntimeError(f"Docker handle {handle.task_id} has no container_id")
        result = self._run_docker(["unpause", handle.sandbox_id])
        if result.returncode != 0:
            logger.warning("docker unpause failed for %s: %s", handle.task_id, result.stderr)
        handle.state = "running"
        handle.updated_at = time.time()
        self._append_log(handle, f"=== resume at {handle.updated_at} ===\n")
        store_handle(handle)
        logger.info("DockerSandboxBackend.resume: %s running (container=%s)",
                    handle.task_id, handle.sandbox_id[:12])
        return handle

    def kill(self, handle: SandboxHandle) -> None:
        if handle.sandbox_id:
            result = self._run_docker(["rm", "-f", handle.sandbox_id])
            if result.returncode != 0:
                logger.warning("docker rm failed for %s: %s", handle.task_id, result.stderr)
            # Release the port from the handle URL
            if handle.url:
                try:
                    port = int(handle.url.split(":")[-1])
                    _release_port(port)
                except (ValueError, IndexError):
                    pass
        self._containers.pop(handle.task_id, None)
        delete_handle(handle.task_id)
        logger.info("DockerSandboxBackend.kill: %s removed", handle.task_id)

    def health_check(self, handle: SandboxHandle) -> Dict[str, Any]:
        if not handle.sandbox_id:
            return {"status": "stopped", "state": handle.state}
        info = self._inspect_container(handle.sandbox_id)
        if not info:
            return {"status": "stopped", "state": "missing"}
        state = info.get("State", {})
        running = state.get("Running", False)
        paused = state.get("Paused", False)
        if not running:
            return {"status": "stopped", "state": "exited"}
        if paused:
            return {"status": "ok", "state": "paused"}
        # Check OpenCode health endpoint
        if handle.url:
            try:
                import httpx
                r = httpx.get(f"{handle.url}/api/health", timeout=5)
                return {
                    "status": "ok" if r.status_code == 200 else "error",
                    "url": handle.url,
                    "http_status": r.status_code,
                    "state": "running",
                }
            except Exception as e:
                return {"status": "error", "error": str(e), "state": "running"}
        return {"status": "ok", "state": "running"}

    def get_log_path(self, handle: SandboxHandle) -> Optional[Path]:
        return Path(handle.log_path) if handle.log_path else None

    # ------------------------------------------------------------------
    #  debug helpers                                                    #
    # ------------------------------------------------------------------

    def _append_log(self, handle: SandboxHandle, line: str) -> None:
        if not handle.log_path:
            return
        try:
            with open(handle.log_path, "a") as f:
                f.write(line)
        except Exception as e:
            logger.debug("append log failed: %s", e)
