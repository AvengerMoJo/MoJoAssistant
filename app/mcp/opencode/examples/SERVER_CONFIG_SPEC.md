# opencode-mcp-tool Server Configuration Specification

## File Location
`~/.memory/opencode-mcp-tool-servers.json`

## Purpose
This configuration file is managed by the OpenCode Manager and read by opencode-mcp-tool to:
- Know which OpenCode servers are available
- Route MCP tool requests to the correct server
- Authenticate with each OpenCode server
- Determine the default server when none is specified

## File Format

### Top-Level Structure
```json
{
  "version": "1.0",
  "servers": [ /* array of server objects */ ],
  "default_server": "server-id"
}
```

### Fields

#### `version` (string, required)
- Configuration file format version
- Currently: `"1.0"`
- Used for future compatibility if schema changes

#### `servers` (array, required)
- Array of server configuration objects
- Can be empty if no projects are configured
- Each server represents one OpenCode instance

#### `default_server` (string, nullable)
- The `id` of the server to use when no `server` parameter is provided in MCP tool calls
- Should match one of the server IDs in the `servers` array
- Can be `null` if no servers exist
- OpenCode Manager sets this to the first project created

### Server Object Structure

Each server object in the `servers` array has these fields:

```json
{
  "id": "project-name",
  "title": "Display Name",
  "description": "Optional description",
  "url": "http://127.0.0.1:PORT",
  "password": "opencode-server-password",
  "status": "active|inactive",
  "added_at": "ISO-8601-timestamp"
}
```

#### `id` (string, required)
- Unique identifier for this server
- Matches the OpenCode project name
- Used in MCP tool calls to select which server to use
- Pattern: `^[a-zA-Z0-9_-]+$`
- Examples: `"blog-api"`, `"chatmcp"`, `"ml-training-pipeline"`

#### `title` (string, required)
- Human-readable display name for the project
- Used in UI/logs for easier identification
- Can contain spaces and special characters
- Examples: `"Blog API"`, `"ChatMCP Client"`, `"ML Training Pipeline"`

#### `description` (string, optional)
- Optional description of what this project does
- Helps users remember the purpose of each project
- Can be empty string `""`

#### `url` (string, required)
- Full URL to the OpenCode web server
- Format: `http://127.0.0.1:{PORT}`
- Port is assigned by OpenCode Manager (4100-4199 range)
- Examples: `"http://127.0.0.1:4100"`, `"http://127.0.0.1:4101"`

#### `password` (string, required)
- OpenCode server password for HTTP Basic Auth
- Used when making requests to OpenCode API
- **SECURITY**: This file contains sensitive passwords and MUST have 0600 permissions
- Examples: `"2400"`, `"a7f3e9d2c1b8a4f6e5d3c2b1a9f8e7d6"`

#### `status` (string, required)
- Current status of the OpenCode server
- Values:
  - `"active"` - OpenCode server is running
  - `"inactive"` - OpenCode server is stopped
- opencode-mcp-tool can filter to only show/route to active servers
- OpenCode Manager updates this when projects start/stop

#### `added_at` (string, required)
- ISO-8601 formatted timestamp of when this server was added
- Format: `YYYY-MM-DDTHH:MM:SSZ` (UTC timezone)
- Examples: `"2026-02-01T10:00:00Z"`, `"2025-12-20T16:45:00Z"`

## File Lifecycle

### Creation
- Created by OpenCode Manager when first project starts
- Initial permissions: `chmod 600` (owner read/write only)
- Location: `~/.memory/opencode-mcp-tool-servers.json`

### Updates
- **Add server**: When `opencode_start` creates new project
- **Update status to "active"**: When project starts or restarts
- **Update status to "inactive"**: When project stops
- **Update password**: When project restarts with new password
- **Remove server**: When `opencode_destroy` deletes project

### Deletion
- Never deleted automatically
- User can manually delete if resetting all projects

## Security Considerations

### File Permissions
```bash
# REQUIRED: Restrict access to owner only
chmod 600 ~/.memory/opencode-mcp-tool-servers.json

# Verify permissions
ls -la ~/.memory/opencode-mcp-tool-servers.json
# Should show: -rw------- (600)
```

### Password Storage
- Passwords are stored in **plain text** in this file
- File access is restricted by OS permissions (0600)
- Future enhancement: Encrypt passwords at rest

### Access Control
- Only the user account that runs OpenCode Manager should access this file
- opencode-mcp-tool process must run as the same user
- Do NOT commit this file to version control
- Do NOT share this file with others

## Usage by opencode-mcp-tool

