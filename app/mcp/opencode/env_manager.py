"""
Environment Configuration Manager

Handles .env file creation, reading, and validation for OpenCode projects.
Secrets are NEVER passed through MCP chat - always stored in .env files.

File: app/mcp/opencode/env_manager.py
"""

import os
import secrets
from pathlib import Path
from typing import Dict, Optional, Tuple
from app.mcp.opencode.models import ProjectConfig


class EnvManager:
    """Manages .env files for OpenCode projects"""

    def __init__(self, memory_root: str = None):
        self.memory_root = Path(memory_root or os.path.expanduser("~/.memory"))
        self.sandboxes_dir = self.memory_root / "opencode-sandboxes"
        self.keys_dir = self.memory_root / "opencode-keys"
        self.template_path = (
            Path(__file__).parent / "templates" / "project.env.template"
        )

    def get_env_path(self, project_name: str) -> Path:
        """Get path to project's .env file"""
        return self.sandboxes_dir / project_name / ".env"

    def env_exists(self, project_name: str) -> bool:
        """Check if .env file exists for project"""
        return self.get_env_path(project_name).exists()

    def read_env(self, project_name: str) -> Dict[str, str]:
        """
        Read .env file and return as dictionary

        Returns:
            Dictionary of environment variables

        Raises:
            FileNotFoundError: If .env file doesn't exist
        """
        env_path = self.get_env_path(project_name)
        if not env_path.exists():
            raise FileNotFoundError(
                f".env file not found at {env_path}\n\n"
                f"Please create it using the template:\n"
                f"cp {self.template_path} {env_path}\n"
                f"Then edit with your configuration."
            )

        env_vars = {}
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue
                # Parse KEY=VALUE
                if "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()

        return env_vars

    def generate_env(
        self, project_name: str, git_url: str, ssh_key_path: Optional[str] = None
    ) -> Tuple[Path, str]:
        """
        Generate .env file for development mode with auto-generated secrets

        Args:
            project_name: Name of the project
            git_url: Git repository URL
            ssh_key_path: Optional SSH key path (will generate if None)

        Returns:
            Tuple of (.env path, warning message)
        """
        env_path = self.get_env_path(project_name)

        # Generate secrets
        password = secrets.token_hex(16)
        bearer_token = secrets.token_hex(32)

        # Use provided SSH key or generate path for new one
        if ssh_key_path is None:
            ssh_key_path = str(self.keys_dir / f"{project_name}-deploy")

        # Create .env content
        content = f"""# OpenCode Project Configuration - AUTO-GENERATED
# ⚠️  WARNING: This file was auto-generated in DEVELOPMENT mode
# Review and customize before production use!
# Location: {env_path}

# Git repository SSH URL
GIT_URL={git_url}

# SSH key for git clone/pull/push
# ⚠️  Key will be auto-generated if it doesn't exist
SSH_KEY_PATH={ssh_key_path}

# OpenCode web server password (auto-generated)
OPENCODE_SERVER_PASSWORD={password}

# MCP tool bearer token (auto-generated)
MCP_TOOL_BEARER_TOKEN={bearer_token}

# Optional: Custom ports (will be auto-assigned if commented out)
# OPENCODE_PORT=4101
# MCP_TOOL_PORT=5101

# Optional: OpenCode binary path
OPENCODE_BIN={os.path.expanduser('~/.bun/bin/opencode')}

# Optional: opencode-mcp-tool path
MCP_TOOL_DIR=/home/alex/Development/Sandbox/opencode-mcp-tool
"""

        # Ensure directory exists
        env_path.parent.mkdir(parents=True, exist_ok=True)

        # Write .env file
        with open(env_path, "w") as f:
            f.write(content)

        # Set restrictive permissions
        os.chmod(env_path, 0o600)

        warning = f"""⚠️  DEVELOPMENT MODE: Auto-generated .env file

Configuration saved to: {env_path}

Auto-generated secrets:
- OpenCode password: {password}
- MCP bearer token: {bearer_token[:16]}... (truncated)

SSH key path: {ssh_key_path}
- Public key will be at: {ssh_key_path}.pub
- You'll need to add the public key to your Git repository

Review the .env file and customize as needed before production use!
"""

        return env_path, warning

    def load_project_config(self, project_name: str) -> ProjectConfig:
        """
        Load project configuration from .env file

        Args:
            project_name: Name of the project

        Returns:
            ProjectConfig object

        Raises:
            FileNotFoundError: If .env doesn't exist
            ValueError: If required fields are missing
        """
        env_vars = self.read_env(project_name)

        # Validate required fields
        required = ["GIT_URL", "SSH_KEY_PATH", "OPENCODE_SERVER_PASSWORD", "MCP_TOOL_BEARER_TOKEN"]
        missing = [key for key in required if key not in env_vars]
        if missing:
            raise ValueError(
                f"Missing required fields in .env: {', '.join(missing)}\n"
                f"Please edit {self.get_env_path(project_name)}"
            )

        # Build sandbox directory path
        sandbox_dir = str(self.sandboxes_dir / project_name)

        # Create ProjectConfig
        config = ProjectConfig(
            project_name=project_name,
            git_url=env_vars["GIT_URL"],
            sandbox_dir=sandbox_dir,
            ssh_key_path=os.path.expanduser(env_vars["SSH_KEY_PATH"]),
            opencode_password=env_vars["OPENCODE_SERVER_PASSWORD"],
            mcp_bearer_token=env_vars["MCP_TOOL_BEARER_TOKEN"],
            opencode_bin=env_vars.get("OPENCODE_BIN", "opencode"),
            mcp_tool_dir=env_vars.get(
                "MCP_TOOL_DIR", "/home/alex/Development/Sandbox/opencode-mcp-tool"
            ),
            opencode_port=int(env_vars["OPENCODE_PORT"])
            if "OPENCODE_PORT" in env_vars
            else None,
            mcp_tool_port=int(env_vars["MCP_TOOL_PORT"])
            if "MCP_TOOL_PORT" in env_vars
            else None,
        )

        return config

    def validate_config(self, config: ProjectConfig) -> Tuple[bool, Optional[str]]:
        """
        Validate project configuration

        Args:
            config: Project configuration to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check SSH key exists
        if config.ssh_key_path and not os.path.exists(config.ssh_key_path):
            return (
                False,
                f"SSH key not found at {config.ssh_key_path}\n"
                f"Generate with: ssh-keygen -t ed25519 -f {config.ssh_key_path}",
            )

        # Check OpenCode binary exists
        opencode_path = config.opencode_bin
        if not opencode_path.startswith("/"):
            # Check if in PATH
            from shutil import which

            if which(opencode_path) is None:
                return (
                    False,
                    f"OpenCode binary '{opencode_path}' not found in PATH\n"
                    f"Please install OpenCode or set OPENCODE_BIN in .env",
                )
        elif not os.path.exists(opencode_path):
            return False, f"OpenCode binary not found at {opencode_path}"

        # Check MCP tool directory exists
        if not os.path.isdir(config.mcp_tool_dir):
            return (
                False,
                f"opencode-mcp-tool directory not found at {config.mcp_tool_dir}\n"
                f"Please clone the repository or set MCP_TOOL_DIR in .env",
            )

        return True, None
