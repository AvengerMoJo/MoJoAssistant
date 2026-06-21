"""Per-task OpenCode backend — spawns one OpenCode process per scheduler task.

Replaces the long-running shared OpenCode model with task-scoped instances.
Each task gets:
  - Its own CWD (the working_dir from the task config)
  - Its own port (4400-4499 range, separate from shared sandboxes)
  - Its own log file at ~/.memory/task_logs/<task_id>/agent.log
  - Its own pid/pgid files for clean process group kill
  - Random OpenCode password (not shared across tasks)
  - Lifecycle bound to the scheduler task — kill on task end

Public API:
  backend = OpenCodePerTaskBackend()
  info = backend.spawn(task_id="cs-abc", working_dir="/path/to/project")
  backend.status(task_id)
  backend.kill(task_id)  # clean process group kill + cleanup
"""
from __future__ import annotations

import logging
import os
import secrets
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Port range dedicated to per-task OpenCode instances.
# Separate from SandboxManager's 4100-4299 range so they don't collide.
_TASK_PORT_START = 4400
_TASK_PORT_END = 4499

# Per-task log dir base
_TASK_LOG_DIR = Path.home() / ".memory" / "task_logs"

# OpenCode server health timeout
_HEALTH_TIMEOUT = 20

# OpenCode binary location (same as ProcessBackend)
_OPENCODE_BIN = os.path.expanduser("~/.bun/bin/opencode")


@dataclass
class TaskInstance:
    """One running per-task OpenCode instance."""
    task_id: str
    working_dir: str
    port: int
    pid: int
    pgid: int
    password: str
    log_path: str
    started_at: float
    task_dir: str  # base dir for pid/pgid files


def _is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _allocate_port() -> int:
    """Find a free port in the per-task range.

    Returns the lowest free port, or raises if range is exhausted.
    """
    for port in range(_TASK_PORT_START, _TASK_PORT_END + 1):
        if _is_port_free(port):
            return port
    raise RuntimeError(
        f"No free port in {_TASK_PORT_START}-{_TASK_PORT_END} for per-task OpenCode. "
        "Kill stale instances or extend the range."
    )


def _wait_healthy(port: int, password: str, timeout: float = _HEALTH_TIMEOUT) -> bool:
    """Poll OpenCode's / endpoint until it answers (or timeout)."""
    import base64
    auth = f"opencode:{password}".encode()
    auth_header = f"Basic {base64.b64encode(auth).decode()}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/",
                headers={"Authorization": auth_header},
            )
            urllib.request.urlopen(req, timeout=2).read()
            return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.5)
    return False


