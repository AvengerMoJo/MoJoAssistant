"""
Configuration Manager for opencode-mcp-tool servers

Manages the global configuration file listing all OpenCode servers.

File: app/mcp/opencode/config_manager.py
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime


class ConfigManager:
    """Manages opencode-mcp-tool-servers.json configuration"""

    def __init__(self, memory_root: str = None):
        self.memory_root = Path(memory_root or os.path.expanduser("~/.memory"))
        self.config_path = self.memory_root / "opencode-mcp-tool-servers.json"

    def _read_config(self) -> Dict:
        """Read configuration file"""
        if not self.config_path.exists():
            return {"version": "1.0", "servers": [], "default_server": None}

        with open(self.config_path, "r") as f:
            return json.load(f)

    def _write_config(self, config: Dict):
        """Write configuration file with secure permissions"""
        # Ensure directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)

        # Set restrictive permissions (owner read/write only)
        os.chmod(self.config_path, 0o600)

    def add_server(
        self,
        project_name: str,
        port: int,
        password: str,
        title: str = None,
        description: str = "",
    ):
        """Add OpenCode server to configuration"""
        config = self._read_config()

        # Check if server already exists
        for server in config["servers"]:
            if server["id"] == project_name:
                # Update existing server
                server["url"] = f"http://127.0.0.1:{port}"
                server["password"] = password
                server["status"] = "active"
                self._write_config(config)
                return

        # Add new server
        config["servers"].append(
            {
                "id": project_name,
                "title": title or project_name.replace("-", " ").title(),
                "description": description,
                "url": f"http://127.0.0.1:{port}",
                "password": password,
                "status": "active",
                "added_at": datetime.utcnow().isoformat() + "Z",
            }
        )

        # Set as default if it's the first server
        if not config["default_server"]:
            config["default_server"] = project_name

        self._write_config(config)

    def remove_server(self, project_name: str):
        """Remove server from configuration"""
        config = self._read_config()
        config["servers"] = [s for s in config["servers"] if s["id"] != project_name]

        # Update default if we removed it
        if config["default_server"] == project_name:
            config["default_server"] = (
                config["servers"][0]["id"] if config["servers"] else None
            )

        self._write_config(config)

    def update_server_status(self, project_name: str, status: str):
        """Update server status (active/inactive)"""
        config = self._read_config()
        for server in config["servers"]:
            if server["id"] == project_name:
                server["status"] = status
                break
        self._write_config(config)

    def get_server(self, project_name: str) -> Optional[Dict]:
        """Get server configuration by project name"""
        config = self._read_config()
        for server in config["servers"]:
            if server["id"] == project_name:
                return server
        return None

    def list_servers(self) -> List[Dict]:
        """List all servers in configuration"""
        config = self._read_config()
        return config["servers"]

    def get_active_servers(self) -> List[Dict]:
        """List only active servers"""
        config = self._read_config()
        return [s for s in config["servers"] if s["status"] == "active"]

    def get_config_path(self) -> str:
        """Get path to configuration file"""
        return str(self.config_path)
