# OpenCode Manager N:1 Architecture - Executive Summary

## Problem Statement

Current architecture runs **one opencode-mcp-tool instance per project**, which is:
- Resource inefficient (multiple Node.js processes)
- Hard to manage (multiple ports to track)
- Difficult for clients (must connect to different ports per project)

## Proposed Solution

**N:1 Architecture**: Many OpenCode servers → One global opencode-mcp-tool instance

```
Before (1:1):                    After (N:1):
Project A → OC:4100 → MCP:5100   Project A → OC:4100 ──┐
Project B → OC:4101 → MCP:5101   Project B → OC:4101 ──┼→ MCP:5100 (global)
Project C → OC:4102 → MCP:5102   Project C → OC:4102 ──┘
```

## Key Design Decisions

### 1. State Model
- Add `global_mcp_tool` at root level (separate from projects)
- Remove `mcp_tool` from individual project states
- Track `active_project_count` to manage global tool lifecycle

### 2. Server Configuration File
- **Location**: `~/.memory/opencode-mcp-tool-servers.json`
- **Purpose**: Lists all OpenCode servers with URLs and passwords
- **Security**: Stored with 0600 permissions (contains sensitive passwords)
- **Format**:
  ```json
  {
    "version": "1.0",
    "servers": [
      {
        "id": "blog-api",
        "title": "Blog API",
        "url": "http://127.0.0.1:4100",
        "password": "***",
        "status": "active"
      }
    ],
    "default_server": "blog-api"
  }
  ```

### 3. Global MCP Tool Lifecycle
- **Start**: When first project starts (count: 0 → 1)
- **Keep Running**: When projects stop/restart (count > 0)
- **Stop**: When last project stops (count: 1 → 0)
- **Port**: Fixed at 5100 (reused across restarts)

### 4. Configuration Management
- **Add server**: When project starts → update config → reload mcp-tool
- **Update status**: When project stops → mark inactive
- **Remove server**: When project destroyed → update config
- **Hot-reload**: opencode-mcp-tool watches config file for changes

### 5. Project Selection
MCP tools include optional `server` parameter:
```json
{
  "name": "run_terminal_command",
  "arguments": {
    "command": "npm install",
    "server": "blog-api"  // ← Which OpenCode server to use
  }
}
```

If omitted, uses `default_server` from configuration.

## Implementation Changes

### New Files
- `app/mcp/opencode/config_manager.py` - Manages server configuration file

### Modified Files
- `models.py` - Add GlobalMCPToolInfo, remove mcp_tool from ProjectState
- `state_manager.py` - Add global tool state management + migration logic
- `process_manager.py` - Add start_global_mcp_tool(), check_global_mcp_tool_health()
- `manager.py` - Refactor bootstrap/start/stop/restart/destroy to use global tool
- `tools.py` - Add opencode_mcp_status, opencode_mcp_restart tools

### Manager Behavior Changes

**start_project():**
1. Start OpenCode server
2. Add server to global configuration file
3. Ensure global MCP tool is running (start if needed)
4. Increment active_project_count

**stop_project():**
1. Stop OpenCode server
2. Update server status to "inactive" in config
3. Decrement active_project_count
4. Stop global MCP tool if count reaches 0

**restart_project():**
1. Stop OpenCode server
2. Mark inactive in config
3. Start OpenCode server
4. Mark active in config (config auto-reloads in mcp-tool)

**destroy_project():**
1. Stop OpenCode server
2. Remove from global configuration
3. Decrement active_project_count
4. Stop global MCP tool if count reaches 0
5. Delete sandbox and state

## Dependencies on opencode-mcp-tool

This refactoring requires **opencode-mcp-tool repository** to support:

### Required Changes in opencode-mcp-tool
1. **Multi-server CLI mode**:
   ```bash
   npm run dev:http -- \
     --bearer-token <token> \
     --servers-config ~/.memory/opencode-mcp-tool-servers.json \
     --port 5100
   ```

2. **Configuration file watching**:
   - Watch `servers-config` file for changes
   - Hot-reload server list when file changes
   - Log: "Configuration reloaded: X servers available"

