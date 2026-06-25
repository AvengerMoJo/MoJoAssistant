"""Agentic tool wrappers around Docker sandbox operations.

These functions are exposed to agentic LLMs (Popo, Rebecca, etc.) via
the ``python`` executor in config/dynamic_tools.json. Each tool delegates
to the Docker CLI via subprocess — no Python Docker SDK dependency required.

The pattern mirrors cubesandbox_tools.py: a per-session in-process map
of name -> container_id, with create/exec/list/destroy/upload operations.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Per-session cache: name -> {container_id, port, last_used_ts}
_CONTAINERS: Dict[str, Dict[str, Any]] = {}

# Port range for host mapping
_PORT_START = 4600
_PORT_END = 4699
_allocated_ports: set[int] = set()

DEFAULT_IMAGE = os.getenv("DOCKER_SANDBOX_IMAGE", "opencode-sandbox:latest")


def _next_port() -> int:
    for port in range(_PORT_START, _PORT_END + 1):
        if port not in _allocated_ports:
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


def _run_docker(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["docker"] + args, capture_output=True, text=True, timeout=timeout)


# -------------------------------------------------------------------
#  docker_sandbox_create
# -------------------------------------------------------------------


def docker_sandbox_create(args: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new Docker container and register it under ``name``.

    Required: ``name``. Optional: ``image`` (default: DOCKER_SANDBOX_IMAGE
    env or opencode-sandbox:latest), ``memory`` (default: 2g), ``cpus``
    (default: 2), ``timeout`` (seconds, for future use).

    The container runs the image's default CMD (expected to be OpenCode
    listening on port 4173). Returns the container ID and mapped host URL.
    """
    name = (args.get("name") or "").strip()
    if not name:
        return {"success": False, "error": "name is required"}

    if name in _CONTAINERS:
        entry = _CONTAINERS[name]
        info = _inspect(entry["container_id"])
        if info and info.get("State", {}).get("Running"):
            return {
                "success": True,
                "name": name,
                "container_id": entry["container_id"],
                "url": f"http://127.0.0.1:{entry['port']}",
                "reused": True,
            }

    image = args.get("image") or DEFAULT_IMAGE
    memory = args.get("memory", "2g")
    cpus = args.get("cpus", "2")

    try:
        port = _next_port()
    except RuntimeError as e:
        return {"success": False, "error": str(e)}

    container_name = f"mojo-agentic-{name}-{int(time.time()) % 10000}"
    cmd = [
        "docker", "run", "-d",
        "--name", container_name,
        f"--memory={memory}",
        f"--cpus={cpus}",
        "-p", f"{port}:4173",
    ]
    cmd.append(image)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        _release_port(port)
        return {"success": False, "error": "docker run timed out"}

    if result.returncode != 0:
        _release_port(port)
        return {"success": False, "error": f"docker run failed: {result.stderr.strip()}"}

    container_id = result.stdout.strip()
    _CONTAINERS[name] = {
        "container_id": container_id,
        "port": port,
        "last_used_ts": time.time(),
    }

    return {
        "success": True,
        "name": name,
        "container_id": container_id,
        "url": f"http://127.0.0.1:{port}",
        "image": image,
    }


# -------------------------------------------------------------------
#  docker_sandbox_exec
# -------------------------------------------------------------------


def docker_sandbox_exec(args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a shell command inside the Docker container registered as ``name``.

    Required: ``name``, ``command``. Optional: ``timeout`` (seconds,
    default 60). Returns stdout, stderr, and exit_code.
    """
    name = (args.get("name") or "").strip()
    command = args.get("command")
    timeout = int(args.get("timeout", 60))

    if not name or not command:
        return {"success": False, "error": "name and command are required"}

    entry = _CONTAINERS.get(name)
    if not entry:
        return {"success": False, "error": f"No container for name='{name}'. Call docker_sandbox_create first."}

    container_id = entry["container_id"]
    try:
        result = _run_docker(
            ["exec", container_id, "sh", "-c", command],
            timeout=timeout,
        )
        entry["last_used_ts"] = time.time()
        return {
            "success": True,
            "name": name,
            "container_id": container_id,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}"}


# -------------------------------------------------------------------
#  docker_sandbox_list
# -------------------------------------------------------------------


def docker_sandbox_list(args: Dict[str, Any]) -> Dict[str, Any]:
    """List all Docker containers the agentic process has handles for."""
    out = []
    for name, entry in _CONTAINERS.items():
        info = _inspect(entry["container_id"])
        running = info.get("State", {}).get("Running", False) if info else False
        out.append({
            "name": name,
            "container_id": entry["container_id"],
            "port": entry["port"],
            "is_running": running,
            "last_used_ts": entry["last_used_ts"],
        })
    return {"success": True, "count": len(out), "sandboxes": out}


# -------------------------------------------------------------------
#  docker_sandbox_destroy
# -------------------------------------------------------------------


def docker_sandbox_destroy(args: Dict[str, Any]) -> Dict[str, Any]:
    """Tear down the Docker container registered as ``name``.

    Idempotent: destroying a name that doesn't exist returns success.
    """
    name = (args.get("name") or "").strip()
    if not name:
        return {"success": False, "error": "name is required"}

    entry = _CONTAINERS.pop(name, None)
    if entry is None:
        return {"success": True, "name": name, "already_destroyed": True}

    container_id = entry["container_id"]
    _run_docker(["rm", "-f", container_id])
    _release_port(entry["port"])
    return {"success": True, "name": name, "destroyed": True, "container_id": container_id}


# -------------------------------------------------------------------
#  docker_sandbox_upload
# -------------------------------------------------------------------


def docker_sandbox_upload(args: Dict[str, Any]) -> Dict[str, Any]:
    """Upload a host directory into the Docker container.

    Required: ``name``, ``local_path``. Optional: ``remote_path``
    (default: /workspace).
    """
    name = (args.get("name") or "").strip()
    local_path = (args.get("local_path") or "").strip()
    remote_path = args.get("remote_path", "/workspace")

    if not name or not local_path:
        return {"success": False, "error": "name and local_path are required"}

    entry = _CONTAINERS.get(name)
    if not entry:
        return {"success": False, "error": f"No container for name='{name}'"}

    p = Path(local_path).expanduser()
    if not p.is_dir():
        return {"success": False, "error": f"local_path '{p}' is not a directory"}

    container_id = entry["container_id"]
    try:
        result = _run_docker(
            ["cp", f"{p}/.", f"{container_id}:{remote_path}"],
            timeout=120,
        )
        if result.returncode != 0:
            return {"success": False, "error": f"docker cp failed: {result.stderr.strip()}"}
        entry["last_used_ts"] = time.time()
        return {
            "success": True,
            "name": name,
            "container_id": container_id,
            "uploaded": str(p),
            "remote_path": remote_path,
        }
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}"}


# -------------------------------------------------------------------
#  helpers
# -------------------------------------------------------------------


def _inspect(container_id: str) -> Optional[Dict[str, Any]]:
    result = _run_docker(["inspect", container_id])
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)[0]
    except (json.JSONDecodeError, IndexError):
        return None