### Startup
1. Read configuration file on startup
2. Parse JSON
3. Build internal routing table: `{server_id → {url, password}}`
4. Validate that `default_server` exists in `servers` array
5. Filter to only active servers (optional)

### File Watching (Hot-Reload)
```javascript
const chokidar = require('chokidar');

const watcher = chokidar.watch('~/.memory/opencode-mcp-tool-servers.json', {
  persistent: true,
  ignoreInitial: true
});

watcher.on('change', (path) => {
  console.log('Configuration changed, reloading...');
  reloadServerConfig();
});

function reloadServerConfig() {
  const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));

  // Rebuild routing table
  servers = {};
  config.servers.forEach(server => {
    servers[server.id] = {
      url: server.url,
      password: server.password,
      title: server.title,
      status: server.status
    };
  });

  defaultServer = config.default_server;

  console.log(`Reloaded: ${Object.keys(servers).length} servers available`);
  console.log(`Default server: ${defaultServer}`);
}
```

### Routing MCP Tool Calls

When opencode-mcp-tool receives an MCP tool call:

```javascript
async function handleToolCall(toolName, args) {
  // 1. Determine which server to use
  const serverId = args.server || defaultServer;

  // 2. Look up server configuration
  const serverConfig = servers[serverId];
  if (!serverConfig) {
    throw new Error(`Server '${serverId}' not found in configuration`);
  }

  // 3. Check if server is active
  if (serverConfig.status !== 'active') {
    throw new Error(`Server '${serverId}' is not active (status: ${serverConfig.status})`);
  }

  // 4. Make request to OpenCode server
  const response = await fetch(`${serverConfig.url}/api/mcp/${toolName}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Basic ${btoa('opencode:' + serverConfig.password)}`
    },
    body: JSON.stringify(args)
  });

  return await response.json();
}
```

### MCP Tool Schema Changes

All MCP tools should accept optional `server` parameter:

```json
{
  "name": "run_terminal_command",
  "description": "Run a terminal command in the specified OpenCode project",
  "inputSchema": {
    "type": "object",
    "properties": {
      "command": {
        "type": "string",
        "description": "The command to execute"
      },
      "server": {
        "type": "string",
        "description": "OpenCode server ID to use (defaults to default_server from config)",
        "pattern": "^[a-zA-Z0-9_-]+$"
      }
    },
    "required": ["command"]
  }
}
```

## Example Usage

### Scenario 1: Use Default Server
```json
{
  "name": "run_terminal_command",
  "arguments": {
    "command": "npm install"
  }
}
```
→ Routes to `personal-update-version-of-chatmcp-client` (default_server)

### Scenario 2: Specify Server
```json
{
  "name": "run_terminal_command",
  "arguments": {
    "command": "npm install",
    "server": "blog-api"
  }
}
```
→ Routes to `blog-api` server at `http://127.0.0.1:4101`

### Scenario 3: Server Not Found
```json
{
  "name": "run_terminal_command",
  "arguments": {
    "command": "npm install",
    "server": "nonexistent-project"
  }
}
```
→ Error: `Server 'nonexistent-project' not found in configuration`

### Scenario 4: Inactive Server
```json
{
  "name": "run_terminal_command",
  "arguments": {
    "command": "npm install",
    "server": "ml-training-pipeline"
  }
}
```
→ Error: `Server 'ml-training-pipeline' is not active (status: inactive)`

## CLI Usage

### Current CLI (Single Server)
```bash
npm run dev:http -- \
  --bearer-token 730d60768d2f6ac0bfd971b2cfb69eba0b3f3bf980745a13b98d3538b996ba6a \
  --opencode-url http://127.0.0.1:4100 \
  --opencode-password 2400 \
  --port 5100
```

### New CLI (Multi-Server Mode)
```bash
npm run dev:http -- \
  --bearer-token 730d60768d2f6ac0bfd971b2cfb69eba0b3f3bf980745a13b98d3538b996ba6a \
  --servers-config ~/.memory/opencode-mcp-tool-servers.json \
  --port 5100
```

**Arguments:**
- `--bearer-token` - Bearer token for MCP authentication (unchanged)
- `--servers-config` - Path to server configuration JSON file (NEW)
- `--port` - Port for MCP HTTP server (unchanged)

**Removed:**
- `--opencode-url` - Replaced by servers-config
- `--opencode-password` - Replaced by servers-config

## Error Handling

### File Not Found
```javascript
if (!fs.existsSync(configPath)) {
  console.error('ERROR: Server configuration file not found');
  console.error(`Expected location: ${configPath}`);
  console.error('Please ensure OpenCode Manager has created this file');
  process.exit(1);
}
```

