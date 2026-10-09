"""
Process Manager

Manages OpenCode and opencode-mcp-tool process lifecycle using shell commands.

File: app/mcp/opencode/process_manager.py
"""

import os
import re
import subprocess
import time
import requests
from pathlib import Path
from app.config.paths import get_memory_path
from typing import Optional, Set, Tuple
from app.mcp.opencode.models import ProjectConfig


class ProcessManager:
    """Manages process lifecycle for OpenCode projects"""

    def __init__(self, memory_root: str = None):
        self.memory_root = Path(memory_root or get_memory_path())
        self.logs_dir = self.memory_root / "opencode-logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def find_free_port(self, start_port: int = 4100, end_port: int = 4199) -> int:
        """
        Find a free port in the given range

        Args:
            start_port: Start of port range
            end_port: End of port range

        Returns:
            Free port number

        Raises:
            RuntimeError: If no free port found
        """
        import socket

        for port in range(start_port, end_port + 1):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    continue

        raise RuntimeError(f"No free port found in range {start_port}-{end_port}")

    def kill_process_on_port(self, port: int) -> Tuple[bool, Optional[str]]:
        """
        Kill any process listening on the specified port

        Args:
            port: Port number

        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Find process using the port
            result = subprocess.run(
                f"lsof -ti :{port}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split("\n")
                for pid_str in pids:
                    try:
                        pid = int(pid_str)
                        os.kill(pid, 9)  # SIGKILL
                        time.sleep(0.5)
                    except (ValueError, ProcessLookupError):
                        continue

                return True, None
            else:
                # No process found on port
                return True, None

        except subprocess.TimeoutExpired:
            return False, f"Timeout finding process on port {port}"
        except Exception as e:
            return False, f"Error killing process on port {port}: {str(e)}"

    @staticmethod
    def listening_pids(port: int) -> list:
        """PIDs listening on a TCP port (empty if none or lsof is unavailable)."""
        try:
            out = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return []
        return [int(x) for x in out.stdout.split() if x.strip().isdigit()]

    @staticmethod
    def is_this_projects_server(pid: int, repo_dir: Path) -> bool:
        """True if `pid` is an opencode server whose working directory is this project's repo."""
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            cwd = os.path.realpath(os.readlink(f"/proc/{pid}/cwd"))
        except OSError:
            return False
        return "opencode" in cmd and cwd == os.path.realpath(str(repo_dir))

    @staticmethod
    def opencode_cli_major(opencode_bin: str) -> Optional[int]:
        """Major version of the installed OpenCode CLI (None if it cannot be determined)."""
        try:
            out = subprocess.run([opencode_bin, "--version"], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            return None
        m = re.search(r"v?(\d+)\.\d+", (out.stdout or "") + (out.stderr or ""))
        return int(m.group(1)) if m else None

    @staticmethod
    def launch_spec(major: int) -> Tuple[str, str]:
        """(subcommand, default bind address) for an OpenCode CLI generation.

        v1 started the server with `opencode web --hostname H --port P`, protected by
        OPENCODE_SERVER_PASSWORD. v2 (2.0.x) rejects those flags on `web` ("Unrecognized flag:
        --hostname"); the server is `opencode serve --hostname H --port P`, and it does NOT enforce the
        password (unauthenticated requests get 200), so it is bound to loopback unless explicitly
        overridden with OPENCODE_HOSTNAME.
        """
        return ("serve", "127.0.0.1") if major >= 2 else ("web", "0.0.0.0")

    @staticmethod
    def _log_tail(path: Path, lines: int = 6) -> str:
        try:
            return " | ".join(l.strip() for l in Path(path).read_text(errors="replace").splitlines()[-lines:] if l.strip())
        except OSError:
            return "(no launcher log)"

    def start_opencode(
        self, config: ProjectConfig, repo_dir: Path, reserved_ports: Optional[Set[int]] = None
    ) -> Tuple[int, int, Optional[str]]:
        """
        Start OpenCode web server

        Args:
            config: Project configuration
            repo_dir: Repository directory (working directory for OpenCode)

        Returns:
            Tuple of (pid, port, error_message)
        """
        # Port: user-specified, else deterministic from git_url but probed forward past ports that
        # other projects own (reserved_ports) or that anything is listening on.
        if config.opencode_port:
            port = config.opencode_port
        else:
            # Import here to avoid circular dependency
            from app.mcp.opencode.utils import deterministic_port_for_git_url
            avoid = set(reserved_ports or ())
            avoid |= {p for p in range(4100, 4200) if self.listening_pids(p) and not any(
                self.is_this_projects_server(pid, repo_dir) for pid in self.listening_pids(p))}
            try:
                port = deterministic_port_for_git_url(config.git_url, start_port=4100, port_range=100, avoid=avoid)
            except ValueError as e:
                return 0, 0, str(e)

        # A listener on the port is only cleared if it is THIS project's own stale server. This used
        # to SIGKILL whatever held the port, so two repos that hashed to 4104 killed each other's
        # servers on every start, and could kill an unrelated service.
        for pid in self.listening_pids(port):
            if not self.is_this_projects_server(pid, repo_dir):
                return 0, port, (f"port {port} is held by pid {pid}, which is not this project's OpenCode "
                                 "server; refusing to kill it")
        success, error = self.kill_process_on_port(port)
        if not success:
            return 0, port, error

        log_file = self.logs_dir / f"{config.project_name}-opencode.log"
        pid_file = Path(config.base_dir) / "opencode.pid"

        major = self.opencode_cli_major(config.opencode_bin)
        if major is None:
            return 0, port, f"cannot determine the OpenCode CLI version ('{config.opencode_bin} --version' failed)"
        subcommand, default_host = self.launch_spec(major)
        hostname = os.getenv("OPENCODE_HOSTNAME") or default_host

        # Build command
        # Use pgrep to find actual process PID (not bash wrapper)
        # Set GIT_SSH_COMMAND so OpenCode can use the project's SSH key for git operations
        cmd = f"""cd {repo_dir} && \\
OPENCODE_SERVER_PASSWORD={config.opencode_password} \\
GIT_SSH_COMMAND='ssh -i {config.ssh_key_path} -o StrictHostKeyChecking=accept-new' \\
nohup {config.opencode_bin} {subcommand} \\
  --hostname {hostname} \\
  --port {port} \\
  >> {log_file} 2>&1 & \\
sleep 1 && \\
pgrep -f "opencode.*{subcommand}.*--port {port}" | tail -1 > {pid_file}"""

        try:
            # Execute command
            result = subprocess.run(
                cmd,
                shell=True,
                executable="/bin/bash",
                timeout=30,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return 0, port, f"Failed to start OpenCode: {result.stderr}"

            # Read PID from file
            time.sleep(1)  # Give process time to start and write PID
            if pid_file.exists():
                with open(pid_file, "r") as f:
                    text = f.read().strip()
                if not text.isdigit():
                    # pgrep found nothing: the server exited at once. Say why (the launcher log has it).
                    return 0, port, f"OpenCode exited right after launch; log: {self._log_tail(log_file)}"
                return int(text), port, None
            else:
                return 0, port, "PID file not created"

        except subprocess.TimeoutExpired:
            # Even if timeout, check if PID file was created (process might be running)
            time.sleep(1)
            if pid_file.exists():
                with open(pid_file, "r") as f:
                    pid = int(f.read().strip())
                # Check if process is actually running
                if self.is_process_running(pid):
                    return pid, port, None
                else:
                    return 0, port, "Process started but died immediately"
            return 0, port, "OpenCode start command timed out"
        except Exception as e:
            return 0, port, f"Error starting OpenCode: {str(e)}"

    def start_mcp_tool(
        self, config: ProjectConfig, opencode_port: int
    ) -> Tuple[int, int, Optional[str]]:
        """
        Start opencode-mcp-tool server

        Args:
            config: Project configuration
            opencode_port: Port where OpenCode is running

        Returns:
            Tuple of (pid, port, error_message)
        """
        # Find free port if not specified
        port = config.mcp_tool_port or self.find_free_port(5100, 5199)

        log_file = self.logs_dir / f"{config.project_name}-mcp-tool.log"
        pid_file = Path(config.base_dir) / "mcp-tool.pid"

        # Build command
        # Use pgrep to find actual node process PID (not npm wrapper)
        cmd = f"""cd {config.mcp_tool_dir} && \\
nohup npm run dev:http -- \\
  --bearer-token {config.mcp_bearer_token} \\
  --opencode-url http://127.0.0.1:{opencode_port} \\
  --opencode-password {config.opencode_password} \\
  --port {port} \\
  >> {log_file} 2>&1 & \\
sleep 2 && \\
pgrep -f "node.*index-http.*--port {port}" | tail -1 > {pid_file}"""

        try:
            # Execute command
            result = subprocess.run(
                cmd,
                shell=True,
                executable="/bin/bash",
                timeout=30,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return 0, port, f"Failed to start MCP tool: {result.stderr}"

            # Read PID from file
            time.sleep(2)  # Give process time to start
            if pid_file.exists():
                with open(pid_file, "r") as f:
                    pid = int(f.read().strip())
                return pid, port, None
            else:
                return 0, port, "PID file not created"

        except subprocess.TimeoutExpired:
            # Even if timeout, check if PID file was created (process might be running)
            time.sleep(2)
            if pid_file.exists():
                with open(pid_file, "r") as f:
                    pid = int(f.read().strip())
                # Check if process is actually running
                if self.is_process_running(pid):
                    return pid, port, None
                else:
                    return 0, port, "Process started but died immediately"
            return 0, port, "MCP tool start command timed out"
        except Exception as e:
            return 0, port, f"Error starting MCP tool: {str(e)}"

    def stop_process(self, pid: int, process_name: str) -> Tuple[bool, Optional[str]]:
        """
        Stop a process by PID

        Args:
            pid: Process ID
            process_name: Name for logging

        Returns:
            Tuple of (success, error_message)
        """
        if not self.is_process_running(pid):
            return True, None

        try:
            # Try graceful termination first
            os.kill(pid, 15)  # SIGTERM

            # Wait up to 5 seconds for process to stop
            for _ in range(10):
                time.sleep(0.5)
                if not self.is_process_running(pid):
                    return True, None

            # Force kill if still running
            os.kill(pid, 9)  # SIGKILL
            time.sleep(0.5)

            if not self.is_process_running(pid):
                return True, None
            else:
                return False, f"Failed to stop {process_name} (PID {pid})"

        except ProcessLookupError:
            # Process already dead
            return True, None
        except PermissionError:
            return False, f"Permission denied to stop {process_name} (PID {pid})"
        except Exception as e:
            return False, f"Error stopping {process_name}: {str(e)}"

    def is_process_running(self, pid: Optional[int]) -> bool:
        """
        Check if a process is running

        Args:
            pid: Process ID (can be None)

        Returns:
            True if running, False otherwise
        """
        if pid is None:
            return False

        try:
            # Send signal 0 to check if process exists
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            return False

    def check_opencode_health(
        self, port: int, password: str, timeout: int = 60
    ) -> Tuple[bool, str]:
        """
        Check if OpenCode server is healthy

        Args:
            port: OpenCode port
            password: OpenCode password
            timeout: Timeout in seconds

        Returns:
            Tuple of (is_healthy, message)
        """
        # OpenCode doesn't have a /health endpoint, so we check the root /
        url = f"http://127.0.0.1:{port}/"
        auth = ("opencode", password)

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(url, auth=auth, timeout=5)
                # OpenCode returns 200 with HTML for the web interface
                if response.status_code == 200:
                    return True, "OpenCode is healthy"
            except requests.exceptions.RequestException:
                pass

            time.sleep(2)

        return False, f"OpenCode health check failed after {timeout}s"

    def check_mcp_tool_health(
        self, port: int, bearer_token: str, timeout: int = 60
    ) -> Tuple[bool, str]:
        """
        Check if MCP tool server is healthy

        Args:
            port: MCP tool port
            bearer_token: Bearer token
            timeout: Timeout in seconds

        Returns:
            Tuple of (is_healthy, message)
        """
        url = f"http://127.0.0.1:{port}/health"
        headers = {"Authorization": f"Bearer {bearer_token}"}

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(url, headers=headers, timeout=5)
                if response.status_code == 200:
                    return True, "MCP tool is healthy"
            except requests.exceptions.RequestException:
                pass

            time.sleep(2)

        return False, f"MCP tool health check failed after {timeout}s"

    def clone_repository(
        self, git_url: str, target_dir: Path, ssh_key_path: str
    ) -> Tuple[bool, str]:
        """
        Clone Git repository using SSH key

        Args:
            git_url: Git repository URL
            target_dir: Target directory for clone
            ssh_key_path: Path to SSH private key

        Returns:
            Tuple of (success, message)
        """
        # Ensure parent directory exists
        target_dir.parent.mkdir(parents=True, exist_ok=True)

        # Set up Git SSH command
        env = os.environ.copy()
        env["GIT_SSH_COMMAND"] = (
            f"ssh -i {ssh_key_path} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
        )

        cmd = ["git", "clone", git_url, str(target_dir)]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes
                env=env,
            )

            if result.returncode == 0:
                return True, f"Repository cloned successfully to {target_dir}"
            else:
                return False, f"Git clone failed:\n{result.stderr}"

        except subprocess.TimeoutExpired:
            return False, "Git clone timed out after 5 minutes"
        except Exception as e:
            return False, f"Error cloning repository: {str(e)}"

    # ========================================================================
    # Global MCP Tool Process Management (N:1 Architecture)
    # ========================================================================

    def start_global_mcp_tool(
        self, bearer_token: str, servers_config_path: str, port: int = None
    ) -> Tuple[int, int, Optional[str]]:
        """
        Start global opencode-mcp-tool server

        Args:
            bearer_token: MCP tool bearer token
            servers_config_path: Path to servers configuration JSON
            port: Port to use (will use configured default if None)

        Returns:
            Tuple of (pid, port, error_message)
        """
        # Use configured port from environment, or default to 3005
        if port is None:
            port = int(os.getenv("GLOBAL_MCP_TOOL_PORT", "3005"))

        # Determine coding-agent-mcp binary
        import shutil

        coding_agent_bin = os.getenv("CODING_AGENT_MCP_BIN", "")
        if not coding_agent_bin:
            coding_agent_bin = shutil.which("coding-agent-mcp") or ""
        if not coding_agent_bin:
            return 0, port, "CODING_AGENT_MCP_BIN not set and coding-agent-mcp not found in PATH."

        log_file = self.logs_dir / "global-mcp-tool.log"
        pid_file = Path(self.memory_root) / "global-mcp-tool.pid"

        # Build command for the Python MCP tool
        # NOTE: Bearer token is passed via environment variable (not CLI arg) for security
        cmd = f"""nohup {coding_agent_bin} \\
  --port {port} \\
  --servers-config {servers_config_path} \\
  >> {log_file} 2>&1 & \\
sleep 1 && \\
pgrep -f "coding.agent.mcp.*--port {port}" | tail -1 > {pid_file}"""

        # Prepare environment with bearer token (secure: not visible in ps aux)
        env = os.environ.copy()
        env["MCP_BEARER_TOKEN"] = bearer_token

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                executable="/bin/bash",
                timeout=30,
                capture_output=True,
                text=True,
                env=env,  # Pass bearer token via environment
            )

            if result.returncode != 0:
                return 0, port, f"Failed to start global MCP tool: {result.stderr}"

            # Read PID from file
            time.sleep(2)  # Give process time to start
            if pid_file.exists():
                with open(pid_file, "r") as f:
                    pid = int(f.read().strip())
                return pid, port, None
            else:
                return 0, port, "PID file not created"

        except subprocess.TimeoutExpired:
            # Check if PID file was created
            time.sleep(2)
            if pid_file.exists():
                with open(pid_file, "r") as f:
                    pid = int(f.read().strip())
                if self.is_process_running(pid):
                    return pid, port, None
                else:
                    return 0, port, "Process started but died immediately"
            return 0, port, "Global MCP tool start command timed out"
        except Exception as e:
            return 0, port, f"Error starting global MCP tool: {str(e)}"

    def check_global_mcp_tool_health(
        self, port: int, bearer_token: str, timeout: int = 60
    ) -> Tuple[bool, str]:
        """
        Check if global MCP tool server is healthy

        Args:
            port: MCP tool port
            bearer_token: Bearer token for authentication
            timeout: Timeout in seconds

        Returns:
            Tuple of (is_healthy, message)
        """
        url = f"http://127.0.0.1:{port}/health"
        headers = {"Authorization": f"Bearer {bearer_token}"}

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(url, headers=headers, timeout=5)
                if response.status_code == 200:
                    return True, "Global MCP tool is healthy"
            except requests.exceptions.RequestException:
                pass

            time.sleep(2)

        return False, f"Global MCP tool health check failed after {timeout}s"
