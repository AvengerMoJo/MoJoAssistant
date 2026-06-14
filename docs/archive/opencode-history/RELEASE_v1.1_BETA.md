# OpenCode Manager v1.1 Beta - Agent Management Pattern

**Date**: 2026-02-03
**Version**: 1.1.0-beta (N:1 Architecture)
**Status**: ✅ **READY FOR TESTING**
**Scope**: First implementation of MoJoAssistant's Agent Manager pattern

---

## Position Within MoJoAssistant

This OpenCode Manager is the **first implementation** of MoJoAssistant's broader **Agent Manager** architecture. It establishes a reusable pattern for managing AI coding agents (and other agentic tools) that will be extended to:

- **Gemini CLI agents**
- **Custom tool agents** (internal optimization)
- **Third-party MCP servers**
- **Future agentic tools** as the ecosystem evolves

### MoJoAssistant's Four Pillars

1. **Memory System** - Foundation for everything (security policies, entity relationships)
2. **Agent Manager** ← **You are here (OpenCode = first implementation)**
3. **Scheduler** - Task tracking, dreaming, resource optimization
4. **Security & Policy** - Fine-grained permissions, smart authorization

## What's New in v1.1 Beta

### 🏗️ N:1 Architecture (Agent Management Pattern)

**Before**: Each project had its own MCP tool instance (1:1 architecture)
```
Project A → OpenCode:4100 → MCP Tool:5100
Project B → OpenCode:4101 → MCP Tool:5101
Project C → OpenCode:4102 → MCP Tool:5102
```

**After**: One global MCP tool serves all projects (N:1 architecture)
```
Project A → OpenCode:4100 ──┐
Project B → OpenCode:4101 ──┼→ Global MCP Tool:3005
Project C → OpenCode:4102 ──┘
```

**Benefits**:
- 🚀 **Resource Efficient**: One Node.js process instead of N
- 🔌 **Simpler Clients**: Always connect to port 3005
- 🔄 **Hot Reload**: Add/remove servers without restart
- 🎯 **Smart Lifecycle**: Auto-start with first project, auto-stop with last

### 🔒 Security Improvements (High Priority)

✅ **Bearer Token Protection**
- Moved from CLI arguments to environment variables
- Tokens NO LONGER visible in `ps aux`
- Prevents credential leakage in logs and process monitors

✅ **File Permissions**
- All sensitive files created with 0600 permissions
- SSH keys, state files, and configs properly secured

### 📄 Enhanced Documentation

✅ **Migration Guide**: Automatic v1.0 → v2.0 upgrade path
✅ **Security Model**: Comprehensive security documentation
✅ **N:1 Architecture**: 44KB detailed technical specification

---

## Release Checklist

### Core Functionality ✅ COMPLETE

- [x] N:1 architecture implementation
- [x] Global MCP tool lifecycle management
- [x] Multi-server configuration file support
- [x] Automatic state migration from v1.0
- [x] Port consistency and reuse on restart
- [x] Health check authentication

### Security ✅ COMPLETE

- [x] Bearer token moved to environment variable
- [x] File permissions set to 0600 for sensitive files
- [x] Security audit completed
- [x] Integration testing passed
- [x] Security documentation updated

### Documentation ✅ COMPLETE

- [x] README updated with N:1 architecture
- [x] Migration guide added
- [x] Security improvements documented
- [x] Configuration guide updated
- [x] Security audit results published

### Testing ✅ VERIFIED

- [x] Integration tests passed (N:1 architecture)
- [x] Security tests passed (no token in process list)
- [x] Health checks working correctly
- [x] Multi-server configuration verified
- [x] Automatic migration tested

---

## Files Changed

### MoJoAssistant Repository

**Modified**:
- `app/mcp/opencode/process_manager.py` - Bearer token security fix
- `app/mcp/opencode/SECURITY_TODOS.md` - Updated with completed fixes
- `app/mcp/opencode/README.md` - N:1 architecture, migration guide, security updates

**Created**:
- `app/mcp/opencode/SECURITY_AUDIT_RESULTS.md` - Comprehensive security audit
- `app/mcp/opencode/RELEASE_READY_v2.0.md` - This file

### opencode-mcp-tool Repository

**Modified**:
- `src/index-http.ts` - Added `MCP_BEARER_TOKEN` environment variable support
- `src/tools/registry.ts` - Fixed toolRegistry export

---

## Deployment Instructions

### For New Users

Simply clone and run - everything works out of the box:

```bash
git clone https://github.com/your-repo/MoJoAssistant.git
cd MoJoAssistant
pip install -r requirements.txt
python3 unified_mcp_server.py --mode http --port 8000
```

### For Existing Users (Upgrading from v1.0)

**Automatic Migration** - Just restart:

```bash
# Pull latest code
git pull origin main

# Restart projects (migration happens automatically)
# Use opencode_restart tool or:
python3 -c "
import asyncio
from app.mcp.opencode.manager import OpenCodeManager
asyncio.run(OpenCodeManager().restart_project('YOUR_PROJECT_NAME'))
"
```

