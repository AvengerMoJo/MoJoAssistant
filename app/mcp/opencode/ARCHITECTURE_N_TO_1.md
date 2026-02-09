# OpenCode Manager N:1 Architecture Design

## Overview

Refactor from **1:1 architecture** (one opencode-mcp-tool per project) to **N:1 architecture** (many OpenCode servers sharing one global opencode-mcp-tool instance).

### Current (Wrong) Architecture
```
Project A → OpenCode:4100 → opencode-mcp-tool:5100
Project B → OpenCode:4101 → opencode-mcp-tool:5101
Project C → OpenCode:4102 → opencode-mcp-tool:5102
```

Problems:
- Multiple mcp-tool instances consuming resources
- Each project needs separate port for MCP client connection
- No easy way to switch between projects
- Complex state management

### New (Correct) Architecture
```
Project A → OpenCode:4100 ──┐
Project B → OpenCode:4101 ──┼─→ Single opencode-mcp-tool:5100
Project C → OpenCode:4102 ──┘
```

Benefits:
- Single MCP endpoint for all projects
- Runtime project switching
- Cleaner resource management
- Global mcp-tool lifecycle tied to active projects

---

## 1. State Model Changes

### Current State Schema
```json
{
  "projects": {
    "blog-api": {
      "project_name": "blog-api",
      "sandbox_dir": "/home/alex/.memory/opencode-sandboxes/blog-api",
      "git_url": "git@github.com:user/blog-api.git",
      "ssh_key_path": "/home/alex/.memory/opencode-keys/blog-api-deploy",
      "opencode": {
        "pid": 12345,
        "port": 4100,
        "status": "running",
        "error": null
      },
      "mcp_tool": {
        "pid": 12346,
        "port": 5100,
        "status": "running",
        "error": null
      },
      "created_at": "2026-02-01T10:00:00",
      "last_health_check": "2026-02-01T10:05:00"
    }
  }
}
```

### New State Schema
```json
{
  "global_mcp_tool": {
    "pid": 67890,
    "port": 5100,
    "status": "running",
    "error": null,
    "started_at": "2026-02-01T10:00:00",
    "last_health_check": "2026-02-01T10:05:00",
    "active_project_count": 3
  },
  "projects": {
    "blog-api": {
      "project_name": "blog-api",
      "sandbox_dir": "/home/alex/.memory/opencode-sandboxes/blog-api",
      "git_url": "git@github.com:user/blog-api.git",
      "ssh_key_path": "/home/alex/.memory/opencode-keys/blog-api-deploy",
      "opencode": {
        "pid": 12345,
        "port": 4100,
        "status": "running",
        "error": null
      },
      "created_at": "2026-02-01T10:00:00",
      "last_health_check": "2026-02-01T10:05:00"
    },
    "chatmcp": {
      "project_name": "chatmcp",
      "sandbox_dir": "/home/alex/.memory/opencode-sandboxes/chatmcp",
      "git_url": "git@github.com:user/chatmcp.git",
      "ssh_key_path": "/home/alex/.memory/opencode-keys/chatmcp-deploy",
      "opencode": {
        "pid": 12346,
        "port": 4101,
        "status": "running",
        "error": null
      },
      "created_at": "2026-02-01T10:01:00",
      "last_health_check": "2026-02-01T10:05:00"
    }
  }
}
```

**Key Changes:**
- Added `global_mcp_tool` at root level (separate from projects)
- Removed `mcp_tool` from individual project states
- Added `active_project_count` to track when to start/stop global tool
- State model now has two distinct sections: global tool + individual projects

---

## 2. Configuration File for opencode-mcp-tool

### File Location
`~/.memory/opencode-mcp-tool-servers.json`

This configuration file lists all available OpenCode servers that the global mcp-tool can connect to.

### Configuration Schema
```json
{
  "version": "1.0",
  "servers": [
    {
      "id": "blog-api",
      "title": "Blog API",
      "description": "REST API for blog platform",
      "url": "http://127.0.0.1:4100",
      "password": "***SENSITIVE***",
      "status": "active",
      "added_at": "2026-02-01T10:00:00"
    },
    {
      "id": "chatmcp",
      "title": "ChatMCP Client",
      "description": "Web-based MCP chat interface",
      "url": "http://127.0.0.1:4101",
      "password": "***SENSITIVE***",
      "status": "active",
      "added_at": "2026-02-01T10:01:00"
    },
    {
      "id": "ecommerce-backend",
      "title": "E-commerce Backend",
      "description": "Payment processing service",
      "url": "http://127.0.0.1:4102",
      "password": "***SENSITIVE***",
      "status": "inactive",
      "added_at": "2026-01-15T08:30:00"
    }
  ],
  "default_server": "blog-api"
}
```

