"""SandboxRegistry — pick an isolation backend by name.

Usage in the handler:
    backend = SandboxRegistry.create(
        name=cfg.get("sandbox_backend", "host"),
        config={"template_id": cfg.get("sandbox_template")},
    )
    handle = backend.start(task_id, working_dir)
    url = backend.get_opencode_url(handle)

Available backends:
  - "host"  : OpenCodePerTaskBackend (one host process per task)
  - "cube"  : CubeSandboxBackend (one KVM microVM per task, persisted)
  - "docker": DockerSandboxBackend (one docker container per task)

Adding a new backend = register in _BACKENDS below.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Type

from app.scheduler.sandbox.base import SandboxBackend

logger = logging.getLogger(__name__)


_BACKENDS: Dict[str, Type[SandboxBackend]] = {}


def register_backend(name: str):
    """Decorator that registers a backend class in the registry."""
    def deco(cls: Type[SandboxBackend]) -> Type[SandboxBackend]:
        if name in _BACKENDS:
            logger.warning("Sandbox backend %r already registered; overwriting", name)
        _BACKENDS[name] = cls
        cls.name = name
        return cls
    return deco


def list_backends() -> list[str]:
    """Return the names of all registered backends."""
    return sorted(_BACKENDS.keys())


# Register built-in backends. Imports are inside the function so a backend
# failing to import (missing optional dep) doesn't break the others.
def _register_builtins() -> None:
    if "host" not in _BACKENDS:
        try:
            from app.scheduler.sandbox.host_backend import HostOpenCodeBackend
            register_backend("host")(HostOpenCodeBackend)
        except Exception as e:
            logger.warning("Failed to register 'host' backend: %s", e)

    if "cube" not in _BACKENDS:
        try:
            from app.scheduler.sandbox.cube_backend import CubeSandboxBackend
            register_backend("cube")(CubeSandboxBackend)
        except Exception as e:
            logger.warning("Failed to register 'cube' backend: %s", e)

    if "docker" not in _BACKENDS:
        try:
            from app.scheduler.sandbox.docker_backend import DockerSandboxBackend
            register_backend("docker")(DockerSandboxBackend)
        except Exception as e:
            logger.warning("Failed to register 'docker' backend: %s", e)


_register_builtins()


class SandboxRegistry:
    """Factory + cache for sandbox backends."""

    _instances: Dict[str, SandboxBackend] = {}

    @classmethod
    def create(cls, name: str, config: Dict[str, Any] = None) -> SandboxBackend:
        """Get or create a backend by name. Cached per name (singleton per process).

        config keys are passed to the backend's __init__ as keyword args.
        Backends that don't accept them should ignore extras (use **kwargs).
        """
        if name not in _BACKENDS:
            available = list_backends()
            raise ValueError(
                f"Unknown sandbox backend {name!r}. "
                f"Available: {available}. "
                f"Set task.config['sandbox_backend'] = {available[0]!r} or add a custom backend."
            )
        if name in cls._instances:
            return cls._instances[name]

        backend_cls = _BACKENDS[name]
        config = config or {}
        try:
            instance = backend_cls(**config)
        except TypeError as e:
            # Backend doesn't accept the config — try without
            logger.debug("Backend %s rejected config %r: %s; trying no-arg", name, config, e)
            instance = backend_cls()
        cls._instances[name] = instance
        logger.info("SandboxRegistry: created %r backend (config=%s)", name, config)
        return instance

    @classmethod
    def reset(cls) -> None:
        """Forget cached backends. Mostly for tests."""
        cls._instances.clear()

    @classmethod
    def available(cls) -> list[str]:
        """List all registered backend names."""
        return list_backends()