**Verify Migration**:
```bash
# Check global MCP tool status
python3 -c "
import asyncio
from app.mcp.opencode.manager import OpenCodeManager
status = asyncio.run(OpenCodeManager().list_projects())
print(f\"Global MCP Tool: {status['global_mcp_tool']['status']}\")
print(f\"Active projects: {status['global_mcp_tool']['active_projects']}\")
"
```

**Update Client Configuration**:
- Old: Connect to different ports per project (5100, 5101, 5102...)
- New: Connect to port **3005** for all projects

---

## Post-Release Recommendations

### Optional Security Improvements

1. **Rotate Bearer Token** (recommended):
   ```bash
   NEW_TOKEN=$(openssl rand -hex 32)
   sed -i "s/GLOBAL_MCP_BEARER_TOKEN=.*/GLOBAL_MCP_BEARER_TOKEN=$NEW_TOKEN/" .env
   # Then restart global MCP tool
   ```

2. **Clean Up Old Logs** (recommended):
   ```bash
   # Old logs contain credentials from v1.0
   rm ~/.memory/opencode-logs/*-mcp-tool.log
   ```

### Short-term Enhancements (Next Sprint)

- [ ] Automated log rotation and cleanup
- [ ] Log sanitization (redact credentials)
- [ ] Move bearer token to config file (Phase 2)
- [ ] Improved error messages

### Long-term Enhancements

- [ ] Encryption at rest for credentials
- [ ] System keyring integration
- [ ] Auto-restart on crash
- [ ] Idle timeout (auto-stop after inactivity)
- [ ] Health monitoring dashboard

---

## Known Issues

### Non-Blocking

1. **Old log files contain credentials** (from v1.0)
   - **Impact**: Low (requires filesystem access)
   - **Fix**: Clean up logs manually (see above)
   - **Status**: Documented in security audit

2. **Bearer token visible in /proc/environ**
   - **Impact**: Very Low (requires root or owner permissions)
   - **Fix**: Phase 2 - config file approach
   - **Status**: Acceptable for single-user systems

### None! 🎉

All HIGH-priority security issues have been resolved.

---

## Performance Metrics

### Resource Usage Improvement

**Before (1:1 Architecture)**:
- 3 projects = 3 OpenCode + 3 MCP tool = 6 processes
- Memory: ~150MB per MCP tool = 450MB total
- Ports: 6 ports used (4100-4102, 5100-5102)

**After (N:1 Architecture)**:
- 3 projects = 3 OpenCode + 1 MCP tool = 4 processes
- Memory: ~150MB for global MCP tool = 150MB total
- Ports: 4 ports used (4100-4102, 3005)

**Savings**: 33% fewer processes, 66% less memory for MCP tools

---

## Success Criteria

### Must-Have (Release Blockers) ✅

- [x] N:1 architecture working correctly
- [x] Bearer token security fix implemented
- [x] Integration tests passing
- [x] Documentation complete
- [x] Migration path verified

### Should-Have (Post-Release) ⏳

- [ ] Log cleanup automation
- [ ] Configuration file approach (Phase 2)
- [ ] Performance monitoring

### Nice-to-Have (Future) 📋

- [ ] Encryption at rest
- [ ] Multi-user support
- [ ] Health monitoring dashboard

---

## Release Notes

### v1.1.0-beta (2026-02-03)

**Major Features**:
- **N:1 Architecture**: One global MCP tool serves all OpenCode instances
- **Automatic Migration**: Seamless upgrade from v1.0 with zero data loss
- **Security**: Bearer tokens now passed via environment variables (not CLI)
- **Hot Reload**: Server configuration reloads without restart

**Security Fixes**:
- Fixed bearer token exposure in process listings (HIGH)
- Improved file permissions (all sensitive files 0600)

**Documentation**:
- Comprehensive migration guide
- Security audit results
- N:1 architecture specification (44KB)

**Breaking Changes**:
- Clients must connect to port 3005 instead of per-project ports
- State file format updated (automatic migration)

**Upgrade Path**: Automatic migration on first restart

---

## Sign-Off

**Development**: ✅ Complete
**Testing**: ✅ Passed
**Security**: ✅ Audited
**Documentation**: ✅ Complete

**Ready for Release**: ✅ **YES**

**Recommended Action**:
1. Merge to `main` branch
2. Tag as `v2.0.0`
3. Create GitHub release
4. Update production deployments
5. Notify users of upgrade path

---

## Contact & Support

**Issues**: Report at GitHub Issues
**Security**: See `SECURITY_AUDIT_RESULTS.md`
**Documentation**: See `README.md`, `ARCHITECTURE_N_TO_1.md`
**Migration**: See "Migration Guide" in `README.md`

---

**Status**: 🚀 **READY TO SHIP** 🚀
