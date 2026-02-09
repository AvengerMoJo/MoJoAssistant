# OpenCode Manager

Infrastructure manager for OpenCode coding agent instances.

## Overview

The OpenCode Manager provides MCP tools to bootstrap, manage, and monitor OpenCode server instances. Each project runs in an isolated sandbox with its own OpenCode web server and opencode-mcp-tool instance.

## Architecture (N:1 Design)

**Version: 1.1 Beta - Agent Management Pattern** (Updated Feb 2026)

> **Note**: This is the first implementation of MoJoAssistant's reusable Agent Manager architecture. The pattern established here (N:1 lifecycle management, configuration hot-reload, process monitoring) will be extended to manage other AI agents (Gemini CLI, custom tools, etc.).

```
Memory MCP (This Project)
├─ Manager Tools (via MCP)
│  ├─ opencode_start
│  ├─ opencode_status
│  ├─ opencode_stop
│  ├─ opencode_restart
│  ├─ opencode_destroy
│  ├─ opencode_list
│  ├─ opencode_mcp_status
│  └─ opencode_mcp_restart
│
└─ Spawns & Monitors
    ├─ Project A: OpenCode Web (port 4100) ──┐
    ├─ Project B: OpenCode Web (port 4101) ──┤
    ├─ Project C: OpenCode Web (port 4102) ──┼→ Global MCP Tool (port 3005)
    └─ Project N: OpenCode Web (port 41xx) ──┘    └─ MCP Client connects here
```

**Key Changes:**
- **One global MCP tool** serves all OpenCode servers
- **Resource efficient**: Single Node.js process instead of N processes
- **Simpler client config**: Always connect to port 3005
- **Auto-lifecycle**: Global tool starts with first project, stops with last
- **Hot-reload config**: Projects can be added/removed without restart

For detailed architecture documentation, see [ARCHITECTURE_N_TO_1.md](ARCHITECTURE_N_TO_1.md)

## Security Model

**Secrets are NEVER passed through MCP chat!**

All sensitive configuration (SSH keys, passwords, tokens) is stored in `.env` files within each project sandbox at `~/.memory/opencode-sandboxes/<project>/.env`.

### Security Improvements (v1.1 Beta)

✅ **Bearer Token Protection** (Feb 2026)
- Bearer tokens passed via environment variables (not CLI arguments)
- Tokens NOT visible in process listings (`ps aux`)
- Prevents credential leakage in logs and process monitors

✅ **File Permissions**
- All sensitive files created with 0600 permissions (owner read/write only)
- SSH keys, state files, and server configs properly secured

### Development Mode
- ✅ Auto-generates `.env` with random passwords/tokens
- ✅ Auto-generates SSH keys automatically
- ⚠️ Shows warnings to review configuration
- Use for: Testing, learning, prototyping

### Production Mode
- ✅ Creates minimal `.env` with SSH key path only
- ⚠️ Requires you to set passwords/tokens manually
- ✅ Auto-generates SSH keys automatically (low security risk)
- ❌ Does NOT auto-generate passwords/tokens (high security risk)
- Use for: Real projects, team collaboration

**Key Insight:** SSH keys are auto-generated in BOTH modes because:
- Private key stays local (never transmitted)
- Public key is meant to be shared
- User controls authorization by adding public key to GitHub
- Same security whether you generate it or the system does

## File Structure

```
~/.memory/
├── opencode-sandboxes/          # Project sandboxes
│   └── <project-name>/
│       ├── .env                 # Secrets (gitignored, 0600)
│       ├── .gitignore           # Auto-created
│       ├── repo/                # Git clone
│       └── opencode.pid         # Process ID
├── opencode-keys/               # Generated SSH keys
│   ├── <project>-deploy         # Private key (0600)
│   └── <project>-deploy.pub     # Public key
├── opencode-logs/               # Process logs
│   ├── <project>-opencode.log
│   └── global-mcp-tool.log      # ← Global MCP tool log (N:1)
├── opencode-state.json          # Persistent state (0600)
├── opencode-mcp-tool-servers.json  # ← Global server config (0600, N:1)
└── global-mcp-tool.pid          # ← Global MCP tool PID (N:1)
```

**Note**: Files marked with `(N:1)` are new in v1.1 beta N:1 architecture.

## MCP Tools

### `opencode_start`
Start or bootstrap a project.

**Parameters:**
- `project_name` (required): Alphanumeric project name
- `git_url` (required): SSH Git URL (e.g., `git@github.com:user/repo.git`)
- `user_ssh_key` (optional): Path to existing SSH key

**Workflow:**
1. Check if `.env` exists
   - Dev mode: Auto-generate with passwords/tokens
   - Prod mode: Create minimal .env, return "waiting_for_passwords"
