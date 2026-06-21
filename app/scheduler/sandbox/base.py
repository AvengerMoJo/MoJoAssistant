"""SandboxBackend abstract interface.

A SandboxBackend owns the lifecycle of an OpenCode coding session and the
underlying isolation mechanism (CubeSandbox microVM, host process, docker
container, etc.). All backends expose the same interface so the handler can
pick one via task.config["sandbox_backend"] = "cube" | "host" | "docker".

Persistence: backends MAY keep a session alive across handler invocations.
CubeSandboxBackend, for example, pauses (not kills) the microVM when a
task completes, so the user can later re-attach to see what OpenCode
did or continue debugging. The session_store records task_id -> state.
"""

from __future__ import annotations

import abc
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Handle / State
# ----------------------------------------------------------------------


@dataclass
class SandboxHandle:
    """Concrete reference to a running (or paused) sandbox session."""

    task_id: str
    backend: str
    sandbox_id: Optional[str] = None  # microVM/sandbox/container ID
    url: Optional[str] = None  # OpenCode HTTP URL inside the sandbox
    state: str = "pending"  # pending | running | paused | completed | failed | killed
    working_dir: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    log_path: Optional[str] = None  # for debug/learn — points at the backend's log file

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SandboxHandle":
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


# ----------------------------------------------------------------------
# ABC
# ----------------------------------------------------------------------


class SandboxBackend(abc.ABC):
    """Abstract interface every sandbox backend must implement."""

    name: str = "abstract"

    @abc.abstractmethod
    def start(self, task_id: str, working_dir: str, **kwargs: Any) -> SandboxHandle:
        """Boot a sandbox for the given task. Returns a handle.

        If the same task_id already has a paused handle in the session
        store, this should RESUME it (not create a new one) so the
        session's history is preserved.
        """

    @abc.abstractmethod
    def get_opencode_url(self, handle: SandboxHandle) -> str:
        """Return the URL the handler / client should use to talk to OpenCode."""

    @abc.abstractmethod
    def pause(self, handle: SandboxHandle) -> SandboxHandle:
        """Pause the sandbox. State preserved, resources freed."""

    @abc.abstractmethod
    def resume(self, handle: SandboxHandle) -> SandboxHandle:
        """Resume a paused sandbox."""

    @abc.abstractmethod
    def kill(self, handle: SandboxHandle) -> None:
        """Tear down. Frees all resources, deletes handle from store."""

    @abc.abstractmethod
    def health_check(self, handle: SandboxHandle) -> Dict[str, Any]:
        """Return {status: ok|error|stopped, ...}."""

    @abc.abstractmethod
    def get_log_path(self, handle: SandboxHandle) -> Optional[Path]:
        """Path to a log file the user can read to see what OpenCode did.

        For CubeSandbox: pulls from cube-proxy/cube-api access log + the
        microVM's session JSON. For host: points at the agent.log file.
        """


# ----------------------------------------------------------------------
# Session store (persistence across handler invocations)
# ----------------------------------------------------------------------


SESSION_STORE_PATH = Path(
    os.getenv("SANDBOX_SESSION_STORE", str(Path.home() / ".memory" / "sandbox_sessions.json"))
)


def _load_store() -> Dict[str, Dict[str, Any]]:
    if not SESSION_STORE_PATH.exists():
        return {}
    try:
        return json.loads(SESSION_STORE_PATH.read_text())
    except Exception as e:
        logger.warning("Failed to load session store at %s: %s", SESSION_STORE_PATH, e)
        return {}


def _save_store(store: Dict[str, Dict[str, Any]]) -> None:
    SESSION_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SESSION_STORE_PATH.with_suffix(SESSION_STORE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(store, indent=2, default=str))
    tmp.replace(SESSION_STORE_PATH)


def store_handle(handle: SandboxHandle) -> None:
    """Persist a handle to disk so we can re-attach later."""
    store = _load_store()
    handle.updated_at = time.time()
    store[handle.task_id] = handle.to_dict()
    _save_store(store)


def load_handle(task_id: str) -> Optional[SandboxHandle]:
    """Load a previously-persisted handle by task_id, or None."""
    store = _load_store()
    d = store.get(task_id)
    if not d:
        return None
    return SandboxHandle.from_dict(d)


def delete_handle(task_id: str) -> None:
    store = _load_store()
    if task_id in store:
        del store[task_id]
        _save_store(store)


def list_handles(backend: Optional[str] = None) -> List[SandboxHandle]:
    """List all live handles, optionally filtered by backend name."""
    store = _load_store()
    out = []
    for d in store.values():
        h = SandboxHandle.from_dict(d)
        if backend is None or h.backend == backend:
            out.append(h)
    return out
