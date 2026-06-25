"""Sandbox package — pluggable OpenCode isolation backends.

Each backend exposes the same SandboxBackend interface so the handler
can pick one via task.config["sandbox_backend"]:

    backend = SandboxRegistry.create(
        name=cfg.get("sandbox_backend", "host"),
        config={"template_id": cfg.get("sandbox_template")},
    )

Available backends today:
  - "host"  : HostOpenCodeBackend (one host process per task)
  - "cube"  : CubeSandboxBackend (KVM microVM per task, persisted across restarts)
  - "docker": DockerSandboxBackend (one Docker container per task, pause/resume via cgroup freezer)

Session persistence is handled by `app.scheduler.sandbox.base.session_store`
which lives at ~/.memory/sandbox_sessions.json. Paused sessions survive
handler restarts; use the MCP `list_sessions` / `attach_session` tools to
re-attach from the dashboard.
"""

from app.scheduler.sandbox.base import (
    SandboxBackend,
    SandboxHandle,
    delete_handle,
    find_by_sandbox_id,
    list_handles,
    list_orphan_sandbox_ids,
    load_handle,
    store_handle,
)
from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient, CubeSandboxError
from app.scheduler.sandbox.opencode_client import OpenCodeClient
from app.scheduler.sandbox.registry import SandboxRegistry, list_backends

# Import backends so they register themselves via the @register_backend decorator.
from app.scheduler.sandbox import host_backend  # noqa: F401
from app.scheduler.sandbox import cube_backend  # noqa: F401
from app.scheduler.sandbox import docker_backend  # noqa: F401

__all__ = [
    "CubeSandboxClient",
    "CubeSandboxError",
    "OpenCodeClient",
    "SandboxBackend",
    "SandboxHandle",
    "SandboxRegistry",
    "delete_handle",
    "find_by_sandbox_id",
    "list_backends",
    "list_handles",
    "list_orphan_sandbox_ids",
    "load_handle",
    "store_handle",
]
