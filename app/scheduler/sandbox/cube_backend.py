"""CubeSandbox backend — wraps CubeSandboxClient with session persistence.

Each task that uses this backend creates a paused-state microVM that
survives handler restarts and can be re-attached via the dashboard or
the MCP tool. The session_store maps task_id -> SandboxHandle.

Persistence contract:
  - On start(): if session_store has a paused handle for task_id, resume it.
  - On pause(): pause the microVM, store handle.
  - On kill(): kill the microVM, delete from store.
  - The handle includes a log_path pointing at the session JSON the user
    can read to understand what the agent did.
"""

from __future__ import annotations

import logging
import os
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


@register_backend("cube")
class CubeSandboxBackend(SandboxBackend):
    """KVM-isolated microVM per task, with persisted paused state."""

    name = "cube"  # mirrored by register_backend decorator at import time

    def __init__(self, template_id: Optional[str] = None) -> None:
        self._template_id = template_id or os.getenv("CUBE_TEMPLATE_ID", "opencode-sandbox")
        self._clients: Dict[str, Any] = {}  # task_id -> CubeSandboxClient

    # ------------------------------------------------------------------
    #  helpers                                                          #
    # ------------------------------------------------------------------

    def _client_for(self, task_id: str):
        """Return the live CubeSandboxClient for task_id, creating one on first use."""
        if task_id not in self._clients:
            from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient
            self._clients[task_id] = CubeSandboxClient(template_id=self._template_id)
        return self._clients[task_id]

    def _session_log_path(self, task_id: str, sandbox_id: Optional[str]) -> Path:
        base = Path.home() / ".memory" / "sandbox_logs"
        base.mkdir(parents=True, exist_ok=True)
        suffix = sandbox_id or task_id
        return base / f"{task_id}-{suffix}.log"

    # ------------------------------------------------------------------
    #  SandboxBackend API                                                #
    # ------------------------------------------------------------------

    def start(self, task_id: str, working_dir: str, **kwargs: Any) -> SandboxHandle:
        # Resume existing paused session if present
        existing = load_handle(task_id)
        if existing and existing.state == "paused" and existing.sandbox_id:
            logger.info("CubeSandboxBackend.start: resuming paused %s for %s",
                        existing.sandbox_id, task_id)
            return self.resume(existing)

        # Start fresh
        client = self._client_for(task_id)
        sandbox_id = client.start()
        url = client.get_opencode_url()
        handle = SandboxHandle(
            task_id=task_id,
            backend=self.name,
            sandbox_id=sandbox_id,
            url=url,
            state="running",
            working_dir=working_dir,
            log_path=str(self._session_log_path(task_id, sandbox_id)),
        )
        if working_dir and Path(working_dir).is_dir():
            try:
                client.upload_project(working_dir)
            except Exception as e:
                logger.warning("upload_project(%s) failed: %s", working_dir, e)
        self._append_log(handle, f"=== start: sandbox_id={sandbox_id} url={url} ===\n")
        store_handle(handle)
        return handle

    def get_opencode_url(self, handle: SandboxHandle) -> str:
        if not handle.url:
            raise RuntimeError(f"Sandbox {handle.task_id} has no URL")
        return handle.url

    def pause(self, handle: SandboxHandle) -> SandboxHandle:
        client = self._clients.get(handle.task_id)
        if client is not None:
            client.pause()
        handle.state = "paused"
        handle.updated_at = __import__("time").time()
        self._append_log(handle, f"=== pause at {handle.updated_at} ===\n")
        store_handle(handle)
        logger.info("CubeSandboxBackend.pause: %s paused (sandbox_id=%s)",
                    handle.task_id, handle.sandbox_id)
        return handle

    def resume(self, handle: SandboxHandle) -> SandboxHandle:
        # Re-use the existing paused client if we still have it; otherwise
        # we have to rely on cube-proxy re-attaching via the persisted
        # sandbox_id (the microVM image lives on the cubelet host).
        client = self._clients.get(handle.task_id)
        if client is None:
            from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient
            client = CubeSandboxClient(template_id=self._template_id)
            # Mark this client as having a pre-existing sandbox so get_opencode_url
            # doesn't trip on _sandbox=None; set up the minimal fields needed.
            client._sandbox_id = handle.sandbox_id
            client._sandbox = _AttachedSandbox(handle.sandbox_id, handle.url or "")
            self._clients[handle.task_id] = client
        try:
            client.resume()
        except Exception as e:
            logger.warning("client.resume failed for %s (continuing — VM may auto-resume): %s",
                           handle.task_id, e)
        handle.state = "running"
        try:
            handle.url = client.get_opencode_url()
        except Exception:
            # Fall back to stored URL — VM may still be coming back up
            pass
        handle.updated_at = __import__("time").time()
        self._append_log(handle, f"=== resume at {handle.updated_at} ===\n")
        store_handle(handle)
        logger.info("CubeSandboxBackend.resume: %s running again (sandbox_id=%s)",
                    handle.task_id, handle.sandbox_id)
        return handle

    def kill(self, handle: SandboxHandle) -> None:
        client = self._clients.pop(handle.task_id, None)
        if client is not None:
            try:
                client.kill()
            except Exception as e:
                logger.warning("kill(%s) failed: %s", handle.task_id, e)
        delete_handle(handle.task_id)
        logger.info("CubeSandboxBackend.kill: %s removed", handle.task_id)

    def health_check(self, handle: SandboxHandle) -> Dict[str, Any]:
        client = self._clients.get(handle.task_id)
        if client is None:
            return {"status": "stopped", "state": handle.state}
        try:
            return client.health_check()
        except Exception as e:
            return {"status": "error", "error": str(e), "state": handle.state}

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


class _AttachedSandbox:
    """Lightweight stand-in for an e2b Sandbox that was started in a prior session.

    Carries just enough info for CubeSandboxClient.get_opencode_url() to work
    when we re-attach to a persisted handle. The real resume call talks to
    cube-api directly via the underlying client.
    """

    def __init__(self, sandbox_id: str, host: str) -> None:
        self.sandbox_id = sandbox_id
        # get_host is the method the client calls; mimic it
        self._host = host

    def get_host(self, port: int) -> str:
        # cube-proxy expects <port>-<sandbox_id>.<sandbox_domain>
        return self._host

    def resume(self) -> None:
        # The cube-api/cube-proxy actually handles resume at the protocol
        # level; the client layer doesn't need to do anything locally.
        return None

    def kill(self) -> None:
        return None
