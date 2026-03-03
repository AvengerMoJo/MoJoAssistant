"""
Claude Code Manager Data Models

File: app/mcp/claude_code/models.py
"""

from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
from datetime import datetime


@dataclass
class SessionConfig:
    """Configuration for a Claude Code session"""

    session_id: str
    working_dir: str
    model: str = "claude-sonnet-4-5-20250929"
    claude_bin: str = ""  # Path to claude binary (auto-detected via shutil.which)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SessionState:
    """Persistent state for a Claude Code session"""

    session_id: str
    status: str = "stopped"  # stopped, running, failed
    pid: int = 0
    working_dir: str = ""
    model: str = ""
    created_at: str = ""
    stopped_at: str = ""
    error: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "pid": self.pid,
            "working_dir": self.working_dir,
            "model": self.model,
            "created_at": self.created_at,
            "stopped_at": self.stopped_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionState":
        return cls(
            session_id=data.get("session_id", ""),
            status=data.get("status", "stopped"),
            pid=data.get("pid", 0),
            working_dir=data.get("working_dir", ""),
            model=data.get("model", ""),
            created_at=data.get("created_at", ""),
            stopped_at=data.get("stopped_at", ""),
            error=data.get("error", ""),
        )