**Field Descriptions:**
- `id`: Unique identifier (matches project_name)
- `title`: Human-readable display name
- `description`: Optional description of the project
- `url`: OpenCode server URL (http://127.0.0.1:{port})
- `password`: OpenCode server password (SENSITIVE - stored in this config file)
- `status`: `active` (OpenCode running) or `inactive` (OpenCode stopped)
- `added_at`: When this server was added to the configuration
- `default_server`: Which server to connect to by default

### Security Considerations

**CRITICAL: Password Storage**
- This configuration file contains OpenCode passwords (SENSITIVE)
- Must be stored with restrictive permissions: `chmod 600`
- Location: `~/.memory/opencode-mcp-tool-servers.json` (NOT in project sandboxes)
- This file is READ by opencode-mcp-tool to know which servers exist

**File Permissions:**
```bash
chmod 600 ~/.memory/opencode-mcp-tool-servers.json
```

### Configuration Management Operations

**Add Server (when project starts):**
```python
def add_server_to_config(project_name: str, port: int, password: str):
    """Add OpenCode server to global configuration"""
    config = read_config()
    config["servers"].append({
        "id": project_name,
        "title": project_name.replace("-", " ").title(),
        "description": "",
        "url": f"http://127.0.0.1:{port}",
        "password": password,
        "status": "active",
        "added_at": datetime.utcnow().isoformat()
    })
    write_config(config)
```

**Update Server Status (when project stops/starts):**
```python
def update_server_status(project_name: str, status: str):
    """Update server status in configuration"""
    config = read_config()
    for server in config["servers"]:
        if server["id"] == project_name:
            server["status"] = status
            break
    write_config(config)
```

**Remove Server (when project destroyed):**
```python
def remove_server_from_config(project_name: str):
    """Remove OpenCode server from global configuration"""
    config = read_config()
    config["servers"] = [s for s in config["servers"] if s["id"] != project_name]
    write_config(config)
```

---

## 3. Global MCP Tool Lifecycle Management

### Lifecycle States

```
NO_PROJECTS → STARTING → RUNNING → STOPPING → NO_PROJECTS
     ↑                                            ↓
     └────────────────────────────────────────────┘
```

### Lifecycle Rules

**Start Global MCP Tool When:**
- First project starts (active_project_count: 0 → 1)
- Global tool is not running AND any project starts

**Stop Global MCP Tool When:**
- Last project stops (active_project_count: 1 → 0)
- All projects are destroyed
- User explicitly calls `opencode_stop_mcp_tool` (new command)

**Don't Restart Global MCP Tool When:**
- Individual projects stop (as long as at least 1 project is still active)
- Individual projects restart (just reload configuration)

### Port Assignment for Global MCP Tool

**Strategy: Fixed Port with Fallback**
```python
GLOBAL_MCP_TOOL_PORT = 5100  # Default fixed port

def get_global_mcp_tool_port(state) -> int:
    """Get port for global MCP tool"""
    # If already running, reuse existing port
    if state.get("global_mcp_tool") and state["global_mcp_tool"].get("port"):
        return state["global_mcp_tool"]["port"]

    # Otherwise use default port (or find free port if occupied)
    return find_free_port(start_port=5100, end_port=5199)
```

---

## 4. opencode-mcp-tool Interface Design

### Expected opencode-mcp-tool CLI Changes

The `opencode-mcp-tool` repository needs to support multi-server mode:

**Current CLI (Single Server):**
```bash
npm run dev:http -- \
  --bearer-token <token> \
  --opencode-url http://127.0.0.1:4100 \
  --opencode-password <password> \
  --port 5100
```

**New CLI (Multi-Server Mode):**
```bash
npm run dev:http -- \
  --bearer-token <token> \
  --servers-config ~/.memory/opencode-mcp-tool-servers.json \
  --port 5100
```

**Key Changes:**
- Replace `--opencode-url` and `--opencode-password` with `--servers-config`
- Load server list from JSON configuration file
- Support runtime server selection via MCP tool parameter

### MCP Tool Interface for Server Selection

**Option 1: Tool Parameter (Recommended)**

Every MCP tool call includes optional `server` parameter:

```json
{
  "name": "run_terminal_command",
  "arguments": {
    "command": "npm install",
    "server": "blog-api"  // ← Optional: which OpenCode server to use
  }
}
```

If `server` is not specified, use `default_server` from configuration.

**Option 2: Session Context (Alternative)**

Client sets active server once per session:

```json
{
  "name": "opencode_select_server",
  "arguments": {
    "server": "chatmcp"
  }
}
```

Then subsequent tool calls go to the selected server until changed.

**Recommendation: Option 1 (Tool Parameter)**
- More explicit
- No hidden state
- Allows multi-server operations in same session
- Backwards compatible (defaults to default_server)

### Configuration Hot-Reload

**When configuration file changes:**
1. opencode-mcp-tool watches `~/.memory/opencode-mcp-tool-servers.json`
2. On file change, reload server list
3. Update internal routing table
4. Log: "Configuration reloaded: 3 servers available"

**Implementation in opencode-mcp-tool:**
```javascript
const fs = require('fs');
const chokidar = require('chokidar');

function watchConfig(configPath) {
  const watcher = chokidar.watch(configPath);

  watcher.on('change', () => {
    console.log('Configuration file changed, reloading...');
    reloadServers();
  });
}

function reloadServers() {
  const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  servers = config.servers.filter(s => s.status === 'active');
  defaultServer = config.default_server;
  console.log(`Configuration reloaded: ${servers.length} servers available`);
}
```

---

## 5. Manager Behavior Changes

### Models Changes (models.py)

**Add GlobalMCPToolInfo:**
```python
@dataclass
class GlobalMCPToolInfo:
    """Information about the global MCP tool instance"""
    pid: Optional[int] = None
    port: Optional[int] = None
    status: ProcessStatus = ProcessStatus.STOPPED
    error: Optional[str] = None
    started_at: Optional[str] = None
    last_health_check: Optional[str] = None
    active_project_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pid": self.pid,
            "port": self.port,
            "status": self.status.value,
            "error": self.error,
            "started_at": self.started_at,
            "last_health_check": self.last_health_check,
            "active_project_count": self.active_project_count,
        }
```

**Remove mcp_tool from ProjectState:**
```python
@dataclass
class ProjectState:
    """State of an OpenCode project"""
    project_name: str
    sandbox_dir: str
    git_url: str
    ssh_key_path: Optional[str] = None
    opencode: ProcessInfo = None  # Keep this
    # mcp_tool: ProcessInfo = None  # ← REMOVE THIS
    created_at: Optional[str] = None
    last_health_check: Optional[str] = None
```

### State Manager Changes (state_manager.py)

**Add global MCP tool state management:**
```python
class StateManager:
    # ... existing code ...

    def get_global_mcp_tool(self) -> Optional[GlobalMCPToolInfo]:
        """Get global MCP tool state"""
        state = self._read_state()
        if "global_mcp_tool" not in state:
            return None
        data = state["global_mcp_tool"]
        return GlobalMCPToolInfo(
            pid=data.get("pid"),
            port=data.get("port"),
            status=ProcessStatus(data.get("status", "stopped")),
            error=data.get("error"),
            started_at=data.get("started_at"),
            last_health_check=data.get("last_health_check"),
            active_project_count=data.get("active_project_count", 0),
        )

    def save_global_mcp_tool(self, mcp_tool_info: GlobalMCPToolInfo):
        """Save global MCP tool state"""
        state = self._read_state()
        state["global_mcp_tool"] = mcp_tool_info.to_dict()
        self._write_state(state)

    def update_global_mcp_tool_status(self, **kwargs):
        """Update specific fields of global MCP tool"""
        mcp_tool = self.get_global_mcp_tool() or GlobalMCPToolInfo()
        for key, value in kwargs.items():
            if hasattr(mcp_tool, key):
                setattr(mcp_tool, key, value)
        self.save_global_mcp_tool(mcp_tool)

    def increment_active_projects(self):
        """Increment active project count"""
        mcp_tool = self.get_global_mcp_tool() or GlobalMCPToolInfo()
        mcp_tool.active_project_count += 1
        self.save_global_mcp_tool(mcp_tool)

    def decrement_active_projects(self):
        """Decrement active project count"""
        mcp_tool = self.get_global_mcp_tool()
        if mcp_tool and mcp_tool.active_project_count > 0:
            mcp_tool.active_project_count -= 1
            self.save_global_mcp_tool(mcp_tool)
```

### Process Manager Changes (process_manager.py)

**Add global MCP tool process management:**
```python
class ProcessManager:
    # ... existing code ...

    def start_global_mcp_tool(
        self, bearer_token: str, servers_config_path: str, port: int = None
    ) -> Tuple[int, int, Optional[str]]:
        """
        Start global opencode-mcp-tool server

        Args:
            bearer_token: MCP tool bearer token
            servers_config_path: Path to servers configuration JSON
            port: Port to use (will find free port if None)

        Returns:
            Tuple of (pid, port, error_message)
        """
        port = port or self.find_free_port(5100, 5199)

        # Determine MCP tool directory from environment or config
        mcp_tool_dir = os.getenv(
            "OPENCODE_MCP_TOOL_PATH",
            "/home/alex/Development/Sandbox/opencode-mcp-tool"
        )

        log_file = self.logs_dir / "global-mcp-tool.log"
        pid_file = self.memory_root / "global-mcp-tool.pid"

        # Build command for multi-server mode
        cmd = f"""cd {mcp_tool_dir} && \\
nohup npm run dev:http -- \\
  --bearer-token {bearer_token} \\
  --servers-config {servers_config_path} \\
  --port {port} \\
  >> {log_file} 2>&1 & \\
echo $! > {pid_file}"""

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                executable="/bin/bash",
                timeout=30,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return 0, port, f"Failed to start global MCP tool: {result.stderr}"

            # Read PID from file
            time.sleep(2)  # Give npm time to start
            if pid_file.exists():
                with open(pid_file, "r") as f:
                    pid = int(f.read().strip())
                return pid, port, None
            else:
                return 0, port, "PID file not created"

        except subprocess.TimeoutExpired:
            # Check if PID file was created
            time.sleep(2)
            if pid_file.exists():
                with open(pid_file, "r") as f:
                    pid = int(f.read().strip())
                if self.is_process_running(pid):
                    return pid, port, None
                else:
                    return 0, port, "Process started but died immediately"
            return 0, port, "Global MCP tool start command timed out"
        except Exception as e:
            return 0, port, f"Error starting global MCP tool: {str(e)}"

    def check_global_mcp_tool_health(
        self, port: int, bearer_token: str, timeout: int = 60
    ) -> Tuple[bool, str]:
        """
        Check if global MCP tool server is healthy

        Args:
            port: MCP tool port
            bearer_token: Bearer token
            timeout: Timeout in seconds

        Returns:
            Tuple of (is_healthy, message)
        """
        url = f"http://127.0.0.1:{port}/health"
        headers = {"Authorization": f"Bearer {bearer_token}"}

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(url, headers=headers, timeout=5)
                if response.status_code == 200:
                    return True, "Global MCP tool is healthy"
            except requests.exceptions.RequestException:
                pass

            time.sleep(2)

        return False, f"Global MCP tool health check failed after {timeout}s"
```

### Configuration Manager (NEW: config_manager.py)

Create new module for managing `opencode-mcp-tool-servers.json`:

```python
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
        config["servers"].append({
            "id": project_name,
            "title": title or project_name.replace("-", " ").title(),
            "description": description,
            "url": f"http://127.0.0.1:{port}",
            "password": password,
            "status": "active",
            "added_at": datetime.utcnow().isoformat(),
        })

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
            config["default_server"] = config["servers"][0]["id"] if config["servers"] else None

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
```

### Manager Orchestrator Changes (manager.py)

**Add ConfigManager:**
```python
from app.mcp.opencode.config_manager import ConfigManager

class OpenCodeManager:
    def __init__(self, memory_root: str = None, logger=None):
        self.memory_root = memory_root or os.path.expanduser("~/.memory")
        self.logger = logger
        self.env_manager = EnvManager(self.memory_root)
        self.state_manager = StateManager(self.memory_root)
        self.ssh_manager = SSHManager(self.memory_root)
        self.process_manager = ProcessManager(self.memory_root)
        self.config_manager = ConfigManager(self.memory_root)  # ← NEW
```

**Modified: start_project() - Bootstrap Flow**

Key changes in bootstrap flow:
1. Start OpenCode server (unchanged)
2. Add server to global configuration
3. Start global MCP tool (if not running)
4. Reload global MCP tool configuration (if already running)
5. No per-project MCP tool startup

```python
async def _bootstrap_project(
    self, project_name: str, git_url: str, user_ssh_key: Optional[str] = None
) -> Dict[str, Any]:
    """Bootstrap a new project from scratch"""
    self._log(f"Bootstrapping project: {project_name}")

    try:
        # Steps 1-7: Same as before (env, config, SSH, clone, state)
        # ... (unchanged) ...

        # Step 8: Start OpenCode server
        self._log(f"Starting OpenCode server for {project_name}")
        opencode_pid, opencode_port, opencode_error = (
            self.process_manager.start_opencode(config, repo_dir)
        )

        if opencode_error:
            self.state_manager.update_process_status(
                project_name, "opencode", status="failed", error=opencode_error
            )
            return {
                "status": "error",
                "error": "opencode_start_failed",
                "message": opencode_error,
            }

        self.state_manager.update_process_status(
            project_name,
            "opencode",
            pid=opencode_pid,
            port=opencode_port,
            status="starting",
        )

        # Step 9: Health check OpenCode
        self._log(f"Checking OpenCode health for {project_name}")
        healthy, health_message = self.process_manager.check_opencode_health(
            opencode_port, config.opencode_password
        )

        if not healthy:
            self.state_manager.update_process_status(
                project_name, "opencode", status="failed", error=health_message
            )
            return {
                "status": "error",
                "error": "opencode_unhealthy",
                "message": health_message,
            }

        self.state_manager.update_process_status(
            project_name, "opencode", status="running"
        )

        # Step 10: Add server to global configuration
        self._log(f"Adding {project_name} to global server configuration")
        self.config_manager.add_server(
            project_name=project_name,
            port=opencode_port,
            password=config.opencode_password,
        )

        # Step 11: Ensure global MCP tool is running
        await self._ensure_global_mcp_tool_running()

        # Step 12: Increment active project count
        self.state_manager.increment_active_projects()

        # Success!
        self._log(f"Project {project_name} started successfully")

        mcp_tool = self.state_manager.get_global_mcp_tool()
        result = {
            "status": "success",
            "project": project_name,
            "opencode_port": opencode_port,
            "opencode_pid": opencode_pid,
            "mcp_tool_port": mcp_tool.port if mcp_tool else None,
            "sandbox_dir": config.sandbox_dir,
            "message": f"Project {project_name} started successfully",
        }

        if warning_message:
            result["warning"] = warning_message

        return result

    except Exception as e:
        self._log(f"Error bootstrapping project: {str(e)}", "error")
        return {
            "status": "error",
            "error": "bootstrap_failed",
            "message": f"Unexpected error: {str(e)}",
        }
```

**New Helper: _ensure_global_mcp_tool_running()**

```python
async def _ensure_global_mcp_tool_running(self) -> bool:
    """
    Ensure global MCP tool is running, start if needed

    Returns:
        True if running, False if failed to start
    """
    mcp_tool = self.state_manager.get_global_mcp_tool()

    # Check if already running
    if mcp_tool and self.process_manager.is_process_running(mcp_tool.pid):
        self._log("Global MCP tool already running, reloading configuration")
        # Configuration will be automatically reloaded by file watcher
        return True

    # Start global MCP tool
    self._log("Starting global MCP tool")

    # Get bearer token from first project's .env
    # (All projects could share same token, or we generate a global one)
    # For now, use a fixed global token
    global_bearer_token = os.getenv(
        "GLOBAL_MCP_BEARER_TOKEN",
        "730d60768d2f6ac0bfd971b2cfb69eba0b3f3bf980745a13b98d3538b996ba6a"  # Fixed token
    )

    servers_config_path = self.config_manager.get_config_path()

    # Determine port (reuse if exists, otherwise default)
    port = mcp_tool.port if mcp_tool else 5100

    pid, port, error = self.process_manager.start_global_mcp_tool(
        bearer_token=global_bearer_token,
        servers_config_path=servers_config_path,
        port=port,
    )

    if error:
        self._log(f"Failed to start global MCP tool: {error}", "error")
        self.state_manager.update_global_mcp_tool_status(
            status=ProcessStatus.FAILED,
            error=error,
        )
        return False

    # Update state
    self.state_manager.update_global_mcp_tool_status(
        pid=pid,
        port=port,
        status=ProcessStatus.STARTING,
        started_at=datetime.utcnow().isoformat(),
    )

    # Health check
    self._log("Checking global MCP tool health")
    healthy, health_message = self.process_manager.check_global_mcp_tool_health(
        port, global_bearer_token
    )

    if not healthy:
        self._log(f"Global MCP tool unhealthy: {health_message}", "error")
        self.state_manager.update_global_mcp_tool_status(
            status=ProcessStatus.FAILED,
            error=health_message,
        )
        return False

    # Success
    self.state_manager.update_global_mcp_tool_status(
        status=ProcessStatus.RUNNING,
        last_health_check=datetime.utcnow().isoformat(),
    )

    self._log(f"Global MCP tool started successfully on port {port}")
    return True
```

**Modified: stop_project()**

Changes:
1. Stop OpenCode server
2. Update server status to "inactive" in configuration
3. Decrement active project count
4. Stop global MCP tool if no active projects

```python
async def stop_project(self, project_name: str) -> Dict[str, Any]:
    """Stop a project"""
    project = self.state_manager.get_project(project_name)
    if not project:
        return {"status": "not_found", "message": f"Project {project_name} not found"}

    self._log(f"Stopping project: {project_name}")

    # Stop OpenCode
    if project.opencode.pid:
        success, error = self.process_manager.stop_process(
            project.opencode.pid, "OpenCode"
        )
        if success:
            self.state_manager.update_process_status(
                project_name, "opencode", status="stopped"
            )

    # Update server status in configuration
    self.config_manager.update_server_status(project_name, "inactive")

    # Decrement active project count
    self.state_manager.decrement_active_projects()

    # Check if we should stop global MCP tool
    mcp_tool = self.state_manager.get_global_mcp_tool()
    if mcp_tool and mcp_tool.active_project_count == 0:
        self._log("No active projects, stopping global MCP tool")
        await self._stop_global_mcp_tool()

    return {"status": "success", "project": project_name, "message": "Project stopped"}
```

**New Helper: _stop_global_mcp_tool()**

```python
async def _stop_global_mcp_tool(self):
    """Stop global MCP tool"""
    mcp_tool = self.state_manager.get_global_mcp_tool()
    if not mcp_tool or not mcp_tool.pid:
        return

    self._log(f"Stopping global MCP tool (PID {mcp_tool.pid})")
    success, error = self.process_manager.stop_process(
        mcp_tool.pid, "Global MCP tool"
    )

    if success:
        self.state_manager.update_global_mcp_tool_status(
            status=ProcessStatus.STOPPED,
            pid=None,
        )
        self._log("Global MCP tool stopped")
    else:
        self._log(f"Failed to stop global MCP tool: {error}", "error")
```

**Modified: restart_project()**

Changes:
1. Stop OpenCode
2. Update configuration status to "inactive"
3. Start OpenCode
4. Update configuration status to "active"
5. Ensure global MCP tool is running (no restart needed, config auto-reloads)

```python
async def restart_project(self, project_name: str) -> Dict[str, Any]:
    """Restart a project"""
    self._log(f"Restarting project: {project_name}")

    # Get existing project state to reuse ports
    project = self.state_manager.get_project(project_name)
    if not project:
        return {"status": "error", "message": f"Project {project_name} not found"}

    # Stop OpenCode (but don't stop global MCP tool)
    if project.opencode.pid:
        success, error = self.process_manager.stop_process(
            project.opencode.pid, "OpenCode"
        )
        if success:
            self.state_manager.update_process_status(
                project_name, "opencode", status="stopped"
            )

    # Temporarily mark as inactive
    self.config_manager.update_server_status(project_name, "inactive")

    # Get configuration
    try:
        config = self.env_manager.load_project_config(project_name)
    except Exception as e:
        return {"status": "error", "message": f"Failed to load config: {str(e)}"}

    # IMPORTANT: Reuse existing port
    if project.opencode.port:
        config.opencode_port = project.opencode.port
        self._log(f"Reusing OpenCode port: {project.opencode.port}")

    repo_dir = Path(config.sandbox_dir) / "repo"

    # Start OpenCode
    opencode_pid, opencode_port, opencode_error = (
        self.process_manager.start_opencode(config, repo_dir)
    )
    if opencode_error:
        return {"status": "error", "message": opencode_error}

    self.state_manager.update_process_status(
        project_name,
        "opencode",
        pid=opencode_pid,
        port=opencode_port,
        status="running",
    )

    # Update server configuration (mark as active, update password if changed)
    self.config_manager.add_server(
        project_name=project_name,
        port=opencode_port,
        password=config.opencode_password,
    )

    # Ensure global MCP tool is running (will reload config automatically)
    await self._ensure_global_mcp_tool_running()

    mcp_tool = self.state_manager.get_global_mcp_tool()

    return {
        "status": "success",
        "project": project_name,
        "message": "Project restarted",
        "opencode_port": opencode_port,
        "mcp_tool_port": mcp_tool.port if mcp_tool else None,
    }
```

**Modified: destroy_project()**

Changes:
1. Stop OpenCode
2. Remove from global configuration
3. Decrement active project count
4. Stop global MCP tool if no active projects
5. Delete sandbox and state

```python
async def destroy_project(self, project_name: str) -> Dict[str, Any]:
    """Destroy a project (stop + delete sandbox)"""
    self._log(f"Destroying project: {project_name}")

    # Stop first
    await self.stop_project(project_name)

    # Remove from global configuration
    self.config_manager.remove_server(project_name)

    # Get project state
    project = self.state_manager.get_project(project_name)
    if project:
        # Delete sandbox directory
        sandbox_dir = Path(project.sandbox_dir)
        if sandbox_dir.exists():
            import shutil
            shutil.rmtree(sandbox_dir)

        # Delete from state
        self.state_manager.delete_project(project_name)

    return {
        "status": "success",
        "project": project_name,
        "message": "Project destroyed",
    }
```

**Modified: get_status()**

Include global MCP tool status:

```python
async def get_status(self, project_name: str) -> Dict[str, Any]:
    """Get project status"""
    project = self.state_manager.get_project(project_name)
    if not project:
        return {
            "status": "not_found",
            "project": project_name,
            "message": f"Project {project_name} not found",
        }

    # Check process health
    opencode_running = self.process_manager.is_process_running(
        project.opencode.pid
    )

    # Update status
    if opencode_running:
        self.state_manager.update_process_status(
            project_name, "opencode", status="running"
        )
    else:
        self.state_manager.update_process_status(
            project_name, "opencode", status="stopped"
        )

    self.state_manager.update_health_check(project_name)

    # Reload project state
    project = self.state_manager.get_project(project_name)

    # Get global MCP tool status
    mcp_tool = self.state_manager.get_global_mcp_tool()
    mcp_tool_running = self.process_manager.is_process_running(
        mcp_tool.pid if mcp_tool else None
    )

    return {
        "status": "ok",
        "project": project_name,
        "opencode": {
            "pid": project.opencode.pid,
            "port": project.opencode.port,
            "status": project.opencode.status,
            "running": opencode_running,
        },
        "global_mcp_tool": {
            "pid": mcp_tool.pid if mcp_tool else None,
            "port": mcp_tool.port if mcp_tool else None,
            "status": mcp_tool.status.value if mcp_tool else "not_started",
            "running": mcp_tool_running,
            "active_projects": mcp_tool.active_project_count if mcp_tool else 0,
        },
        "sandbox_dir": project.sandbox_dir,
        "git_url": project.git_url,
        "created_at": project.created_at,
        "last_health_check": project.last_health_check,
    }
```

**Modified: list_projects()**

Include global MCP tool information:

```python
async def list_projects(self) -> Dict[str, Any]:
    """List all projects"""
    projects = self.state_manager.get_all_projects()

    result = {"status": "success", "projects": []}

    for name, project in projects.items():
        opencode_running = self.process_manager.is_process_running(
            project.opencode.pid
        )

        result["projects"].append(
            {
                "name": name,
                "opencode_running": opencode_running,
                "opencode_port": project.opencode.port,
                "sandbox_dir": project.sandbox_dir,
            }
        )

    # Add global MCP tool info
    mcp_tool = self.state_manager.get_global_mcp_tool()
    if mcp_tool:
        result["global_mcp_tool"] = {
            "pid": mcp_tool.pid,
            "port": mcp_tool.port,
            "status": mcp_tool.status.value,
            "running": self.process_manager.is_process_running(mcp_tool.pid),
            "active_projects": mcp_tool.active_project_count,
        }

    return result
```

---

## 6. MCP Tools Interface Changes

### Existing Tools (Modified)

**opencode_start** - No interface change, internal behavior changed
**opencode_status** - Returns global MCP tool status
**opencode_stop** - Stops OpenCode, may stop global tool if last project
**opencode_restart** - Restarts OpenCode, reloads global tool config
**opencode_destroy** - Destroys project, removes from config
**opencode_list** - Includes global MCP tool info

### New Tools

**opencode_mcp_status** - Get global MCP tool status

```json
{
  "name": "opencode_mcp_status",
  "description": "Get status of the global opencode-mcp-tool instance serving all projects",
  "inputSchema": {
    "type": "object",
    "properties": {},
    "required": []
  }
}
```

Implementation:
```python
async def opencode_mcp_status(self) -> Dict[str, Any]:
    """Get global MCP tool status"""
    mcp_tool = self.state_manager.get_global_mcp_tool()

    if not mcp_tool:
        return {
            "status": "not_started",
            "message": "Global MCP tool has never been started"
        }

    running = self.process_manager.is_process_running(mcp_tool.pid)

    return {
        "status": "running" if running else "stopped",
        "pid": mcp_tool.pid,
        "port": mcp_tool.port,
        "active_projects": mcp_tool.active_project_count,
        "started_at": mcp_tool.started_at,
        "last_health_check": mcp_tool.last_health_check,
        "error": mcp_tool.error,
    }
```

**opencode_mcp_restart** - Manually restart global MCP tool

```json
{
  "name": "opencode_mcp_restart",
  "description": "Manually restart the global opencode-mcp-tool instance (useful after updating opencode-mcp-tool repository)",
  "inputSchema": {
    "type": "object",
    "properties": {},
    "required": []
  }
}
```

Implementation:
```python
async def opencode_mcp_restart(self) -> Dict[str, Any]:
    """Manually restart global MCP tool"""
    mcp_tool = self.state_manager.get_global_mcp_tool()

    if mcp_tool and mcp_tool.active_project_count == 0:
        return {
            "status": "error",
            "message": "No active projects - MCP tool will not be restarted"
        }

    # Stop if running
    await self._stop_global_mcp_tool()

    # Start again
    success = await self._ensure_global_mcp_tool_running()

    if success:
        mcp_tool = self.state_manager.get_global_mcp_tool()
        return {
            "status": "success",
            "message": "Global MCP tool restarted",
            "pid": mcp_tool.pid,
            "port": mcp_tool.port,
        }
    else:
        return {
            "status": "error",
            "message": "Failed to restart global MCP tool"
        }
```

---

## 7. Migration Strategy

### For Existing Deployments

**Step 1: Stop all running projects**
```bash
# Via MCP tools or manually
opencode_stop blog-api
opencode_stop chatmcp
# etc.
```

**Step 2: Backup existing state**
```bash
cp ~/.memory/opencode-state.json ~/.memory/opencode-state.json.backup
```

**Step 3: Deploy new code**
```bash
git pull
# Code will automatically migrate state on first run
```

**Step 4: State migration logic (in StateManager)**

```python
def _migrate_state_to_n_to_1(self):
    """Migrate old state format to N:1 architecture"""
    state = self._read_state()

    # Check if already migrated
    if "global_mcp_tool" in state:
        return  # Already migrated

    # Create global MCP tool entry (stopped initially)
    state["global_mcp_tool"] = {
        "pid": None,
        "port": None,
        "status": "stopped",
        "error": None,
        "started_at": None,
        "last_health_check": None,
        "active_project_count": 0,
    }

    # Remove mcp_tool from each project
    for project_name, project_data in state.get("projects", {}).items():
        if "mcp_tool" in project_data:
            del project_data["mcp_tool"]

    self._write_state(state)
    print("Migrated state to N:1 architecture")
```

**Step 5: Restart projects**
```bash
opencode_start blog-api ...
opencode_start chatmcp ...
```

---

## 8. Environment Variables

### New Environment Variable

**OPENCODE_MCP_TOOL_PATH** - Path to opencode-mcp-tool repository
- Default: `/home/alex/Development/Sandbox/opencode-mcp-tool`
- Used by ProcessManager to find npm executable

**GLOBAL_MCP_BEARER_TOKEN** - Bearer token for global MCP tool
- Default: Fixed token (for now)
- Future: Could be generated and stored in state

### Project .env Files (No Changes)

Project `.env` files remain unchanged:
```bash
GIT_URL=git@github.com:user/repo.git
SSH_KEY_PATH=/home/alex/.memory/opencode-keys/project-deploy
OPENCODE_SERVER_PASSWORD=password123
MCP_TOOL_BEARER_TOKEN=token456  # ← Still needed for server config
OPENCODE_BIN=/home/alex/.bun/bin/opencode
MCP_TOOL_DIR=/home/alex/Development/Sandbox/opencode-mcp-tool  # ← Not used anymore
```

Note: `MCP_TOOL_BEARER_TOKEN` in project `.env` is still needed because it gets written to the global servers configuration file.

---

## 9. Summary of Changes

### Files to Create
- `app/mcp/opencode/config_manager.py` - New module for server configuration management
- `~/.memory/opencode-mcp-tool-servers.json` - Global server list (created at runtime)

### Files to Modify
- `app/mcp/opencode/models.py` - Add GlobalMCPToolInfo, remove mcp_tool from ProjectState
- `app/mcp/opencode/state_manager.py` - Add global MCP tool state management methods
- `app/mcp/opencode/process_manager.py` - Add start_global_mcp_tool(), check_global_mcp_tool_health()
- `app/mcp/opencode/manager.py` - Refactor all methods to use global MCP tool
- `app/mcp/core/tools.py` - Add opencode_mcp_status, opencode_mcp_restart tools

### Files Unchanged
- `app/mcp/opencode/env_manager.py` - No changes needed
- `app/mcp/opencode/ssh_manager.py` - No changes needed
- Project `.env` files - Still contain same fields

### Breaking Changes
- Existing state format incompatible (migration needed)
- Old per-project MCP tool instances must be manually stopped before upgrade
- opencode-mcp-tool repository needs multi-server support implementation

---

## 10. Implementation Checklist

- [ ] 1. Create config_manager.py
- [ ] 2. Modify models.py (add GlobalMCPToolInfo, update ProjectState)
- [ ] 3. Modify state_manager.py (add global MCP tool methods, migration logic)
- [ ] 4. Modify process_manager.py (add global MCP tool process management)
- [ ] 5. Modify manager.py (refactor all lifecycle methods)
- [ ] 6. Modify tools.py (add new tools, update existing ones)
- [ ] 7. Test bootstrap flow with new project
- [ ] 8. Test stop/start/restart with multiple projects
- [ ] 9. Test global MCP tool lifecycle (start with first, stop with last)
- [ ] 10. Implement opencode-mcp-tool multi-server support (separate repository)
- [ ] 11. Document the architecture and migration guide
- [ ] 12. Create example configuration files

---

## 11. Future Enhancements

### Phase 2: Enhanced Features
- **Project switching UI** in opencode-mcp-tool
- **Health monitoring** for all servers
- **Auto-restart** on server crashes
- **Load balancing** across multiple mcp-tool instances (for high load)

### Phase 3: Security Improvements
- **Encrypted password storage** in configuration file
- **Token rotation** for bearer tokens
- **Role-based access control** per project

### Phase 4: Observability
- **Centralized logging** for all servers
- **Metrics collection** (CPU, memory per project)
- **Dashboard** showing all project statuses
