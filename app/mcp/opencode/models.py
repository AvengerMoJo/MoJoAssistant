"""
OpenCode Manager Data Models

File: app/mcp/opencode/models.py
"""

from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
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
class ProjectConfig:
    """Configuration for an OpenCode project"""

    project_name: str
    git_url: str
    sandbox_dir: str
    ssh_key_path: Optional[str] = None
    opencode_password: Optional[str] = None
    mcp_bearer_token: Optional[str] = None
    opencode_bin: str = "opencode"
    mcp_tool_dir: str = "/home/alex/Development/Sandbox/opencode-mcp-tool"
    opencode_port: Optional[int] = None
    mcp_tool_port: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)


@dataclass
class ProjectState:
    """Complete state of a managed project"""

    project_name: str
    sandbox_dir: str
    git_url: str
    ssh_key_path: Optional[str] = None
    opencode: ProcessInfo = None
    mcp_tool: ProcessInfo = None
    created_at: Optional[str] = None
    last_health_check: Optional[str] = None

    def __post_init__(self):
        if self.opencode is None:
            self.opencode = ProcessInfo()
        if self.mcp_tool is None:
            self.mcp_tool = ProcessInfo()
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = {
            "project_name": self.project_name,
            "sandbox_dir": self.sandbox_dir,
            "git_url": self.git_url,
            "ssh_key_path": self.ssh_key_path,
            "opencode": self.opencode.to_dict(),
            "mcp_tool": self.mcp_tool.to_dict(),
            "created_at": self.created_at,
            "last_health_check": self.last_health_check,
        }
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectState":
        """Create from dictionary"""
        opencode_data = data.get("opencode", {})
        mcp_tool_data = data.get("mcp_tool", {})

        return cls(
            project_name=data["project_name"],
            sandbox_dir=data["sandbox_dir"],
            git_url=data["git_url"],
            ssh_key_path=data.get("ssh_key_path"),
            opencode=ProcessInfo(
                pid=opencode_data.get("pid"),
                port=opencode_data.get("port"),
                status=ProcessStatus(opencode_data.get("status", "unknown")),
                started_at=opencode_data.get("started_at"),
                last_error=opencode_data.get("last_error"),
            ),
            mcp_tool=ProcessInfo(
                pid=mcp_tool_data.get("pid"),
                port=mcp_tool_data.get("port"),
                status=ProcessStatus(mcp_tool_data.get("status", "unknown")),
                started_at=mcp_tool_data.get("started_at"),
                last_error=mcp_tool_data.get("last_error"),
            ),
            created_at=data.get("created_at"),
            last_health_check=data.get("last_health_check"),
        )