3. **Server selection in MCP tools**:
   - Accept optional `server` parameter in tool arguments
   - Route requests to specified OpenCode server
   - Use `default_server` if parameter omitted

### Implementation Notes for opencode-mcp-tool
- Use `chokidar` to watch configuration file
- Parse JSON configuration on startup and reload
- Maintain map of server_id → {url, password}
- Add `server` parameter to all existing MCP tool schemas
- Route tool calls to appropriate OpenCode instance

## Migration Path

### For Existing Deployments

1. **Backup state**:
   ```bash
   cp ~/.memory/opencode-state.json ~/.memory/opencode-state.json.backup
   ```

2. **Stop all projects** (manually or via MCP):
   ```bash
   opencode_stop blog-api
   opencode_stop chatmcp
   ```

3. **Deploy new code**:
   ```bash
   git pull origin wip_opencode_manager
   # State migration runs automatically on first start
   ```

4. **Restart projects**:
   ```bash
   opencode_start blog-api ...
   opencode_start chatmcp ...
   ```

### Automatic State Migration
On first run, StateManager detects old format and:
- Adds `global_mcp_tool` section (initially stopped)
- Removes `mcp_tool` from each project
- Sets `active_project_count` to 0
- Saves migrated state

## Environment Variables

### New Variables
- `OPENCODE_MCP_TOOL_PATH` - Path to opencode-mcp-tool repo
  - Default: `/home/alex/Development/Sandbox/opencode-mcp-tool`
- `GLOBAL_MCP_BEARER_TOKEN` - Bearer token for global MCP tool
  - Default: Fixed token (for now)

### Unchanged Variables (in project .env)
- `GIT_URL`, `SSH_KEY_PATH`, `OPENCODE_SERVER_PASSWORD` - Same as before
- `MCP_TOOL_BEARER_TOKEN` - Still used (written to server config file)
- `MCP_TOOL_DIR` - Deprecated (use OPENCODE_MCP_TOOL_PATH instead)

## New MCP Tools

### opencode_mcp_status
Get status of global MCP tool instance:
```json
{
  "status": "running",
  "pid": 67890,
  "port": 5100,
  "active_projects": 3,
  "started_at": "2026-02-01T10:00:00"
}
```

### opencode_mcp_restart
Manually restart global MCP tool (useful after updating repo):
```json
{
  "status": "success",
  "message": "Global MCP tool restarted",
  "pid": 67891,
  "port": 5100
}
```

## Benefits

1. **Single MCP endpoint** - Clients connect to one port (5100)
2. **Runtime project switching** - Change projects without reconnecting
3. **Resource efficiency** - One Node.js process instead of N processes
4. **Cleaner state management** - Global tool separate from projects
5. **Better UX** - Less port management, easier to understand

## Risks and Mitigation

### Risk 1: opencode-mcp-tool dependency
- **Risk**: Requires changes in separate repository
- **Mitigation**: Detailed specification provided, user will implement

### Risk 2: Migration complexity
- **Risk**: Existing deployments need migration
- **Mitigation**: Automatic migration logic + backup instructions

### Risk 3: Configuration file security
- **Risk**: Passwords stored in JSON file
- **Mitigation**: File permissions (0600) + future encryption option

### Risk 4: Single point of failure
- **Risk**: If global MCP tool crashes, all projects affected
- **Mitigation**: Health checks + auto-restart logic (future enhancement)

## Next Steps

1. **Review** this architecture design
2. **Confirm** approach with user
3. **Implement** changes in MoJoAssistant (this repo)
4. **Implement** multi-server support in opencode-mcp-tool (separate repo)
5. **Test** end-to-end with multiple projects
6. **Document** for users

## Questions for User

1. Is the global bearer token approach acceptable, or should each project have its own token?
2. Should we support backward compatibility mode (1:1) for transition period?
3. Do you want auto-restart functionality for global MCP tool if it crashes?
4. Should we encrypt passwords in the configuration file, or is 0600 permissions sufficient?

---

**Full details**: See `ARCHITECTURE_N_TO_1.md` for complete technical specification.
