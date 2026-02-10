"""
OpenCode Manager Data Models

File: app/mcp/opencode/models.py
"""

from dataclasses import dataclass, asdict, field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum


class ProcessStatus(str, Enum):
    """Status of a managed process"""

    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass
class ProcessInfo:
    """Information about a managed process"""

    pid: Optional[int] = None
    port: Optional[int] = None
    status: ProcessStatus = ProcessStatus.UNKNOWN
    started_at: Optional[str] = None
    last_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)


@dataclass
class GlobalMCPToolInfo:
    """Information about the global MCP tool instance"""

    pid: Optional[int] = None
    port: Optional[int] = None
    status: ProcessStatus = ProcessStatus.STOPPED
    error: Optional[str] = None
    started_at: Optional[str] = None
    last_health_check: Optional[str] = None
    active_project_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "pid": self.pid,
            "port": self.port,
            "status": self.status.value,
            "error": self.error,
            "started_at": self.started_at,
            "last_health_check": self.last_health_check,
            "active_project_count": self.active_project_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GlobalMCPToolInfo":
        """Create from dictionary"""
        return cls(
            pid=data.get("pid"),
            port=data.get("port"),
            status=ProcessStatus(data.get("status", "stopped")),
            error=data.get("error"),
            started_at=data.get("started_at"),
            last_health_check=data.get("last_health_check"),
            active_project_count=data.get("active_project_count", 0),
        )


@dataclass
class ProjectConfig:
    """Configuration for an OpenCode project (Phase 1 Refactor)"""

    git_url: str  # PRIMARY KEY: Normalized git remote URL
    project_id: Optional[str] = None  # OpenCode's project ID (hash of git URL)
    base_dir: str = None  # Base directory where repo is cloned
    project_name: Optional[str] = None  # Display name (generated from git_url)
    worktrees: List[str] = None  # List of worktree names/paths
    ssh_key_path: Optional[str] = None
    opencode_password: Optional[str] = None
    mcp_bearer_token: Optional[str] = None
    opencode_bin: str = "opencode"
    mcp_tool_dir: str = "/home/alex/Development/Sandbox/opencode-mcp-tool"
    opencode_port: Optional[int] = None

    def __post_init__(self):
        if self.worktrees is None:
            self.worktrees = []
        if self.project_name is None:
            # Generate from git_url
            from app.mcp.opencode.utils import generate_project_name
            self.project_name = generate_project_name(self.git_url)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)


@dataclass
class ProjectState:
    """Complete state of a managed project (Phase 1 Refactor)"""

    git_url: str  # PRIMARY KEY: Normalized git remote URL
    project_id: Optional[str] = None  # OpenCode's project ID
    base_dir: str = None  # Base directory where repo is cloned
    project_name: Optional[str] = None  # Display name (backward compat)
    worktrees: List[str] = None  # List of worktree names
    ssh_key_path: Optional[str] = None
    opencode: ProcessInfo = None
    created_at: Optional[str] = None
    last_health_check: Optional[str] = None

    # Deprecated fields (backward compat, will be removed in Phase 2)
    sandbox_dir: Optional[str] = None  # Use base_dir instead

    def __post_init__(self):
        if self.opencode is None:
            self.opencode = ProcessInfo()
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()
        if self.worktrees is None:
            self.worktrees = []
        if self.project_name is None:
            from app.mcp.opencode.utils import generate_project_name
            self.project_name = generate_project_name(self.git_url)
        # Migrate sandbox_dir → base_dir
        if self.base_dir is None and self.sandbox_dir:
            self.base_dir = self.sandbox_dir

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = {
            "git_url": self.git_url,
            "project_id": self.project_id,
            "base_dir": self.base_dir,
            "project_name": self.project_name,
            "worktrees": self.worktrees,
            "ssh_key_path": self.ssh_key_path,
            "opencode": self.opencode.to_dict(),
            "created_at": self.created_at,
            "last_health_check": self.last_health_check,
        }
        # Backward compat: include sandbox_dir if base_dir exists
        if self.base_dir:
            data["sandbox_dir"] = self.base_dir
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectState":
        """Create from dictionary (handles both old and new formats)"""
        opencode_data = data.get("opencode", {})

        return cls(
            git_url=data.get("git_url") or data.get("git_url", ""),
            project_id=data.get("project_id"),
            base_dir=data.get("base_dir") or data.get("sandbox_dir"),
            project_name=data.get("project_name"),
            worktrees=data.get("worktrees", []),
            ssh_key_path=data.get("ssh_key_path"),
            opencode=ProcessInfo(
                pid=opencode_data.get("pid"),
                port=opencode_data.get("port"),
                status=ProcessStatus(opencode_data.get("status", "unknown")),
                started_at=opencode_data.get("started_at"),
                last_error=opencode_data.get("last_error"),
            ),
            created_at=data.get("created_at"),
            last_health_check=data.get("last_health_check"),
            sandbox_dir=data.get("sandbox_dir"),  # For backward compat
        )
