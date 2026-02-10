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

        # Automatically run migrations if config exists
        if self.config_path.exists():
            self._migrate_to_phase1()

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
        git_url: str,
        port: int,
        password: str,
        project_name: str = None,
        title: str = None,
        description: str = None,
        ssh_key_path: str = None,
        base_dir: str = None,
    ):
        """
        Add OpenCode server to configuration (Phase 1 Refactor)

        Args:
            git_url: Git repository URL (will be normalized, used as primary key)
            port: OpenCode server port
            password: OpenCode server password
            project_name: Display name (optional, generated from git_url if not provided)
            title: Server title (optional)
            description: Server description (optional)
            ssh_key_path: Path to SSH key (optional)
            base_dir: Base directory where repo is cloned (optional)
        """
        from app.mcp.opencode.utils import normalize_git_url, generate_project_name

        config = self._read_config()
        normalized_url = normalize_git_url(git_url)

        # Auto-generate project_name if not provided
        if not project_name:
            project_name = generate_project_name(normalized_url)

        # Check if server already exists
        for server in config["servers"]:
            if server["id"] == normalized_url:
                # Update existing server
                server["url"] = f"http://127.0.0.1:{port}"
                server["password"] = password
                server["status"] = "active"
                server["project_name"] = project_name
                if ssh_key_path:
                    server["ssh_key_path"] = ssh_key_path
                if base_dir:
                    server["base_dir"] = base_dir
                self._write_config(config)
                return

        # Add new server
        server_entry = {
            "id": normalized_url,  # PRIMARY KEY: normalized git URL
            "git_url": normalized_url,  # Explicit field for clarity
            "project_name": project_name,  # Display name
            "title": title or project_name.replace("-", " ").title(),
            "description": description or f"OpenCode server for {project_name}",
            "url": f"http://127.0.0.1:{port}",
            "password": password,
            "status": "active",
            "added_at": datetime.utcnow().isoformat() + "Z",
        }

        # Add optional metadata
        if ssh_key_path:
            server_entry["ssh_key_path"] = ssh_key_path
        if base_dir:
            server_entry["base_dir"] = base_dir

        config["servers"].append(server_entry)

        # Set as default if it's the first server
        if not config["default_server"]:
            config["default_server"] = normalized_url

        self._write_config(config)

    def remove_server(self, git_url: str):
        """
        Remove server from configuration (Phase 1 Refactor)

        Args:
            git_url: Git repository URL (will be normalized)
        """
        from app.mcp.opencode.utils import normalize_git_url

        config = self._read_config()
        normalized_url = normalize_git_url(git_url)
        config["servers"] = [s for s in config["servers"] if s["id"] != normalized_url]

        # Update default if we removed it
        if config["default_server"] == normalized_url:
            config["default_server"] = (
                config["servers"][0]["id"] if config["servers"] else None
            )

        self._write_config(config)

    def update_server_status(self, git_url: str, status: str):
        """
        Update server status (Phase 1 Refactor)

        Args:
            git_url: Git repository URL (will be normalized)
            status: Status to set (active/inactive)
        """
        from app.mcp.opencode.utils import normalize_git_url

        config = self._read_config()
        normalized_url = normalize_git_url(git_url)
        for server in config["servers"]:
            if server["id"] == normalized_url:
                server["status"] = status
                break
        self._write_config(config)

    def get_server(self, git_url: str) -> Optional[Dict]:
        """
        Get server configuration by git URL (Phase 1 Refactor)

        Args:
            git_url: Git repository URL (will be normalized)

        Returns:
            Server configuration dict if found, None otherwise
        """
        from app.mcp.opencode.utils import normalize_git_url

        config = self._read_config()
        normalized_url = normalize_git_url(git_url)
        for server in config["servers"]:
            if server["id"] == normalized_url:
                return server
        return None

    def get_server_by_name(self, project_name: str) -> Optional[Dict]:
        """
        Get server by display name (backward compat helper)

        Note: This is slower than get_server() as it scans all servers.
        Use get_server(git_url) when possible.

        Args:
            project_name: Display name of project

        Returns:
            Server configuration dict if found, None otherwise
        """
        config = self._read_config()
        for server in config["servers"]:
            if server.get("project_name") == project_name:
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

    def _migrate_to_phase1(self):
        """
        Migrate config file to Phase 1: project_name IDs → git_url IDs

        Changes:
        - Re-key servers from project_name → git_url
        - Add project_name field for display
        - Add git_url field explicitly
        - Rename sandbox_dir → base_dir
        """
        from app.mcp.opencode.utils import normalize_git_url, generate_project_name

        if not self.config_path.exists():
            return  # No config to migrate

        config = self._read_config()
        servers = config.get("servers", [])

        if not servers:
            return  # No servers to migrate

        # Check if already migrated (if any server ID looks like a git URL)
        for server in servers:
            server_id = server.get("id", "")
            if "@" in server_id or server_id.startswith("http"):
                return  # Already migrated

        print("[OpenCode ConfigManager] Migrating config to Phase 1 (git_url IDs)...")

        new_servers = []
        seen_urls = set()

        for server in servers:
            old_id = server.get("id")
            git_url = server.get("git_url")

            # Skip if no git_url available
            if not git_url:
                print(f"  ⚠️  WARNING: Server '{old_id}' has no git_url, skipping")
                continue

            # Normalize git_url
            normalized_url = normalize_git_url(git_url)

            # Check for duplicates
            if normalized_url in seen_urls:
                print(
                    f"  ⚠️  WARNING: Duplicate git_url detected!\\n"
                    f"     Server '{old_id}' has same git_url as existing server.\\n"
                    f"     URL: {normalized_url}\\n"
                    f"     Keeping first instance only."
                )
                continue

            seen_urls.add(normalized_url)

            # Migrate server entry
            migrated = {
                "id": normalized_url,  # New primary key
                "git_url": normalized_url,  # Explicit field
                "project_name": server.get("project_name") or old_id,  # Preserve or use old ID
                "title": server.get("title"),
                "description": server.get("description"),
                "url": server.get("url"),
                "password": server.get("password"),
                "status": server.get("status", "active"),
                "added_at": server.get("added_at"),
            }

            # Migrate optional fields
            if "ssh_key_path" in server:
                migrated["ssh_key_path"] = server["ssh_key_path"]
            if "sandbox_dir" in server:
                migrated["base_dir"] = server["sandbox_dir"]  # Rename
            elif "base_dir" in server:
                migrated["base_dir"] = server["base_dir"]

            new_servers.append(migrated)
            print(f"  ✓ Migrated: {old_id} → {normalized_url}")

        # Update config
        config["servers"] = new_servers

        # Update default_server if it was set
        if config.get("default_server"):
            old_default = config["default_server"]
            # Try to find the new ID for the old default
            for server in new_servers:
                if server.get("project_name") == old_default:
                    config["default_server"] = server["id"]
                    break
            else:
                # Fallback: use first server if old default not found
                config["default_server"] = new_servers[0]["id"] if new_servers else None

        self._write_config(config)
        print(f"[OpenCode ConfigManager] Phase 1 migration complete! ({len(new_servers)} servers)")

    def migrate_all(self):
        """Run all migrations in sequence"""
        self._migrate_to_phase1()
