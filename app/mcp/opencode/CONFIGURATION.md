# OpenCode Manager Configuration Guide

## Global MCP Tool Port Configuration

The global opencode-mcp-tool instance uses a **fixed port** that should be configured once and reused consistently.

### Port Selection Logic

1. **First Priority: Existing State**
   - If global MCP tool has been started before, reuses the same port from state
   - Ensures consistency across restarts

2. **Second Priority: Environment Variable**
   - Set `GLOBAL_MCP_TOOL_PORT` to specify the port
   - Example: `export GLOBAL_MCP_TOOL_PORT=3005`

3. **Third Priority: Default**
   - Default port: `3005`
   - Changed from previous default (5100) to support cloudflared setups

### Configuration Methods

#### Method 1: Environment Variable (Recommended)

Add to your shell profile (`~/.bashrc`, `~/.zshrc`, or `~/.profile`):

```bash
export GLOBAL_MCP_TOOL_PORT=3005
```

Or set in your MCP server startup:

```bash
GLOBAL_MCP_TOOL_PORT=3005 python3 unified_mcp_server.py --mode http --port 8000
```

#### Method 2: Default Behavior

If you don't set `GLOBAL_MCP_TOOL_PORT`, it defaults to `3005`.

This works out-of-the-box for cloudflared setups like:

```yaml
tunnel: your-tunnel-id
credentials-file: /path/to/credentials.json

ingress:
  - hostname: opencode.eclipsogate.org
    service: http://localhost:3005  # ← Matches default port
  - service: http_status:404
```

### Port Persistence

Once the global MCP tool starts, the port is saved in:
```
~/.memory/opencode-state.json
```

Example state:
```json
{
  "global_mcp_tool": {
    "pid": 123456,
    "port": 3005,  // ← Persisted port
    "status": "running",
    "active_project_count": 2
  }
}
```

**Important:** The port will remain `3005` across all restarts, even if you change the environment variable later. This ensures stability.

### Changing the Port

To change the port after it's been set:

1. **Stop all projects:**
   ```
   opencode_stop <project_name>
   ```

2. **Stop global MCP tool:**
   ```
   opencode_mcp_restart
   ```

3. **Edit state file** (or delete it to reset):
   ```bash
   # Option A: Edit manually
   nano ~/.memory/opencode-state.json
   # Change "port": 3005 to your new port

   # Option B: Reset everything (⚠️ stops all projects)
   rm ~/.memory/opencode-state.json
   ```

4. **Set new environment variable:**
   ```bash
   export GLOBAL_MCP_TOOL_PORT=4000  # Your new port
   ```

5. **Restart projects:**
   ```
   opencode_start <project_name> ...
   ```

### Verifying the Port

Check the current port with:

```
opencode_mcp_status
```

Output:
```json
{
  "status": "running",
  "pid": 123456,
  "port": 3005,  // ← Current port
  "active_projects": 2
}
```

Or check the state file:
```bash
cat ~/.memory/opencode-state.json | jq '.global_mcp_tool.port'
```

### Common Scenarios

#### Scenario 1: Fresh Install with Cloudflared

You have cloudflared configured for port 3005:

```bash
# No configuration needed! Default is 3005
python3 unified_mcp_server.py --mode http --port 8000

# Start your project
opencode_start my-project git@github.com:user/repo.git
# Global MCP tool will start on port 3005 automatically
```

#### Scenario 2: Custom Port for Development

You want port 5000 for development:

```bash
# Set environment variable
export GLOBAL_MCP_TOOL_PORT=5000

# Start MCP server
python3 unified_mcp_server.py --mode http --port 8000

# Start project
opencode_start my-project git@github.com:user/repo.git
# Global MCP tool will use port 5000
```

#### Scenario 3: Multiple Environments

Development vs Production with different ports:

```bash
# Development (.bashrc or .zshrc)
export GLOBAL_MCP_TOOL_PORT=5000

# Production (systemd service or docker-compose)
Environment="GLOBAL_MCP_TOOL_PORT=3005"
```

### Troubleshooting

#### Problem: Port Already in Use

**Symptom:** Global MCP tool fails to start with "address already in use"

**Solution:**
```bash
# Check what's using the port
lsof -i :3005

# Kill the process or choose a different port
export GLOBAL_MCP_TOOL_PORT=3006
```

#### Problem: Port Keeps Changing

**Symptom:** Each restart uses a different port (5100, 5101, 5102...)

**Cause:** This was a bug in versions before the N:1 refactoring

**Solution:**
- Update to latest code (includes port persistence)
- Verify state is being saved correctly
- Check logs for errors during startup

#### Problem: Cloudflared Can't Connect

**Symptom:** cloudflared shows "connection refused" or "target error"

**Solution:**
```bash
# Verify MCP tool is running on expected port
opencode_mcp_status

# Check if port matches cloudflared config
cat ~/.cloudflared/config.yml | grep service

# If ports don't match, restart with correct port
export GLOBAL_MCP_TOOL_PORT=3005
opencode_mcp_restart
```

### Best Practices

1. **Set Once, Use Everywhere**
   - Configure `GLOBAL_MCP_TOOL_PORT` in your shell profile
   - Don't change it unless necessary

2. **Match Infrastructure**
   - If using cloudflared/nginx/reverse proxy, set port to match
   - Document the port in your infrastructure config

3. **Avoid Dynamic Ports**
   - Don't rely on auto-assigned ports (5100+)
   - Always use a fixed port for production

4. **Version Control**
   - Add `GLOBAL_MCP_TOOL_PORT` to your project's `.env.example`
   - Document in README for team members

### Environment Variables Reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `GLOBAL_MCP_TOOL_PORT` | `3005` | Port for global MCP tool HTTP server |
| `GLOBAL_MCP_BEARER_TOKEN` | (auto-generated) | Bearer token for MCP authentication |
| `OPENCODE_MCP_TOOL_PATH` | `/home/alex/Development/Sandbox/opencode-mcp-tool` | Path to opencode-mcp-tool repository |
| `ENVIRONMENT` | `production` | Mode: `development` or `production` |

### Related Files

- **State File:** `~/.memory/opencode-state.json` - Persisted port and PIDs
- **Server Config:** `~/.memory/opencode-mcp-tool-servers.json` - OpenCode server list
- **Logs:** `~/.memory/opencode-logs/global-mcp-tool.log` - Startup/error logs

### Design Rationale

**Why a Fixed Port?**

1. **Cloudflared/Reverse Proxy:** Infrastructure expects consistent port
2. **Client Configuration:** MCP clients connect to fixed endpoint
3. **Firewall Rules:** Security rules based on known ports
4. **Monitoring:** Health checks need stable targets

**Why 3005 as Default?**

1. **Out of common ranges:** Avoids conflicts with common services
   - 3000: React/Node dev servers
   - 5000: Flask default
   - 8000: Django/FastAPI default
2. **Easy to remember:** 3000 + 5 = 3005 (MCP-tool)
3. **User's cloudflared setup:** Matches existing infrastructure

**Why Not Auto-Assign?**

Previous behavior (5100, 5101, 5102...) was problematic:
- Unpredictable endpoint
- Configuration drift
- Hard to debug
- Doesn't work with reverse proxies
