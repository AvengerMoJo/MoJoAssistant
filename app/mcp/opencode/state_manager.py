"""
State Manager for OpenCode Projects

Manages persistent state in ~/.memory/opencode-state.json

File: app/mcp/opencode/state_manager.py
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime
from app.mcp.opencode.models import ProjectState


class StateManager:
    """Manages persistent state for OpenCode projects"""

    def __init__(self, memory_root: str = None):
        self.memory_root = Path(memory_root or os.path.expanduser("~/.memory"))
        self.state_file = self.memory_root / "opencode-state.json"
        self._ensure_state_file()

    def _ensure_state_file(self):
        """Ensure state file and directory exist"""
        self.memory_root.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            self._write_state({"projects": {}})

    def _read_state(self) -> Dict:
        """Read state from JSON file"""
        try:
            with open(self.state_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            # Corrupted or missing, reset
            return {"projects": {}}

    def _write_state(self, state: Dict):
        """Write state to JSON file"""
        with open(self.state_file, "w") as f:
            json.dump(state, f, indent=2)
        # Restrictive permissions
        os.chmod(self.state_file, 0o600)

    def save_project(self, project_state: ProjectState):
        """
        Save or update project state

        Args:
            project_state: Project state to save
        """
        state = self._read_state()
        state["projects"][project_state.project_name] = project_state.to_dict()
        self._write_state(state)

    def get_project(self, project_name: str) -> Optional[ProjectState]:
        """
        Get project state by name

        Args:
            project_name: Name of the project

        Returns:
            ProjectState if found, None otherwise
        """
        state = self._read_state()
        project_data = state["projects"].get(project_name)
        if project_data:
            return ProjectState.from_dict(project_data)
        return None

    def delete_project(self, project_name: str):
        """
        Delete project from state

        Args:
            project_name: Name of the project
        """
        state = self._read_state()
        if project_name in state["projects"]:
            del state["projects"][project_name]
            self._write_state(state)

    def list_projects(self) -> List[str]:
        """
        List all project names

        Returns:
            List of project names
        """
        state = self._read_state()
        return list(state["projects"].keys())

    def update_health_check(self, project_name: str):
        """
        Update last health check timestamp

        Args:
            project_name: Name of the project
        """
        project = self.get_project(project_name)
        if project:
            project.last_health_check = datetime.utcnow().isoformat()
            self.save_project(project)

    def update_process_status(
        self,
        project_name: str,
        process_type: str,  # "opencode" or "mcp_tool"
        pid: Optional[int] = None,
        port: Optional[int] = None,
        status: str = None,
        error: Optional[str] = None,
    ):
        """
        Update process status for a project

        Args:
            project_name: Name of the project
            process_type: "opencode" or "mcp_tool"
            pid: Process ID
            port: Port number
            status: Process status
            error: Error message if failed
        """
        project = self.get_project(project_name)
        if not project:
            return

        process_info = (
            project.opencode if process_type == "opencode" else project.mcp_tool
        )

        if pid is not None:
            process_info.pid = pid
        if port is not None:
            process_info.port = port
        if status is not None:
            process_info.status = status
        if error is not None:
            process_info.last_error = error
        if status == "running":
            process_info.started_at = datetime.utcnow().isoformat()

        self.save_project(project)

    def get_all_projects(self) -> Dict[str, ProjectState]:
        """
        Get all projects

        Returns:
            Dictionary mapping project names to ProjectState objects
        """
        state = self._read_state()
        projects = {}
        for name, data in state["projects"].items():
            projects[name] = ProjectState.from_dict(data)
        return projects
