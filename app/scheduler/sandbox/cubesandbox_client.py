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
  - CubeSandbox server running (CUBEMASTER_ADDR)
  - pip install e2b
  - OpenCode template built (see docker/opencode-sandbox/Dockerfile)
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
            self._sandbox = Sandbox(
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
            resp = httpx.get(f"{url}/health", timeout=5)
            return {
                "status": "ok" if resp.status_code == 200 else "error",
                "url": url,
                "http_status": resp.status_code,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
