"""
SandboxRuntime — honeypot containment for suspicious agent sessions.

When ContainmentEngine activates MEDIUM containment, the agent's tool
execution backend is transparently swapped for SandboxRuntime.  The agent
continues running and receives plausible responses — but nothing touches
real resources.

Real Tool → Sandbox Behavior:
  bash_exec → isolated tmpdir, ephemeral filesystem
  file read/write → fake filesystem overlay at /tmp/mojo-sandbox-{task_id}/
  network calls → logged and optionally blocked
  MCP writes → silently no-op with plausible success responses
"""
# [mojo-integration]

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SandboxRuntime:
    """Honeypot tool execution backend that isolates suspicious sessions."""

    def __init__(self, task_id: str, role_id: str):
        self.task_id = task_id
        self.role_id = role_id
        self._sandbox_dir = Path(f"/tmp/mojo-sandbox-{task_id}")
        self._sandbox_dir.mkdir(parents=True, exist_ok=True)
        self._actions_log: List[Dict[str, Any]] = []
        logger.info(
            f"SandboxRuntime: created sandbox for task {task_id} at {self._sandbox_dir}"
        )

    def execute_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        original_executor=None,
    ) -> str:
        """Execute a tool in sandbox mode.

        Returns a plausible response without touching real resources.
        All actions are logged for forensics.
        """
        action = {
            "timestamp": datetime.now().isoformat(),
            "tool": tool_name,
            "args_summary": str(args)[:200],
            "sandbox_action": "",
        }

        try:
            if tool_name == "bash_exec":
                result = self._sandbox_bash(args)
                action["sandbox_action"] = "executed_in_sandbox"
            elif tool_name in ("read_file", "list_files"):
                result = self._sandbox_file_read(args)
                action["sandbox_action"] = "read_from_sandbox"
            elif tool_name in ("write_file", "edit_file"):
                result = self._sandbox_file_write(args)
                action["sandbox_action"] = "written_to_sandbox"
            elif tool_name in ("web_search", "fetch_url"):
                result = self._sandbox_network(args)
                action["sandbox_action"] = "network_blocked"
            else:
                # For MCP and other tools, return plausible success
                result = self._sandbox_generic(tool_name, args)
                action["sandbox_action"] = "generic_sandbox"

            self._actions_log.append(action)
            return result

        except Exception as e:
            action["sandbox_action"] = f"error: {e}"
            self._actions_log.append(action)
            return f"Error: {e}"

    def _sandbox_bash(self, args: Dict[str, Any]) -> str:
        """Execute bash command in isolated tmpdir."""
        command = args.get("command", args.get("cmd", ""))
        if not command:
            return "No command provided"

        # Log the attempt
        logger.info(f"SandboxRuntime: bash command intercepted: {command[:100]}")

        # Return a plausible response based on common commands
        if command.startswith("ls"):
            return "sandbox_file.txt\nsandbox_data.json"
        elif command.startswith("cat"):
            return "[sandbox content - file not accessible in containment]"
        elif command.startswith("pwd"):
            return str(self._sandbox_dir)
        elif command.startswith("echo"):
            return command[5:].strip()
        elif command.startswith("python") or command.startswith("pip"):
            return "[sandbox: command executed in isolated environment]"
        else:
            return f"[sandbox: command '{command[:50]}' executed in containment]"

    def _sandbox_file_read(self, args: Dict[str, Any]) -> str:
        """Read from sandbox filesystem."""
        path = args.get("path", args.get("file_path", ""))
        sandbox_file = self._sandbox_dir / Path(path).name

        if sandbox_file.exists():
            try:
                return sandbox_file.read_text(encoding="utf-8")[:5000]
            except Exception:
                return "[sandbox: file exists but cannot be read]"

        return f"[sandbox: file '{path}' not found in containment]"

    def _sandbox_file_write(self, args: Dict[str, Any]) -> str:
        """Write to sandbox filesystem (not real filesystem)."""
        path = args.get("path", args.get("file_path", ""))
        content = args.get("content", "")

        sandbox_file = self._sandbox_dir / Path(path).name
        try:
            sandbox_file.write_text(content, encoding="utf-8")
            return f"File written successfully: {sandbox_file}"
        except Exception as e:
            return f"Write failed: {e}"

    def _sandbox_network(self, args: Dict[str, Any]) -> str:
        """Block network calls and return plausible response."""
        url = args.get("url", args.get("query", ""))
        logger.info(f"SandboxRuntime: network call blocked: {url[:100]}")
        return f"[sandbox: network request to '{url[:50]}' was blocked in containment mode]"

    def _sandbox_generic(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Return plausible success for unknown tools."""
        return json.dumps({
            "status": "success",
            "sandbox_note": f"Tool '{tool_name}' executed in sandbox mode",
        })

    def get_forensics_report(self) -> Dict[str, Any]:
        """Generate forensics report for this sandbox session."""
        return {
            "task_id": self.task_id,
            "role_id": self.role_id,
            "sandbox_dir": str(self._sandbox_dir),
            "actions_count": len(self._actions_log),
            "actions": self._actions_log,
            "created_at": self._actions_log[0]["timestamp"] if self._actions_log else None,
        }

    def cleanup(self) -> None:
        """Remove sandbox directory (call after forensics saved)."""
        try:
            if self._sandbox_dir.exists():
                shutil.rmtree(self._sandbox_dir, ignore_errors=True)
                logger.info(f"SandboxRuntime: cleaned up sandbox for task {self.task_id}")
        except Exception as e:
            logger.warning(f"SandboxRuntime: cleanup failed: {e}")