def _pid_alive(pid: int) -> bool:
    """Check if a process is alive.

    Note: os.kill(pid, 0) alone is unreliable — kernel can recycle the PID
    to a different process after our process exits. To be sure, we read
    /proc/<pid>/cmdline and check the process name. But the simplest reliable
    check is to send signal 0 AND verify via /proc/<pid>/status that it's not
    a zombie. For our use case (a freshly-spawned OpenCode), the simple
    os.kill(0) check is good enough as long as we keep our own state in sync
    — the worst case is a false "alive" that resolves on the next health poll.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # Confirm via /proc that the PID is a real process, not a recycled zombie.
    # If /proc/<pid> exists and state is Z (zombie), the process is dead.
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("State:"):
                    state = line.split(":", 1)[1].strip().split()[0]
                    return state != "Z"  # Z = zombie (dead but reaped-pending)
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return False
    return True


class OpenCodePerTaskBackend:
    """Spawn one OpenCode process per scheduler task."""

    def __init__(self) -> None:
        # In-memory registry of live instances for status checks
        self._instances: dict = {}

    # ------------------------------------------------------------------
    #  spawn                                                              #
    # ------------------------------------------------------------------

    def spawn(self, task_id: str, working_dir: str) -> TaskInstance:
        """Start a new OpenCode instance for the task.

        Returns the TaskInstance info. Raises on failure.
        Does NOT clone or init git — caller is responsible for project setup.
        """
        if task_id in self._instances and _pid_alive(self._instances[task_id].pid):
            logger.info("PerTaskBackend.spawn: %s already running, returning existing", task_id)
            return self._instances[task_id]

        working_path = Path(working_dir)
        if not working_path.is_dir():
            raise RuntimeError(
                f"working_dir does not exist: {working_dir}. "
                "Create the directory first, or use a different start_new path."
            )

        # Set up per-task directory
        task_dir = _TASK_LOG_DIR / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        log_path = task_dir / "agent.log"
        pid_path = task_dir / "agent.pid"
        pgid_path = task_dir / "agent.pgid"

        port = _allocate_port()
        password = secrets.token_urlsafe(16)
        cmd = [_OPENCODE_BIN, "--port", str(port), "--hostname", "127.0.0.1", "serve"]

        env = os.environ.copy()
        env["OPENCODE_SERVER_PASSWORD"] = password

        logger.info(
            "PerTaskBackend.spawn: task=%s cwd=%s port=%d log=%s",
            task_id, working_dir, port, log_path,
        )

        # Open the log file and keep the handle open — Popen holds a reference
        # via stdout/stderr. Closing too early would race with the child.
        logf = open(log_path, "a")
        logf.write(
            f"\n=== PerTaskBackend spawning task={task_id} port={port} at {time.ctime()} ===\n"
        )
        logf.flush()
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(working_path),
                env=env,
                stdout=logf,
                stderr=logf,
                start_new_session=True,  # new session = new pgid
            )
        except Exception:
            logf.close()
            raise

        pid_path.write_text(str(proc.pid))
        pgid_path.write_text(str(proc.pid))  # start_new_session: pid == pgid
        logf.write(
            f"=== spawned pid={proc.pid} pgid={proc.pid} ===\n"
        )
        logf.flush()

        # Wait for healthy
        if not _wait_healthy(port, password):
            self._kill_process_group(proc.pid)
            logf.close()
            raise RuntimeError(
                f"OpenCode did not become healthy on port {port} within {_HEALTH_TIMEOUT}s. "
                f"Check {log_path}"
            )

        logf.write(f"=== OpenCode healthy on port {port} ===\n")
        logf.flush()

        instance = TaskInstance(
            task_id=task_id,
            working_dir=working_dir,
            port=port,
            pid=proc.pid,
            pgid=proc.pid,
            password=password,
            log_path=str(log_path),
            started_at=time.time(),
            task_dir=str(task_dir),
        )
        self._instances[task_id] = instance
        logger.info("PerTaskBackend.spawn: %s ready on port %d", task_id, port)
        # Note: logf is intentionally NOT closed — Popen holds a reference and
        # the OS will release the FD when the child exits.
        return instance

    # ------------------------------------------------------------------
    #  status                                                             #
    # ------------------------------------------------------------------

    def status(self, task_id: str):
        """Return the live instance if the process is still alive, else None."""
        inst = self._instances.get(task_id)
        if inst and _pid_alive(inst.pid):
            return inst
        if task_id in self._instances:
            self._instances.pop(task_id, None)
        return None

    def url(self, task_id: str):
        """Return the OpenCode URL for the task, or None if not running."""
        inst = self.status(task_id)
        return f"http://127.0.0.1:{inst.port}" if inst else None

    def password(self, task_id: str):
        inst = self._instances.get(task_id)
        return inst.password if inst else None

    # ------------------------------------------------------------------
    #  kill                                                               #
    # ------------------------------------------------------------------

    def kill(self, task_id: str) -> bool:
        """Kill the OpenCode process group for this task. Idempotent.

        Always attempts the kill (since the process could be in any state),
        then checks if it really died. We don't short-circuit on _pid_alive
        because in fast-test environments PIDs get recycled, making the
        pre-check unreliable.
        """
        inst = self._instances.get(task_id)
        if not inst:
            return False

        # Try the kill regardless of pre-check — process group kill is safe
        # even if the process is already dead
        try:
            self._kill_process_group(inst.pid)
            logger.info("PerTaskBackend.kill: task=%s pid=%d", task_id, inst.pid)
        except Exception as e:
            logger.warning("PerTaskBackend.kill failed for %s: %s", task_id, e)
        finally:
            self._instances.pop(task_id, None)
        return True

    def kill_all(self) -> int:
        """Kill all per-task instances. Used on server shutdown."""
        count = 0
        for task_id in list(self._instances.keys()):
            if self.kill(task_id):
                count += 1
        return count

    def _kill_process_group(self, pid: int) -> None:
        """SIGTERM the whole process group, wait, then SIGKILL if needed."""
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                return
        for _ in range(10):
            time.sleep(0.3)
            if not _pid_alive(pid):
                return
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                return

    # ------------------------------------------------------------------
    #  info                                                               #
    # ------------------------------------------------------------------

    def list(self) -> list:
        """Return all live instances."""
        alive = []
        for task_id in list(self._instances.keys()):
            inst = self.status(task_id)
            if inst:
                alive.append(inst)
        return alive
