# SSH Key Architecture for OpenCode Projects

**Date**: 2026-02-06
**Status**: ✅ Implemented and working

## Problem Statement

Each OpenCode instance needs its own SSH key for git operations (git clone, push, pull). The challenge was making this information available across the entire stack:

1. **OpenCode Manager** - Generates and tracks SSH keys
2. **MCP Servers Config** - Needs to expose SSH key path to MCP clients
3. **OpenCode Runtime** - Needs to use the correct SSH key for git operations
4. **MCP Clients** - Need to inform users about SSH key location

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  OpenCode Manager (Python)                                  │
│  • Generates SSH key per project                            │
│  • Stores ssh_key_path in state file                        │
│  • Passes ssh_key_path to MCP servers config                │
│  • Sets GIT_SSH_COMMAND when starting OpenCode              │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  MCP Servers Config (~/.memory/opencode-mcp-tool-servers.json)│
│  {                                                           │
│    "id": "project-name",                                     │
│    "ssh_key_path": "/path/to/key",      ◄─── NEW            │
│    "git_url": "git@github.com:...",     ◄─── NEW            │
│    "sandbox_dir": "/path/to/sandbox"    ◄─── NEW            │
│  }                                                           │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  OpenCode Runtime (Node.js)                                 │
│  Environment:                                                │
│    GIT_SSH_COMMAND='ssh -i /path/to/key ...'  ◄─── NEW      │
│  • Uses SSH key for all git operations                      │
│  • No additional configuration needed                       │
└─────────────────────────────────────────────────────────────┘
```

## Implementation Details

### 1. Per-Project SSH Keys

**Location**: `~/.memory/opencode-keys/{project-name}-deploy`

**Generation**: Automatic when project starts (if not exists)

**Format**: ED25519 SSH key pair
- Private key: `{project-name}-deploy`
- Public key: `{project-name}-deploy.pub`

**Key naming**: `opencode-mcp-{project-name}`

### 2. State Management

**File**: `~/.memory/opencode-state.json`

**Structure**:
```json
{
  "projects": {
    "project-name": {
      "ssh_key_path": "/home/alex/.memory/opencode-keys/project-name-deploy",
      "git_url": "git@github.com:user/repo.git",
      "sandbox_dir": "/home/alex/.memory/opencode-sandboxes/project-name"
    }
  }
}
```

### 3. MCP Servers Configuration

**File**: `~/.memory/opencode-mcp-tool-servers.json`

**Before** (missing SSH info):
```json
{
  "servers": [{
    "id": "project-name",
    "url": "http://127.0.0.1:4104",
    "password": "2400",
    "status": "active"
  }]
}
```

**After** (includes SSH info):
```json
{
  "servers": [{
    "id": "project-name",
    "url": "http://127.0.0.1:4104",
    "password": "2400",
    "status": "active",
    "ssh_key_path": "/home/alex/.memory/opencode-keys/project-name-deploy",
    "git_url": "git@github.com:user/repo.git",
    "sandbox_dir": "/home/alex/.memory/opencode-sandboxes/project-name"
  }]
}
```

### 4. OpenCode Runtime Environment

**OpenCode process environment**:
```bash
GIT_SSH_COMMAND='ssh -i /home/alex/.memory/opencode-keys/project-name-deploy -o StrictHostKeyChecking=accept-new'
```

**This means**:
- All git commands run by OpenCode automatically use the correct SSH key
- No need to configure git config
- No need for global SSH config
- Works out of the box

## Code Changes

### 1. config_manager.py

**Method**: `add_server()`

**Changes**:
- Added parameters: `ssh_key_path`, `git_url`, `sandbox_dir`
- Writes these fields to MCP servers config
- Updates existing servers with new metadata

**Location**: `app/mcp/opencode/config_manager.py:43-87`

### 2. manager.py

**Two call sites updated**:

**A. start_project()** (line 284):
```python
self.config_manager.add_server(
    project_name=project_name,
    port=opencode_port,
    password=config.opencode_password,
    ssh_key_path=ssh_key_path,        # ← NEW
    git_url=git_url,                  # ← NEW
    sandbox_dir=config.sandbox_dir,   # ← NEW
)
```

**B. restart_project()** (line 495):
```python
self.config_manager.add_server(
    project_name=project_name,
    port=opencode_port,
    password=config.opencode_password,
    ssh_key_path=project.ssh_key_path,  # ← NEW (from state)
    git_url=project.git_url,            # ← NEW (from state)
    sandbox_dir=project.sandbox_dir,    # ← NEW (from state)
)
```

### 3. process_manager.py

**Method**: `start_opencode()`

**Changes**:
- Added `GIT_SSH_COMMAND` to OpenCode startup environment
- Uses `config.ssh_key_path` for the key location

**Before**:
```bash
cd {repo_dir} && \
OPENCODE_SERVER_PASSWORD={password} \
nohup {opencode_bin} web ...
```

**After**:
```bash
cd {repo_dir} && \
OPENCODE_SERVER_PASSWORD={password} \
GIT_SSH_COMMAND='ssh -i {ssh_key_path} -o StrictHostKeyChecking=accept-new' \
nohup {opencode_bin} web ...
```

**Location**: `app/mcp/opencode/process_manager.py:116-125`

## Verification

### Check MCP Config
```bash
cat ~/.memory/opencode-mcp-tool-servers.json
```

Should show `ssh_key_path`, `git_url`, `sandbox_dir` fields.

### Check OpenCode Environment
```bash
# Find OpenCode PID
ps aux | grep "opencode.*web.*4104" | grep -v grep

