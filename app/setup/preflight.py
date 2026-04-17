"""
Preflight checker — validates system dependencies and MCP tool installation
before MoJoAssistant starts. Each check maps to a concrete install command
so the user (or the interactive CLI) can fix gaps in one step.

Usage (from code):
    checker = PreflightChecker()
    items = checker.check_all()
    failed = [i for i in items if i.status == "fail"]

Usage (interactive CLI):
    python scripts/preflight.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class PreflightItem:
    name: str           # human label, e.g. "tmux binary"
    source: str         # which component needs this, e.g. "tmux MCP server"
    check_type: str     # "binary" | "file" | "env_key"
    check_value: str    # binary name, file path, or env key
    hint: str           # install/fix command shown to user
    manual: bool = False  # True → print hint only, never auto-run (e.g. rustup needs shell restart)
    status: str = "unknown"   # "pass" | "fail" | "skip"
    detail: str = ""


class PreflightChecker:
    """
    Reads MCP server configs and project structure, then builds and runs
    a checklist of required system dependencies and binaries.
    """

    def __init__(self, config_path: str = "config/mcp_servers.json"):
        self._config_path = config_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_all(self) -> List[PreflightItem]:
        items: List[PreflightItem] = []
        items += self._check_core()
        items += self._check_mcp_servers()
        for item in items:
            if item.status == "unknown":
                item.status, item.detail = self._run_check(item)
        return items

    def install_item(self, item: PreflightItem) -> tuple[bool, str]:
        """
        Attempt to run the item's install hint as a shell command.
        Returns (success, output).
        Never called for manual=True items.
        """
        if item.manual:
            return False, "Manual install required — run the command yourself and restart."
        try:
            result = subprocess.run(
                item.hint,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode == 0:
                return True, (result.stdout or "").strip()
            return False, (result.stderr or result.stdout or "non-zero exit").strip()
        except subprocess.TimeoutExpired:
            return False, "Install command timed out after 5 minutes."
        except Exception as e:
            return False, str(e)

    def summary(self, items: List[PreflightItem]) -> dict:
        passed = sum(1 for i in items if i.status == "pass")
        failed = sum(1 for i in items if i.status == "fail")
        skipped = sum(1 for i in items if i.status == "skip")
        return {
            "total": len(items),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "ready": failed == 0,
        }

    # ------------------------------------------------------------------
    # Core project checks (venv, .env, agent-shell)
    # ------------------------------------------------------------------

    def _check_core(self) -> List[PreflightItem]:
        items = []

        # Python venv
        venv_python = _PROJECT_ROOT / "venv" / "bin" / "python"
        items.append(PreflightItem(
            name="Python venv",
            source="MoJoAssistant core",
            check_type="file",
            check_value=str(venv_python),
            hint="python3 -m venv venv && venv/bin/pip install -r requirements.txt",
        ))

        # .env file
        env_file = _PROJECT_ROOT / ".env"
        items.append(PreflightItem(
            name=".env config",
            source="MoJoAssistant core",
            check_type="file",
            check_value=str(env_file),
            hint="cp .env.example .env  # then edit .env with your API keys",
            manual=True,
        ))

        # agent-shell script (required by tmux MCP)
        agent_shell = _PROJECT_ROOT / "scripts" / "agent-shell"
        items.append(PreflightItem(
            name="scripts/agent-shell",
            source="tmux MCP server",
            check_type="file_executable",
            check_value=str(agent_shell),
            hint=f"chmod +x {agent_shell}",
        ))

        # tmux-mcp config
        tmux_toml = _PROJECT_ROOT / "config" / "tmux-mcp.toml"
        items.append(PreflightItem(
            name="config/tmux-mcp.toml",
            source="tmux MCP server",
            check_type="file",
            check_value=str(tmux_toml),
            hint="File should exist in repo — check git status",
            manual=True,
        ))

        return items

    # ------------------------------------------------------------------
    # MCP server dependency checks
    # ------------------------------------------------------------------

    def _check_mcp_servers(self) -> List[PreflightItem]:
        items: List[PreflightItem] = []
        try:
            import json
            paths = [
                _PROJECT_ROOT / self._config_path,
                Path(os.path.expanduser("~/.memory/config/mcp_servers.json")),
            ]
            servers = {}
            for path in paths:
                if not path.exists():
                    continue
                data = json.loads(path.read_text())
                for srv in data.get("servers", []):
                    if srv.get("enabled", True):
                        servers[srv["id"]] = srv
        except Exception:
            return items

        for srv_id, srv in servers.items():
            srv_name = srv.get("name", srv_id)
            command = srv.get("command", "")
            install_hint = srv.get("install_hint", f"Install {command}")

            # Determine if the MCP binary itself is already present
            # (used to skip install-only requires like cargo/rustup)
            mcp_binary_present = False
            if command and srv.get("transport", "stdio") == "stdio":
                expanded = os.path.expanduser(os.path.expandvars(command))
                if os.path.isabs(expanded):
                    mcp_binary_present = Path(expanded).is_file()
                else:
                    mcp_binary_present = bool(shutil.which(expanded))

            # Check each requires[] entry (system deps)
            for req in srv.get("requires", []):
                binary = req.get("binary", "")
                hint = req.get("hint", f"Install {binary}")
                is_manual = str(req.get("manual", "false")).lower() == "true"
                if not binary:
                    continue
                # Skip install-only (manual) deps when the MCP binary is already present
                if is_manual and mcp_binary_present:
                    items.append(PreflightItem(
                        name=f"{binary} (system)",
                        source=srv_name,
                        check_type="binary",
                        check_value=binary,
                        hint=hint,
                        manual=is_manual,
                        status="skip",
                        detail=f"Skipped — {srv_id} binary already installed",
                    ))
                    continue
                items.append(PreflightItem(
                    name=f"{binary} (system)",
                    source=srv_name,
                    check_type="binary",
                    check_value=binary,
                    hint=hint,
                    manual=is_manual,
                ))

            # Check the MCP server binary itself
            if command and srv.get("transport", "stdio") == "stdio":
                expanded = os.path.expanduser(os.path.expandvars(command))
                items.append(PreflightItem(
                    name=f"{srv_id} MCP binary",
                    source=srv_name,
                    check_type="binary_path",
                    check_value=expanded,
                    hint=install_hint,
                ))

        return items

    # ------------------------------------------------------------------
    # Check runner
    # ------------------------------------------------------------------

    def _run_check(self, item: PreflightItem) -> tuple[str, str]:
        """Returns (status, detail)."""
        if item.check_type == "binary":
            found = shutil.which(item.check_value)
            if found:
                return "pass", f"Found: {found}"
            return "fail", f"'{item.check_value}' not found on PATH"

        elif item.check_type == "binary_path":
            path = Path(item.check_value)
            if path.is_absolute():
                if path.is_file():
                    return "pass", f"Found: {path}"
                return "fail", f"Not found: {path}"
            else:
                found = shutil.which(item.check_value)
                if found:
                    return "pass", f"Found: {found}"
                return "fail", f"'{item.check_value}' not found on PATH"

        elif item.check_type == "file":
            path = Path(item.check_value)
            if path.exists():
                return "pass", f"Found: {path}"
            return "fail", f"Missing: {path}"

        elif item.check_type == "file_executable":
            path = Path(item.check_value)
            if path.exists() and os.access(path, os.X_OK):
                return "pass", f"Found and executable: {path}"
            if path.exists():
                return "fail", f"Exists but not executable: {path}"
            return "fail", f"Missing: {path}"

        elif item.check_type == "env_key":
            val = os.environ.get(item.check_value)
            if val:
                return "pass", f"Set (length={len(val)})"
            return "fail", f"Environment variable '{item.check_value}' not set"

        return "skip", "Unknown check type"
