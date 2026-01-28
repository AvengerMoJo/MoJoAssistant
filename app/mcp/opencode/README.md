# OpenCode Manager

Infrastructure manager for OpenCode coding agent instances.

## Overview

The OpenCode Manager provides MCP tools to bootstrap, manage, and monitor OpenCode server instances. Each project runs in an isolated sandbox with its own OpenCode web server and opencode-mcp-tool instance.

## Architecture

```
Memory MCP (This Project)
├─ Manager Tools (via MCP)
│  ├─ opencode_start
│  ├─ opencode_status
│  ├─ opencode_stop
│  ├─ opencode_restart
│  ├─ opencode_destroy
│  └─ opencode_list
│
└─ Spawns & Monitors
    ├─ OpenCode Web (port 4100-4199)
    └─ opencode-mcp-tool (port 5100-5199)
         └─ MCP Client connects here for coding operations
```

## Security Model

**Secrets are NEVER passed through MCP chat!**

All sensitive configuration (SSH keys, passwords, tokens) is stored in `.env` files within each project sandbox at `~/.memory/opencode-sandboxes/<project>/.env`.

### Development Mode
- Auto-generates `.env` with random secrets
- Auto-generates SSH keys if not provided
- Shows warnings to review configuration

### Production Mode
- Requires manual `.env` creation
- Fails if `.env` missing or invalid
- Validates all paths and credentials

## File Structure

```
~/.memory/
├── opencode-sandboxes/          # Project sandboxes
│   └── <project-name>/
│       ├── .env                 # Secrets (gitignored)
│       ├── .gitignore           # Auto-created
│       ├── repo/                # Git clone
│       ├── opencode.pid         # Process ID
│       └── mcp-tool.pid         # Process ID
├── opencode-keys/               # Generated SSH keys
│   ├── <project>-deploy
│   └── <project>-deploy.pub
├── opencode-logs/               # Process logs
│   ├── <project>-opencode.log
│   └── <project>-mcp-tool.log
└── opencode-state.json          # Persistent state
```

## MCP Tools

### `opencode_start`
Start or bootstrap a project.

**Parameters:**
- `project_name` (required): Alphanumeric project name
- `git_url` (required): SSH Git URL (e.g., `git@github.com:user/repo.git`)
- `user_ssh_key` (optional): Path to existing SSH key

**Workflow:**
1. Check if `.env` exists
   - Dev mode: Auto-generate with warnings
   - Prod mode: Fail if missing
2. Load and validate configuration
3. Generate or validate SSH key
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

## Usage Example

### Starting a Project

**User:** "Start my blog-api project"

**AI:** Calls `opencode_start(project_name="blog-api", git_url="git@github.com:user/blog-api.git")`

**If SSH key needed:**
```
Status: waiting_for_key

Please add this public key to your GitHub repository:
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5...

Public key saved at: ~/.memory/opencode-keys/blog-api-deploy.pub

After adding the key, run the command again to continue.
```

**User:** "Done, added the key"

**AI:** Calls `opencode_start(...)` again

**Success:**
```
Status: success

Project blog-api started successfully!

OpenCode Web: http://127.0.0.1:4101 (PID: 12345)
MCP Tool: http://127.0.0.1:5101 (PID: 12346)

Connect your MCP client to http://127.0.0.1:5101
Bearer token: (stored in .env)
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

## Future Enhancements

- [ ] Auto-restart on crash
- [ ] Idle timeout (auto-stop after 2h inactive)
- [ ] Resource limits (systemd-run integration)
- [ ] Multi-agent support (Gemini CLI, etc.)
- [ ] Health monitoring dashboard