### Invalid JSON
```javascript
try {
  const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
} catch (error) {
  console.error('ERROR: Invalid JSON in server configuration');
  console.error(`File: ${configPath}`);
  console.error(`Error: ${error.message}`);
  process.exit(1);
}
```

### No Servers
```javascript
if (!config.servers || config.servers.length === 0) {
  console.warn('WARNING: No servers configured');
  console.warn('Please create a project using OpenCode Manager');
}
```

### Invalid Default Server
```javascript
const serverIds = config.servers.map(s => s.id);
if (config.default_server && !serverIds.includes(config.default_server)) {
  console.error('ERROR: default_server references non-existent server');
  console.error(`default_server: ${config.default_server}`);
  console.error(`Available servers: ${serverIds.join(', ')}`);
  process.exit(1);
}
```

## Migration from Single-Server Mode

For backward compatibility during transition:

### Option 1: Support Both Modes
```bash
# Old mode (still works)
npm run dev:http -- \
  --bearer-token TOKEN \
  --opencode-url http://127.0.0.1:4100 \
  --opencode-password PASSWORD \
  --port 5100

# New mode (multi-server)
npm run dev:http -- \
  --bearer-token TOKEN \
  --servers-config ~/.memory/opencode-mcp-tool-servers.json \
  --port 5100
```

### Option 2: Auto-Generate Config
If old-style arguments provided, generate temporary config:
```javascript
if (args.opencodeUrl && args.opencodePassword) {
  // Legacy mode: create temporary single-server config
  const tempConfig = {
    version: "1.0",
    servers: [{
      id: "default",
      title: "OpenCode Server",
      url: args.opencodeUrl,
      password: args.opencodePassword,
      status: "active"
    }],
    default_server: "default"
  };
  useConfig(tempConfig);
}
```

## Testing

### Manual Testing
```bash
# 1. Create test configuration
cat > ~/.memory/opencode-mcp-tool-servers.json << 'EOF'
{
  "version": "1.0",
  "servers": [
    {
      "id": "test-project",
      "title": "Test Project",
      "description": "Testing multi-server support",
      "url": "http://127.0.0.1:4100",
      "password": "test-password",
      "status": "active",
      "added_at": "2026-02-01T10:00:00Z"
    }
  ],
  "default_server": "test-project"
}
EOF

# 2. Set permissions
chmod 600 ~/.memory/opencode-mcp-tool-servers.json

# 3. Start opencode-mcp-tool
npm run dev:http -- \
  --bearer-token test-token \
  --servers-config ~/.memory/opencode-mcp-tool-servers.json \
  --port 5100

# 4. Verify hot-reload (in another terminal)
# Modify the config file
echo '...' > ~/.memory/opencode-mcp-tool-servers.json

# Check logs for "Configuration reloaded" message
```

### Unit Testing
```javascript
describe('Server Configuration', () => {
  it('should load valid configuration', () => {
    const config = loadConfig('test-config.json');
    expect(config.servers).toHaveLength(3);
    expect(config.default_server).toBe('blog-api');
  });

  it('should handle missing file', () => {
    expect(() => loadConfig('nonexistent.json')).toThrow();
  });

  it('should validate server references', () => {
    const config = {
      servers: [{id: 'server1'}],
      default_server: 'nonexistent'
    };
    expect(() => validateConfig(config)).toThrow();
  });

  it('should reload on file change', (done) => {
    const watcher = watchConfig('test-config.json');
    watcher.on('reload', () => {
      expect(servers['new-server']).toBeDefined();
      done();
    });
    // Modify file...
  });
});
```

## Troubleshooting

### Issue: "Server not found"
- Check that server ID matches exactly (case-sensitive)
- Verify server exists in configuration file
- Check for typos in server ID

### Issue: "Server is not active"
- OpenCode server is stopped
- Use OpenCode Manager to start: `opencode_start <project_name>`
- Or manually update status in config (not recommended)

### Issue: "Authentication failed"
- Password in config may be incorrect
- OpenCode server may have been restarted with new password
- Restart the project using OpenCode Manager to sync password

### Issue: "Configuration not reloading"
- Check file watcher is enabled
- Verify file path is correct
- Restart opencode-mcp-tool
- Check file permissions (should be 600)

## Summary

This configuration file enables:
- **Multi-server support** - One opencode-mcp-tool serving many OpenCode instances
- **Runtime switching** - Select different projects without reconnecting
- **Hot-reload** - Add/remove servers without restarting
- **Default routing** - Implicit server selection for convenience
- **Security** - Centralized credential storage with OS-level protection

**Key Implementation Points:**
1. File watching with hot-reload
2. Server parameter in all MCP tools
3. Routing logic based on server ID
4. Graceful error handling
5. Backward compatibility (optional)
