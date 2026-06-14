# MoJoAssistant v1.1.0-beta Release Notes

**Release Date**: 2026-02-07
**Branch**: wip_opencode_manager → main
**Focus**: OpenCode Manager - Production-ready N:1 Architecture

## 🎯 Major Features

### 1. OpenCode Manager (N:1 Architecture)

**Complete lifecycle management for OpenCode AI coding agents**

- ✅ **Process Management**: Start, stop, restart OpenCode instances
- ✅ **Multi-Project Support**: Manage multiple projects simultaneously
- ✅ **Global MCP Tool**: Single port (3005) routes to all OpenCode instances
- ✅ **State Persistence**: Projects survive system restarts
- ✅ **Health Monitoring**: Automatic health checks and recovery
- ✅ **SSH Key Management**: Per-project SSH deploy keys (auto-generated)

**Architecture**:
```
N OpenCode Projects → 1 Global MCP Tool (port 3005) → MCP Clients
```

### 2. Global Password Configuration

**Simplified credential management**

- ✅ **One Config File**: `~/.memory/opencode-manager.env`
- ✅ **Global Passwords**: Single password for all OpenCode instances
- ✅ **No Manual Intervention**: Auto-used when creating projects
- ✅ **Smooth UX**: No more "edit .env file" blockers in chat interfaces

### 3. SSH Key Architecture

**Per-project git access with automatic configuration**

- ✅ **Auto-Generated Keys**: ED25519 SSH keys per project
- ✅ **Git Integration**: `GIT_SSH_COMMAND` set automatically
- ✅ **MCP Exposure**: SSH key paths visible in MCP servers config
- ✅ **Isolated Access**: Each project has its own GitHub deploy key

### 4. Development Tools

**Hot reload and debugging improvements**

- ✅ **Auto-Reload**: `run_dev_watch.sh` using watchfiles
- ✅ **Development Mode**: Fast iteration without manual restarts
- ✅ **Network Access**: OpenCode bound to 0.0.0.0 (remote accessible)

## 🔧 Technical Improvements

### Process Management
- Fixed PID tracking bugs (processes killed externally)
- Fixed stale state detection and cleanup
- Fixed port reuse on restart
- Fixed MCP tool startup hang issues
- Removed strict health check delays

### Security
- Global password configuration (one place to secure)
- Per-project SSH keys (principle of least privilege)
- Password-protected web servers
- Secure file permissions (600) on configs

### Configuration
- Simplified .env structure (no per-project passwords)
- Global MCP tool port (3005, fixed for cloudflared)
- Auto-reload of server configurations
- Environment-based development mode

## 📋 Breaking Changes

### OpenCode Manager
- **Per-project passwords removed**: Use global config instead
- **MCP tool architecture**: Single global tool vs per-project
- **Port assignments**: Auto-assigned from range (4100-4199)

### Migration Required
1. Create `~/.memory/opencode-manager.env`:
   ```env
   OPENCODE_PASSWORD=<your-password>
   MCP_BEARER_TOKEN=<your-bearer-token>
   ```

2. Set permissions:
   ```bash
   chmod 600 ~/.memory/opencode-manager.env
   ```

3. Restart projects (will use new global config)

## 🐛 Bug Fixes

- Fixed PID file tracking (handle external kills)
- Fixed stale state detection (dead processes)
- Fixed port assignment (reuse on restart)
- Fixed MCP tool hang (removed health check delay)
- Fixed global MCP tool authentication
- Fixed linting errors (ruff)
- Fixed event loop conflicts (hot reload)

## 🗑️ Deprecated

### opencode-mcp-tool CLI Tools
- `ask-opencode` - Disabled (spawned CLI processes)
- `build` - Disabled (spawned CLI processes)
- `plan` - Disabled (spawned CLI processes)

**Use instead**: Session-based tools
- `opencode-session-message`
- `opencode-session-create`
- `opencode-session-list`

## 📚 Documentation

### New Documents
- `SETUP_GLOBAL_CONFIG.md` - Global configuration setup
- `SSH_KEY_ARCHITECTURE.md` - SSH key flow documentation
- `SIMPLE_MODEL.md` - Clean architecture explanation
- `TERMINOLOGY.md` - Project vs Session clarification
- `STATUS.md` - Testing status and readiness
- `GLOBAL_CONFIG_MIGRATION.md` - Migration guide
- `HOW_TO_AUTO_RELOAD.md` - Development workflow
- `HOW_TO_AUTO_RELOAD_FIXED.md` - Working hot reload solution

### Updated
- `README.md` - Updated with OpenCode Manager features
- `.env` - Added GLOBAL_MCP_TOOL_PORT, GLOBAL_MCP_BEARER_TOKEN

## 🧪 Testing Status

### Automated Tests
- ✅ 8/8 tests passing in OpenCode Manager
- ✅ Process lifecycle (start, stop, restart)
- ✅ State persistence
- ✅ Health checks
- ✅ SSH key generation

### Manual Testing Needed
- ⏳ Session persistence (verify sessions survive restart)
- ⏳ Multi-project isolation
- ⏳ Claude Desktop integration
- ⏳ Git operations (push with SSH keys)

## 🚀 Deployment

### Requirements
- Python 3.12+
- OpenCode CLI (`~/.bun/bin/opencode`)
- opencode-mcp-tool (in ~/Development/Sandbox/)
- LMStudio (port 8080) or other LLM provider

### Setup
1. Create global config:
   ```bash
   cp app/mcp/opencode/templates/opencode-manager.env.template \
      ~/.memory/opencode-manager.env
   # Edit with your passwords
   chmod 600 ~/.memory/opencode-manager.env
   ```

2. Start a project:
   ```python
   from app.mcp.opencode.manager import OpenCodeManager
   manager = OpenCodeManager()
   await manager.start_project("my-project", "git@github.com:user/repo.git")
   ```

3. Access via MCP:
   - Global MCP tool: `http://localhost:3005`
   - Bearer token: (from ~/.memory/opencode-manager.env)

## 📊 Statistics

- **Commits**: 18 commits since main
- **Files Changed**: 50+ files
- **Lines Added**: 3000+ lines
- **Documentation**: 10+ new markdown files
- **Bug Fixes**: 15+ issues resolved

## 🎉 What's Next (v1.2)

- Web UI for OpenCode Manager
- Session export/import
- Multi-user support
- Enhanced monitoring dashboard
- Automated testing integration

## 👥 Contributors

- Claude Sonnet 4.5 (AI Assistant)
- Alex (Product Owner & Developer)

## 📝 Notes

This is a **beta release**. While the core functionality is stable and tested, we recommend:
- Testing in development environment first
- Keeping backups of important projects
- Reporting issues on GitHub

## 🔗 Links

- Repository: github.com/AvengerMoJo/MoJoAssistant
- Documentation: /app/mcp/opencode/
- Issues: github.com/AvengerMoJo/MoJoAssistant/issues

---

**Ready for beta testing!** 🚀
