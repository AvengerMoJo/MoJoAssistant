"""Agentic tool wrappers around CubeSandbox microVM operations.

These functions are exposed to agentic LLMs (Popo, Rebecca, etc.) via the
``python`` executor in config/agentic_tools.json. Each function takes a
single ``args`` dict and returns a JSON-serializable dict with at least
``{"success": bool, ...}`` — the contract that
``CapabilityRegistry._run_python_executor`` expects.

The wrappers call into the existing ``CubeSandboxClient`` from
``app.scheduler.sandbox.cubesandbox_client``, which talks to the
CubeMaster cluster. No new dependencies, no shell-out, no path
allowlist issues — the agent calls the tool, we get a real KVM-isolated
microVM back.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Per-session in-process map: tool_name -> (CubeSandboxClient, last_used_ts).
# The agentic loop calls cubesandbox_create then cubesandbox_exec many
# times; we keep the client warm so we don't pay Sandbox.create() twice.
_CLIENT_CACHE: Dict[str, Dict[str, Any]] = {}


def _get_client(name: str) -> "CubeSandboxClient":  # noqa: F821
    """Return a warm CubeSandboxClient for ``name``, creating on first use."""
    from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient

    entry = _CLIENT_CACHE.get(name)
    if entry is not None:
        entry["last_used_ts"] = time.time()
        return entry["client"]
    template_id = os.getenv("CUBE_TEMPLATE_ID", "opencode-sandbox")
    client = CubeSandboxClient(template_id=template_id)
    _CLIENT_CACHE[name] = {"client": client, "last_used_ts": time.time()}
    return client


def _drop_client(name: str) -> None:
    _CLIENT_CACHE.pop(name, None)


# ---------------------------------------------------------------------
#  cubesandbox_create
# ---------------------------------------------------------------------


def cubesandbox_create(args: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new KVM-isolated microVM and register it under ``name``.

    Required: ``name`` (unique identifier the agent will use to refer
    to this VM in subsequent cubesandbox_exec / cubesandbox_destroy
    calls). Optional: ``template_id`` (defaults to CUBE_TEMPLATE_ID
    env var), ``timeout`` (seconds, default 300), ``upload_dir`` (a
    host directory whose contents are uploaded into the VM before
    returning — useful for seeding a cloned repo).

    Returns ``{"success": true, "name": ..., "sandbox_id": ..., "url": ...}``
    on success. The ``url`` is the OpenCode HTTP endpoint inside the VM
    that the agent can hit directly for AI-native code edits.
    """
    name = (args.get("name") or "").strip()
    if not name:
        return {"success": False, "error": "name is required"}

    # If a warm client already exists, just return its info (idempotent).
    existing = _CLIENT_CACHE.get(name)
    if existing and existing["client"].is_running:
        client = existing["client"]
        return {
            "success": True,
            "name": name,
            "sandbox_id": client.sandbox_id,
            "url": client.get_opencode_url(),
            "reused": True,
        }

    try:
        client = _get_client(name)
        template_id = args.get("template_id") or os.getenv("CUBE_TEMPLATE_ID", "opencode-sandbox")
        # Honor a per-call template override
        if template_id and template_id != client._template_id:
            client._template_id = template_id
        timeout = int(args.get("timeout", 300))

        sandbox_id = client.start()  # raises CubeSandboxError on failure
        url = client.get_opencode_url()

        upload_dir = args.get("upload_dir")
        if upload_dir:
            from pathlib import Path
            p = Path(upload_dir).expanduser()
            if p.is_dir():
                try:
                    client.upload_project(str(p))
                except Exception as e:
                    logger.warning("upload_project(%s) failed: %s", p, e)

        # Apply timeout override (post-start — e2b SDK takes it at create time)
        try:
            client._sandbox.set_timeout(timeout)
        except Exception:
            pass

        return {
            "success": True,
            "name": name,
            "sandbox_id": sandbox_id,
            "url": url,
            "template_id": client._template_id,
            "timeout_s": timeout,
        }
    except Exception as e:
        _drop_client(name)
        return {"success": False, "error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------
#  cubesandbox_exec
# ---------------------------------------------------------------------


def cubesandbox_exec(args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a shell command inside the microVM registered as ``name``.

    Required: ``name``, ``command``. Returns ``{"success": true, "stdout":
    ..., "stderr": ..., "exit_code": int}`` on completion. The command
    runs as the VM's default user (the OpenCode template runs as root
    in the microVM) and has no host-filesystem access — the host
    secrets at ``~/.ssh``, ``~/.aws``, ``~/.memory`` are physically
    unreachable from inside the VM.

    Failures (VM not running, E2B timeout) return
    ``{"success": false, "error": ...}`` without raising so the agentic
    loop can recover gracefully.
    """
    name = (args.get("name") or "").strip()
    command = args.get("command")
    if not name or not command:
        return {"success": False, "error": "name and command are required"}

    entry = _CLIENT_CACHE.get(name)
    if entry is None or not entry["client"].is_running:
        return {
            "success": False,
            "error": f"No running CubeSandbox for name='{name}'. "
                     f"Call cubesandbox_create first.",
        }
    client = entry["client"]
    try:
        proc = client._sandbox.process.start(command)
        out = proc.wait()
        return {
            "success": True,
            "name": name,
            "sandbox_id": client.sandbox_id,
            "stdout": getattr(out, "stdout", "") or "",
            "stderr": getattr(out, "stderr", "") or "",
            "exit_code": getattr(out, "exit_code", 0),
        }
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------
#  cubesandbox_list
# ---------------------------------------------------------------------


def cubesandbox_list(args: Dict[str, Any]) -> Dict[str, Any]:
    """List all microVMs the agentic process has live handles for.

    This is the in-process view, NOT a CubeMaster-wide listing (use
    the MCP ``sandbox_purge_orphans`` for that). It returns the names
    the agent created via ``cubesandbox_create`` and that haven't yet
    been destroyed.
    """
    out = []
    for name, entry in _CLIENT_CACHE.items():
        client = entry["client"]
        out.append({
            "name": name,
            "sandbox_id": client.sandbox_id,
            "is_running": client.is_running,
            "last_used_ts": entry["last_used_ts"],
        })
    return {"success": True, "count": len(out), "sandboxes": out}


# ---------------------------------------------------------------------
#  cubesandbox_destroy
# ---------------------------------------------------------------------


def cubesandbox_destroy(args: Dict[str, Any]) -> Dict[str, Any]:
    """Tear down the microVM registered as ``name``.

    Required: ``name``. Idempotent: destroying a name that doesn't
    exist returns ``success=true, already_destroyed=true`` so the
    agentic loop can retry safely.
    """
    name = (args.get("name") or "").strip()
    if not name:
        return {"success": False, "error": "name is required"}

    entry = _CLIENT_CACHE.get(name)
    if entry is None:
        return {"success": True, "name": name, "already_destroyed": True}
    client = entry["client"]
    try:
        if client.is_running:
            client.kill()
    except Exception as e:
        logger.warning("cubesandbox_destroy: kill(%s) failed: %s", name, e)
    finally:
        _drop_client(name)
    return {"success": True, "name": name, "destroyed": True}


# ---------------------------------------------------------------------
#  cubesandbox_upload
# ---------------------------------------------------------------------


def cubesandbox_upload(args: Dict[str, Any]) -> Dict[str, Any]:
    """Upload a host directory into the microVM.

    Required: ``name``, ``local_path`` (host directory to upload).
    Optional: ``remote_path`` (defaults to /root in the VM).
    """
    name = (args.get("name") or "").strip()
    local_path = (args.get("local_path") or "").strip()
    if not name or not local_path:
        return {"success": False, "error": "name and local_path are required"}

    entry = _CLIENT_CACHE.get(name)
    if entry is None or not entry["client"].is_running:
        return {
            "success": False,
            "error": f"No running CubeSandbox for name='{name}'",
        }
    client = entry["client"]

    from pathlib import Path
    p = Path(local_path).expanduser()
    if not p.is_dir():
        return {"success": False, "error": f"local_path '{p}' is not a directory"}
    try:
        client.upload_project(str(p))
        return {
            "success": True,
            "name": name,
            "sandbox_id": client.sandbox_id,
            "uploaded": str(p),
        }
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}"}
