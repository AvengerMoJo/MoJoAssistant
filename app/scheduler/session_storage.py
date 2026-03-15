"""
Task Session Storage

Persistent per-task conversation trails for agentic tasks.
Stores one JSON file per task in ~/.memory/task_sessions/.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.config.paths import get_memory_subpath


@dataclass
class SessionMessage:
    """A single message in a task's conversation trail."""

    role: str  # "system", "user", "assistant", "tool"
    content: str
    timestamp: str  # ISO format
    iteration: int
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskSession:
    """Complete session for a single agentic task execution."""

    task_id: str
    status: str  # "running", "completed", "failed", "timed_out"
    messages: List[SessionMessage]
    started_at: str
    completed_at: Optional[str] = None
    final_answer: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "messages": [asdict(m) for m in self.messages],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "final_answer": self.final_answer,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskSession":
        messages = [SessionMessage(**m) for m in data.get("messages", [])]
        return cls(
            task_id=data["task_id"],
            status=data["status"],
            messages=messages,
            started_at=data["started_at"],
            completed_at=data.get("completed_at"),
            final_answer=data.get("final_answer"),
            error_message=data.get("error_message"),
            metadata=data.get("metadata", {}),
        )


class SessionStorage:
    """File-based storage for agentic task sessions."""

    @property
    def STORAGE_DIR(self) -> Path:
        return Path(get_memory_subpath("task_sessions"))

    def __init__(self, storage_dir: Optional[Path] = None):
        self._dir = storage_dir or self.STORAGE_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, task_id: str) -> Path:
        # Sanitize task_id to be filename-safe
        safe_id = task_id.replace("/", "_").replace("..", "_")
        return self._dir / f"{safe_id}.json"

    def save_session(self, session: TaskSession) -> None:
        """Write full session to disk."""
        path = self._path(session.task_id)
        path.write_text(
            json.dumps(session.to_dict(), indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_session(self, task_id: str) -> Optional[TaskSession]:
        """Load a session from disk. Returns None if not found."""
        path = self._path(task_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return TaskSession.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None

    def append_message(self, task_id: str, message: SessionMessage) -> None:
        """Append a message to an existing session (loads, appends, saves)."""
        session = self.load_session(task_id)
        if session is None:
            return
        session.messages.append(message)
        self.save_session(session)

    def update_status(
        self,
        task_id: str,
        status: str,
        final_answer: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update session status and optional final fields."""
        session = self.load_session(task_id)
        if session is None:
            return
        session.status = status
        session.completed_at = datetime.now().isoformat()
        if final_answer is not None:
            session.final_answer = final_answer
        if error_message is not None:
            session.error_message = error_message
        self.save_session(session)

    def list_sessions(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all sessions, optionally filtered by status."""
        results = []
        for path in sorted(self._dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if status and data.get("status") != status:
                    continue
                results.append({
                    "task_id": data["task_id"],
                    "status": data["status"],
                    "started_at": data["started_at"],
                    "completed_at": data.get("completed_at"),
                    "message_count": len(data.get("messages", [])),
                    "has_final_answer": data.get("final_answer") is not None,
                    "session_file": str(path),
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return results
