"""Dynamic Tool Registry with Sandbox Security."""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.config.paths import get_memory_path


def _get_agent_workdir() -> str:
    """Return the configured agent working directory, creating it if needed.

    Reads `agent_workdir` from ~/.memory/config/infra_context.json.
    Falls back to ~/.memory/sandboxes if not set.
    """
    fallback = Path.home() / ".memory" / "sandboxes"
    try:
        infra_path = Path(get_memory_path()) / "config" / "infra_context.json"
        data = json.loads(infra_path.read_text(encoding="utf-8"))
        raw = data.get("agent_workdir", "")
        workdir = Path(raw).expanduser() if raw else fallback
    except Exception:
        workdir = fallback
    workdir.mkdir(parents=True, exist_ok=True)
    return str(workdir)


class SandboxSecurity:
    """Enforces sandbox security boundaries for tools.

    Write operations are restricted to the memory path.
    Read operations additionally allow the project working directory.
    """

    def __init__(self, allowed_paths: List[str] = None, max_file_size_mb: int = 10):
        self.allowed_paths = allowed_paths or []
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024

    def _write_roots(self) -> List[str]:
        """Absolute paths where writes are permitted."""
        roots = [str(Path(get_memory_path()).resolve())]
        for p in self.allowed_paths:
            roots.append(str(Path(p).expanduser().resolve()))
        return roots

    def _read_roots(self) -> List[str]:
        """Absolute paths where reads are permitted (writes + cwd)."""
        return self._write_roots() + [str(Path.cwd().resolve())]

    def is_path_allowed(self, path: str, write: bool = False) -> bool:
        """Check if path is within allowed sandbox directories."""
        path_abs = str(Path(path).expanduser().resolve())
        roots = self._write_roots() if write else self._read_roots()
        return any(path_abs.startswith(r) for r in roots)

    def is_write_allowed(self, path: str) -> bool:
        return self.is_path_allowed(path, write=True)

    def is_file_size_allowed(self, size: int) -> bool:
        """Check if file size is within limits."""
        return size <= self.max_file_size_bytes

    def is_file_size_allowed(self, size: int) -> bool:
        """Check if file size is within limits."""
        return size <= self.max_file_size_bytes


class CapabilityDefinition:
    """
    Defines a tool with metadata, execution logic, and security levels.

    The `executor` field controls how the tool is run:
      {"type": "builtin"}                                — hardcoded handler (default)
      {"type": "shell", "command": "python3 /path/script.py"}  — subprocess, JSON on stdin/stdout
      {"type": "python", "module": "my.module", "function": "run"} — importlib + call
      {"type": "mcp_proxy", "tool": "mcp__Server__tool_name"}     — proxy to MCP tool
    """

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
        executor: Dict[str, Any] = None,
        category: str = "",
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
        # How to run the tool — defaults to builtin (hardcoded handler lookup)
        self.executor: Dict[str, Any] = executor or {"type": "builtin"}
        # Tool catalog category (memory, file, web, exec, comms, browser, terminal, ...)
        self.category = category

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
        d = {
            "name": self.name,
            "description": self.description,
            "danger_level": self.danger_level,
            "version": self.version,
            "requires_auth": self.requires_auth,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "parameters": self.parameters,
            "executor": self.executor,
        }
        if self.category:
            d["category"] = self.category
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapabilityDefinition":
        return cls(
            name=data["name"],
            description=data["description"],
            danger_level=data.get("danger_level", "low"),
            version=data.get("version", "1.0.0"),
            requires_auth=data.get("requires_auth", False),
            created_at=data.get("created_at"),
            created_by=data.get("created_by", "system"),
            parameters=data.get("parameters"),
            executor=data.get("executor"),
            category=data.get("category", ""),
        )


