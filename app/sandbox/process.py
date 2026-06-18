"""ProcessBackend — bare-process sandbox (no Docker, no VMs).

For opencode:  clones repo, starts `opencode --port X serve`, tracks PID.
For claude_code: clone only — claude -p subprocess is managed per-task by
                 ClaudeCodeBackend in coding-agent-mcp-tool.
"""
from __future__ import annotations

import logging
import os
import shlex
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.sandbox.backend import SandboxBackend
from app.sandbox.models import SandboxEntry

logger = logging.getLogger(__name__)

_PORT_START = 4100
_PORT_END   = 4299
_HEALTH_TIMEOUT = 20   # seconds to wait for opencode to answer /
_OPENCODE_BIN = shutil.which("opencode") or os.path.expanduser("~/.bun/bin/opencode")


class ProcessBackend(SandboxBackend):
    """Manage coding agents as plain OS processes."""

    def __init__(self, hostname: str = "0.0.0.0") -> None:
        self._hostname = hostname

    # ------------------------------------------------------------------ #
    #  create                                                              #
    # ------------------------------------------------------------------ #

    def create(self, entry: SandboxEntry, base_dir: Path) -> SandboxEntry:
        """Clone the repo into base_dir/<sandbox_id>/repo (skip if already there)."""
        repo_dir = Path(entry.working_dir)
        if repo_dir.exists() and (repo_dir / ".git").exists():
            logger.info("ProcessBackend.create: repo already exists at %s", repo_dir)
            return entry

        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        logger.info("ProcessBackend.create: cloning %s → %s", entry.repo_url, repo_dir)
        try:
            subprocess.run(
                ["git", "clone", entry.repo_url, str(repo_dir)],
                check=True,
                timeout=120,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode(errors="replace").strip()
            raise RuntimeError(f"git clone failed: {err}") from e
        return entry

    # ------------------------------------------------------------------ #
    #  start                                                               #
    # ------------------------------------------------------------------ #

    def start(self, entry: SandboxEntry) -> SandboxEntry:
        if entry.agent_type == "claude_code":
            # No persistent server — mark running so the handler can proceed.
            return SandboxEntry(**{**entry.to_dict(), "status": "running", "port": None, "pid": None})

        # opencode — find a free port and launch headless server
        port = entry.port or self._free_port()
        log_path = Path(entry.working_dir).parent / "agent.log"
        pid_path = Path(entry.working_dir).parent / "agent.pid"

        if not _OPENCODE_BIN:
            raise RuntimeError("opencode binary not found — install it or set PATH")

        cmd = [_OPENCODE_BIN, "--port", str(port), "--hostname", self._hostname, "serve"]
        logger.info("ProcessBackend.start: %s", shlex.join(cmd))

        env = os.environ.copy()
        if entry.password:
            env["OPENCODE_SERVER_PASSWORD"] = entry.password

        with open(log_path, "a") as logf:
            proc = subprocess.Popen(
                cmd,
                cwd=entry.working_dir,
                env=env,
                stdout=logf,
                stderr=logf,
                start_new_session=True,   # detach from our process group
            )

        pid_path.write_text(str(proc.pid))
        logger.info("ProcessBackend.start: pid=%d port=%d", proc.pid, port)

        # Wait for the HTTP server to answer
        if not self._wait_healthy(port, timeout=_HEALTH_TIMEOUT):
            proc.kill()
            pid_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"opencode did not become healthy on port {port} within {_HEALTH_TIMEOUT}s. "
                f"Check {log_path}"
            )

        return SandboxEntry(**{
            **entry.to_dict(),
            "pid": proc.pid,
            "port": port,
            "status": "running",
            "last_error": None,
        })

    # ------------------------------------------------------------------ #
    #  stop                                                                #
    # ------------------------------------------------------------------ #

    def stop(self, entry: SandboxEntry) -> SandboxEntry:
        pid = self._read_pid(entry)
        if pid and self._pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
                for _ in range(10):
                    time.sleep(0.5)
                    if not self._pid_alive(pid):
                        break
                else:
                    os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            logger.info("ProcessBackend.stop: pid=%d stopped", pid)

        pid_path = Path(entry.working_dir).parent / "agent.pid"
        pid_path.unlink(missing_ok=True)

        return SandboxEntry(**{**entry.to_dict(), "pid": None, "status": "stopped"})

    # ------------------------------------------------------------------ #
    #  status                                                              #
    # ------------------------------------------------------------------ #

    def status(self, entry: SandboxEntry) -> SandboxEntry:
        if entry.agent_type == "claude_code":
            return SandboxEntry(**{**entry.to_dict(), "status": "running"})

        pid = self._read_pid(entry) or entry.pid
        if not pid or not self._pid_alive(pid):
            return SandboxEntry(**{**entry.to_dict(), "pid": None, "status": "stopped"})

        port = entry.port
        if port and not self._wait_healthy(port, timeout=2):
            return SandboxEntry(**{**entry.to_dict(), "status": "failed",
                                   "last_error": f"port {port} not responding"})

        return SandboxEntry(**{**entry.to_dict(), "pid": pid, "status": "running"})

    # ------------------------------------------------------------------ #
    #  destroy                                                             #
    # ------------------------------------------------------------------ #

    def destroy(self, entry: SandboxEntry, base_dir: Path) -> None:
        self.stop(entry)
        sandbox_dir = base_dir / entry.sandbox_id
        if sandbox_dir.exists():
            shutil.rmtree(sandbox_dir)
            logger.info("ProcessBackend.destroy: removed %s", sandbox_dir)

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _free_port(self) -> int:
        for port in range(_PORT_START, _PORT_END + 1):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    continue
        raise RuntimeError(f"No free port in {_PORT_START}–{_PORT_END}")

    def _wait_healthy(self, port: int, timeout: int) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
                return True
            except (urllib.error.URLError, OSError):
                time.sleep(1)
        return False

    def _read_pid(self, entry: SandboxEntry) -> int | None:
        pid_path = Path(entry.working_dir).parent / "agent.pid"
        if pid_path.exists():
            try:
                return int(pid_path.read_text().strip())
            except ValueError:
                return None
        return None

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False