2. Load and validate configuration
   - Checks for placeholder passwords
3. Auto-generate SSH key if missing (both modes)
4. Test Git repository access
   - If fails: Return public key for user to add
5. Clone repository
6. Start OpenCode web server
7. Health check OpenCode
8. Start opencode-mcp-tool
9. Health check MCP tool

**Returns:**
- `status`: `success`, `waiting_for_key`, `error`
- `opencode_port`, `mcp_tool_port`: Connection details
- `warning`: Dev mode warnings (if any)

### `opencode_status`
Check project status.

**Parameters:**
- `project_name` (required): Project name

**Returns:**
- Process PIDs, ports, running status
- Sandbox directory, Git URL
- Last health check timestamp

### `opencode_stop`
Stop project processes (keeps sandbox intact).

### `opencode_restart`
Restart both processes.

### `opencode_destroy`
⚠️ **DESTRUCTIVE**: Stop and delete sandbox.

### `opencode_list`
List all projects with status.

## Configuration (.env)

Example `.env` file (created in sandbox):

```bash
# Git repository
GIT_URL=git@github.com:user/repo.git

# SSH key (read/write access required)
SSH_KEY_PATH=/home/alex/.ssh/myproject-deploy

# OpenCode password
OPENCODE_SERVER_PASSWORD=your-secure-password

# MCP tool bearer token
MCP_TOOL_BEARER_TOKEN=your-bearer-token

# Optional: Custom ports
# OPENCODE_PORT=4101
# MCP_TOOL_PORT=5101

# Optional: Binary paths
# OPENCODE_BIN=/home/alex/.bun/bin/opencode
# MCP_TOOL_DIR=/home/alex/Development/Sandbox/opencode-mcp-tool
```

## Usage Examples

### Example 1: Development Mode (Fast Start)

**Setup:**
```bash
export ENVIRONMENT=development
python3 unified_mcp_server.py --mode http --port 8000
```

**User:** "Start my blog-api project"

**AI:** Calls `opencode_start(project_name="blog-api", git_url="git@github.com:user/blog-api.git")`

**Response (waiting for SSH key):**
```
Status: waiting_for_key

Please add this public key to your GitHub repository:
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5...

Public key saved at: ~/.memory/opencode-keys/blog-api-deploy.pub

⚠️ Development mode: Auto-generated .env with passwords
Review: ~/.memory/opencode-sandboxes/blog-api/.env
```

**User:** "Done, added the key to GitHub"

**AI:** Calls `opencode_start(...)` again

**Success:**
```
Status: success

Project blog-api started successfully!

OpenCode Web: http://127.0.0.1:4101 (PID: 12345)
MCP Tool: http://127.0.0.1:5101 (PID: 12346)

⚠️ DEVELOPMENT MODE WARNING:
Auto-generated passwords in .env - review before production use!
```

---

### Example 2: Production Mode (Secure)

**Setup:**
```bash
# Don't set ENVIRONMENT (defaults to production)
python3 unified_mcp_server.py --mode http --port 8000
```

**User:** "Start my blog-api project"

**AI:** Calls `opencode_start(project_name="blog-api", git_url="git@github.com:user/blog-api.git")`

**Response (need passwords):**
```
Status: waiting_for_passwords

📝 Configuration file created at:
   ~/.memory/opencode-sandboxes/blog-api/.env

⚠️ Please set secure passwords in the .env file:
   - OPENCODE_SERVER_PASSWORD (generate: openssl rand -hex 16)
   - MCP_TOOL_BEARER_TOKEN (generate: openssl rand -hex 32)

SSH key will be auto-generated automatically.

After setting passwords, call opencode_start again to continue.
```

**User edits .env:**
```bash
# Generate secure values
openssl rand -hex 16  # Copy to OPENCODE_SERVER_PASSWORD
openssl rand -hex 32  # Copy to MCP_TOOL_BEARER_TOKEN

# Edit file
nano ~/.memory/opencode-sandboxes/blog-api/.env
```

**User:** "Done, set the passwords"

**AI:** Calls `opencode_start(...)` again

**Response (waiting for SSH key):**
```
Status: waiting_for_key

SSH key auto-generated at:
   ~/.memory/opencode-keys/blog-api-deploy

Please add this public key to your GitHub repository:
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5...

Public key: ~/.memory/opencode-keys/blog-api-deploy.pub
```

**User:** "Added key to GitHub"

**AI:** Calls `opencode_start(...)` again

**Success:**
```
Status: success

Project blog-api started successfully!

OpenCode Web: http://127.0.0.1:4101 (PID: 12345)
MCP Tool: http://127.0.0.1:5101 (PID: 12346)
```

