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

    def __init__(self, hostname: str = "0.0.0.0", base_dir: Path | None = None) -> None:
        self._hostname = hostname
        # Default to ~/.memory/sandboxes — needed by status() to persist meta.json
        from pathlib import Path as _P
        self._base = base_dir or _P.home() / ".memory" / "sandboxes"

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

        # Build env with SSH key — check GIT_SSH_COMMAND, then well-known key paths
        clone_env = os.environ.copy()
        if "GIT_SSH_COMMAND" not in clone_env:
            for candidate in [
                os.path.expanduser("~/.ssh/id_MoJoAssistant_read_key"),
                os.path.expanduser("~/.ssh/id_rsa"),
                os.path.expanduser("~/.ssh/id_ed25519"),
            ]:
                if os.path.exists(candidate):
                    clone_env["GIT_SSH_COMMAND"] = (
                        f"ssh -i {candidate} -o StrictHostKeyChecking=no"
                    )
                    logger.info("ProcessBackend.create: using SSH key %s", candidate)
                    break

        try:
            subprocess.run(
                ["git", "clone", entry.repo_url, str(repo_dir)],
                check=True,
                timeout=120,
                capture_output=True,
                env=clone_env,
            )
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode(errors="replace").strip()
            raise RuntimeError(f"git clone failed: {err}") from e

        self._configure_git_identity(entry, repo_dir)
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

        # Configure git identity for both new and pre-existing repos
        # (one-time migration for sandboxes created before git_identity existed)
        self._configure_git_identity(entry, Path(entry.working_dir))

        cmd = [_OPENCODE_BIN, "--port", str(port), "--hostname", self._hostname, "serve"]
        logger.info("ProcessBackend.start: %s", shlex.join(cmd))

        env = os.environ.copy()
        if entry.password:
            env["OPENCODE_SERVER_PASSWORD"] = entry.password

        # Inject git identity so commits are attributed to the real user
        git_env = self._get_git_env(entry)
        if git_env:
            env.update(git_env)

        with open(log_path, "a") as logf:
            proc = subprocess.Popen(
                cmd,
                cwd=entry.working_dir,
                env=env,
                stdout=logf,
                stderr=logf,
                start_new_session=True,   # detach into new session/process group
            )

        pid_path.write_text(str(proc.pid))
        # Also write PGID so stop() can kill the whole process group
        # (children spawned by opencode would otherwise survive)
        pgid_path = Path(entry.working_dir).parent / "agent.pgid"
        pgid_path.write_text(str(proc.pid))  # start_new_session=True makes pid == pgid
        logger.info("ProcessBackend.start: pid=%d pgid=%d port=%d", proc.pid, proc.pid, port)

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
        # Prefer PGID for process group kill (catches children)
        pgid = self._read_pgid(entry) or pid
        if pid and self._pid_alive(pid):
            try:
                # SIGTERM the whole process group; children get it too
                if pgid:
                    try:
                        os.killpg(pgid, signal.SIGTERM)
                    except (ProcessLookupError, PermissionError):
                        os.kill(pid, signal.SIGTERM)
                else:
                    os.kill(pid, signal.SIGTERM)
                for _ in range(10):
                    time.sleep(0.5)
                    if not self._pid_alive(pid):
                        break
                else:
                    # Force kill the whole group
                    if pgid:
                        try:
                            os.killpg(pgid, signal.SIGKILL)
                        except (ProcessLookupError, PermissionError):
                            os.kill(pid, signal.SIGKILL)
                    else:
                        os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            logger.info("ProcessBackend.stop: pid=%d pgid=%d stopped", pid, pgid)

        pid_path = Path(entry.working_dir).parent / "agent.pid"
        pid_path.unlink(missing_ok=True)
        pgid_path = Path(entry.working_dir).parent / "agent.pgid"
        pgid_path.unlink(missing_ok=True)

        return SandboxEntry(**{**entry.to_dict(), "pid": None, "status": "stopped"})

    # ------------------------------------------------------------------ #
    #  status                                                              #
    # ------------------------------------------------------------------ #

    def status(self, entry: SandboxEntry, persist: bool = True) -> SandboxEntry:
        """Compute live status from PID/port. If persist=True, also write meta.json.

        Persisting on every status() call fixes the desync where meta.json says
        'running' but the process is dead. Caller can set persist=False for
        pure read-only checks.
        """
        if entry.agent_type == "claude_code":
            return SandboxEntry(**{**entry.to_dict(), "status": "running"})

        pid = self._read_pid(entry) or entry.pid
        if not pid or not self._pid_alive(pid):
            new_entry = SandboxEntry(**{**entry.to_dict(), "pid": None, "status": "stopped"})
            if persist:
                new_entry.save(self._base)
            return new_entry

        port = entry.port
        if port and not self._wait_healthy(port, timeout=2):
            new_entry = SandboxEntry(**{**entry.to_dict(), "status": "failed",
                                         "last_error": f"port {port} not responding"})
            if persist:
                new_entry.save(self._base)
            return new_entry

        new_entry = SandboxEntry(**{**entry.to_dict(), "pid": pid, "status": "running"})
        if persist:
            new_entry.save(self._base)
        return new_entry

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

    def _configure_git_identity(self, entry: SandboxEntry, repo_dir: Path) -> None:
        """Set git user.name/user.email in the cloned repo so commits are
        attributed to the real user, not 'opencode@local'."""
        try:
            from app.sandbox.git_identity import load_git_identity, configure_repo_git_identity
            identity = load_git_identity(entry.repo_url)
            configure_repo_git_identity(repo_dir, identity)
        except Exception as e:
            logger.warning("git identity setup failed for %s: %s", repo_dir, e)

    def _get_git_env(self, entry: SandboxEntry) -> dict:
        """Return GIT_AUTHOR_*/GIT_COMMITTER_* env vars for OpenCode process."""
        try:
            from app.sandbox.git_identity import load_git_identity
            identity = load_git_identity(entry.repo_url)
            env = identity.to_env()
            if identity.assistant_attribution:
                env["MOJO_GIT_TRAILER"] = identity.assistant_attribution
            return env
        except Exception as e:
            logger.warning("git env build failed: %s", e)
            return {}

    def _wait_healthy(self, port: int, timeout: int) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
                return True
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    return True  # server up, password-protected
                time.sleep(1)
            except (urllib.error.URLError, OSError):
                time.sleep(1)
        return False

    def _read_pgid(self, entry: SandboxEntry) -> int | None:
        """Read the process group ID from agent.pgid."""
        pgid_path = Path(entry.working_dir).parent / "agent.pgid"
        if not pgid_path.exists():
            return None
        try:
            return int(pgid_path.read_text().strip())
        except (ValueError, OSError):
            return None

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
