"""
Process Manager

Manages OpenCode and opencode-mcp-tool process lifecycle using shell commands.

File: app/mcp/opencode/process_manager.py
"""

import os
import subprocess
import time
import requests
from pathlib import Path
from typing import Tuple, Optional
from app.mcp.opencode.models import ProjectConfig


class ProcessManager:
    """Manages process lifecycle for OpenCode projects"""

    def __init__(self, memory_root: str = None):
        self.memory_root = Path(memory_root or os.path.expanduser("~/.memory"))
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

    def start_opencode(
        self, config: ProjectConfig, repo_dir: Path
    ) -> Tuple[int, int, Optional[str]]:
        """
        Start OpenCode web server

        Args:
            config: Project configuration
            repo_dir: Repository directory (working directory for OpenCode)

        Returns:
            Tuple of (pid, port, error_message)
        """
        # Find free port if not specified
        port = config.opencode_port or self.find_free_port(4100, 4199)

        log_file = self.logs_dir / f"{config.project_name}-opencode.log"
        pid_file = Path(config.sandbox_dir) / "opencode.pid"

        # Build command
        cmd = f"""cd {repo_dir} && \\
OPENCODE_SERVER_PASSWORD={config.opencode_password} \\
nohup {config.opencode_bin} web \\
  --hostname 127.0.0.1 \\
  --port {port} \\
  >> {log_file} 2>&1 & \\
echo $! > {pid_file}"""

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
                    pid = int(f.read().strip())
                return pid, port, None
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
        pid_file = Path(config.sandbox_dir) / "mcp-tool.pid"

        # Build command
        cmd = f"""cd {config.mcp_tool_dir} && \\
nohup npm run dev:http -- \\
  --bearer-token {config.mcp_bearer_token} \\
  --opencode-url http://127.0.0.1:{opencode_port} \\
  --opencode-password {config.opencode_password} \\
  --port {port} \\
  >> {log_file} 2>&1 & \\
echo $! > {pid_file}"""

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
            time.sleep(2)  # Give npm time to start
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
            port: Port to use (will find free port if None)

        Returns:
            Tuple of (pid, port, error_message)
        """
        port = port or self.find_free_port(5100, 5199)

        # Determine MCP tool directory from environment or default
        mcp_tool_dir = os.getenv(
            "OPENCODE_MCP_TOOL_PATH",
            "/home/alex/Development/Sandbox/opencode-mcp-tool",
        )

        log_file = self.logs_dir / "global-mcp-tool.log"
        pid_file = Path(self.memory_root) / "global-mcp-tool.pid"

        # Build command for multi-server mode
        cmd = f"""cd {mcp_tool_dir} && \\
nohup npm run dev:http -- \\
  --bearer-token {bearer_token} \\
  --servers-config {servers_config_path} \\
  >> {log_file} 2>&1 & \\
echo $! > {pid_file}"""

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                executable="/bin/bash",
                timeout=30,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return 0, port, f"Failed to start global MCP tool: {result.stderr}"

            # Read PID from file
            time.sleep(2)  # Give npm time to start
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
        self, port: int, timeout: int = 60
    ) -> Tuple[bool, str]:
        """
        Check if global MCP tool server is healthy

        Args:
            port: MCP tool port
            timeout: Timeout in seconds

        Returns:
            Tuple of (is_healthy, message)
        """
        # Note: We don't use bearer token for health check
        # The opencode-mcp-tool /health endpoint should be public
        url = f"http://127.0.0.1:{port}/health"

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    return True, "Global MCP tool is healthy"
            except requests.exceptions.RequestException:
                pass

            time.sleep(2)

        return False, f"Global MCP tool health check failed after {timeout}s"
