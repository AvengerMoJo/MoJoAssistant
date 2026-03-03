"""
Claude Code Manager

Manages Claude Code subprocess lifecycle (start/stop/restart/health).
Does NOT expose coding tools — those are handled by external MCP tool projects.

File: app/mcp/claude_code/manager.py
"""

import os
import signal
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from app.mcp.agents.base import BaseAgentManager
from app.mcp.claude_code.models import SessionConfig, SessionState
from app.mcp.claude_code.state_manager import ClaudeCodeStateManager


class ClaudeCodeManager(BaseAgentManager):
    """
    Manages Claude Code CLI subprocess lifecycle.

    Responsibilities:
    - Start/stop/restart claude subprocess
    - Track PID and process health
    - Persist session state
    """

    agent_type = "claude_code"
    identifier_description = "session_id (unique string, e.g. 'my-project')"

    def __init__(self, memory_root: str = None, logger=None):
        self.memory_root = memory_root or os.path.expanduser("~/.memory")
        self.logger = logger
        self.state_manager = ClaudeCodeStateManager(memory_root=self.memory_root)

        # Detect claude binary
        self.claude_bin = os.getenv("CLAUDE_BIN") or shutil.which("claude") or ""

    def _log(self, level: str, msg: str):
        if self.logger:
            getattr(self.logger, level, self.logger.info)(msg)

    def _is_process_running(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _stop_process(self, pid: int) -> bool:
        if not self._is_process_running(pid):
            return True
        try:
            os.kill(pid, signal.SIGTERM)
            # Wait briefly for graceful shutdown
            import time
            for _ in range(10):
                time.sleep(0.5)
                if not self._is_process_running(pid):
                    return True
            # Force kill
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)
            return not self._is_process_running(pid)
        except (OSError, ProcessLookupError):
            return True

    async def start_project(self, identifier: str, **kwargs) -> Dict[str, Any]:
        """Start a Claude Code session.

        Args:
            identifier: Session ID
            working_dir: Working directory for the agent (required in kwargs)
            model: Model to use (optional in kwargs)
        """
        session_id = identifier
        working_dir = kwargs.get("working_dir", "")
        model = kwargs.get("model", "claude-sonnet-4-5-20250929")

        if not working_dir:
            return {
                "status": "error",
                "message": "working_dir is required",
            }

        working_dir = os.path.expanduser(working_dir)
        if not os.path.isdir(working_dir):
            return {
                "status": "error",
                "message": f"Working directory does not exist: {working_dir}",
            }

        if not self.claude_bin:
            return {
                "status": "error",
                "message": "claude binary not found. Install Claude Code CLI or set CLAUDE_BIN.",
            }

        # Check if already running
        existing = self.state_manager.get_session(session_id)
        if existing and existing.status == "running":
            if self._is_process_running(existing.pid):
                return {
                    "status": "error",
                    "message": f"Session '{session_id}' is already running (PID {existing.pid})",
                }
            # Process died, update state
            existing.status = "failed"
            existing.error = "Process died unexpectedly"
            self.state_manager.save_session(existing)

        # Start claude subprocess
        cmd = [self.claude_bin, "--dangerously-skip-permissions"]
        if model:
            cmd.extend(["--model", model])

        self._log("info", f"Starting Claude Code session '{session_id}' in {working_dir}")

        try:
            process = subprocess.Popen(
                cmd,
                cwd=working_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError:
            return {
                "status": "error",
                "message": f"claude binary not found at: {self.claude_bin}",
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to start claude process: {str(e)}",
            }

        # Save state
        session_state = SessionState(
            session_id=session_id,
            status="running",
            pid=process.pid,
            working_dir=working_dir,
            model=model,
            created_at=datetime.utcnow().isoformat(),
        )
        self.state_manager.save_session(session_state)

        self._log("info", f"Claude Code session '{session_id}' started (PID {process.pid})")

        return {
            "status": "success",
            "message": f"Session '{session_id}' started",
            "session_id": session_id,
            "pid": process.pid,
            "working_dir": working_dir,
            "model": model,
        }

    async def stop_project(self, identifier: str) -> Dict[str, Any]:
        """Stop a Claude Code session."""
        session_id = identifier
        session = self.state_manager.get_session(session_id)

        if not session:
            return {
                "status": "error",
                "message": f"Session '{session_id}' not found",
            }

        if session.status != "running":
            return {
                "status": "error",
                "message": f"Session '{session_id}' is not running (status: {session.status})",
            }

        stopped = self._stop_process(session.pid)

        session.status = "stopped" if stopped else "failed"
        session.stopped_at = datetime.utcnow().isoformat()
        if not stopped:
            session.error = f"Failed to stop process {session.pid}"
        self.state_manager.save_session(session)

        self._log("info", f"Claude Code session '{session_id}' stopped")

        return {
            "status": "success" if stopped else "error",
            "message": f"Session '{session_id}' {'stopped' if stopped else 'failed to stop'}",
            "session_id": session_id,
        }

    async def get_status(self, identifier: str) -> Dict[str, Any]:
        """Get Claude Code session status."""
        session_id = identifier
        session = self.state_manager.get_session(session_id)

        if not session:
            return {
                "status": "error",
                "message": f"Session '{session_id}' not found",
            }

        # Check actual process state
        if session.status == "running" and not self._is_process_running(session.pid):
            session.status = "failed"
            session.error = "Process died unexpectedly"
            session.stopped_at = datetime.utcnow().isoformat()
            self.state_manager.save_session(session)

        return {
            "status": "success",
            "session": session.to_dict(),
        }

    async def list_projects(self) -> Dict[str, Any]:
        """List all Claude Code sessions."""
        all_sessions = self.state_manager.get_all_sessions()

        sessions_list = []
        for sid, session in all_sessions.items():
            # Refresh process status
            if session.status == "running" and not self._is_process_running(session.pid):
                session.status = "failed"
                session.error = "Process died unexpectedly"
                session.stopped_at = datetime.utcnow().isoformat()
                self.state_manager.save_session(session)

            sessions_list.append(session.to_dict())

        return {
            "status": "success",
            "sessions": sessions_list,
            "count": len(sessions_list),
        }

    async def restart_project(self, identifier: str) -> Dict[str, Any]:
        """Restart a Claude Code session."""
        session_id = identifier
        session = self.state_manager.get_session(session_id)

        if not session:
            return {
                "status": "error",
                "message": f"Session '{session_id}' not found",
            }

        # Stop if running
        if session.status == "running":
            self._stop_process(session.pid)

        # Re-start with saved config
        return await self.start_project(
            session_id,
            working_dir=session.working_dir,
            model=session.model,
        )

    async def destroy_project(self, identifier: str) -> Dict[str, Any]:
        """Stop and remove a Claude Code session from state."""
        session_id = identifier
        session = self.state_manager.get_session(session_id)

        if not session:
            return {
                "status": "error",
                "message": f"Session '{session_id}' not found",
            }

        # Stop if running
        if session.status == "running":
            self._stop_process(session.pid)

        # Delete state
        self.state_manager.delete_session(session_id)

        self._log("info", f"Claude Code session '{session_id}' destroyed")

        return {
            "status": "success",
            "message": f"Session '{session_id}' destroyed",
            "session_id": session_id,
        }
