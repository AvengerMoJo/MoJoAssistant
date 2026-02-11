"""
Error classes and error handling utilities for OpenCode Manager

Provides user-friendly error messages with actionable suggestions.

File: app/mcp/opencode/errors.py
"""

from typing import Optional, Dict, Any


class OpenCodeError(Exception):
    """Base exception for OpenCode Manager errors"""

    def __init__(self, message: str, suggestion: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.suggestion = suggestion
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MCP responses"""
        result = {
            "status": "error",
            "message": self.message,
        }
        if self.suggestion:
            result["suggestion"] = self.suggestion
        if self.details:
            result["details"] = self.details
        return result


class ProjectNotFoundError(OpenCodeError):
    """Project does not exist"""

    def __init__(self, git_url: str):
        super().__init__(
            message=f"Project not found for repository: {git_url}",
            suggestion=(
                "The project may not have been started yet. "
                "Use 'opencode_project_start' to initialize this repository."
            ),
            details={"git_url": git_url}
        )


class ProjectAlreadyRunningError(OpenCodeError):
    """Project is already running"""

    def __init__(self, git_url: str, port: int, pid: int):
        super().__init__(
            message=f"Project already running on port {port} (PID: {pid})",
            suggestion=(
                f"The project is already active. "
                f"Use 'opencode_project_status' to check status, "
                f"or 'opencode_project_restart' to restart it."
            ),
            details={
                "git_url": git_url,
                "port": port,
                "pid": pid
            }
        )


class ProjectNotRunningError(OpenCodeError):
    """Project is not currently running"""

    def __init__(self, git_url: str):
        super().__init__(
            message=f"Project is not running: {git_url}",
            suggestion=(
                "The OpenCode server is not active for this project. "
                "Use 'opencode_project_start' to start it."
            ),
            details={"git_url": git_url}
        )


class PortInUseError(OpenCodeError):
    """Requested port is already in use"""

    def __init__(self, port: int):
        super().__init__(
            message=f"Port {port} is already in use",
            suggestion=(
                f"Another process is using port {port}. "
                f"Let OpenCode Manager auto-assign a port, or check what's using this port with: "
                f"'lsof -i :{port}'"
            ),
            details={"port": port}
        )


class SSHKeyError(OpenCodeError):
    """SSH key related error"""

    def __init__(self, message: str, key_path: Optional[str] = None, public_key: Optional[str] = None):
        details = {}
        if key_path:
            details["key_path"] = key_path
        if public_key:
            details["public_key"] = public_key

        super().__init__(
            message=message,
            suggestion=(
                "SSH key issues can usually be resolved by:\n"
                "1. Verifying the key exists and has correct permissions (600)\n"
                "2. Adding the public key to your Git repository's deploy keys\n"
                "3. Testing SSH access: ssh -T git@github.com"
            ),
            details=details
        )


class WorktreeError(OpenCodeError):
    """Git worktree related error"""

    def __init__(self, message: str, worktree_name: Optional[str] = None):
        details = {}
        if worktree_name:
            details["worktree_name"] = worktree_name

        super().__init__(
            message=message,
            suggestion=(
                "Worktree operations require:\n"
                "1. A valid branch name (or leave empty for current branch)\n"
                "2. Unique worktree names within the project\n"
                "3. The project must be running"
            ),
            details=details
        )


class ConfigurationError(OpenCodeError):
    """Configuration file or environment error"""

    def __init__(self, message: str, config_file: Optional[str] = None):
        details = {}
        if config_file:
            details["config_file"] = config_file

        super().__init__(
            message=message,
            suggestion=(
                "Check your configuration:\n"
                "1. Global config: ~/.memory/opencode-manager.env\n"
                "2. Ensure OPENCODE_PASSWORD and MCP_BEARER_TOKEN are set\n"
                "3. Verify OpenCode binary is installed: which opencode"
            ),
            details=details
        )


class InvalidGitUrlError(OpenCodeError):
    """Invalid git URL format"""

    def __init__(self, git_url: str):
        super().__init__(
            message=f"Invalid git URL format: {git_url}",
            suggestion=(
                "Git URLs should be in one of these formats:\n"
                "  - SSH: git@github.com:user/repo.git\n"
                "  - HTTPS: https://github.com/user/repo\n"
                "Both will be normalized to SSH format automatically."
            ),
            details={"git_url": git_url}
        )


class ProcessStartError(OpenCodeError):
    """Failed to start OpenCode process"""

    def __init__(self, message: str, command: Optional[str] = None, stderr: Optional[str] = None):
        details = {}
        if command:
            details["command"] = command
        if stderr:
            details["stderr"] = stderr

        super().__init__(
            message=message,
            suggestion=(
                "Process startup failures are usually caused by:\n"
                "1. OpenCode not installed or not in PATH\n"
                "2. Port already in use\n"
                "3. Invalid configuration\n"
                "4. Insufficient permissions\n\n"
                "Check the stderr output in details for more information."
            ),
            details=details
        )


def format_error_response(error: Exception, git_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Format any exception as a user-friendly MCP response

    Args:
        error: The exception to format
        git_url: Optional git_url to include in response

    Returns:
        Dictionary formatted for MCP response
    """
    if isinstance(error, OpenCodeError):
        return error.to_dict()

    # Generic error formatting
    response = {
        "status": "error",
        "message": str(error),
        "error_type": type(error).__name__,
    }

    if git_url:
        response["git_url"] = git_url

    # Add suggestion based on error type
    if "permission" in str(error).lower():
        response["suggestion"] = (
            "This appears to be a permissions error. "
            "Check file/directory permissions and ensure your user has access."
        )
    elif "not found" in str(error).lower() or "no such file" in str(error).lower():
        response["suggestion"] = (
            "A required file or directory was not found. "
            "Verify the path exists and is accessible."
        )
    elif "connection" in str(error).lower() or "timeout" in str(error).lower():
        response["suggestion"] = (
            "Network connection issue detected. "
            "Check your internet connection and firewall settings."
        )

    return response
