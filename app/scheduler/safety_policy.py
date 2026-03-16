"""Safety Policy Enforcement for Agentic Tasks."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from app.config.paths import get_memory_path


class SafetyPolicy:
    """Enforces safety rules for agentic tasks."""

    def __init__(self, policy_path: str = "config/safety_policy.json"):
        self.policy_path = policy_path
        self._policy = self._load_policy()
        self._operation_log_path = "config/tool_operation_logs.json"
        self._ensure_dirs()

    def _load_policy(self) -> Dict[str, Any]:
        """Load safety policy from file or create default."""
        if os.path.exists(self.policy_path):
            with open(self.policy_path, "r") as f:
                return json.load(f)

        # Create default policy
        default_policy = {
            "_version": "1.0.0",
            "_description": "Immutable safety rules for agentic tasks",
            "sandbox_policy": {
                "allowed_paths": ["~/.memory/"],
                "max_file_size_mb": 10,
                "enforce_path_sandbox": True,
            },
            "ai_modification_rules": {
                "allow_non_sandbox_writes": False,
                "require_backup_before_change": True,
                "require_test_after_change": True,
                "auto_rollback_on_failure": True,
                "sandbox_operation_tracking": True,
                "max_danger_level_for_new_tools": "high",
            },
            "immutable_rules": {
                "blocked_tool_names": [
                    "rm",
                    "delete",
                    "format",
                    "shutdown",
                    "kill",
                    "dd",
                    "mkfs",
                ],
                "blocked_paths": [
                    "/",
                    "/home",
                    "/etc",
                    "/usr",
                    "/var",
                    "/root",
                    "/boot",
                    "/sys",
                    "/proc",
                ],
                "min_danger_level_for_bash": "high",
                "cannot_lower_danger_level": True,
                "cannot_disable_auth_for_critical_tools": True,
            },
            "rollback_policy": {
                "auto_backup_enabled": True,
                "backup_location": "config/rollback_snapshots/",
                "max_versions_per_file": 10,
                "rollback_on_error": True,
                "versioned_naming": True,
            },
        }

        os.makedirs(os.path.dirname(self.policy_path), exist_ok=True)
        with open(self.policy_path, "w") as f:
            json.dump(default_policy, f, indent=2)

        return default_policy

    def check_tool_execution(
        self, tool_name: str, tool: Optional[Dict], args: Dict
    ) -> Dict[str, Any]:
        """Check if tool execution is allowed by policy."""

        sandbox = self._policy["sandbox_policy"]
        immutable = self._policy["immutable_rules"]

        # Check if tool name is blocked
        if tool_name in immutable["blocked_tool_names"]:
            return {
                "allowed": False,
                "reason": f"Tool name '{tool_name}' is blocked by immutable rules",
            }

        # For write operations, check sandbox (bash_exec has its own whitelist)
        if tool_name == "write_file":
            path_arg = args.get("path", "")

            # Check if path is in allowed sandbox.
            # Always include the runtime memory path (respects MEMORY_PATH env var)
            # alongside any configured allowed_paths.
            memory_root = os.path.abspath(get_memory_path())
            runtime_allowed = [memory_root] + [
                os.path.abspath(os.path.expanduser(p))
                for p in sandbox["allowed_paths"]
            ]
            abs_path = os.path.abspath(os.path.expanduser(path_arg))
            allowed = any(abs_path.startswith(ap) for ap in runtime_allowed)

            if not allowed:
                return {
                    "allowed": False,
                    "reason": f"Path '{path_arg}' not in sandbox. Allowed: {sandbox['allowed_paths']}",
                }

        # Check bash tool danger level
        if tool_name == "bash_exec":
            danger = tool.get("danger_level", "low") if tool else "low"
            min_danger = immutable["min_danger_level_for_bash"]

            if danger not in ["high", "critical"]:
                return {
                    "allowed": False,
                    "reason": f"Bash tool must be '{min_danger}' danger or higher",
                }

        return {"allowed": True}

    def check_tool_addition(self, tool_definition: Dict) -> Dict[str, Any]:
        """Check if new tool can be added by policy."""

        ai_rules = self._policy["ai_modification_rules"]
        immutable = self._policy["immutable_rules"]

        tool_name = tool_definition.get("name", "")
        danger = tool_definition.get("danger_level", "low")

        # Check blocked names
        if tool_name in immutable["blocked_tool_names"]:
            return {
                "allowed": False,
                "reason": f"Tool name '{tool_name}' is blocked by immutable rules",
                "requires_user_approval": True,
            }

        # Check danger level
        max_danger = ai_rules["max_danger_level_for_new_tools"]
        if self._danger_to_int(danger) > self._danger_to_int(max_danger):
            return {
                "allowed": False,
                "reason": f"Tool danger '{danger}' exceeds max '{max_danger}'",
                "requires_user_approval": True,
            }

        return {"allowed": True}

    def track_operation(
        self,
        operation: str,
        tool_name: Optional[str] = None,
        target: Optional[str] = None,
        success: bool = True,
        rollback: bool = False,
        backup_path: Optional[str] = None,
        reason: Optional[str] = None,
    ):
        """Track operation in log file."""

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "tool_name": tool_name,
            "target": target,
            "success": success,
            "rollback": rollback,
            "backup_path": backup_path,
            "reason": reason,
        }

        # Load existing log
        logs = []
        if os.path.exists(self._operation_log_path):
            with open(self._operation_log_path, "r") as f:
                logs = json.load(f)

        # Append new entry
        logs.append(log_entry)

        # Save
        with open(self._operation_log_path, "w") as f:
            json.dump(logs, f, indent=2)

    def _danger_to_int(self, danger: str) -> int:
        """Convert danger level to integer for comparison."""
        mapping = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        return mapping.get(danger, 0)

    def _ensure_dirs(self):
        """Ensure required directories exist."""
        os.makedirs("config/rollback_snapshots", exist_ok=True)
        os.makedirs(get_memory_path(), exist_ok=True)
