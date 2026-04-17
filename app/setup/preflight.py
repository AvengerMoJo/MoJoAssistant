"""
Preflight checker — validates system dependencies and MCP tool installation
before MoJoAssistant starts. Platform-aware: detects Linux distro, macOS,
and Windows and shows the correct install command for each.

Usage (from code):
    checker = PreflightChecker()
    items = checker.check_all()
    failed = [i for i in items if i.status == "fail"]

Usage (interactive CLI):
    python scripts/preflight.py
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def detect_platform() -> str:
    """
    Returns a platform key used to look up install hints:
      linux_debian  — Debian, Ubuntu, Mint, Pop!_OS, Raspberry Pi OS …
      linux_fedora  — Fedora, RHEL, CentOS, AlmaLinux, Rocky …
      linux_arch    — Arch, Manjaro, EndeavourOS …
      linux_suse    — openSUSE, SLES …
      linux         — other / unknown Linux
      macos         — macOS / Darwin
      windows       — Windows (native or WSL1)
    """
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    if system == "linux":
        try:
            text = Path("/etc/os-release").read_text()
            ids = {}
            for line in text.splitlines():
                if "=" in line:
                    k, _, v = line.partition("=")
                    ids[k.strip()] = v.strip().strip('"').lower()
            id_val  = ids.get("ID", "")
            id_like = ids.get("ID_LIKE", "")
            combined = f"{id_val} {id_like}"
            if any(x in combined for x in ("ubuntu", "debian", "mint", "raspbian", "pop")):
                return "linux_debian"
            if any(x in combined for x in ("fedora", "rhel", "centos", "alma", "rocky")):
                return "linux_fedora"
            if any(x in combined for x in ("arch", "manjaro", "endeavour")):
                return "linux_arch"
            if any(x in combined for x in ("suse", "sles", "opensuse")):
                return "linux_suse"
        except OSError:
            pass
        return "linux"
    return "unknown"


_PLATFORM = detect_platform()


# ---------------------------------------------------------------------------
# Per-binary install hints (platform-keyed)
# Falls back: specific → linux → default
# manual=True means print but never auto-run (needs shell restart / browser)
# ---------------------------------------------------------------------------

_BINARY_HINTS: Dict[str, Dict] = {
    "tmux": {
        "linux_debian": {"cmd": "sudo apt install -y tmux"},
        "linux_fedora": {"cmd": "sudo dnf install -y tmux"},
        "linux_arch":   {"cmd": "sudo pacman -S --noconfirm tmux"},
        "linux_suse":   {"cmd": "sudo zypper install -y tmux"},
        "linux":        {"cmd": "sudo apt install -y tmux  # adjust for your package manager"},
        "macos":        {"cmd": "brew install tmux"},
        "windows":      {"cmd": "tmux is not available natively on Windows — use WSL2: wsl --install", "manual": True},
    },
    "cargo": {
        "linux":   {"cmd": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh  # then restart shell", "manual": True},
        "macos":   {"cmd": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh  # then restart shell", "manual": True},
        "windows": {"cmd": "winget install Rustup.Rustup  # or visit https://rustup.rs", "manual": True},
    },
    "node": {
        "linux_debian": {"cmd": "curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - && sudo apt install -y nodejs", "manual": True},
        "linux_fedora": {"cmd": "sudo dnf install -y nodejs", "manual": True},
        "linux_arch":   {"cmd": "sudo pacman -S --noconfirm nodejs npm", "manual": True},
        "linux_suse":   {"cmd": "sudo zypper install -y nodejs", "manual": True},
        "linux":        {"cmd": "Visit https://nodejs.org or use nvm: curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/HEAD/install.sh | bash", "manual": True},
        "macos":        {"cmd": "brew install node  # or: https://nodejs.org", "manual": True},
        "windows":      {"cmd": "winget install OpenJS.NodeJS  # or: https://nodejs.org", "manual": True},
    },
    "npx": {
        "default":  {"cmd": "npm install -g npm  # npx is bundled with npm 5.2+"},
    },
    "brew": {
        "macos":   {"cmd": '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"', "manual": True},
        "default": {"cmd": "Homebrew is macOS/Linux only — visit https://brew.sh", "manual": True},
    },
    "git": {
        "linux_debian": {"cmd": "sudo apt install -y git"},
        "linux_fedora": {"cmd": "sudo dnf install -y git"},
        "linux_arch":   {"cmd": "sudo pacman -S --noconfirm git"},
        "macos":        {"cmd": "xcode-select --install  # or: brew install git"},
        "windows":      {"cmd": "winget install Git.Git  # or: https://git-scm.com"},
        "linux":        {"cmd": "sudo apt install -y git"},
    },
    "python3": {
        "linux_debian": {"cmd": "sudo apt install -y python3 python3-venv python3-pip"},
        "linux_fedora": {"cmd": "sudo dnf install -y python3 python3-pip"},
        "linux_arch":   {"cmd": "sudo pacman -S --noconfirm python python-pip"},
        "macos":        {"cmd": "brew install python  # or: https://python.org", "manual": True},
        "windows":      {"cmd": "winget install Python.Python.3  # or: https://python.org", "manual": True},
        "linux":        {"cmd": "sudo apt install -y python3 python3-venv python3-pip"},
    },
}


def resolve_hint(binary: str, override_hint: str = "", override_manual: bool = False) -> Tuple[str, bool]:
    """
    Return (hint_cmd, is_manual) for a binary on the current platform.
    If override_hint is provided (from mcp_servers.json), use it directly.
    """
    if override_hint:
        return override_hint, override_manual

    table = _BINARY_HINTS.get(binary)
    if not table:
        return f"Install '{binary}' for your platform", False

    # Try: exact platform → linux (fallback for all linux variants) → default
    for key in (_PLATFORM, "linux", "default"):
        if key in table:
            entry = table[key]
            return entry["cmd"], entry.get("manual", False)

    return f"Install '{binary}' for your platform", False


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PreflightItem:
    name: str
    source: str
    check_type: str     # "binary" | "binary_path" | "file" | "file_executable" | "env_key"
    check_value: str    # binary name, absolute path, or env key
    hint: str           # install/fix command shown to user
    manual: bool = False  # True → display only, never auto-run
    status: str = "unknown"
    detail: str = ""


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------

class PreflightChecker:
    """
    Reads MCP server configs and project structure, builds a checklist of
    required system dependencies, and optionally installs missing ones.
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

    def install_item(self, item: PreflightItem) -> Tuple[bool, str]:
        """Run item.hint as a shell command. Returns (success, output)."""
        if item.manual:
            return False, "Manual step — run the command yourself, then re-run preflight."
        try:
            result = subprocess.run(
                item.hint, shell=True, capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                return True, (result.stdout or "").strip()
            return False, (result.stderr or result.stdout or "non-zero exit").strip()
        except subprocess.TimeoutExpired:
            return False, "Install command timed out after 5 minutes."
        except Exception as e:
            return False, str(e)

    def summary(self, items: List[PreflightItem]) -> dict:
        passed  = sum(1 for i in items if i.status == "pass")
        failed  = sum(1 for i in items if i.status == "fail")
        skipped = sum(1 for i in items if i.status == "skip")
        return {
            "total": len(items), "passed": passed,
            "failed": failed, "skipped": skipped,
            "ready": failed == 0,
            "platform": _PLATFORM,
        }

    # ------------------------------------------------------------------
    # Core project checks
    # ------------------------------------------------------------------

    def _check_core(self) -> List[PreflightItem]:
        items = []
        is_windows = _PLATFORM == "windows"

        # Python venv
        venv_python = _PROJECT_ROOT / ("venv/Scripts/python.exe" if is_windows else "venv/bin/python")
        pip_cmd = "python -m venv venv && venv\\Scripts\\pip install -r requirements.txt" if is_windows \
                  else "python3 -m venv venv && venv/bin/pip install -r requirements.txt"
        items.append(PreflightItem(
            name="Python venv",
            source="MoJoAssistant core",
            check_type="file",
            check_value=str(venv_python),
            hint=pip_cmd,
        ))

        # .env file
        env_copy = "copy .env.example .env" if is_windows else "cp .env.example .env"
        items.append(PreflightItem(
            name=".env config",
            source="MoJoAssistant core",
            check_type="file",
            check_value=str(_PROJECT_ROOT / ".env"),
            hint=f"{env_copy}  # then edit .env with your API keys",
            manual=True,
        ))

        # agent-shell (Unix only — Windows uses WSL)
        if not is_windows:
            agent_shell = _PROJECT_ROOT / "scripts" / "agent-shell"
            items.append(PreflightItem(
                name="scripts/agent-shell",
                source="tmux MCP server",
                check_type="file_executable",
                check_value=str(agent_shell),
                hint=f"chmod +x {agent_shell}",
            ))
            items.append(PreflightItem(
                name="config/tmux-mcp.toml",
                source="tmux MCP server",
                check_type="file",
                check_value=str(_PROJECT_ROOT / "config" / "tmux-mcp.toml"),
                hint="File should be in the repo — run: git status",
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
            servers: Dict[str, dict] = {}
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

            # Is the MCP binary already present? (used to skip install-only deps)
            mcp_binary_present = False
            if command and srv.get("transport", "stdio") == "stdio":
                expanded = os.path.expanduser(os.path.expandvars(command))
                mcp_binary_present = (
                    Path(expanded).is_file() if os.path.isabs(expanded) else bool(shutil.which(expanded))
                )

            # requires[] — system dependencies
            for req in srv.get("requires", []):
                binary = req.get("binary", "")
                if not binary:
                    continue
                # Resolve hint: JSON override first, then platform table
                hint, is_manual = resolve_hint(
                    binary,
                    override_hint=req.get("hint", ""),
                    override_manual=str(req.get("manual", "false")).lower() == "true",
                )
                # Skip install-only (manual) deps when the binary is already installed
                if is_manual and mcp_binary_present:
                    items.append(PreflightItem(
                        name=f"{binary} (system)",
                        source=srv_name,
                        check_type="binary",
                        check_value=binary,
                        hint=hint,
                        manual=is_manual,
                        status="skip",
                        detail=f"Skipped — {srv_id} binary already present",
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

            # The MCP server binary itself
            if command and srv.get("transport", "stdio") == "stdio":
                expanded = os.path.expanduser(os.path.expandvars(command))
                # Resolve install_hint through platform table if it's a known binary
                bin_name = Path(expanded).name  # e.g. "tmux-mcp-rs", "npx"
                raw_hint = srv.get("install_hint", "")
                hint, is_manual = resolve_hint(bin_name, override_hint=raw_hint)
                items.append(PreflightItem(
                    name=f"{srv_id} MCP binary",
                    source=srv_name,
                    check_type="binary_path",
                    check_value=expanded,
                    hint=hint,
                    manual=is_manual,
                ))

        return items

    # ------------------------------------------------------------------
    # Check runner
    # ------------------------------------------------------------------

    def _run_check(self, item: PreflightItem) -> Tuple[str, str]:
        if item.check_type == "binary":
            found = shutil.which(item.check_value)
            return ("pass", f"Found: {found}") if found else ("fail", f"'{item.check_value}' not found on PATH")

        if item.check_type == "binary_path":
            path = Path(item.check_value)
            if path.is_absolute():
                return ("pass", f"Found: {path}") if path.is_file() else ("fail", f"Not found: {path}")
            found = shutil.which(item.check_value)
            return ("pass", f"Found: {found}") if found else ("fail", f"'{item.check_value}' not found on PATH")

        if item.check_type == "file":
            path = Path(item.check_value)
            return ("pass", f"Found: {path}") if path.exists() else ("fail", f"Missing: {path}")

        if item.check_type == "file_executable":
            path = Path(item.check_value)
            if path.exists() and os.access(path, os.X_OK):
                return "pass", f"Found and executable: {path}"
            if path.exists():
                return "fail", f"Exists but not executable: {path}"
            return "fail", f"Missing: {path}"

        if item.check_type == "env_key":
            val = os.environ.get(item.check_value)
            return ("pass", f"Set (length={len(val)})") if val else ("fail", f"'{item.check_value}' not set")

        return "skip", "Unknown check type"
