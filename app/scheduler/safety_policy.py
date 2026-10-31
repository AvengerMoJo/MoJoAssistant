"""Safety Policy Enforcement for Agentic Tasks."""
# [hitl-orchestrator: generic]

import fnmatch
import json
import os
import shlex
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from app.config.paths import get_memory_path


# Commands whose non-option arguments are paths they write or remove.
_WRITERS = {"rm", "rmdir", "mv", "cp", "tee", "touch", "mkdir", "ln", "install",
            "truncate", "dd", "shred", "unlink", "chmod", "chown", "chgrp"}
_SECRET_DIRS = {".ssh", ".gnupg", ".aws", "ai-credential-manager", ".mcp_service"}
_SECRET_FILES = ("id_rsa*", "id_ed25519*", "id_ecdsa*", "id_dsa*", "*.pem", "*.p12", "*.pfx",
                 "*.key", "*.kdbx", "auth.json", "clients.json", "ai_credential_manager_client.json",
                 "shadow", "sudoers")
_ENV_TEMPLATE = (".example", ".sample", ".template")
# Harmless system files an agent may read.
_SAFE_READS = ["/etc/os-release", "/etc/resolv.conf", "/etc/hostname", "/proc/self",
               "/proc/cpuinfo", "/proc/meminfo"]


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

        # Path sandbox: enforce for write_file and read_file — UNLESS a
        # per-task sandbox container/host process is active, in which case
        # the sandbox itself is the isolation boundary (same principle
        # bash_exec already documents: "no blocklist applies" inside an
        # active sandbox). Without this check, read_file/write_file blocked
        # every path outside ~/.memory/ even when _read_file/_write_file's
        # own sandbox-routing logic (checking _cv_sandbox_handle) would have
        # correctly and safely served the request — this fired for real
        # against a git-cloned repo under /workspace/repo.
        if tool_name in ("write_file", "read_file"):
            _sandbox_active = False
            try:
                from app.scheduler.sandbox.context import _cv_sandbox_handle
                _sandbox_active = _cv_sandbox_handle.get() is not None
            except Exception:
                _sandbox_active = False

            if not _sandbox_active:
                path_arg = args.get("path", "")
                memory_root = os.path.abspath(get_memory_path())
                runtime_allowed = [memory_root] + [
                    os.path.abspath(os.path.expanduser(p))
                    for p in sandbox["allowed_paths"]
                ]
                abs_path = os.path.abspath(os.path.expanduser(path_arg))
                if not any(abs_path.startswith(ap) for ap in runtime_allowed):
                    if path_arg.startswith(("~/memory/", "~/memory")):
                        hint = " The memory directory is '~/.memory/' (with the dot), not '~/memory/'."
                    else:
                        hint = (" Files of a git repo outside ~/.memory/ are read with knowledge_get_file "
                                "(the repo must be registered with knowledge_add_repo), not read_file.")
                    return {
                        "allowed": False,
                        "reason": f"Path '{path_arg}' not in sandbox. Allowed: {sandbox['allowed_paths']}.{hint}",
                    }

        # Check bash tool danger level AND block commands targeting blocked paths
        if tool_name == "bash_exec":
            danger = tool.get("danger_level", "low") if tool else "low"
            min_danger = immutable["min_danger_level_for_bash"]

            if danger not in ["high", "critical"]:
                return {
                    "allowed": False,
                    "reason": f"Bash tool must be '{min_danger}' danger or higher",
                }

            violation = self._bash_violation(args.get("commands", args.get("command")), sandbox, immutable)
            if violation:
                return {"allowed": False, "reason": violation}

        return {"allowed": True}

    def _bash_violation(self, raw, sandbox: Dict[str, Any], immutable: Dict[str, Any]) -> Optional[str]:
        """Reason a bash_exec command (string or list) is refused, or None.

        Three rules, checked per simple command (`a && b`, pipes, `$(..)`):
          1. secrets  -- ssh/gpg/aws dirs, .env, private keys, the credential
                         vault, auth/client files: no read, no write.
          2. writes   -- a redirect or a writing command (rm, cp, touch, sed -i,
                         ...) aimed outside the memory dir and /tmp.
          3. system   -- reads of /etc, /var, /root, /boot, /sys, /proc (except
                         a few harmless files) and a bare `/` (whole-disk scan).
        Reading repos under /home is allowed; `commands` is the tool's real
        parameter (the old check only read `command`, so it never fired)."""
        from app.scheduler import bash_command as _bash

        commands = [raw] if isinstance(raw, str) else (raw if isinstance(raw, list) else [])
        allowed_roots = [os.path.abspath(get_memory_path())] + [
            os.path.abspath(os.path.expanduser(p)) for p in sandbox.get("allowed_paths", [])
        ]
        try:
            from app.scheduler.sandbox.context import _cv_sandbox_handle
            in_sandbox = _cv_sandbox_handle.get() is not None
        except Exception:
            in_sandbox = False  # no sandbox module: the strict host rules apply
        write_roots = allowed_roots + ["/tmp"]
        read_blocked = [p for p in immutable.get("blocked_paths", []) if p not in ("/", "/home", "/usr")]

        def under(path: str, roots) -> bool:
            return any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots)

        for command in commands:
            if not isinstance(command, str):
                continue
            try:
                lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
                lexer.whitespace_split = True
                tokens = list(lexer)
            except ValueError:
                tokens = command.split()  # scanning only: stricter, never executed
            for tok in tokens:
                hit = self._secret_hit(tok)
                if hit:
                    return f"Command touches a secret ({hit}); secrets are not readable or writable by agents"
            if in_sandbox:
                continue  # the container is the boundary for writes and system reads
            for simple in _bash.split_commands(command) or []:
                name = _bash.base_name(simple)
                targets = []
                for i, tok in enumerate(simple):
                    if tok.lstrip("0123456789").startswith(">") and i + 1 < len(simple):
                        targets.append(simple[i + 1])  # redirect target
                if name in _WRITERS or (name == "sed" and any(a.startswith("-i") or a == "--in-place" for a in simple[1:])):
                    paths = [t[3:] if t.startswith("of=") else t for t in simple[1:] if not t.startswith("-")]
                    # cp/mv/ln/install read their sources and write only the last argument.
                    targets += paths[-1:] if name in ("cp", "mv", "ln", "install") else paths
                for t in targets:
                    if t.startswith("&") or t in ("/dev/null", "/dev/stderr", "/dev/stdout"):
                        continue
                    if not t.startswith(("/", "~")):
                        if ".." in t.split("/"):
                            return f"Command writes through '..' ({t}); use a path inside the memory dir"
                        continue  # relative: resolved inside the agent workdir
                    ap = os.path.abspath(os.path.expanduser(t))
                    if not under(ap, write_roots):
                        return f"Command writes to '{t}', outside the memory dir and /tmp"
                for tok in simple[1:]:
                    if not tok.startswith(("/", "~")):
                        continue
                    ap = os.path.abspath(os.path.expanduser(tok))
                    if ap == "/":
                        return "Command scans the whole filesystem ('/'); name the directory"
                    if under(ap, read_blocked) and not under(ap, allowed_roots) and not under(ap, _SAFE_READS):
                        return f"Command reads system path '{tok}'"
        return None

    @staticmethod
    def _secret_hit(token: str) -> Optional[str]:
        """Name of the secret rule a path-like token matches, or None."""
        t = token.strip("\"'").lower()
        if not t or t.startswith("-") and "/" not in t:
            return None
        parts = [p for p in t.replace("~", "/~").split("/") if p]
        for part in parts:
            if part in _SECRET_DIRS:
                return part
        base = parts[-1] if parts else t
        if base.startswith(".env") and not base.endswith(_ENV_TEMPLATE):
            return base
        for pat in _SECRET_FILES:
            if fnmatch.fnmatch(base, pat):
                return base
        if fnmatch.fnmatch(t, "*/opencode/service.json"):
            return "opencode/service.json"
        return None

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
