"""Dynamic Tool Registry with Sandbox Security."""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

class SandboxSecurity:
    """Enforces sandbox security boundaries for tools."""

    def __init__(self, allowed_paths: List[str] = None, max_file_size_mb: int = 10):
        self.allowed_paths = allowed_paths or ["~/.memory/"]
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024

    def is_path_allowed(self, path: str) -> bool:
        """Check if path is within allowed sandbox directories."""
        path_abs = str(Path(path).resolve())
        for allowed in self.allowed_paths:
            allowed_abs = str(Path(allowed).expanduser().resolve())
            if path_abs.startswith(allowed_abs):
                return True
        return False

    def is_file_size_allowed(self, size: int) -> bool:
        """Check if file size is within limits."""
        return size <= self.max_file_size_bytes


class ToolDefinition:
    """Defines a tool with metadata, execution logic, and security levels."""

    def __init__(
        self,
        name: str,
        description: str,
        danger_level: str = "low",
        version: str = "1.0.0",
        requires_auth: bool = False,
        created_at: str = None,
        created_by: str = "system",
        parameters: Dict[str, Any] = None,
    ):
        self.name = name
        self.description = description
        self.danger_level = danger_level  # low, medium, high, critical
        self.version = version
        self.requires_auth = requires_auth
        self.created_at = created_at or datetime.now().isoformat()
        self.created_by = created_by
        # JSON schema for the tool's arguments (OpenAI function-calling format)
        self.parameters = parameters or {"type": "object", "properties": {}, "required": []}

    def to_openai_function(self) -> Dict[str, Any]:
        """Return the OpenAI-compatible function definition for LLM tool calling."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "danger_level": self.danger_level,
            "version": self.version,
            "requires_auth": self.requires_auth,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "parameters": self.parameters,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolDefinition":
        return cls(
            name=data["name"],
            description=data["description"],
            danger_level=data.get("danger_level", "low"),
            version=data.get("version", "1.0.0"),
            requires_auth=data.get("requires_auth", False),
            created_at=data.get("created_at"),
            created_by=data.get("created_by", "system"),
            parameters=data.get("parameters"),
        )


class DynamicToolRegistry:
    """Dynamic tool registry that can be updated at runtime."""

    def __init__(self, registry_path: str = None):
        config_dir = os.path.join(os.path.dirname(__file__), "..", "..", "config")
        self.registry_path = registry_path or os.path.join(config_dir, "dynamic_tools.json")
        self.example_registry_path = os.path.join(
            config_dir, "examples", "dynamic_tools.example.json"
        )
        self.sandbox = SandboxSecurity()
        self._memory_service = None
        self._tools: Dict[str, ToolDefinition] = {}
        self._ensure_registry_seeded()
        self._load_registry()
        self._register_builtins()

    def _ensure_registry_seeded(self):
        """Seed runtime registry from example template if runtime file is missing."""
        if os.path.exists(self.registry_path):
            return
        try:
            os.makedirs(os.path.dirname(self.registry_path), exist_ok=True)
            if os.path.exists(self.example_registry_path):
                with open(self.example_registry_path, "r", encoding="utf-8") as src:
                    data = json.load(src)
                with open(self.registry_path, "w", encoding="utf-8") as dst:
                    json.dump(data, dst, indent=2)
        except Exception as e:
            print(f"Failed to seed tool registry from template: {e}")

    def _load_registry(self):
        """Load tools from registry file."""
        if os.path.exists(self.registry_path):
            try:
                with open(self.registry_path, "r") as f:
                    data = json.load(f)
                    for tool_data in data.get("tools", []):
                        tool = ToolDefinition.from_dict(tool_data)
                        self._tools[tool.name] = tool
            except Exception as e:
                print(f"Failed to load tool registry: {e}")

    def _save_registry(self):
        """Save tools to registry file."""
        try:
            os.makedirs(os.path.dirname(self.registry_path), exist_ok=True)
            with open(self.registry_path, "w") as f:
                data = {
                    "last_updated": datetime.now().isoformat(),
                    "tools": [tool.to_dict() for tool in self._tools.values()],
                }
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Failed to save tool registry: {e}")

    def _register_builtins(self):
        """Register built-in tools."""
        builtins = [
            ToolDefinition(
                name="read_file",
                description="Read file contents. Returns full text with line numbers.",
                danger_level="low",
                parameters={"type": "object", "properties": {
                    "path": {"type": "string", "description": "Absolute or relative file path to read"},
                }, "required": ["path"]},
            ),
            ToolDefinition(
                name="write_file",
                description="Write content to file. Overwrites existing file. Only allowed in sandbox paths.",
                danger_level="medium",
                parameters={"type": "object", "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Content to write"},
                }, "required": ["path", "content"]},
            ),
            ToolDefinition(
                name="list_files",
                description="List files and directories in a path.",
                danger_level="low",
                parameters={"type": "object", "properties": {
                    "path": {"type": "string", "description": "Directory path to list"},
                }, "required": ["path"]},
            ),
            ToolDefinition(
                name="search_in_files",
                description="Search for text across files using grep/ripgrep.",
                danger_level="low",
                parameters={"type": "object", "properties": {
                    "pattern": {"type": "string", "description": "Text or regex pattern to search for"},
                    "path": {"type": "string", "description": "Directory or file to search in"},
                }, "required": ["pattern"]},
            ),
            ToolDefinition(
                name="bash_exec",
                description="Execute bash command. Only safe commands in whitelist allowed.",
                danger_level="high",
                requires_auth=True,
                parameters={"type": "object", "properties": {
                    "command": {"type": "string", "description": "Bash command to execute"},
                }, "required": ["command"]},
            ),
            ToolDefinition(
                name="memory_search",
                description="Search user's memory (conversations, documents, knowledge base).",
                danger_level="low",
                parameters={"type": "object", "properties": {
                    "query": {"type": "string", "description": "Search query to find relevant context"},
                }, "required": ["query"]},
            ),
        ]
        for tool in builtins:
            # Always overwrite builtins — code definition (including parameters schema)
            # must take precedence over any stale on-disk registry entry.
            self._tools[tool.name] = tool

        self._save_registry()

    def list_tools(self) -> Dict[str, Dict[str, Any]]:
        """List all tools with metadata."""
        return {name: tool.to_dict() for name, tool in self._tools.items()}

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get tool definition by name."""
        return self._tools.get(name)

    def add_tool(self, tool: ToolDefinition) -> bool:
        """Add or update a tool."""
        self._tools[tool.name] = tool
        self._save_registry()
        return True

    def remove_tool(self, name: str) -> bool:
        """Remove a tool."""
        if name in self._tools:
            del self._tools[name]
            self._save_registry()
            return True
        return False

    async def execute_tool(
        self,
        name: str,
        args: Dict[str, Any],
        user_id: str = None,
    ) -> Dict[str, Any]:
        """Execute a tool with sandbox security."""
        tool = self.get_tool(name)
        if not tool:
            return {"success": False, "error": f"Tool '{name}' not found"}

        if tool.danger_level == "critical" and not user_id:
            return {"success": False, "error": "Critical tools require authentication"}

        try:
            if name == "read_file":
                return await self._read_file(args)
            elif name == "write_file":
                return await self._write_file(args)
            elif name == "list_files":
                return await self._list_files(args)
            elif name == "search_in_files":
                return await self._search_in_files(args)
            elif name == "bash_exec":
                return await self._bash_exec(args)
            elif name == "memory_search":
                return await self._memory_search(args)
            else:
                return {
                    "success": False,
                    "error": f"Tool '{name}' execution not implemented",
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _read_file(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Read file contents."""
        path = args.get("path")
        if not path:
            return {"success": False, "error": "Missing 'path' parameter"}

        if not self.sandbox.is_path_allowed(path):
            return {"success": False, "error": f"Path '{path}' not in sandbox"}

        if not os.path.exists(path):
            return {"success": False, "error": f"File '{path}' not found"}

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                content = "".join(lines)
                return {
                    "success": True,
                    "content": content,
                    "line_count": len(lines),
                    "size_bytes": len(content.encode()),
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _write_file(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Write content to file."""
        path = args.get("path")
        content = args.get("content")
        if not path or content is None:
            return {"success": False, "error": "Missing 'path' or 'content' parameter"}

        if not self.sandbox.is_path_allowed(path):
            return {"success": False, "error": f"Path '{path}' not in sandbox"}

        content_size = len(content.encode())
        if not self.sandbox.is_file_size_allowed(content_size):
            return {
                "success": False,
                "error": f"File size {content_size} exceeds limit",
            }

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return {
                "success": True,
                "message": f"Wrote {len(content)} bytes to {path}",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _list_files(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List files and directories."""
        path = args.get("path", ".")
        if not self.sandbox.is_path_allowed(path):
            return {"success": False, "error": f"Path '{path}' not in sandbox"}

        if not os.path.exists(path):
            return {"success": False, "error": f"Path '{path}' not found"}

        try:
            entries = []
            for entry in os.listdir(path):
                full_path = os.path.join(path, entry)
                stat = os.stat(full_path)
                entries.append(
                    {
                        "name": entry,
                        "is_dir": os.path.isdir(full_path),
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    }
                )
            return {"success": True, "entries": entries, "path": path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _search_in_files(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Search for text in files."""
        query = args.get("query")
        path = args.get("path", ".")
        if not query:
            return {"success": False, "error": "Missing 'query' parameter"}

        if not self.sandbox.is_path_allowed(path):
            return {"success": False, "error": f"Path '{path}' not in sandbox"}

        try:
            result = subprocess.run(
                ["rg", "--json", query, path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return {"success": True, "matches": [], "count": 0}

            matches = []
            for line in result.stdout.split("\n"):
                if line:
                    try:
                        data = json.loads(line)
                        if data.get("type") == "match":
                            matches.append(
                                {
                                    "path": data.get("data", {})
                                    .get("path", {})
                                    .get("text"),
                                    "line": data.get("data", {}).get("line_number"),
                                    "content": data.get("data", {})
                                    .get("lines", {})
                                    .get("text"),
                                }
                            )
                    except json.JSONDecodeError:
                        continue

            return {"success": True, "matches": matches, "count": len(matches)}
        except FileNotFoundError:
            return {"success": False, "error": "ripgrep (rg) not installed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _bash_exec(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute bash command with safety limits."""
        command = args.get("command")
        if not command:
            return {"success": False, "error": "Missing 'command' parameter"}

        # Block destructive commands — everything else is allowed.
        # Rule: read/observe/query = OK; modify/delete/overwrite = blocked.
        BLOCKED_COMMANDS = {
            # Deletion / overwrite
            "rm", "rmdir", "shred", "unlink",
            # Disk / filesystem
            "dd", "mkfs", "fdisk", "parted", "wipefs", "mkswap",
            # Privilege escalation
            "sudo", "su", "doas", "pkexec",
            # Permission / ownership changes
            "chmod", "chown", "chgrp",
            # Process termination
            "kill", "killall", "pkill",
            # Package mutation
            "apt", "apt-get", "dpkg", "yum", "dnf", "pacman", "snap", "pip",
            # Network config changes
            "ifconfig", "ip link set", "iptables", "ufw",
            # Systemd service changes
            "systemctl", "service",
            # Reboot / shutdown
            "reboot", "shutdown", "halt", "poweroff",
            # User / group management
            "useradd", "userdel", "usermod", "groupadd", "passwd",
            # Overwrite shortcuts
            "mv", "cp", "tee", "truncate",
        }

        cmd_parts = command.split()
        base_cmd = cmd_parts[0]

        if base_cmd in BLOCKED_COMMANDS:
            return {
                "success": False,
                "error": f"Command '{base_cmd}' is blocked — destructive or privileged commands are not permitted.",
            }

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=os.getcwd(),
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Command timed out (60s limit)"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _memory_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Search memory using memory service."""
        query = args.get("query", "")
        max_items = args.get("max_items", 5)

        if not self._memory_service:
            return {"success": False, "error": "Memory service not available"}

        try:
            results = await self._memory_service.get_context_for_query_async(
                query, max_items=max_items
            )
            return {
                "success": True,
                "query": query,
                "results": results,
                "count": len(results),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_memory_service(self, memory_service):
        """Set memory service for memory_search tool."""
        self._memory_service = memory_service