### Checking Status

**AI:** Calls `opencode_status(project_name="blog-api")`

```
Project: blog-api
OpenCode: Running (PID 12345, Port 4101)
MCP Tool: Running (PID 12346, Port 5101)
Sandbox: ~/.memory/opencode-sandboxes/blog-api
Last health check: 2026-01-28T10:30:00Z
```

## Development

### Adding New Features

1. **Models** (`models.py`): Data structures
2. **Managers**: Business logic
   - `env_manager.py`: .env handling
   - `state_manager.py`: JSON persistence
   - `ssh_manager.py`: SSH key operations
   - `process_manager.py`: Process lifecycle
3. **Main** (`manager.py`): Orchestration
4. **Tools** (`../core/tools.py`): MCP integration

### Testing

Set `ENVIRONMENT=development` for auto-generated configs:

```bash
export ENVIRONMENT=development
# Start Memory MCP server
# Call opencode_start tool
```

## Troubleshooting

### SSH Key Issues
- **Permission denied**: Check key permissions (`chmod 600 <key>`)
- **Public key missing**: Regenerate with `ssh-keygen -y -f <key> > <key>.pub`

### Process Won't Start
- Check logs: `~/.memory/opencode-logs/<project>-opencode.log`
- Verify binary exists: `which opencode`
- Check port availability: `lsof -i :<port>`

### Health Check Fails
- Wait up to 60 seconds for startup
- Check process logs for errors
- Verify password in `.env` matches

## Security Considerations

1. **Never commit** `.env` files (automatically gitignored)
2. SSH keys are **passphrase-less** (for automation)
3. All processes run as **current user** (not root)
4. Services bind to **127.0.0.1 only** (localhost)
5. Random tokens generated with **cryptographic randomness**
6. **Bearer tokens** passed via environment (not CLI args) - v2.0+
7. All sensitive files have **0600 permissions** (owner only)

## Migration Guide: v1.0 (1:1) → v1.1 Beta (N:1)

### What Changed?

**Old (1:1)**: Each project had its own MCP tool instance on a separate port (5100, 5101, 5102...)
**New (N:1)**: One global MCP tool on port 3005 serves all projects

### Automatic Migration

The OpenCode Manager **automatically migrates** your state file on first run with v1.1 beta:

1. Creates `global_mcp_tool` section in state
2. Removes per-project `mcp_tool` sections
3. Creates `opencode-mcp-tool-servers.json` configuration file
4. Preserves all project data (OpenCode servers still on their ports)

**No data loss, zero downtime!**

### Manual Steps (if needed)

If you encounter issues after upgrade:

```bash
# 1. Stop all old MCP tool processes
ps aux | grep "opencode-mcp-tool" | awk '{print $2}' | xargs kill

# 2. Clean up old PID files
rm ~/.memory/opencode-sandboxes/*/mcp-tool.pid

# 3. Restart projects (global MCP tool will auto-start)
# Use opencode_restart tool or:
python3 -c "
import asyncio
from app.mcp.opencode.manager import OpenCodeManager
asyncio.run(OpenCodeManager().restart_project('YOUR_PROJECT_NAME'))
"
```

### Client Configuration Update

**Old client config** (per-project ports):
```json
{
  "project-a": {"url": "http://127.0.0.1:5100"},
  "project-b": {"url": "http://127.0.0.1:5101"}
}
```

**New client config** (single global port):
```json
{
  "mojoassistant-opencode": {"url": "http://127.0.0.1:3005"}
}
```

Connect to port **3005** for all projects!

### Verification

Check migration succeeded:

```python
from app.mcp.opencode.manager import OpenCodeManager
import asyncio

status = asyncio.run(OpenCodeManager().list_projects())
print(f"Global MCP Tool: {status['global_mcp_tool']['status']}")
print(f"Active projects: {status['global_mcp_tool']['active_projects']}")
```

Expected output:
```
Global MCP Tool: running
Active projects: 2
```

### Rollback (if needed)

If you need to rollback to v1.0:

```bash
# 1. Stop all processes
kill $(cat ~/.memory/global-mcp-tool.pid)
kill $(cat ~/.memory/opencode-sandboxes/*/opencode.pid)

# 2. Restore old state backup
cp ~/.memory/opencode-state.json.backup ~/.memory/opencode-state.json

# 3. Checkout v1.0 code
git checkout v1.0
```

## Future Enhancements

- [ ] Auto-restart on crash
- [ ] Idle timeout (auto-stop after 2h inactive)
- [ ] Resource limits (systemd-run integration)
- [ ] Multi-agent support (Gemini CLI, etc.)
- [ ] Health monitoring dashboard