# Check environment (replace PID)
cat /proc/{PID}/environ | tr '\0' '\n' | grep GIT_SSH_COMMAND
```

Should show: `GIT_SSH_COMMAND=ssh -i /home/alex/.memory/opencode-keys/project-name-deploy ...`

### Test Git Operations

From OpenCode session:
```bash
# This should work without prompting for SSH key
git push origin main
```

## Benefits

1. **Automatic**: SSH keys are generated and configured automatically
2. **Per-Project**: Each project has its own isolated SSH key
3. **Secure**: Keys stored in `~/.memory/` with restricted permissions
4. **Transparent**: MCP clients can access SSH key info from config
5. **No Manual Config**: OpenCode uses keys automatically via `GIT_SSH_COMMAND`

## User Workflow

### 1. Start Project
```python
# Manager generates SSH key if needed
result = manager.start_project("my-project", "git@github.com:user/repo.git")
```

### 2. Add Key to GitHub
If first time, user receives:
```
SSH key does not have access to repository yet.

Please add this public key to your Git repository:

ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIpb... opencode-mcp-my-project

Public key location: /home/alex/.memory/opencode-keys/my-project-deploy.pub

After adding the key, run this command again to retry.
```

### 3. Use OpenCode
Once key is added to GitHub:
- OpenCode can clone, pull, push without issues
- MCP clients know where SSH key is located (from config)
- Can inform user or show SSH key info in UI

## Edge Cases

### Multiple Projects
✅ **Supported**: Each project has its own SSH key
```
~/.memory/opencode-keys/
  ├── project-a-deploy
  ├── project-a-deploy.pub
  ├── project-b-deploy
  └── project-b-deploy.pub
```

### Project Restart
✅ **Supported**: SSH key info preserved in state, reused on restart

### MCP Client Access
✅ **Supported**: MCP clients can read `ssh_key_path` from server config and display to user or use in tools

## Testing Status

✅ **Config Updated**: MCP servers config includes SSH metadata
✅ **Environment Set**: OpenCode runs with `GIT_SSH_COMMAND`
✅ **Process Verified**: Checked via `/proc/{pid}/environ`
✅ **Ready to Test**: User can now test git push from OpenCode session

## Next Steps

User should test:
1. Send message to OpenCode session asking to commit changes
2. Ask OpenCode to push to remote
3. Verify push succeeds without SSH key errors

If issues occur, user can check:
- SSH key exists: `~/.memory/opencode-keys/project-name-deploy`
- Key added to GitHub: Settings → Deploy Keys
- OpenCode environment: `cat /proc/{pid}/environ | grep GIT_SSH`
