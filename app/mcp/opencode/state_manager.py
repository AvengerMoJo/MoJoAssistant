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
from app.mcp.opencode.models import ProjectState, GlobalMCPToolInfo, ProcessStatus


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
            self._write_state({"global_mcp_tool": None, "projects": {}})
        else:
            # Migrate old state format if needed
            self._migrate_state_to_n_to_1()

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
        process_type: str,  # "opencode" only (N:1 architecture)
        pid: Optional[int] = None,
        port: Optional[int] = None,
        status: str = None,
        error: Optional[str] = None,
    ):
        """
        Update process status for a project

        Args:
            project_name: Name of the project
            process_type: "opencode" (mcp_tool is now global, use update_global_mcp_tool_status instead)
            pid: Process ID
            port: Port number
            status: Process status
            error: Error message if failed
        """
        project = self.get_project(project_name)
        if not project:
            return

        if process_type != "opencode":
            # N:1 architecture - mcp_tool is global now
            return

        process_info = project.opencode

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

    # ========================================================================
    # Global MCP Tool State Management (N:1 Architecture)
    # ========================================================================

    def get_global_mcp_tool(self) -> Optional[GlobalMCPToolInfo]:
        """Get global MCP tool state"""
        state = self._read_state()
        if "global_mcp_tool" not in state or state["global_mcp_tool"] is None:
            return None
        return GlobalMCPToolInfo.from_dict(state["global_mcp_tool"])

    def save_global_mcp_tool(self, mcp_tool_info: GlobalMCPToolInfo):
        """Save global MCP tool state"""
        state = self._read_state()
        state["global_mcp_tool"] = mcp_tool_info.to_dict()
        self._write_state(state)

    def update_global_mcp_tool_status(self, **kwargs):
        """Update specific fields of global MCP tool"""
        mcp_tool = self.get_global_mcp_tool() or GlobalMCPToolInfo()
        for key, value in kwargs.items():
            if hasattr(mcp_tool, key):
                setattr(mcp_tool, key, value)
        self.save_global_mcp_tool(mcp_tool)

    def increment_active_projects(self):
        """Increment active project count"""
        mcp_tool = self.get_global_mcp_tool() or GlobalMCPToolInfo()
        mcp_tool.active_project_count += 1
        self.save_global_mcp_tool(mcp_tool)

    def decrement_active_projects(self):
        """Decrement active project count"""
        mcp_tool = self.get_global_mcp_tool()
        if mcp_tool and mcp_tool.active_project_count > 0:
            mcp_tool.active_project_count -= 1
            self.save_global_mcp_tool(mcp_tool)

    # ========================================================================
    # State Migration (1:1 → N:1 Architecture)
    # ========================================================================

    def _migrate_state_to_n_to_1(self):
        """
        Migrate old state format (1:1) to N:1 architecture

        Changes:
        - Add global_mcp_tool section
        - Remove mcp_tool from each project
        - Set active_project_count to number of running OpenCode instances
        """
        state = self._read_state()

        # Check if already migrated
        if "global_mcp_tool" in state:
            return  # Already migrated

        print("[OpenCode State Manager] Migrating state to N:1 architecture...")

        # Create global MCP tool entry (stopped initially)
        state["global_mcp_tool"] = {
            "pid": None,
            "port": None,
            "status": "stopped",
            "error": None,
            "started_at": None,
            "last_health_check": None,
            "active_project_count": 0,
        }

        # Remove mcp_tool from each project (if exists)
        for project_name, project_data in state.get("projects", {}).items():
            if "mcp_tool" in project_data:
                del project_data["mcp_tool"]
                print(f"  - Removed mcp_tool from project: {project_name}")

        self._write_state(state)
        print("[OpenCode State Manager] Migration complete!")