class CapabilityRegistry:
    """Dynamic tool registry that can be updated at runtime.

    Two-layer loading — system layer first, personal layer second (wins on conflict):
      1. config/dynamic_tools.json          — system defaults (repo, read-only)
      2. ~/.memory/config/dynamic_tools.json — user custom tools (personal, writable)

    add_tool() / remove_tool() always write to the personal layer so user changes
    survive git pulls and are never mixed into the repo.
    """

    def __init__(self, registry_path: str = None):
        config_dir = os.path.join(os.path.dirname(__file__), "..", "..", "config")
        self.registry_path = registry_path or os.path.join(config_dir, "dynamic_tools.json")
        self.personal_registry_path = os.path.join(
            get_memory_path(), "config", "dynamic_tools.json"
        )
        self.memory_path = get_memory_path()
        self.example_registry_path = os.path.join(
            config_dir, "examples", "dynamic_tools.example.json"
        )
        self.sandbox = SandboxSecurity()
        self._memory_service = None
        self._mcp_registry = None
        self._mcp_client_manager = None
        self._scheduler = None
        self._current_task_id: Optional[str] = None
        self._current_dispatch_depth: int = 0
        self._tools: Dict[str, CapabilityDefinition] = {}
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
        """Load tools from system layer then personal layer (personal wins on conflict)."""
        # Layer 1: system defaults
        if os.path.exists(self.registry_path):
            try:
                with open(self.registry_path, "r") as f:
                    data = json.load(f)
                    for tool_data in data.get("tools", []):
                        tool = CapabilityDefinition.from_dict(tool_data)
                        self._tools[tool.name] = tool
            except Exception as e:
                print(f"Failed to load system tool registry: {e}")

        # Layer 2: personal user tools (~/.memory/config/dynamic_tools.json)
        if os.path.exists(self.personal_registry_path):
            try:
                with open(self.personal_registry_path, "r") as f:
                    data = json.load(f)
                    for tool_data in data.get("tools", []):
                        tool = CapabilityDefinition.from_dict(tool_data)
                        tool.created_by = tool_data.get("created_by", "user")
                        self._tools[tool.name] = tool  # overrides system if same name
            except Exception as e:
                print(f"Failed to load personal tool registry: {e}")

    def _save_registry(self):
        """Save user-created tools to the personal layer only.

        System tools (created_by='system') are never written back — they live
        in config/dynamic_tools.json and are managed via git.
        """
        try:
            os.makedirs(os.path.dirname(self.personal_registry_path), exist_ok=True)
            user_tools = [
                t.to_dict() for t in self._tools.values()
                if t.created_by != "system"
            ]
            data = {
                "last_updated": datetime.now().isoformat(),
                "tools": user_tools,
            }
            with open(self.personal_registry_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Failed to save personal tool registry: {e}")

    def _register_builtins(self):
        """Register built-in tools."""
        builtins = [
            CapabilityDefinition(
                name="read_file",
                description="Read file contents. Returns full text with line numbers.",
                danger_level="low",
                category="file",
                parameters={"type": "object", "properties": {
                    "path": {"type": "string", "description": "Absolute or relative file path to read"},
                }, "required": ["path"]},
            ),
            CapabilityDefinition(
                name="write_file",
                description="Write content to file. Overwrites existing file. Only allowed in sandbox paths.",
                danger_level="medium",
                category="file",
                parameters={"type": "object", "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Content to write"},
                }, "required": ["path", "content"]},
            ),
            CapabilityDefinition(
                name="list_files",
                description="List files and directories in a path.",
                danger_level="low",
                category="file",
                parameters={"type": "object", "properties": {
                    "path": {"type": "string", "description": "Directory path to list"},
                }, "required": ["path"]},
            ),
            CapabilityDefinition(
                name="search_in_files",
                description="Search for text across files using grep/ripgrep.",
                danger_level="low",
                category="file",
                parameters={"type": "object", "properties": {
                    "query": {"type": "string", "description": "Text or regex query to search for"},
                    "path": {"type": "string", "description": "Directory or file to search in"},
                }, "required": ["query"]},
            ),
            CapabilityDefinition(
                name="bash_exec",
                description=(
                    "Run shell commands on this machine. Accepts a single command string "
                    "or a list of commands to execute sequentially. Destructive and "
                    "privileged commands remain blocked by the sandbox policy."
                ),
                danger_level="high",
                requires_auth=True,
                category="exec",
                parameters={"type": "object", "properties": {
                    "commands": {
                        "description": "Shell command or list of shell commands to run sequentially",
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                    },
                    "command": {
                        "type": "string",
                        "description": "Backward-compatible alias for a single shell command",
                    },
                }, "required": []},
            ),
            CapabilityDefinition(
                name="scheduler_add_task",
                description=(
                    "Schedule a new task for another agent. Use this to hand off work to a "
                    "specialist role after completing your own step — e.g. a provisioner queuing "
                    "a reviewer, or a researcher queuing a code reviewer. "
                    "The new task runs asynchronously; this tool returns immediately."
                ),
                danger_level="medium",
                category="orchestration",
                parameters={"type": "object", "properties": {
                    "task_id":    {"type": "string", "description": "Unique task identifier (snake_case)"},
                    "role_id":    {"type": "string", "description": "Role to run the task as (e.g. 'researcher', 'reviewer')"},
                    "goal":       {"type": "string", "description": "Full goal/instructions for the new task"},
                    "available_tools": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Tools the new task may use. Defaults to role's capabilities."
                    },
                    "max_iterations": {"type": "integer", "description": "Max iterations (default 10)"},
                    "priority":   {"type": "string", "enum": ["low", "normal", "high"], "description": "Task priority"},
                }, "required": ["task_id", "role_id", "goal"]},
            ),
            CapabilityDefinition(
                name="dispatch_subtask",
                description=(
                    "Dispatch a task to another agent role and WAIT for its result before continuing. "
                    "Use when you need a specialist to do work that you cannot do yourself — e.g. "
                    "a researcher dispatches to a provisioner to clone a repo, then reads the report. "
                    "The sub-task runs as a full agentic session; its final answer is returned here. "
                    "Max dispatch depth: 2 (sub-tasks cannot themselves dispatch further sub-tasks). "
                    "Prefer this over scheduler_add_task when you need the result in the current task."
                ),
                danger_level="medium",
                category="orchestration",
                parameters={"type": "object", "properties": {
                    "role_id":         {"type": "string", "description": "Role ID to run the sub-task as (must exist in ~/.memory/roles/)"},
                    "goal":            {"type": "string", "description": "Full goal/instructions for the sub-task"},
                    "available_tools": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Tools the sub-task may use. Defaults to role's capabilities."
                    },
                    "max_iterations":  {"type": "integer", "description": "Max iterations for sub-task (default 10)"},
                    "timeout_s":       {"type": "integer", "description": "Seconds to wait for result (default 300)"},
                }, "required": ["role_id", "goal"]},
            ),
            CapabilityDefinition(
                name="memory_search",
                description="Search user's memory (conversations, documents, knowledge base).",
                danger_level="low",
                category="memory",
                parameters={"type": "object", "properties": {
                    "query": {"type": "string", "description": "Search query to find relevant context"},
                }, "required": ["query"]},
            ),
            CapabilityDefinition(
                name="task_session_read",
                description=(
                    "Read a scheduler task session from ~/.memory/task_sessions by task_id. "
                    "Use this instead of raw filesystem probing when you need iteration logs, "
                    "tool usage, or final answers from prior assistant tasks."
                ),
                danger_level="low",
                category="memory",
                parameters={"type": "object", "properties": {
                    "task_id": {"type": "string", "description": "Task id whose session should be loaded"},
                    "include_metadata": {
                        "type": "boolean",
                        "description": "Include per-message metadata when true",
                        "default": False,
                    },
                }, "required": ["task_id"]},
            ),
            CapabilityDefinition(
                name="task_report_read",
                description=(
                    "Read a normalized task report from ~/.memory/task_reports by task_id. "
                    "Use this when you need the structured completion record instead of the "
                    "full session transcript."
                ),
                danger_level="low",
                category="memory",
                parameters={"type": "object", "properties": {
                    "task_id": {"type": "string", "description": "Task id whose report should be loaded"},
                }, "required": ["task_id"]},
            ),
            CapabilityDefinition(
                name="ask_user",
                description=(
                    "Pause the task and ask the user a question. "
                    "Use when you need information only the user can provide. "
                    "The task will wait in WAITING_FOR_INPUT state until the user replies. "
                    "Do not use this for information you can gather with other tools."
                ),
                danger_level="low",
                category="comms",
                parameters={"type": "object", "properties": {
                    "question": {"type": "string", "description": "The question to ask the user"},
                    "choices": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of suggested answer choices to present to the user",
                    },
                }, "required": ["question"]},
            ),
            CapabilityDefinition(
                name="web_search",
                description=(
                    "Search the web using Google Custom Search. "
                    "Returns titles, snippets, and URLs. "
                    "Requires GOOGLE_API_KEY and GOOGLE_SEARCH_ENGINE_ID environment variables."
                ),
                danger_level="low",
                category="web",
                parameters={"type": "object", "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {
                        "type": "integer",
                        "description": "Number of results to return (max 10, default 5)",
                        "default": 5,
                    },
                }, "required": ["query"]},
            ),
            CapabilityDefinition(
                name="fetch_url",
                description=(
                    "Fetch and return the plain-text content of a specific web page. "
                    "Strips HTML tags and returns readable text. "
                    "Only use on specific article or document URLs — NOT on site homepages, "
                    "section index pages, or search result pages. Those pages are mostly "
                    "navigation HTML and return thousands of tokens of unusable content. "
                    "Typical use: call web_search first, then fetch_url on a specific article "
                    "URL from the results when you need the full text."
                ),
                danger_level="low",
                category="web",
                parameters={"type": "object", "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return (default 8000)",
                        "default": 8000,
                    },
                }, "required": ["url"]},
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

    def get_tool(self, name: str) -> Optional[CapabilityDefinition]:
        """Get tool definition by name."""
        return self._tools.get(name)

    def add_tool(self, tool: CapabilityDefinition) -> bool:
        """Add or update a user tool. Always saved to the personal layer."""
        if tool.created_by == "system":
            tool.created_by = "user"  # user-added tools are never system tools
        self._tools[tool.name] = tool
        self._save_registry()
        return True

    def remove_tool(self, name: str) -> bool:
        """Remove a user tool. System built-in tools cannot be removed."""
        tool = self._tools.get(name)
        if not tool:
            return False
        if tool.created_by == "system":
            return False  # system tools are protected; disable via role capabilities instead
        del self._tools[name]
        self._save_registry()
        return True

    def list_user_tools(self) -> List[CapabilityDefinition]:
        """Return only user-created tools (personal layer)."""
        return [t for t in self._tools.values() if t.created_by != "system"]

    def list_all_tools(self) -> List[CapabilityDefinition]:
        """Return all tools (system + user)."""
        return list(self._tools.values())

    async def execute_tool(
        self,
        name: str,
        args: Dict[str, Any],
        user_id: str = None,
    ) -> Dict[str, Any]:
        """Execute a tool, dispatching on executor type."""
        tool = self.get_tool(name)
        if not tool:
            return {"success": False, "error": f"Tool '{name}' not found"}

        if tool.danger_level == "critical" and not user_id:
            return {"success": False, "error": "Critical tools require authentication"}

        executor_type = tool.executor.get("type", "builtin")

        try:
            if executor_type == "shell":
                return await self._run_shell_executor(tool, args)
            elif executor_type == "python":
                return await self._run_python_executor(tool, args)
            elif executor_type == "mcp_proxy":
                return await self._run_mcp_proxy_executor(tool, args)
            elif executor_type == "external_mcp":
                return await self._run_external_mcp_executor(tool, args)
            else:
                # builtin: dispatch on tool name
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
                elif name == "task_session_read":
                    return await self._task_session_read(args)
                elif name == "task_report_read":
                    return await self._task_report_read(args)
                elif name == "scheduler_add_task":
                    return await self._scheduler_add_task(args)
                elif name == "dispatch_subtask":
                    return await self._dispatch_subtask(args)
                elif name == "memory_search":
                    return await self._memory_search(args)
                elif name == "web_search":
                    return await self._web_search(args)
                elif name == "fetch_url":
                    return await self._fetch_url(args)
                else:
                    return {
                        "success": False,
                        "error": f"Tool '{name}' has no builtin handler",
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

        if not self.sandbox.is_write_allowed(path):
            return {"success": False, "error": f"Path '{path}' not in write sandbox (only ~/.memory/ allowed)"}

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
        # Backward-compatible alias: older schemas/prompts used "pattern".
        # Canonical model-facing schema is now "query" so capability->tool
        # translation matches the runtime handler.
        query = args.get("query") or args.get("pattern")
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

    async def _task_session_read(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Read a task session by task_id."""
        try:
            from app.scheduler.session_storage import SessionStorage

            task_id = args.get("task_id")
            include_metadata = bool(args.get("include_metadata", False))
            if not task_id:
                return {"success": False, "error": "Missing 'task_id' parameter"}

            storage = SessionStorage()
            session = storage.load_session(task_id)
            if session is None:
                return {"success": False, "error": f"No session found for task '{task_id}'"}

            messages = []
            for msg in session.messages:
                entry = {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp,
                    "iteration": msg.iteration,
                }
                if msg.tool_call_id:
                    entry["tool_call_id"] = msg.tool_call_id
                if msg.tool_name:
                    entry["tool_name"] = msg.tool_name
                if include_metadata and msg.metadata:
                    entry["metadata"] = msg.metadata
                messages.append(entry)

            return {
                "success": True,
                "task_id": session.task_id,
                "session_status": session.status,
                "started_at": session.started_at,
                "completed_at": session.completed_at,
                "final_answer": session.final_answer,
                "error_message": session.error_message,
                "message_count": len(messages),
                "messages": messages,
                "metadata": session.metadata,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to read task session: {e}"}

    async def _task_report_read(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Read a task report by task_id."""
        try:
            task_id = args.get("task_id")
            if not task_id:
                return {"success": False, "error": "Missing 'task_id' parameter"}

            report_path = Path(self.memory_path) / "task_reports" / f"{task_id}.json"
            if not report_path.exists():
                return {"success": False, "error": f"No report found for task '{task_id}'"}

            with open(report_path, encoding="utf-8") as f:
                report = json.load(f)

            return {"success": True, "task_id": task_id, "report": report}
        except Exception as e:
            return {"success": False, "error": f"Failed to read task report: {e}"}

    async def _scheduler_add_task(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Schedule a new task for another agent role."""
        if not self._scheduler:
            return {"success": False, "error": "Scheduler not available in this context"}

        from app.scheduler.models import Task, TaskResources
        import uuid

        task_id = args.get("task_id") or f"agent_task_{uuid.uuid4().hex[:8]}"
        role_id = args.get("role_id")
        goal = args.get("goal")

        if not role_id or not goal:
            return {"success": False, "error": "role_id and goal are required"}

        config: Dict[str, Any] = {"goal": goal, "role_id": role_id}
        if args.get("available_tools"):
            config["available_tools"] = args["available_tools"]

        resources = TaskResources(
            max_iterations=int(args.get("max_iterations", 10))
        )

        from app.scheduler.models import TaskPriority, TaskType
        priority_str = args.get("priority", "normal")
        # Map "normal" → "medium" for backwards compat; convert string → enum
        priority_str = "medium" if priority_str == "normal" else priority_str
        try:
            priority_enum = TaskPriority(priority_str.lower())
        except ValueError:
            priority_enum = TaskPriority.MEDIUM

        task = Task(
            id=task_id,
            type=TaskType.ASSISTANT,
            priority=priority_enum,
            config=config,
            resources=resources,
            created_by="agent",
        )

        success = self._scheduler.add_task(task)
        if success:
            return {"success": True, "task_id": task_id, "message": f"Task '{task_id}' scheduled for role '{role_id}'"}
        return {"success": False, "error": f"Failed to schedule task '{task_id}' — may already exist"}

    MAX_DISPATCH_DEPTH = 2
    DISPATCH_POLL_INTERVAL_S = 3
    DISPATCH_DEFAULT_TIMEOUT_S = 300

    async def _dispatch_subtask(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispatch a sub-task to another agent role and block until it completes.

        Creates a Task with parent linkage, adds it to the scheduler queue, then
        polls until done (or timeout). Returns the sub-task's final_answer.
        """
        if not self._scheduler:
            return {"success": False, "error": "Scheduler not available in this context"}

        if self._current_dispatch_depth >= self.MAX_DISPATCH_DEPTH:
            return {
                "success": False,
                "error": (
                    f"Max dispatch depth ({self.MAX_DISPATCH_DEPTH}) reached. "
                    "Sub-tasks cannot dispatch further sub-tasks."
                ),
            }

        import asyncio
        import uuid
        from app.scheduler.models import Task, TaskType, TaskPriority, TaskResources

        role_id = args.get("role_id")
        goal = args.get("goal")
        if not role_id or not goal:
            return {"success": False, "error": "role_id and goal are required"}

        task_id = f"sub_{self._current_task_id or 'unknown'}_{uuid.uuid4().hex[:6]}"
        timeout_s = int(args.get("timeout_s", self.DISPATCH_DEFAULT_TIMEOUT_S))

        config: Dict[str, Any] = {"goal": goal, "role_id": role_id}
        if args.get("available_tools"):
            config["available_tools"] = args["available_tools"]

        task = Task(
            id=task_id,
            type=TaskType.ASSISTANT,
            priority=TaskPriority.MEDIUM,
            config=config,
            resources=TaskResources(max_iterations=int(args.get("max_iterations", 10))),
            created_by="agent",
            parent_task_id=self._current_task_id,
            dispatch_depth=self._current_dispatch_depth + 1,
        )

        if not self._scheduler.add_task(task):
            return {"success": False, "error": f"Failed to queue sub-task '{task_id}'"}

        # Poll until complete or timeout
        elapsed = 0.0
        while elapsed < timeout_s:
            await asyncio.sleep(self.DISPATCH_POLL_INTERVAL_S)
            elapsed += self.DISPATCH_POLL_INTERVAL_S
            t = self._scheduler.get_task(task_id)
            if t is None:
                return {"success": False, "error": f"Sub-task '{task_id}' disappeared from queue"}
            if t.status.value in ("completed", "failed"):
                if t.status.value == "failed":
                    err = t.last_error or "Sub-task failed without error detail"
                    return {"success": False, "task_id": task_id, "error": err}
                result = t.result
                final_answer = ""
                if result:
                    final_answer = result.metrics.get("final_answer", "") if result.metrics else ""
                return {
                    "success": True,
                    "task_id": task_id,
                    "role_id": role_id,
                    "result": final_answer,
                }

        return {
            "success": False,
            "task_id": task_id,
            "error": f"Sub-task did not complete within {timeout_s}s timeout",
        }

    async def _bash_exec(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute shell command(s) with safety limits."""
        raw_commands = args.get("commands", args.get("command"))
        if raw_commands is None:
            return {"success": False, "error": "Missing 'commands' parameter"}

        if isinstance(raw_commands, str):
            commands = [raw_commands]
        elif isinstance(raw_commands, list) and all(isinstance(cmd, str) for cmd in raw_commands):
            commands = raw_commands
        else:
            return {
                "success": False,
                "error": "'commands' must be a string or list of strings",
            }

        commands = [cmd.strip() for cmd in commands if cmd and cmd.strip()]
        if not commands:
            return {"success": False, "error": "No shell commands provided"}

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

        results = []
        for command in commands:
            cmd_parts = command.split()
            if not cmd_parts:
                continue
            base_cmd = cmd_parts[0]

            if base_cmd in BLOCKED_COMMANDS:
                return {
                    "success": False,
                    "error": (
                        f"Command '{base_cmd}' is blocked — destructive or privileged "
                        "commands are not permitted."
                    ),
                    "results": results,
                }

            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=_get_agent_workdir(),
                )
            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "error": f"Command timed out (60s limit): {command}",
                    "results": results,
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "results": results,
                }

            command_result = {
                "command": command,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "success": result.returncode == 0,
            }
            results.append(command_result)

            if result.returncode != 0:
                return {
                    "success": False,
                    "results": results,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                    "error": f"Command failed: {command}",
                }

        combined_stdout = "".join(item["stdout"] for item in results)
        combined_stderr = "".join(item["stderr"] for item in results)
        return {
            "success": True,
            "results": results,
            "stdout": combined_stdout,
            "stderr": combined_stderr,
            "returncode": 0,
            "executed": len(results),
        }

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

    async def _web_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Google Custom Search API — returns titles, snippets, and URLs."""
        import urllib.request
        import urllib.parse

        query = args.get("query", "").strip()
        if not query:
            return {"success": False, "error": "query is required"}

        limit = min(int(args.get("limit", 5)), 10)

        api_key = os.environ.get("GOOGLE_API_KEY", "")
        cse_id = os.environ.get("GOOGLE_SEARCH_ENGINE_ID", "")
        if not api_key or not cse_id:
            return {
                "success": False,
                "error": (
                    "web_search is not configured. "
                    "Set GOOGLE_API_KEY and GOOGLE_SEARCH_ENGINE_ID environment variables. "
                    "Get a key at https://developers.google.com/custom-search/v1/overview "
                    "and create a search engine at https://programmablesearchengine.google.com/"
                ),
            }

        params = urllib.parse.urlencode({
            "key": api_key,
            "cx": cse_id,
            "q": query,
            "num": limit,
        })
        url = f"https://www.googleapis.com/customsearch/v1?{params}"

        try:
            import asyncio
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(url, timeout=15).read().decode("utf-8"),
            )
            import json as _json
            data = _json.loads(raw)

            results = []
            for item in data.get("items", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                })
            return {
                "success": True,
                "query": query,
                "results": results,
                "count": len(results),
            }
        except Exception as e:
            return {"success": False, "error": f"web_search failed: {e}"}

    async def _fetch_url(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch the text content of a URL. Strips HTML tags, returns plain text."""
        import urllib.request
        import urllib.error

        url = args.get("url", "").strip()
        if not url:
            return {"success": False, "error": "url is required"}

        max_chars = int(args.get("max_chars", 8000))

        try:
            import asyncio
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "MoJoAssistant/1.0 (research agent)"},
            )
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=20).read(),
            )

            # Detect encoding
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1", errors="replace")

            # Strip HTML tags with a simple regex
            import re
            text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"&[a-zA-Z]+;", " ", text)
            text = re.sub(r"\s{3,}", "\n\n", text)
            text = text.strip()

            if len(text) > max_chars:
                text = text[:max_chars] + f"\n\n[truncated — {len(text) - max_chars} chars remaining]"

            return {
                "success": True,
                "url": url,
                "content": text,
                "length": len(text),
            }
        except urllib.error.HTTPError as e:
            return {"success": False, "error": f"HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"success": False, "error": f"fetch_url failed: {e}"}

    async def _run_shell_executor(self, tool: "CapabilityDefinition", args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Shell executor: passes args as JSON on stdin, reads JSON result from stdout.

        Executor config:
          {"type": "shell", "command": "python3 ~/.memory/tools/my_tool.py"}
          {"type": "shell", "command": "/path/to/script.sh", "timeout": 30}

        Contract: script writes {"success": true/false, ...} JSON to stdout.
        """
        command = tool.executor.get("command", "")
        if not command:
            return {"success": False, "error": "Shell executor missing 'command'"}

        timeout = tool.executor.get("timeout", 60)
        command = os.path.expanduser(command)

        try:
            result = subprocess.run(
                command,
                shell=True,
                input=json.dumps(args),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode != 0 and not result.stdout.strip():
                return {
                    "success": False,
                    "error": result.stderr.strip() or f"Process exited with code {result.returncode}",
                }
            output = result.stdout.strip()
            if output:
                try:
                    return json.loads(output)
                except json.JSONDecodeError:
                    # Non-JSON output — wrap it
                    return {"success": result.returncode == 0, "output": output}
            return {"success": result.returncode == 0}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Shell tool timed out ({timeout}s)"}

    async def _run_python_executor(self, tool: "CapabilityDefinition", args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Python executor: dynamically imports a module and calls a function.

        Executor config:
          {"type": "python", "module": "my_package.my_module", "function": "run"}

        The function must accept (args: dict) -> dict and return {"success": bool, ...}.
        """
        module_path = tool.executor.get("module", "")
        func_name = tool.executor.get("function", "run")
        if not module_path:
            return {"success": False, "error": "Python executor missing 'module'"}

        import importlib
        import asyncio
        try:
            mod = importlib.import_module(module_path)
        except ImportError as e:
            return {"success": False, "error": f"Cannot import module '{module_path}': {e}"}

        func = getattr(mod, func_name, None)
        if func is None:
            return {"success": False, "error": f"Function '{func_name}' not found in '{module_path}'"}

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(args)
            else:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, func, args)
            return result if isinstance(result, dict) else {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": f"Python tool '{tool.name}' raised: {e}"}

    async def _run_mcp_proxy_executor(self, tool: "CapabilityDefinition", args: Dict[str, Any]) -> Dict[str, Any]:
        """
        MCP proxy executor: forwards the tool call to a named MCP tool.

        Executor config:
          {"type": "mcp_proxy", "tool": "mcp__MoJoAssistant__web_search"}

        This allows any registered MCP tool to be exposed to agentic agents
        without writing a builtin handler.
        """
        mcp_tool_name = tool.executor.get("tool", "")
        if not mcp_tool_name:
            return {"success": False, "error": "MCP proxy executor missing 'tool'"}

        # MCP proxy requires the ToolRegistry to be available
        if self._mcp_registry is None:
            return {
                "success": False,
                "error": "MCP proxy not available (no ToolRegistry set)",
            }

        try:
            result = await self._mcp_registry.execute(mcp_tool_name, args)
            if isinstance(result, dict):
                return result
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": f"MCP proxy '{mcp_tool_name}' failed: {e}"}

    async def _run_external_mcp_executor(self, tool: "CapabilityDefinition", args: Dict[str, Any]) -> Dict[str, Any]:
        """
        External MCP executor: forwards the call to a server managed by MCPClientManager.

        Executor config:
          {"type": "external_mcp", "server": "playwright", "tool": "browser_navigate"}
        """
        if self._mcp_client_manager is None:
            return {"success": False, "error": "External MCP not available (MCPClientManager not set)"}
        server_id = tool.executor.get("server", "")
        tool_name = tool.executor.get("tool", "")
        if not server_id or not tool_name:
            return {"success": False, "error": "external_mcp executor missing 'server' or 'tool'"}
        return await self._mcp_client_manager.call_tool(server_id, tool_name, args)

    def set_memory_service(self, memory_service):
        """Set memory service for memory_search tool."""
        self._memory_service = memory_service

    def set_mcp_registry(self, mcp_registry) -> None:
        """Set the MCP ToolRegistry for mcp_proxy executor support."""
        self._mcp_registry = mcp_registry

    def set_mcp_client_manager(self, manager) -> None:
        """Set the MCPClientManager for external_mcp executor support."""
        self._mcp_client_manager = manager

    def set_task_context(self, task_id: str, dispatch_depth: int = 0) -> None:
        """Set the current task context so dispatch_subtask can link parent→child."""
        self._current_task_id = task_id
        self._current_dispatch_depth = dispatch_depth

    def set_scheduler(self, scheduler) -> None:
        """Set the Scheduler for scheduler_add_task tool support."""
        self._scheduler = scheduler

    def get_tools_by_category(self, category: str) -> List[str]:
        """Return all tool names whose category matches."""
        return [name for name, tool in self._tools.items() if tool.category == category]
