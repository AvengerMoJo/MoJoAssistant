# OpenCode Manager - Global Configuration Setup

**Date**: 2026-02-06
**Version**: 1.1 Beta

## Overview

OpenCode Manager now uses a **global configuration file** for passwords instead of per-project .env files. This solves the UX problem where MCP clients (chat interfaces) couldn't ask users to edit files on the server.

## Why Global Config?

### The Problem (Before)

```
User in MCP Client (chat) → "Create new project"
                          ↓
Manager: "Please edit .env file on the server..."
                          ↓
User: "I'm in a chat client, can't access the server!"
                          ↓
❌ WORKFLOW BLOCKED
```

### The Solution (Now)

```
One-time setup: Create global config
                          ↓
Manager uses global passwords for all projects
                          ↓
No manual intervention needed when creating projects
                          ✅ SMOOTH WORKFLOW
```

## Setup Instructions

### Step 1: Create Global Config (One Time)

```bash
# Copy template
cp ~/.memory/opencode-manager.env.template ~/.memory/opencode-manager.env

# OR create manually:
cat > ~/.memory/opencode-manager.env <<'EOF'
# OpenCode Manager Global Configuration
# Global OpenCode password (used by all OpenCode instances)
OPENCODE_PASSWORD=CHANGE_ME

# Global MCP bearer token (used by the global MCP tool on port 3005)
MCP_BEARER_TOKEN=CHANGE_ME
EOF
```

### Step 2: Generate Secure Passwords

```bash
# Generate OpenCode password (16 chars)
openssl rand -hex 16

# Generate MCP bearer token (32 chars)
openssl rand -hex 32
```

### Step 3: Edit Config File

```bash
# Edit the file
nano ~/.memory/opencode-manager.env

# Set the generated passwords:
OPENCODE_PASSWORD=<your-16-char-password>
MCP_BEARER_TOKEN=<your-32-char-bearer-token>

# Save and exit
```

### Step 4: Set Secure Permissions

```bash
chmod 600 ~/.memory/opencode-manager.env
```

### Step 5: Verify Setup

```bash
# Test that manager can load config
python3 -c "
from app.mcp.opencode.manager import OpenCodeManager
manager = OpenCodeManager()
print('✅ Global config loaded successfully')
"
```

## What Changed

### Global Config File

**Location**: `~/.memory/opencode-manager.env`

**Contains**:
- `OPENCODE_PASSWORD` - One password for all OpenCode instances
- `MCP_BEARER_TOKEN` - One token for the global MCP tool

**Purpose**: Protects OpenCode web interfaces if accidentally exposed to internet

### Per-Project Config Files

**Location**: `~/.memory/opencode-sandboxes/{project-name}/.env`

**Contains** (NO passwords):
- `GIT_URL` - Repository URL
- `SSH_KEY_PATH` - Project's SSH key path
- `OPENCODE_BIN` - Path to OpenCode binary
- `MCP_TOOL_DIR` - Path to opencode-mcp-tool

**Auto-generated**: Created automatically when starting a project

## Migration from Old Setup

If you have existing projects with passwords in their .env files:

### Option 1: Let It Auto-Migrate
```bash
# Just restart your projects
# Manager will use global config, ignoring old per-project passwords
python -m app.mcp.opencode.manager restart <project-name>
```

### Option 2: Manual Cleanup (Optional)
```bash
# Remove password lines from old .env files
cd ~/.memory/opencode-sandboxes/<project-name>
nano .env

# Delete these lines (no longer needed):
# OPENCODE_SERVER_PASSWORD=...
# MCP_TOOL_BEARER_TOKEN=...
```

## Using with MCP Clients

### Before (Blocked Workflow)

```
User: "Create new project for my-app"
MCP: "Please SSH to server and edit /home/user/.memory/.../my-app/.env"
User: "I can't SSH from here!"
❌ STUCK
```

### After (Smooth Workflow)

```
User: "Create new project for my-app"
MCP: "✅ Project created! Here's the SSH public key to add to GitHub..."
User: *adds key to GitHub*
MCP: "✅ Project started successfully!"
✅ DONE
```

## Security Notes

### Global Config Security

- File permissions: `600` (owner read/write only)
- Location: `~/.memory/` (already in .gitignore)
- Protected from accidental commit
- Only one place to secure passwords

### Why One Password is OK

- All OpenCode instances run locally (127.0.0.1)
- Not exposed to internet by default
- Password protects against accidental exposure
- Per-project passwords were unnecessary complexity

### SSH Keys Still Per-Project

- Each project has its own SSH deploy key
- Isolated access to repositories
- Follows GitHub best practices
- Auto-generated on project creation

## Troubleshooting

### Manager Won't Start

**Error**: "Failed to load global configuration"

**Solution**:
```bash
# Check if config exists
ls -la ~/.memory/opencode-manager.env

# If missing, follow Step 1-4 above
```

### "CHANGE_ME_REQUIRED" Error

**Error**: "Please set real values for these fields in global config"

**Solution**:
```bash
# Edit config and replace placeholders
nano ~/.memory/opencode-manager.env

# Use generated passwords (Step 2)
```

### Permission Denied

**Error**: "Permission denied: opencode-manager.env"

**Solution**:
```bash
# Fix permissions
chmod 600 ~/.memory/opencode-manager.env
chown $USER ~/.memory/opencode-manager.env
```

## FAQ

### Q: Do I need to update existing projects?

**A**: No. Existing projects will automatically use the global config. You can optionally clean up old password lines from their .env files, but it's not required.

### Q: Can I use different passwords for different projects?

**A**: Not with the current design. The global config uses one password for all OpenCode instances. This is intentional to keep the UX simple and avoid the "stuck in MCP client" problem.

### Q: What if I want project-specific security?

**A**: You can use firewall rules to restrict access to specific OpenCode ports, or use SSH tunneling to access them remotely.

### Q: Is the global config safe?

**A**: Yes:
- File permissions (600) protect it
- Already in .gitignore via `.memory/`
- Only accessible by your user account
- Same security as SSH keys

## Summary

**Before**: Per-project passwords → UX nightmare in MCP clients

**After**: Global config → One-time setup, smooth workflow

**Setup**: 5 minutes, once

**Benefit**: Never get stuck asking users to edit server files from chat

---

**You're ready!** Create the global config and start using OpenCode Manager with MCP clients.
