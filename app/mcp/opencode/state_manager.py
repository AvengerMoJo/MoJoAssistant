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
        Save or update project state (Phase 1: keyed by git_url)

        Args:
            project_state: Project state to save
        """
        from app.mcp.opencode.utils import normalize_git_url

        state = self._read_state()
        git_url = normalize_git_url(project_state.git_url)
        state["projects"][git_url] = project_state.to_dict()
        self._write_state(state)

    def get_project(self, git_url: str) -> Optional[ProjectState]:
        """
        Get project state by git URL (Phase 1 Refactor)

        Args:
            git_url: Git repository URL (will be normalized)

        Returns:
            ProjectState if found, None otherwise
        """
        from app.mcp.opencode.utils import normalize_git_url

        state = self._read_state()
        normalized_url = normalize_git_url(git_url)
        project_data = state["projects"].get(normalized_url)
        if project_data:
            return ProjectState.from_dict(project_data)
        return None

    def get_project_by_name(self, project_name: str) -> Optional[ProjectState]:
        """
        Get project by display name (backward compat helper)

        Note: This is slower than get_project() as it scans all projects.
        Use get_project(git_url) when possible.

        Args:
            project_name: Display name of project

        Returns:
            ProjectState if found, None otherwise
        """
        state = self._read_state()
        for git_url, project_data in state["projects"].items():
            if project_data.get("project_name") == project_name:
                return ProjectState.from_dict(project_data)
        return None

    def delete_project(self, git_url: str):
        """
        Delete project from state (Phase 1: keyed by git_url)

        Args:
            git_url: Git repository URL
        """
        from app.mcp.opencode.utils import normalize_git_url

        state = self._read_state()
        normalized_url = normalize_git_url(git_url)
        if normalized_url in state["projects"]:
            del state["projects"][normalized_url]
            self._write_state(state)

    def list_projects(self) -> List[str]:
        """
        List all git URLs (primary keys)

        Returns:
            List of git URLs
        """
        state = self._read_state()
        return list(state["projects"].keys())

    def update_health_check(self, git_url: str):
        """
        Update last health check timestamp

        Args:
            git_url: Git repository URL
        """
        project = self.get_project(git_url)
        if project:
            project.last_health_check = datetime.utcnow().isoformat()
            self.save_project(project)

    def update_process_status(
        self,
        git_url: str,
        process_type: str,  # "opencode" only (N:1 architecture)
        pid: Optional[int] = None,
        port: Optional[int] = None,
        status: str = None,
        error: Optional[str] = None,
    ):
        """
        Update process status for a project

        Args:
            git_url: Git repository URL
            process_type: "opencode" (mcp_tool is now global, use update_global_mcp_tool_status instead)
            pid: Process ID
            port: Port number
            status: Process status
            error: Error message if failed
        """
        project = self.get_project(git_url)
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
            Dictionary mapping git_urls to ProjectState objects
        """
        state = self._read_state()
        projects = {}
        for git_url, data in state["projects"].items():
            projects[git_url] = ProjectState.from_dict(data)
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
    # State Migration
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

    def _migrate_to_phase1(self):
        """
        Migrate state to Phase 1: project_name keys → git_url keys

        Changes:
        - Re-key projects dict from project_name to git_url
        - Add project_id, base_dir, worktrees fields
        - Rename sandbox_dir → base_dir
        """
        from app.mcp.opencode.utils import normalize_git_url

        state = self._read_state()
        projects = state.get("projects", {})

        # Check if already migrated (if any key looks like a git URL)
        if projects:
            first_key = next(iter(projects))
            if "@" in first_key or first_key.startswith("http"):
                return  # Already migrated

        print("[OpenCode State Manager] Migrating to Phase 1 (git_url keys)...")

        new_projects = {}
        for project_name, project_data in projects.items():
            git_url = project_data.get("git_url")
            if not git_url:
                print(f"  ⚠️  WARNING: Project '{project_name}' has no git_url, skipping")
                continue

            # Normalize git_url
            normalized_url = normalize_git_url(git_url)

            # Migrate fields
            project_data["git_url"] = normalized_url
            project_data["project_name"] = project_name
            project_data["base_dir"] = project_data.get("sandbox_dir")
            project_data["worktrees"] = []
            project_data["project_id"] = None  # Will be set by OpenCode

            # Check for duplicates
            if normalized_url in new_projects:
                print(
                    f"  ⚠️  WARNING: Duplicate git_url detected!\n"
                    f"     Project '{project_name}' has same git_url as existing project.\n"
                    f"     URL: {normalized_url}\n"
                    f"     Keeping first instance only."
                )
                continue

            new_projects[normalized_url] = project_data
            print(f"  ✓ Migrated: {project_name} → {normalized_url}")

        state["projects"] = new_projects
        self._write_state(state)
        print(f"[OpenCode State Manager] Phase 1 migration complete! ({len(new_projects)} projects)")

    def migrate_all(self):
        """Run all migrations in sequence"""
        self._migrate_state_to_n_to_1()
        self._migrate_to_phase1()
