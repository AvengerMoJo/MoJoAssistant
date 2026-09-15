"""SSH remote-host backend — OpenCode serve on a distant machine, reached
over the tailnet.

Use case: a personal business project on a remote host. The scheduler task
carries config["sandbox_backend"] = "ssh"; MoJoAssistant SSHes into the
host (key auth, BatchMode), installs opencode server mode on demand, spawns
`opencode serve` bound to the tailnet interface, and then talks to it over
plain HTTP with BasicAuth, exactly like the host backend but over the wire.
Reachability is expected via the user's existing Tailscale tailnet (MagicDNS
name or 100.x address as the ssh host / url_host), so no port forwarding is
needed and nothing is exposed beyond the tailnet.

Config lives in ~/.memory/config/sandbox.json under backends.ssh:

    "backends": {
      "ssh": {
        "host": "bizbuild-01.tailnet.ts.net",
        "user": "alex",
        "ssh_port": 22,
        "identity_file": "~/.ssh/id_ed25519",
        "url_host": "",           # default: host (set if ssh alias differs)
        "bind_host": "0.0.0.0",   # opencode bind; guarded by tailnet + password
        "port_range": [4600, 4699],
        "install_opencode": true
      }
    }

Remote layout:
  - working dir: task's working_dir, or ~/.mojo/sandboxes/<task_id>
  - logs:        ~/.mojo/task_logs/<task_id>/agent.log (mirrored locally
                 into ~/.memory/task_logs/<task_id>/remote_agent.log on
                 get_log_path so the dashboard has a readable file)
  - password:    written to ~/.mojo/task_logs/<task_id>/env (mode 0600) so
                 it never appears in remote `ps` output

Pause/resume map to remote SIGSTOP/SIGCONT, mirroring HostOpenCodeBackend.
"""

from __future__ import annotations

import base64
import logging
import re
import secrets
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.scheduler.sandbox.base import (
    SandboxBackend,
    SandboxHandle,
    delete_handle,
    load_handle,
    store_handle,
)
from app.scheduler.sandbox.registry import register_backend

logger = logging.getLogger(__name__)

# Remote port range for per-task opencode instances. Distinct from the
# host backend (4400-4499) and docker (4500-4599) ranges for clarity, even
# though those live on different machines.
DEFAULT_PORT_RANGE: Tuple[int, int] = (4600, 4699)

# Candidate opencode binary locations probed on the remote host, in order.
# Detection echoes the EXPANDED absolute path (unquoted ~ expands in the
# remote shell), so downstream shlex.quote is safe.
_REMOTE_OPENCODE_CANDIDATES = (
    ".opencode/bin/opencode",   # curl -fsSL https://opencode.ai/install | bash
    ".bun/bin/opencode",        # bun install -g opencode-ai (repo's docs/INSTALL.md)
    ".local/bin/opencode",
    "usr/local/bin/opencode",
)

_REMOTE_BASE_DIR = ".mojo"


def _q(value: str) -> str:
    return shlex.quote(value)


