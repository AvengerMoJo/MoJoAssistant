"""
Worktree Manager for OpenCode

Wraps OpenCode's /experimental/worktree API to manage git worktrees (sandboxes).

File: app/mcp/opencode/worktree_manager.py
"""

import base64
import json
from typing import Dict, List, Optional, Tuple, Any
import requests
from requests.auth import HTTPBasicAuth


class WorktreeManager:
    """Manages git worktrees via OpenCode's native API"""

    def __init__(self, logger=None):
        self.logger = logger
        self.session = requests.Session()
        # Configure session
        self.session.headers.update({"Content-Type": "application/json"})

    def _log(self, message: str, level: str = "info"):
        """Log message if logger available"""
        if self.logger:
            getattr(self.logger, level)(f"[Worktree Manager] {message}")

    def _make_request(
        self,
        method: str,
        url: str,
        password: str,
        json_data: Dict = None,
        params: Dict = None,
    ) -> Tuple[bool, Optional[Any], Optional[str]]:
        """
        Make authenticated HTTP request to OpenCode API

        Args:
            method: HTTP method (GET, POST, DELETE, PATCH)
            url: Full URL to endpoint
            password: OpenCode server password
            json_data: JSON body for POST/PATCH
            params: Query parameters

        Returns:
            Tuple of (success, response_data, error_message)
        """
        try:
            auth = HTTPBasicAuth("opencode", password)

            response = self.session.request(
                method=method,
                url=url,
                auth=auth,
                json=json_data,
                params=params,
                timeout=30,
            )

            # Check for HTTP errors
            response.raise_for_status()

            # Parse response
            if response.content:
                try:
                    data = response.json()
                    return (True, data, None)
                except json.JSONDecodeError:
                    # Non-JSON response (e.g., plain text)
                    return (True, response.text, None)
            else:
                # Empty response (e.g., 204 No Content)
                return (True, None, None)

        except requests.exceptions.HTTPError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            self._log(f"HTTP error: {error_msg}", "error")
            return (False, None, error_msg)

        except requests.exceptions.RequestException as e:
            error_msg = f"Request failed: {str(e)}"
            self._log(f"Request error: {error_msg}", "error")
            return (False, None, error_msg)

        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            self._log(f"Unexpected error: {error_msg}", "error")
            return (False, None, error_msg)

    def create_worktree(
        self,
        host: str,
        port: int,
        password: str,
        name: str,
        branch: Optional[str] = None,
        start_command: Optional[str] = None,
    ) -> Tuple[bool, Optional[Dict], Optional[str]]:
        """
        Create a git worktree (sandbox)

        Args:
            host: OpenCode server host (e.g., "localhost", "127.0.0.1")
            port: OpenCode server port
            password: OpenCode server password
            name: Worktree name (must be unique)
            branch: Optional branch to checkout (default: current branch)
            start_command: Optional command to run on creation

        Returns:
            Tuple of (success, worktree_data, error_message)
            worktree_data format: {"name": str, "path": str, "branch": str}
        """
        url = f"http://{host}:{port}/experimental/worktree"

        payload = {"name": name}
        if branch:
            payload["branch"] = branch
        if start_command:
            payload["startCommand"] = start_command

        self._log(f"Creating worktree: {name} (branch: {branch or 'default'})")

        success, data, error = self._make_request("POST", url, password, json_data=payload)

        if success:
            self._log(f"Worktree created: {name}")
        else:
            self._log(f"Failed to create worktree: {error}", "error")

        return (success, data, error)

    def list_worktrees(
        self,
        host: str,
        port: int,
        password: str,
    ) -> Tuple[bool, Optional[List[Dict]], Optional[str]]:
        """
        List all worktrees for the project

        Args:
            host: OpenCode server host
            port: OpenCode server port
            password: OpenCode server password

        Returns:
            Tuple of (success, worktrees_list, error_message)
            worktrees_list format: [{"name": str, "path": str, "branch": str}, ...]
        """
        url = f"http://{host}:{port}/experimental/worktree"

        self._log("Listing worktrees")

        success, data, error = self._make_request("GET", url, password)

        if success:
            # Ensure data is a list
            if isinstance(data, list):
                self._log(f"Found {len(data)} worktree(s)")
                return (True, data, None)
            else:
                # Unexpected response format
                error_msg = f"Unexpected response format: {type(data)}"
                self._log(error_msg, "error")
                return (False, None, error_msg)
        else:
            self._log(f"Failed to list worktrees: {error}", "error")
            return (False, None, error)

    def delete_worktree(
        self,
        host: str,
        port: int,
        password: str,
        directory: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Delete a git worktree (sandbox)

        Args:
            host: OpenCode server host
            port: OpenCode server port
            password: OpenCode server password
            directory: Worktree directory path to delete

        Returns:
            Tuple of (success, error_message)
        """
        url = f"http://{host}:{port}/experimental/worktree"
        payload = {"directory": directory}

        self._log(f"Deleting worktree: {directory}")

        success, data, error = self._make_request("DELETE", url, password, json_data=payload)

        if success:
            self._log(f"Worktree deleted: {directory}")
        else:
            self._log(f"Failed to delete worktree: {error}", "error")

        return (success, error)

    def reset_worktree(
        self,
        host: str,
        port: int,
        password: str,
        name: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Reset a worktree to the default branch (clean state)

        Args:
            host: OpenCode server host
            port: OpenCode server port
            password: OpenCode server password
            name: Worktree name to reset

        Returns:
            Tuple of (success, error_message)
        """
        url = f"http://{host}:{port}/experimental/worktree/reset"
        payload = {"name": name}

        self._log(f"Resetting worktree: {name}")

        success, data, error = self._make_request("POST", url, password, json_data=payload)

        if success:
            self._log(f"Worktree reset: {name}")
        else:
            self._log(f"Failed to reset worktree: {error}", "error")

        return (success, error)

    def get_project_info(
        self,
        host: str,
        port: int,
        password: str,
    ) -> Tuple[bool, Optional[Dict], Optional[str]]:
        """
        Get project information including worktree paths

        Args:
            host: OpenCode server host
            port: OpenCode server port
            password: OpenCode server password

        Returns:
            Tuple of (success, project_data, error_message)
            project_data includes: {id, worktree, sandboxes: [...]}
        """
        url = f"http://{host}:{port}/project/current"

        self._log("Getting project info")

        success, data, error = self._make_request("GET", url, password)

        if success:
            self._log(f"Project ID: {data.get('id', 'unknown')}")
        else:
            self._log(f"Failed to get project info: {error}", "error")

        return (success, data, error)
