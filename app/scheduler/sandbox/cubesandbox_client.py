"""
CubeSandbox client — manages KVM/RustVMM microVM lifecycle for coding agent isolation.

Replaces coding-agent-mcp-tool's BackendRegistry with direct E2B-compatible
SDK calls to CubeSandbox. Each coding session gets its own VM with a dedicated
kernel — host secrets (~/.ssh, ~/.aws, ~/.memory) are physically inaccessible.

Architecture:
  1. Boot a microVM from a pre-built OpenCode template (hot start <60ms)
  2. Upload project files into the VM
  3. OpenCode runs inside the VM in server mode (port 4173)
  4. CubeSandbox proxies the port — MoJo connects via the proxy URL
  5. All OpenCode HTTP calls (session, message, permissions) go through the proxy

Prerequisites:
  - cube-proxy reachable at $E2B_API_URL (e.g. http://127.0.0.1:12080 or
    https://sandbox.eclipsogate.org via cloudflared)
  - pip install e2b
  - OpenCode template built (see docker/opencode-sandbox/Dockerfile)
  - E2B_API_KEY and CUBE_TEMPLATE_ID set in env
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 300
DEFAULT_TEMPLATE = os.getenv("CUBE_TEMPLATE_ID", "opencode-sandbox")


class CubeSandboxError(Exception):
    """CubeSandbox lifecycle error."""


class CubeSandboxClient:
    """
    Manages a CubeSandbox microVM running OpenCode.

    Usage:
        client = CubeSandboxClient()
        await client.start()
        url = client.get_opencode_url()
        # Make HTTP calls to url...
        await client.kill()
    """

    def __init__(
        self,
        template_id: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self._template_id = template_id or DEFAULT_TEMPLATE
        self._timeout = timeout
        self._sandbox: Any = None
        self._sandbox_id: Optional[str] = None
        self._opencode_port = 4173

    @property
    def sandbox_id(self) -> Optional[str]:
        return self._sandbox_id

    @property
    def is_running(self) -> bool:
        return self._sandbox is not None

    def start(self) -> str:
        """Boot a microVM from template. Returns sandbox_id.

        Raises CubeSandboxError if the SDK is not installed or the server
        is unreachable.
        """
        if not os.getenv("E2B_API_URL") or not os.getenv("E2B_API_KEY"):
            raise CubeSandboxError(
                "E2B_API_URL and E2B_API_KEY must be set. "
                "Configure in .env or ~/.memory/config/infra_context.json."
            )

        try:
            from e2b import Sandbox
        except ImportError:
            raise CubeSandboxError(
                "e2b SDK not installed. Run: pip install e2b"
            )

        try:
            # e2b SDK >= 2.x exposes create as a classmethod; the old
            # direct constructor (Sandbox(template=...)) was removed.
            self._sandbox = Sandbox.create(
                template=self._template_id,
                timeout=self._timeout,
            )
            self._sandbox_id = self._sandbox.sandbox_id
            logger.info(
                "CubeSandbox started: id=%s template=%s",
                self._sandbox_id, self._template_id,
            )
            return self._sandbox_id
        except Exception as e:
            raise CubeSandboxError(f"Failed to start CubeSandbox: {e}") from e

    def get_opencode_url(self) -> str:
        """Return the proxied URL to reach OpenCode inside the VM.

        CubeSandbox proxies ports from inside the VM to a host-accessible URL.
        """
        if not self._sandbox:
            raise CubeSandboxError("Sandbox not started")

        try:
            host = self._sandbox.get_host(self._opencode_port)
            url = f"http://{host}"
            logger.debug("OpenCode proxy URL: %s", url)
            return url
        except AttributeError:
            raise CubeSandboxError(
                "CubeSandbox SDK does not support get_host(). "
                "Ensure e2b SDK version supports port forwarding."
            )
        except Exception as e:
            raise CubeSandboxError(f"Failed to get OpenCode proxy URL: {e}") from e

    def exec_shell(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """Run a shell command inside the VM.

        Returns {"exit_code": int, "stdout": str, "stderr": str}.
        """
        if not self._sandbox:
            raise CubeSandboxError("Sandbox not started")

        try:
            result = self._sandbox.commands.run(command, timeout=timeout)
            return {
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except Exception as e:
            raise CubeSandboxError(f"Shell exec failed: {e}") from e

    def upload_file(self, vm_path: str, content: str) -> None:
        """Write a file into the VM filesystem."""
        if not self._sandbox:
            raise CubeSandboxError("Sandbox not started")
        try:
            self._sandbox.filesystem.write(vm_path, content)
        except Exception as e:
            raise CubeSandboxError(f"File upload failed: {e}") from e

    def upload_project(self, host_dir: str, vm_dir: str = "/workspace") -> None:
        """Upload a project directory into the VM.

        Walks the host directory and writes each file into the VM.
        Skips .git, node_modules, and other large directories.
        """
        import pathlib

        skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
        host_path = pathlib.Path(host_dir)

        if not host_path.is_dir():
            raise CubeSandboxError(f"Host directory does not exist: {host_dir}")

        try:
            self._sandbox.filesystem.make_dir(vm_dir)
        except Exception:
            pass

        count = 0
        for root, dirs, files in os.walk(host_path):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for f in files:
                src = os.path.join(root, f)
                rel = os.path.relpath(src, host_dir)
                dst = f"{vm_dir}/{rel}"
                try:
                    content = open(src, "r", encoding="utf-8").read()
                    self._sandbox.filesystem.write(dst, content)
                    count += 1
                except (UnicodeDecodeError, OSError):
                    pass

        logger.info("Uploaded %d files to %s", count, vm_dir)

    def pause(self) -> None:
        """Pause the VM and snapshot state for fast resume."""
        if not self._sandbox:
            return
        try:
            self._sandbox.pause()
            logger.info("CubeSandbox paused: %s", self._sandbox_id)
        except Exception as e:
            logger.warning("Failed to pause sandbox: %s", e)

    def resume(self) -> None:
        """Resume the VM from a paused snapshot."""
        if not self._sandbox:
            return
        try:
            self._sandbox.resume()
            logger.info("CubeSandbox resumed: %s", self._sandbox_id)
        except Exception as e:
            logger.warning("Failed to resume sandbox: %s", e)

    def kill(self) -> None:
        """Destroy the VM and release resources."""
        if not self._sandbox:
            return
        try:
            self._sandbox.kill()
            logger.info("CubeSandbox killed: %s", self._sandbox_id)
        except Exception as e:
            logger.warning("Failed to kill sandbox: %s", e)
        finally:
            self._sandbox = None
            self._sandbox_id = None

    def health_check(self) -> Dict[str, Any]:
        """Check if OpenCode inside the VM is responding."""
        if not self._sandbox:
            return {"status": "stopped"}

        try:
            url = self.get_opencode_url()
            import httpx
            resp = httpx.get(f"{url}/api/health", timeout=5)
            return {
                "status": "ok" if resp.status_code == 200 else "error",
                "url": url,
                "http_status": resp.status_code,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ------------------------------------------------------------------
    #  Orphan / kill-by-id path (recovery for VMs not in our registry) #
    # ------------------------------------------------------------------

    @staticmethod
    def kill_by_id(sandbox_id: str) -> Dict[str, Any]:
        """Force-kill a microVM by its cube-id, even when we never held a handle.

        Two kill paths, tried in order:
          1. e2b SDK: ``Sandbox.connect(sandbox_id).kill()``  (preferred)
          2. HTTP fallback: ``DELETE $E2B_API_URL/sandboxes/{id}``  (works
             even when the e2b SDK is not installed or its ``Sandbox.connect``
             method is missing in older versions)

        This is the recovery path for the 5-stranded-VM class of bug: a
        microVM exists on CubeMaster but the local ``sandbox_sessions.json``
        has no record of it (handle_store write failed or was wiped).

        Returns a dict ``{killed, sandbox_id, error, path}`` — never raises
        so the MCP caller can iterate over a list of orphans safely.
        """
        if not sandbox_id:
            return {"killed": False, "sandbox_id": None, "error": "sandbox_id is required", "path": None}
        if not os.getenv("E2B_API_URL") or not os.getenv("E2B_API_KEY"):
            return {
                "killed": False,
                "sandbox_id": sandbox_id,
                "error": "E2B_API_URL and E2B_API_KEY must be set",
                "path": None,
            }

        # Path 1: e2b SDK
        try:
            from e2b import Sandbox
            attached = Sandbox.connect(sandbox_id)
            attached.kill()
            logger.info("CubeSandbox.kill_by_id: killed %s via e2b SDK", sandbox_id)
            return {
                "killed": True,
                "sandbox_id": sandbox_id,
                "error": None,
                "path": "e2b_sdk",
            }
        except ImportError:
            logger.debug("CubeSandbox.kill_by_id: e2b SDK not installed, trying HTTP")
        except Exception as e:
            logger.warning(
                "CubeSandbox.kill_by_id: e2b SDK failed (%s), trying HTTP fallback",
                e,
            )

        # Path 2: HTTP DELETE
        try:
            import httpx
            api_url = os.getenv("E2B_API_URL", "").rstrip("/")
            api_key = os.getenv("E2B_API_KEY", "")
            for path in (f"/sandboxes/{sandbox_id}", f"/cube/sandbox/{sandbox_id}"):
                resp = httpx.delete(
                    f"{api_url}{path}",
                    headers={"X-API-KEY": api_key} if api_key else {},
                    timeout=15,
                )
                if resp.status_code in (200, 204):
                    logger.info(
                        "CubeSandbox.kill_by_id: killed %s via HTTP %s %s",
                        sandbox_id, "DELETE", path,
                    )
                    return {
                        "killed": True,
                        "sandbox_id": sandbox_id,
                        "error": None,
                        "path": f"http_delete:{path}",
                    }
                if resp.status_code == 404:
                    # Already gone — treat as success
                    logger.info(
                        "CubeSandbox.kill_by_id: %s already gone (HTTP 404 on %s)",
                        sandbox_id, path,
                    )
                    return {
                        "killed": True,
                        "sandbox_id": sandbox_id,
                        "error": None,
                        "path": f"http_delete_404:{path}",
                    }
            return {
                "killed": False,
                "sandbox_id": sandbox_id,
                "error": "All HTTP kill paths returned non-success",
                "path": "http_delete",
            }
        except Exception as e:
            logger.error("CubeSandbox.kill_by_id(%s) HTTP fallback failed: %s", sandbox_id, e)
            return {
                "killed": False,
                "sandbox_id": sandbox_id,
                "error": f"{type(e).__name__}: {e}",
                "path": "http_delete",
            }

    @staticmethod
    def list_cubemaster_sandboxes() -> list[Dict[str, Any]]:
        """Enumerate every microVM CubeMaster currently has on file.

        Talks to ``$E2B_API_URL`` via HTTP. Different CubeSandbox deployments
        expose different paths, so we try them in order:
          1. ``/sandboxes``  (e2b / CubeSandbox cloud)
          2. ``/cube/sandbox/list``  (legacy / one-click deploy)
          3. ``/cube/sandboxes``     (alt)

        Returns the JSON list as plain dicts — caller decides which are
        orphans via ``list_orphan_sandbox_ids``.

        Used by the ``sandbox_purge_orphans`` MCP tool.
        """
        api_url = os.getenv("E2B_API_URL", "").rstrip("/")
        api_key = os.getenv("E2B_API_KEY", "")
        if not api_url:
            return []
        try:
            import httpx
        except ImportError:
            return []
        candidates = ["/sandboxes", "/cube/sandbox/list", "/cube/sandboxes"]
        for path in candidates:
            try:
                resp = httpx.get(
                    f"{api_url}{path}",
                    headers={"X-API-KEY": api_key} if api_key else {},
                    timeout=15,
                )
            except Exception as e:
                logger.debug("list_cubemaster_sandboxes: %s failed: %s", path, e)
                continue
            if resp.status_code != 200:
                continue
            try:
                data = resp.json()
            except Exception as e:
                logger.debug("list_cubemaster_sandboxes: %s bad JSON: %s", path, e)
                continue
            if isinstance(data, list):
                logger.info(
                    "list_cubemaster_sandboxes: hit %s (%d items)", path, len(data)
                )
                return [CubeSandboxClient._normalize_sandbox(c) for c in data]
            for key in ("data", "sandboxes", "items"):
                if isinstance(data, dict) and isinstance(data.get(key), list):
                    items = data[key]
                    logger.info(
                        "list_cubemaster_sandboxes: hit %s (key=%s, %d items)",
                        path, key, len(items),
                    )
                    return [CubeSandboxClient._normalize_sandbox(c) for c in items]
        logger.warning(
            "list_cubemaster_sandboxes: none of %s responded with a list", candidates
        )
        return []

    @staticmethod
    def _normalize_sandbox(raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize CubeSandbox / e2b response shape into snake_case.

        The cloud e2b API returns camelCase (``sandboxID``); the on-prem
        cube-api returns snake_case (``sandbox_id``). Other deployments
        may differ. We pick whichever is non-empty and pass through.
        """
        sid = (
            raw.get("sandbox_id")
            or raw.get("sandboxID")
            or raw.get("id")
        )
        return {
            "sandbox_id": sid,
            "host_ip": raw.get("host_ip") or raw.get("clientID") or raw.get("client_id"),
            "sandbox_ip": raw.get("sandbox_ip"),
            "create_at": raw.get("create_at") or raw.get("startedAt"),
            "end_at": raw.get("end_at") or raw.get("endAt"),
            "template_id": raw.get("template_id") or raw.get("templateID"),
            "cpu_count": raw.get("cpu_count") or raw.get("cpuCount"),
            "memory_mb": raw.get("memory_mb") or raw.get("memoryMB"),
            "metadata": raw.get("metadata", {}),
            "raw": raw,
        }