def _safe_id(task_id: str) -> str:
    """Sanitize a scheduler task_id for embedding in remote paths."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", task_id)


def _rp(path: str) -> str:
    """Quote a remote path while keeping tilde/$HOME expansion working.

    shlex.quote('~/.x') would produce a literal '~' directory on the remote
    host; this helper rewrites the tilde prefix to "$HOME" and quotes only
    the remainder.
    """
    if path == "~":
        return '"$HOME"'
    if path.startswith("~/"):
        return f'"$HOME"/{_q(path[2:])}'
    return _q(path)


@register_backend("ssh")
class SSHRemoteBackend(SandboxBackend):
    """One remote `opencode serve` process per task, managed over SSH."""

    name = "ssh"

    def __init__(
        self,
        host: str = "",
        user: str = "",
        ssh_port: int = 22,
        identity_file: str = "",
        url_host: str = "",
        opencode_bin: str = "",
        install_opencode: bool = True,
        bind_host: str = "0.0.0.0",
        port_range: Optional[Sequence[int]] = None,
        connect_timeout: int = 10,
        boot_timeout: int = 120,
        # Managed-mode: attach to an always-on systemd-managed `opencode serve`
        # on the remote host instead of spawning a per-task ephemeral server.
        use_managed: bool = False,
        managed_port: int = 4096,
        managed_env_file: str = "~/.mojo/server.env",
        managed_service: str = "opencode-serve",
        **kwargs: Any,
    ) -> None:
        self._host = (host or "").strip()
        self._user = (user or "").strip()
        self._ssh_port = int(ssh_port or 22)
        self._identity_file = (identity_file or "").strip() or None
        self._url_host = (url_host or "").strip() or self._host
        self._opencode_bin = (opencode_bin or "").strip()
        self._should_install_opencode = bool(install_opencode)
        self._bind_host = bind_host or "0.0.0.0"
        pr = list(port_range or DEFAULT_PORT_RANGE)
        self._port_range = (int(pr[0]), int(pr[1]))
        self._connect_timeout = int(connect_timeout)
        self._boot_timeout = int(boot_timeout)
        # Managed mode
        self._use_managed = bool(use_managed)
        self._managed_port = int(managed_port)
        self._managed_env_file = (managed_env_file or "~/.mojo/server.env").strip()
        self._managed_service = (managed_service or "opencode-serve").strip()

    # ------------------------------------------------------------------
    # SSH plumbing
    # ------------------------------------------------------------------

    def _require_host(self) -> None:
        if not self._host:
            raise RuntimeError(
                "SSH sandbox backend is not configured. Set backends.ssh.host "
                "(and optionally user / identity_file / url_host) in "
                "~/.memory/config/sandbox.json. The host should be the remote "
                "machine's Tailscale MagicDNS name or 100.x address."
            )

    def _ssh_base(self) -> List[str]:
        cmd = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={self._connect_timeout}",
            # Non-interactive first-connect: record the host key instead of
            # prompting (BatchMode would fail outright), still refuse
            # changed keys for mid-session MITM protection.
            "-o", "StrictHostKeyChecking=accept-new",
            "-p", str(self._ssh_port),
        ]
        if self._identity_file:
            cmd += ["-i", str(Path(self._identity_file).expanduser())]
        dest = f"{self._user}@{self._host}" if self._user else self._host
        cmd.append(dest)
        return cmd

    def _run_remote(
        self,
        remote_cmd: str,
        timeout: int = 60,
        input_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run a command on the remote host via ssh. Returns an exec-style dict."""
        try:
            proc = subprocess.run(
                self._ssh_base() + [remote_cmd],
                capture_output=True, text=True, timeout=timeout,
                input=input_text, errors="replace",
            )
            return {
                "success": proc.returncode == 0,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "returncode": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "stdout": "", "stderr": f"ssh timed out ({timeout}s)", "returncode": -1}
        except FileNotFoundError:
            return {"success": False, "stdout": "", "stderr": "ssh binary not found on this machine", "returncode": -1}
        except Exception as e:
            return {"success": False, "stdout": "", "stderr": str(e), "returncode": -1}

    def _run_remote_checked(self, remote_cmd: str, what: str, timeout: int = 60) -> str:
        result = self._run_remote(remote_cmd, timeout=timeout)
        if not result["success"]:
            raise RuntimeError(
                f"SSH sandbox: {what} failed on {self._host}: "
                f"{result['stderr'].strip() or result['stdout'].strip() or 'unknown error'}"
            )
        return result["stdout"]

    # ------------------------------------------------------------------
    # Remote helpers
    # ------------------------------------------------------------------

    def _remote_task_log_dir(self, task_id: str) -> str:
        return f"~/{_REMOTE_BASE_DIR}/task_logs/{_safe_id(task_id)}"

    def _detect_opencode_bin(self) -> str:
        """Probe the remote host for an opencode binary. Returns the
        EXPANDED absolute path (empty string when nothing is found)."""
        if self._opencode_bin:
            return self._opencode_bin
        probes = ["command -v opencode"] + [
            f"test -x ~/{cand} && echo ~/{cand}" for cand in _REMOTE_OPENCODE_CANDIDATES
        ]
        # The probes legitimately exit non-zero when opencode is absent;
        # detection outcome is read from stdout, so force exit 0.
        remote = " ; ".join(f"{{ {p}; }} 2>/dev/null" for p in probes) + " ; true"
        out = self._run_remote_checked(remote, "opencode detection")
        bin_path = next((line.strip() for line in out.splitlines() if line.strip()), "")
        return bin_path

    def _install_opencode(self) -> str:
        """Install opencode on the remote host. Prefers bun (repo convention),
        falls back to the official curl installer. Returns the binary path."""
        bun = self._run_remote(
            'command -v bun >/dev/null 2>&1 && bun install -g opencode-ai >/dev/null 2>&1 && echo OK',
            timeout=300,
        )
        if not bun["success"]:
            curl = self._run_remote(
                'curl -fsSL https://opencode.ai/install | bash >/dev/null 2>&1 && echo OK',
                timeout=300,
            )
            if not curl["success"]:
                raise RuntimeError(
                    f"SSH sandbox: could not install opencode on {self._host} "
                    "(neither bun nor the curl installer worked). Install it "
                    "manually with `bun install -g opencode-ai` on the remote "
                    "host and retry."
                )
        bin_path = self._detect_opencode_bin()
        if not bin_path:
            raise RuntimeError(
                f"SSH sandbox: opencode installed on {self._host} but no binary "
                "found in PATH, ~/.opencode/bin, ~/.bun/bin, ~/.local/bin or "
                "/usr/local/bin. Set backends.ssh.opencode_bin explicitly."
            )
        logger.info("SSH sandbox: installed opencode on %s at %s", self._host, bin_path)
        return bin_path

    def _remote_free_port(self) -> int:
        """Pick the first free port in the configured range on the remote host."""
        start, end = self._port_range
        out = self._run_remote(
            "ss -ltn 2>/dev/null | awk '{print $4}' | grep -oE '[0-9]+$' | sort -un",
            timeout=30,
        )
        used = set()
        if out["success"]:
            used = {int(line) for line in out["stdout"].split() if line.isdigit()}
        for port in range(start, end + 1):
            if port not in used:
                return port
        raise RuntimeError(f"SSH sandbox: no free port in {start}-{end} on {self._host}")

    def _pid_alive_remote(self, pid: int) -> bool:
        out = self._run_remote(f"kill -0 {pid} 2>/dev/null && echo alive", timeout=20)
        return out["success"] and "alive" in out["stdout"]

    @staticmethod
    def _require_pid(handle: SandboxHandle) -> int:
        try:
            return int(handle.sandbox_id or "")
        except ValueError:
            raise RuntimeError(
                f"SSH sandbox: handle for {handle.task_id} has no valid remote pid"
            ) from None

    def _wait_healthy(self, url: str, password: str, timeout: float) -> bool:
        auth = f"opencode:{password}".encode()
        auth_header = f"Basic {base64.b64encode(auth).decode()}"
        deadline = time.time() + timeout
        while time.time() < deadline:
            rejected = True
            for path in ("/api/health", "/"):
                try:
                    req = urllib.request.Request(f"{url}{path}", headers={"Authorization": auth_header})
                    urllib.request.urlopen(req, timeout=5).read()
                    return True
                except urllib.error.HTTPError as e:
                    if e.code not in (401, 403):
                        rejected = False  # endpoint exists, just not 2xx yet
                except (urllib.error.URLError, ConnectionError, OSError):
                    rejected = False
            if rejected:
                # Both endpoints consistently refuse our credentials; retrying
                # with the same password cannot succeed.
                logger.error("SSH sandbox: %s rejected credentials on all endpoints", url)
                return False
            time.sleep(1.5)
        return False

    # ------------------------------------------------------------------
    # Managed-mode helpers
    # ------------------------------------------------------------------

    def _is_managed(self) -> bool:
        return self._use_managed

    def _managed_url(self) -> str:
        return f"http://{self._url_host}:{self._managed_port}"

    def _read_managed_env(self) -> str:
        """Read the OPENCODE_SERVER_PASSWORD from the remote server.env."""
        result = self._run_remote(
            f"cat {_rp(self._managed_env_file)} 2>/dev/null",
            timeout=15,
        )
        if not result["success"]:
            raise RuntimeError(
                f"SSH sandbox managed mode: could not read {self._managed_env_file} "
                f"on {self._host}. Run setup_remote_opencode_host.sh --managed first."
            )
        for line in result["stdout"].splitlines():
            line = line.strip()
            if line.startswith("OPENCODE_SERVER_PASSWORD="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
        raise RuntimeError(
            f"SSH sandbox managed mode: OPENCODE_SERVER_PASSWORD not found in "
            f"{self._managed_env_file} on {self._host}"
        )

    def _managed_ensure_service(self) -> None:
        """Ensure the managed opencode service is running, start if needed."""
        status = self._run_remote(
            f"systemctl --user is-active {self._managed_service} 2>/dev/null",
            timeout=15,
        )
        if status["stdout"].strip() == "active":
            return
        # Not running — start it
        self._run_remote_checked(
            f"systemctl --user start {self._managed_service}",
            f"start managed service {self._managed_service}",
        )
        # Wait for it to become healthy
        password = self._read_managed_env()
        url = self._managed_url()
        if not self._wait_healthy(url, password, self._boot_timeout):
            raise RuntimeError(
                f"SSH sandbox managed mode: service {self._managed_service} on "
                f"{self._host} did not become healthy in {self._boot_timeout}s after start"
            )
        logger.info("SSH sandbox managed mode: started service %s on %s", self._managed_service, self._host)

    def _start_managed(self, task_id: str, working_dir: str, **kwargs: Any) -> SandboxHandle:
        """Attach to the always-on managed opencode server. No per-task process spawned."""
        self._require_host()

        existing = load_handle(task_id)
        if (
            existing
            and existing.backend == self.name
            and existing.state in ("running", "paused")
            and existing.sandbox_id == "managed"
            and existing.url == self._managed_url()
        ):
            # Verify the shared server is still reachable
            try:
                health = self.health_check(existing)
                if health.get("status") == "ok":
                    if existing.state == "paused":
                        existing.state = "running"
                        store_handle(existing)
                    logger.info("SSH sandbox managed mode: re-attached %s url=%s", task_id, existing.url)
                    return existing
            except Exception:
                pass
            delete_handle(task_id)

        password = self._read_managed_env()
        self._managed_ensure_service()
        url = self._managed_url()

        local_log = Path.home() / ".memory" / "task_logs" / _safe_id(task_id) / "remote_agent.log"
        handle = SandboxHandle(
            task_id=task_id,
            backend=self.name,
            sandbox_id="managed",
            url=url,
            state="running",
            working_dir=working_dir or f"~/{_REMOTE_BASE_DIR}/sandboxes/{_safe_id(task_id)}",
            log_path=str(local_log),
            password=password,
            role_id=kwargs.get("role_id"),
            parent_task_id=kwargs.get("parent_task_id"),
            environment=kwargs.get("environment"),
        )
        store_handle(handle)
        logger.info("SSH sandbox managed mode: attached %s url=%s", task_id, url)
        return handle

    def _managed_service_command(self, command: str) -> Dict[str, Any]:
        return self._run_remote(
            f"systemctl --user {command} {self._managed_service} 2>/dev/null",
            timeout=15,
        )

    def start(self, task_id: str, working_dir: str, **kwargs: Any) -> SandboxHandle:
        self._require_host()

        if self._is_managed():
            return self._start_managed(task_id, working_dir, **kwargs)

        # Resume a persisted ssh-backend session if the remote process is
        # still alive. Handles from other backends are left to their owner.
        existing = load_handle(task_id)
        if (
            existing
            and existing.backend == self.name
            and existing.state in ("running", "paused")
            and existing.sandbox_id
        ):
            pid = int(existing.sandbox_id)
            if self._pid_alive_remote(pid):
                if existing.state == "paused":
                    self.resume(existing)
                existing.state = "running"
                store_handle(existing)
                logger.info("SSH sandbox: re-attached %s pid=%s url=%s", task_id, pid, existing.url)
                return existing
            logger.info("SSH sandbox: stale handle for %s (pid=%s dead on remote), restarting", task_id, pid)
            delete_handle(task_id)

        bin_path = self._detect_opencode_bin()
        if not bin_path:
            if not self._should_install_opencode:
                raise RuntimeError(
                    f"SSH sandbox: opencode not found on {self._host} and "
                    "install_opencode is false. Install it there or enable "
                    "backends.ssh.install_opencode."
                )
            bin_path = self._install_opencode()

        remote_workdir = working_dir or f"~/{_REMOTE_BASE_DIR}/sandboxes/{_safe_id(task_id)}"
        self._run_remote_checked(f"mkdir -p {_rp(remote_workdir)}", "working dir creation")

        log_dir = self._remote_task_log_dir(task_id)
        self._run_remote_checked(f"mkdir -p {_rp(log_dir)}", "remote log dir creation")

        port = self._remote_free_port()
        password = secrets.token_urlsafe(16)

        # Password goes into a 0600 env file (not the command line) so it
        # never shows up in remote `ps` output.
        env_file = f"{log_dir}/env"
        write_env = self._run_remote(
            f"umask 077 && cat > {_rp(env_file)} && chmod 600 {_rp(env_file)}",
            input_text=f"OPENCODE_SERVER_PASSWORD={password}\n",
        )
        if not write_env["success"]:
            raise RuntimeError(
                f"SSH sandbox: could not write env file on {self._host}: {write_env['stderr']}"
            )

        # The & must bind ONLY to the opencode launch. Writing
        # `setup && cmd &` backgrounds the whole chain, making opencode the
        # foreground child of the async subshell, which then blocks in
        # waitpid forever and the ssh channel never EOFs (found live
        # 2026-09-14). The brace group backgrounds just the launch; the
        # outer shell prints $! and exits immediately.
        spawn = (
            f"set -a && . {_rp(env_file)} && set +a && "
            f"cd {_rp(remote_workdir)} && "
            f"{{ nohup setsid {_q(bin_path)} --port {port} --hostname {_q(self._bind_host)} serve "
            f">> {_rp(log_dir + '/agent.log')} 2>&1 < /dev/null & }} ; echo $!"
        )
        out = self._run_remote_checked(spawn, "opencode serve spawn")
        try:
            pid = int(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise RuntimeError(f"SSH sandbox: unexpected spawn output on {self._host}: {out!r}") from None

        url = f"http://{self._url_host}:{port}"
        if not self._wait_healthy(url, password, self._boot_timeout):
            # Best-effort diagnosis before failing loud.
            log_tail = self._run_remote(f"tail -n 30 {_rp(log_dir + '/agent.log')}", timeout=20)
            self._run_remote(f"kill {pid} 2>/dev/null", timeout=20)
            raise RuntimeError(
                f"SSH sandbox: opencode on {self._host}:{port} did not become "
                f"healthy in {self._boot_timeout}s. Check tailnet reachability "
                f"(tailscale status, ping {self._url_host}) and remote log: "
                f"{log_tail['stdout'][-800:]}"
            )

        local_log = Path.home() / ".memory" / "task_logs" / _safe_id(task_id) / "remote_agent.log"
        handle = SandboxHandle(
            task_id=task_id,
            backend=self.name,
            sandbox_id=str(pid),
            url=url,
            state="running",
            working_dir=remote_workdir,
            log_path=str(local_log),
            password=password,
            role_id=kwargs.get("role_id"),
            parent_task_id=kwargs.get("parent_task_id"),
            environment=kwargs.get("environment"),
        )
        store_handle(handle)
        logger.info("SSH sandbox: started %s on %s pid=%s url=%s", task_id, self._host, pid, url)
        return handle

    def get_opencode_url(self, handle: SandboxHandle) -> str:
        return handle.url or ""

    def pause(self, handle: SandboxHandle) -> SandboxHandle:
        self._require_host()
        if self._is_managed() and handle.sandbox_id == "managed":
            # Logical-only pause: the shared systemd server keeps serving other
            # tasks, so SIGSTOP is off-limits. This task's session simply stops
            # receiving messages.
            handle.state = "paused"
            store_handle(handle)
            logger.info("SSH sandbox managed mode: paused (logical) %s", handle.task_id)
            return handle
        pid = self._require_pid(handle)
        self._run_remote_checked(f"kill -STOP {pid}", f"SIGSTOP pid={pid}")
        handle.state = "paused"
        store_handle(handle)
        logger.info("SSH sandbox: paused %s pid=%s", handle.task_id, pid)
        return handle

    def resume(self, handle: SandboxHandle) -> SandboxHandle:
        self._require_host()
        if self._is_managed() and handle.sandbox_id == "managed":
            handle.state = "running"
            store_handle(handle)
            logger.info("SSH sandbox managed mode: resumed (logical) %s", handle.task_id)
            return handle
        pid = self._require_pid(handle)
        if not self._pid_alive_remote(pid):
            raise RuntimeError(
                f"SSH sandbox: pid {pid} on {self._host} is gone, cannot resume {handle.task_id}"
            )
        self._run_remote_checked(f"kill -CONT {pid}", f"SIGCONT pid={pid}")
        handle.state = "running"
        store_handle(handle)
        logger.info("SSH sandbox: resumed %s pid=%s", handle.task_id, pid)
        return handle

    def kill(self, handle: SandboxHandle) -> None:
        self._require_host()
        if self._is_managed() and handle.sandbox_id == "managed":
            # Kill the *session*, not the shared managed server — other tasks
            # keep running on it.
            logger.info("SSH sandbox managed mode: killed task %s (server stays up)", handle.task_id)
            delete_handle(handle.task_id)
            return
        if handle.sandbox_id:
            try:
                pid = int(handle.sandbox_id)
            except ValueError:
                logger.warning(
                    "SSH sandbox: corrupt sandbox_id %r for %s, skipping remote kill",
                    handle.sandbox_id, handle.task_id,
                )
            else:
                # TERM, brief wait, KILL. Always best-effort; the handle is
                # removed regardless so it can't leak in the session store.
                self._run_remote(
                    f"kill {pid} 2>/dev/null; sleep 1; kill -9 {pid} 2>/dev/null; true",
                    timeout=30,
                )
        delete_handle(handle.task_id)

    def health_check(self, handle: SandboxHandle) -> Dict[str, Any]:
        if not handle.url:
            return {"status": "stopped", "state": handle.state}
        try:
            import httpx
            r = httpx.get(
                f"{handle.url}/api/health", timeout=8,
                auth=("opencode", handle.password or ""),
            )
            if r.status_code == 200:
                return {"status": "ok", "url": handle.url, "state": handle.state}
            # Older opencode builds only answer at /.
            r2 = httpx.get(f"{handle.url}/", timeout=8, auth=("opencode", handle.password or ""))
            return {
                "status": "ok" if r2.status_code == 200 else "error",
                "url": handle.url,
                "http_status": r2.status_code,
                "state": handle.state,
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "state": handle.state}

    def get_log_path(self, handle: SandboxHandle) -> Optional[Path]:
        """Mirror the remote agent.log tail into the local task log dir."""
        if not handle.task_id:
            return None
        log_dir = self._remote_task_log_dir(handle.task_id)
        result = self._run_remote(f"tail -c 200000 {_rp(log_dir + '/agent.log')} 2>/dev/null", timeout=30)
        local = Path(
            handle.log_path
            or (Path.home() / ".memory" / "task_logs" / _safe_id(handle.task_id) / "remote_agent.log")
        )
        try:
            local.parent.mkdir(parents=True, exist_ok=True)
            if result["stdout"]:
                local.write_text(result["stdout"])
            elif not local.exists():
                local.touch()
        except OSError as e:
            logger.warning("SSH sandbox: could not mirror remote log: %s", e)
        return local

    # ------------------------------------------------------------------
    # Shell / filesystem access (routed by SandboxManager)
    # ------------------------------------------------------------------

    def exec(
        self,
        handle: SandboxHandle,
        command: str,
        timeout: int = 60,
        workdir: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_host()
        cwd = workdir or handle.working_dir or "~"
        remote = f"cd {_rp(cwd)} && bash -c {_q(command)}"
        return self._run_remote(remote, timeout=timeout)

    def read_file(self, handle: SandboxHandle, path: str) -> str:
        self._require_host()
        result = self._run_remote(f"cat {_rp(path)}", timeout=60)
        if not result["success"]:
            raise RuntimeError(f"SSH sandbox read_file {path}: {result['stderr'].strip()}")
        return result["stdout"]

    def write_file(self, handle: SandboxHandle, path: str, content: str) -> None:
        self._require_host()
        parent = path.rsplit("/", 1)[0] if "/" in path else "~"
        result = self._run_remote(
            f"mkdir -p {_rp(parent)} && cat > {_rp(path)}",
            input_text=content,
            timeout=60,
        )
        if not result["success"]:
            raise RuntimeError(f"SSH sandbox write_file {path}: {result['stderr'].strip()}")

    def list_files(self, handle: SandboxHandle, path: str) -> List[str]:
        self._require_host()
        result = self._run_remote(f"ls -1 {_rp(path)}", timeout=30)
        if not result["success"]:
            return []
        return [line for line in result["stdout"].splitlines() if line.strip()]
