"""
SSH Key Manager

Handles SSH key generation and management for Git repository access.

File: app/mcp/opencode/ssh_manager.py
"""

import os
import subprocess
from pathlib import Path
from typing import Tuple, Optional


class SSHManager:
    """Manages SSH keys for OpenCode projects"""

    def __init__(self, memory_root: str = None):
        self.memory_root = Path(memory_root or os.path.expanduser("~/.memory"))
        self.keys_dir = self.memory_root / "opencode-keys"
        self.keys_dir.mkdir(parents=True, exist_ok=True)

    def generate_key(self, project_name: str) -> Tuple[str, str, str]:
        """
        Generate ed25519 SSH key pair for a project

        Args:
            project_name: Name of the project

        Returns:
            Tuple of (private_key_path, public_key_path, public_key_content)

        Raises:
            RuntimeError: If key generation fails
        """
        private_key_path = self.keys_dir / f"{project_name}-deploy"
        public_key_path = Path(str(private_key_path) + ".pub")

        # Check if key already exists
        if private_key_path.exists():
            # Read existing public key
            if public_key_path.exists():
                with open(public_key_path, "r") as f:
                    public_key_content = f.read().strip()
                return str(private_key_path), str(public_key_path), public_key_content
            else:
                # Private key exists but public key missing - regenerate
                private_key_path.unlink()

        # Generate new key pair
        comment = f"opencode-mcp-{project_name}"
        cmd = [
            "ssh-keygen",
            "-t",
            "ed25519",
            "-f",
            str(private_key_path),
            "-N",
            "",  # No passphrase
            "-C",
            comment,
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True, timeout=30
            )

            # Set restrictive permissions
            os.chmod(private_key_path, 0o600)
            os.chmod(public_key_path, 0o644)

            # Read public key content
            with open(public_key_path, "r") as f:
                public_key_content = f.read().strip()

            return str(private_key_path), str(public_key_path), public_key_content

        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to generate SSH key: {e.stderr}\n"
                f"Command: {' '.join(cmd)}"
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("SSH key generation timed out after 30 seconds")

    def validate_key(self, key_path: str) -> Tuple[bool, Optional[str]]:
        """
        Validate SSH key exists and has correct permissions

        Args:
            key_path: Path to private key

        Returns:
            Tuple of (is_valid, error_message)
        """
        key_path = Path(os.path.expanduser(key_path))

        if not key_path.exists():
            return False, f"SSH key not found at {key_path}"

        if not key_path.is_file():
            return False, f"SSH key path is not a file: {key_path}"

        # Check permissions (should be 600 or more restrictive)
        stat_info = key_path.stat()
        mode = stat_info.st_mode & 0o777
        if mode & 0o077:  # Check if group/other have any permissions
            return (
                False,
                f"SSH key has insecure permissions: {oct(mode)}\n"
                f"Fix with: chmod 600 {key_path}",
            )

        # Check if public key exists
        public_key_path = Path(str(key_path) + ".pub")
        if not public_key_path.exists():
            return (
                False,
                f"Public key not found at {public_key_path}\n"
                f"Regenerate with: ssh-keygen -y -f {key_path} > {public_key_path}",
            )

        return True, None

    def get_public_key(self, private_key_path: str) -> Optional[str]:
        """
        Get public key content from private key path

        Args:
            private_key_path: Path to private key

        Returns:
            Public key content or None if not found
        """
        public_key_path = Path(os.path.expanduser(private_key_path) + ".pub")
        if public_key_path.exists():
            with open(public_key_path, "r") as f:
                return f.read().strip()
        return None

    def test_git_access(self, git_url: str, ssh_key_path: str) -> Tuple[bool, str]:
        """
        Test if SSH key has access to Git repository

        Args:
            git_url: Git repository URL (ssh format)
            ssh_key_path: Path to SSH private key

        Returns:
            Tuple of (has_access, message)
        """
        # Use git ls-remote to test access (lightweight, doesn't clone)
        env = os.environ.copy()
        env["GIT_SSH_COMMAND"] = (
            f"ssh -i {ssh_key_path} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
        )

        cmd = ["git", "ls-remote", git_url, "HEAD"]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30, env=env
            )

            if result.returncode == 0:
                return True, "SSH key has access to repository"
            else:
                return (
                    False,
                    f"SSH key authentication failed:\n{result.stderr.strip()}",
                )

        except subprocess.TimeoutExpired:
            return False, "Git access test timed out after 30 seconds"
        except Exception as e:
            return False, f"Error testing Git access: {str(e)}"
