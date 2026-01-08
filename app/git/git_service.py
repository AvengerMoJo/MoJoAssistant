"""
Git Service for MoJoAssistant
Handles git repository management, SSH key storage, and file retrieval
"""

import os
import json
import shutil
import subprocess
import signal
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import logging
from contextlib import contextmanager

# Import GitPython with fallback for optional git features
try:
    from git import Repo, Git
    from git.exc import GitError, InvalidGitRepositoryError

    GIT_AVAILABLE = True
except ImportError:
    # Provide dummy classes when GitPython is not available
    class Repo:
        @classmethod
        def clone_from(cls, *args, **kwargs):
            raise ImportError(
                "GitPython not installed. Install with: pip install GitPython>=3.1.40"
            )

        def __init__(self, *args, **kwargs):
            raise ImportError(
                "GitPython not installed. Install with: pip install GitPython>=3.1.40"
            )

    class Git:
        pass

    class GitError(Exception):
        pass

    class InvalidGitRepositoryError(Exception):
        pass

    GIT_AVAILABLE = False

logger = logging.getLogger(__name__)


class GitService:
    """Git integration service for private repository access"""

    def __init__(self, base_dir: str = ".memory"):
        self.base_dir = Path(base_dir)
        self.git_dir = self.base_dir / "git_repos"
        self.git_dir.mkdir(parents=True, exist_ok=True)

    def add_repository(
        self, repo_name: str, repo_url: str, ssh_key_path: str, branch: str = "main"
    ) -> Dict[str, Any]:
        """
        Register and clone a git repository with SSH key

        Args:
            repo_name: Local name for the repository
            repo_url: Git repository URL (SSH format)
            ssh_key_path: Path to SSH private key file
            branch: Branch to track (default: main)

        Returns:
            Dict with status and repository info
        """
        if not GIT_AVAILABLE:
            return {
                "status": "error",
                "message": "Git features not available. Install GitPython with: pip install GitPython>=3.1.40",
            }

        try:
            repo_path = self.git_dir / repo_name
            config_path = repo_path / "config.json"

            # Create repository directory
            repo_path.mkdir(parents=True, exist_ok=True)

            # Expand SSH key path
            ssh_key_full_path = Path(ssh_key_path).expanduser().absolute()
            if not ssh_key_full_path.exists():
                raise FileNotFoundError(f"SSH key not found: {ssh_key_full_path}")

            if not os.access(ssh_key_full_path, os.R_OK):
                raise PermissionError(f"SSH key is not readable: {ssh_key_full_path}")

            # Check if SSH key has a passphrase
            if self._ssh_key_has_passphrase(ssh_key_full_path):
                raise ValueError(
                    f"SSH key has a passphrase which is not supported. "
                    f"Please use a passwordless SSH key or remove the passphrase from: {ssh_key_full_path}. "
                    f"You can remove the passphrase with: ssh-keygen -p -f {ssh_key_full_path}"
                )

            # Copy SSH key to local storage for security
            local_ssh_key = repo_path / "ssh_key"
            shutil.copy2(ssh_key_full_path, local_ssh_key)
            os.chmod(local_ssh_key, 0o600)  # Secure permissions

            # Configure Git to use SSH key - need to set environment before creating Git object
            ssh_command = f"ssh -i {local_ssh_key} -o StrictHostKeyChecking=no"

            # Set environment variable for this process
            original_ssh_command = os.environ.get("GIT_SSH_COMMAND")
            os.environ["GIT_SSH_COMMAND"] = ssh_command

            try:
                # Clone or update repository
                repo_clone_path = repo_path / "repo"
                if repo_clone_path.exists():
                    # Update existing repo with timeout
                    repo = Repo(repo_clone_path)
                    with self._git_operation_timeout(f"update {repo_name}", 300):
                        repo.remote().pull()
                    logger.info(f"Updated existing repository: {repo_name}")
                else:
                    # Clone new repo with timeout
                    with self._git_operation_timeout(f"clone {repo_name}", 600):
                        Repo.clone_from(repo_url, repo_clone_path, branch=branch)
                    logger.info(f"Cloned new repository: {repo_name}")
            finally:
                # Restore original environment
                if original_ssh_command is None:
                    os.environ.pop("GIT_SSH_COMMAND", None)
                else:
                    os.environ["GIT_SSH_COMMAND"] = original_ssh_command

            # Save configuration
            config = {
                "repo_name": repo_name,
                "repo_url": repo_url,
                "ssh_key_path": str(local_ssh_key),
                "branch": branch,
                "clone_path": str(repo_clone_path),
                "last_updated": self._get_current_timestamp(),
            }

            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)

            return {
                "status": "success",
                "message": f"Repository {repo_name} added successfully",
                "repo_info": {
                    "name": repo_name,
                    "url": repo_url,
                    "branch": branch,
                    "clone_path": str(repo_clone_path),
                },
            }

        except Exception as e:
            logger.error(f"Failed to add repository {repo_name}: {e}")
            return {"status": "error", "message": f"Failed to add repository: {str(e)}"}

    def get_file_content(
        self,
        repo_name: str,
        file_path: str,
        git_hash: Optional[str] = None,
        update_repo: bool = False,
    ) -> Dict[str, Any]:
        """
        Retrieve file content from git repository

        Args:
            repo_name: Name of the registered repository
            file_path: Path to file within repository
            git_hash: Optional specific commit hash (defaults to HEAD)

        Returns:
            Dict with file content and metadata
        """
        if not GIT_AVAILABLE:
            return {
                "status": "error",
                "message": "Git features not available. Install GitPython with: pip install GitPython>=3.1.40",
            }

        try:
            repo_config = self._get_repo_config(repo_name)
            if not repo_config:
                return {
                    "status": "error",
                    "message": f"Repository {repo_name} not found",
                }

            repo_path = Path(repo_config["clone_path"])
            repo = Repo(repo_path)

            # Update repository to latest (optional)
            if update_repo:
                update_result = self._update_repository(repo_name)
                if update_result["status"] != "success":
                    # Continue anyway, but log the warning
                    logger.warning(
                        f"Failed to update repository {repo_name}: {update_result['message']}"
                    )

            # Get file at specific commit or HEAD
            if git_hash:
                try:
                    commit = repo.commit(git_hash)
                    file_blob = commit.tree / file_path
                    content = file_blob.data_stream.read().decode("utf-8")
                    actual_hash = commit.hexsha[:8]
                except Exception:
                    return {
                        "status": "error",
                        "message": f"File {file_path} not found at hash {git_hash}",
                    }
            else:
                # Get from working directory
                full_file_path = repo_path / file_path
                if not full_file_path.exists():
                    return {"status": "error", "message": f"File {file_path} not found"}

                with open(full_file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                # Get current commit hash
                actual_hash = repo.head.commit.hexsha[:8]

            # Get file stats
            file_stats = {
                "size": len(content),
                "lines": content.count("\n") + 1,
                "language": self._detect_language(file_path),
            }

            return {
                "status": "success",
                "content": content,
                "metadata": {
                    "repo": repo_name,
                    "file_path": file_path,
                    "git_hash": actual_hash,
                    "branch": repo_config["branch"],
                    "stats": file_stats,
                    "retrieved_at": self._get_current_timestamp(),
                },
            }

        except Exception as e:
            logger.error(f"Failed to get file {file_path} from {repo_name}: {e}")
            return {"status": "error", "message": f"Failed to retrieve file: {str(e)}"}

    def list_repositories(self) -> Dict[str, Any]:
        """List all registered repositories"""
        try:
            repos = []
            for repo_dir in self.git_dir.iterdir():
                if repo_dir.is_dir():
                    config_path = repo_dir / "config.json"
                    if config_path.exists():
                        with open(config_path, "r") as f:
                            config = json.load(f)

                        # Get current status
                        repo_path = Path(config["clone_path"])
                        status = "active" if repo_path.exists() else "missing"

                        repos.append(
                            {
                                "name": config["repo_name"],
                                "url": config["repo_url"],
                                "branch": config["branch"],
                                "status": status,
                                "last_updated": config.get("last_updated", "unknown"),
                            }
                        )

            return {"status": "success", "repositories": repos, "total": len(repos)}

        except Exception as e:
            logger.error(f"Failed to list repositories: {e}")
            return {
                "status": "error",
                "message": f"Failed to list repositories: {str(e)}",
            }

    def remove_repository(self, repo_name: str) -> Dict[str, Any]:
        """Remove a registered repository"""
        try:
            repo_path = self.git_dir / repo_name
            if repo_path.exists():
                shutil.rmtree(repo_path)
                logger.info(f"Removed repository: {repo_name}")
                return {
                    "status": "success",
                    "message": f"Repository {repo_name} removed",
                }
            else:
                return {
                    "status": "error",
                    "message": f"Repository {repo_name} not found",
                }

        except Exception as e:
            logger.error(f"Failed to remove repository {repo_name}: {e}")
            return {
                "status": "error",
                "message": f"Failed to remove repository: {str(e)}",
            }

    def update_repository(self, repo_name: str) -> Dict[str, Any]:
        """Update repository to latest version"""
        try:
            return self._update_repository(repo_name)
        except Exception as e:
            logger.error(f"Failed to update repository {repo_name}: {e}")
            return {
                "status": "error",
                "message": f"Failed to update repository: {str(e)}",
            }

    def _update_repository(self, repo_name: str) -> Dict[str, Any]:
        """Internal method to update repository"""
        repo_config = self._get_repo_config(repo_name)
        if not repo_config:
            return {"status": "error", "message": f"Repository {repo_name} not found"}

        repo_path = Path(repo_config["clone_path"])
        repo = Repo(repo_path)

        # Configure SSH
        ssh_command = (
            f"ssh -i {repo_config['ssh_key_path']} -o StrictHostKeyChecking=no"
        )

        # Set environment variable for this process
        original_ssh_command = os.environ.get("GIT_SSH_COMMAND")
        os.environ["GIT_SSH_COMMAND"] = ssh_command

        try:
            with self._git_operation_timeout(f"update {repo_name}", 300):
                repo.remote().pull()
        finally:
            # Restore original environment
            if original_ssh_command is None:
                os.environ.pop("GIT_SSH_COMMAND", None)
            else:
                os.environ["GIT_SSH_COMMAND"] = original_ssh_command

        # Update config timestamp
        config_path = self.git_dir / repo_name / "config.json"
        repo_config["last_updated"] = self._get_current_timestamp()
        with open(config_path, "w") as f:
            json.dump(repo_config, f, indent=2)

        return {"status": "success", "message": f"Repository {repo_name} updated"}

    def _get_repo_config(self, repo_name: str) -> Optional[Dict[str, Any]]:
        """Get repository configuration"""
        config_path = self.git_dir / repo_name / "config.json"
        if config_path.exists():
            with open(config_path, "r") as f:
                return json.load(f)
        return None

    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension"""
        ext = Path(file_path).suffix.lower()
        language_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "jsx",
            ".tsx": "tsx",
            ".java": "java",
            ".cpp": "cpp",
            ".c": "c",
            ".cs": "csharp",
            ".go": "go",
            ".rs": "rust",
            ".php": "php",
            ".rb": "ruby",
            ".swift": "swift",
            ".kt": "kotlin",
            ".scala": "scala",
            ".sh": "bash",
            ".sql": "sql",
            ".html": "html",
            ".css": "css",
            ".scss": "scss",
            ".sass": "sass",
            ".less": "less",
            ".json": "json",
            ".xml": "xml",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".toml": "toml",
            ".ini": "ini",
            ".md": "markdown",
            ".txt": "text",
        }
        return language_map.get(ext, "unknown")

    def _get_current_timestamp(self) -> str:
        """Get current timestamp as ISO string"""
        from datetime import datetime

        return datetime.now().isoformat()

    @contextmanager
    def _git_operation_timeout(self, operation_name: str, timeout: int):
        """
        Context manager to timeout git operations

        Args:
            operation_name: Description of the operation for error messages
            timeout: Timeout in seconds

        Raises:
            TimeoutError: If operation exceeds timeout
        """

        class TimeoutException(Exception):
            pass

        def timeout_handler(signum, frame):
            raise TimeoutException(
                f"Git operation '{operation_name}' timed out after {timeout} seconds"
            )

        original_handler = None

        try:
            # Set alarm signal
            original_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout)
            yield
        finally:
            # Cancel alarm and restore original handler
            signal.alarm(0)
            if original_handler is not None:
                signal.signal(signal.SIGALRM, original_handler)

    def _ssh_key_has_passphrase(self, key_path: Path) -> bool:
        """
        Check if SSH key has a passphrase by attempting to extract public key

        Returns:
            True if key has passphrase, False otherwise
        """
        try:
            # Try to extract public key - this will fail if key has passphrase
            result = subprocess.run(
                ["ssh-keygen", "-y", "-f", str(key_path)],
                capture_output=True,
                timeout=5,
                input=b"",  # Empty input to ensure it doesn't hang
            )

            # Check if error message indicates passphrase requirement
            if result.returncode != 0:
                error_msg = result.stderr.decode("utf-8", errors="ignore").lower()
                if "enter passphrase" in error_msg or "passphrase" in error_msg:
                    return True
                # Other errors, might still have passphrase
                return True

            # Command succeeded, key has no passphrase
            return False

        except subprocess.TimeoutExpired:
            # Timeout suggests it's waiting for passphrase input
            return True
        except Exception:
            # Any other error, assume it might have passphrase to be safe
            return True
        except subprocess.CalledProcessError:
            # Command failed, but not due to passphrase timeout
            # Try alternative method
            pass

        # Alternative method: try to use key with ssh-keygen -l
        try:
            result = subprocess.run(
                ["ssh-keygen", "-y", "-f", str(key_path)],
                capture_output=True,
                timeout=5,
            )
            # If succeeds, key has no passphrase
            return False
        except subprocess.TimeoutExpired:
            # Timeout suggests it's waiting for passphrase input
            return True
        except subprocess.CalledProcessError:
            # Command failed, assume it might have passphrase
            return True
