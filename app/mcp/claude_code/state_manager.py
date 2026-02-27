"""
State Manager for Claude Code Sessions

Manages persistent state in ~/.memory/claude-code-state.json

File: app/mcp/claude_code/state_manager.py
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Optional, List

from app.mcp.claude_code.models import SessionState


class ClaudeCodeStateManager:
    """Manages persistent state for Claude Code sessions"""

    def __init__(self, memory_root: str = None):
        self.memory_root = Path(memory_root or os.path.expanduser("~/.memory"))
        self.state_file = self.memory_root / "claude-code-state.json"
        self._ensure_state_file()

    def _ensure_state_file(self):
        self.memory_root.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            self._write_state({"sessions": {}})

    def _read_state(self) -> Dict:
        try:
            with open(self.state_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"sessions": {}}

    def _write_state(self, state: Dict):
        # Atomic write via temp file + rename
        dir_path = self.state_file.parent
        fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_path, str(self.state_file))
            os.chmod(self.state_file, 0o600)
        except Exception:
            # Clean up temp file on failure
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def save_session(self, session_state: SessionState):
        state = self._read_state()
        state["sessions"][session_state.session_id] = session_state.to_dict()
        self._write_state(state)

    def get_session(self, session_id: str) -> Optional[SessionState]:
        state = self._read_state()
        session_data = state["sessions"].get(session_id)
        if session_data:
            return SessionState.from_dict(session_data)
        return None

    def delete_session(self, session_id: str):
        state = self._read_state()
        if session_id in state["sessions"]:
            del state["sessions"][session_id]
            self._write_state(state)

    def list_sessions(self) -> List[str]:
        state = self._read_state()
        return list(state["sessions"].keys())

    def get_all_sessions(self) -> Dict[str, SessionState]:
        state = self._read_state()
        sessions = {}
        for sid, data in state["sessions"].items():
            sessions[sid] = SessionState.from_dict(data)
        return sessions
